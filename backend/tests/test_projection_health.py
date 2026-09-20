"""投影滞后观测与按 Run 重建投影的服务层 + API 层测试。"""

import hashlib
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import JSON, create_engine, delete
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cqrs import (
    DomainError,
    STATE_ALIGNED,
    STATE_LAGGING,
    STATE_MISSING,
    STATE_CORRUPT,
    all_projection_health,
    attach_artifact,
    complete_run,
    projection_health,
    rebuild_run_projection,
    record_metric,
    start_run,
)
from app.database import Base, get_db
from app.main import app
from app.models import RunProjection


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, compiler, **kw):
    return "JSON"


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _make_completed_run(db, *, name="run"):
    run = start_run(
        db,
        actor="researcher",
        project="p1",
        name=name,
        dataset_content_sha256=sha(f"ds-{name}"),
        code_commit_sha="deadbeef",
        description="d",
    )
    run = record_metric(
        db, run_id=run.id, actor="researcher", name="acc",
        value=0.9, step=1, expected_version=run.version,
    )
    run = attach_artifact(
        db, run_id=run.id, actor="researcher", name="model.bin",
        uri="s3://x/model.bin", content_sha256=sha("model"),
        media_type="application/octet-stream", expected_version=run.version,
    )
    run = complete_run(
        db, run_id=run.id, actor="researcher",
        result_summary="ok", expected_version=run.version,
    )
    return run


# ---------- 服务层 ----------

def test_health_aligned_on_normal_flow(db):
    run = _make_completed_run(db)
    h = projection_health(db, run.id)
    assert h["state"] == STATE_ALIGNED
    assert h["event_version"] == 4
    assert h["projection_version"] == 4
    assert h["lag"] == 0


def test_health_detects_lag(db):
    run = _make_completed_run(db)
    # 人为把投影版本回退一档，制造滞后
    proj = db.get(RunProjection, run.id)
    proj.version = run.version - 1
    db.commit()

    h = projection_health(db, run.id)
    assert h["state"] == STATE_LAGGING
    assert h["lag"] == 1
    assert h["event_version"] == 4
    assert h["projection_version"] == 3


def test_health_detects_missing_after_wipe(db):
    run = _make_completed_run(db)
    db.execute(delete(RunProjection).where(RunProjection.id == run.id))
    db.commit()

    h = projection_health(db, run.id)
    assert h["state"] == STATE_MISSING
    assert h["projection_version"] == 0
    assert h["lag"] == h["event_version"] == 4


def test_health_detects_corrupt_when_projection_ahead(db):
    run = _make_completed_run(db)
    proj = db.get(RunProjection, run.id)
    proj.version = run.version + 5
    db.commit()

    assert projection_health(db, run.id)["state"] == STATE_CORRUPT


def test_health_unknown_run_404(db):
    with pytest.raises(DomainError) as exc:
        projection_health(db, uuid4())
    assert exc.value.status_code == 404


def test_rebuild_realigns_lagging_projection(db):
    run = _make_completed_run(db)
    proj = db.get(RunProjection, run.id)
    proj.version = 1  # 严重滞后
    db.commit()

    rebuilt = rebuild_run_projection(db, run.id)
    assert rebuilt.version == 4
    assert rebuilt.status == "completed"
    assert len(rebuilt.metrics_json) == 1
    assert len(rebuilt.artifacts_json) == 1
    assert rebuilt.result_summary == "ok"
    assert projection_health(db, run.id)["state"] == STATE_ALIGNED
    # 已持久化
    assert db.get(RunProjection, run.id).version == 4


def test_rebuild_restores_wiped_projection(db):
    run = _make_completed_run(db)
    db.execute(delete(RunProjection).where(RunProjection.id == run.id))
    db.commit()
    assert db.get(RunProjection, run.id) is None

    rebuilt = rebuild_run_projection(db, run.id)
    stored = db.get(RunProjection, run.id)
    assert stored is not None
    assert rebuilt.id == stored.id == run.id
    assert stored.version == 4
    assert stored.status == "completed"
    assert stored.dataset_content_sha256 == run.dataset_content_sha256
    assert stored.code_commit_sha == run.code_commit_sha
    assert len(stored.metrics_json) == 1
    assert len(stored.artifacts_json) == 1
    assert projection_health(db, run.id)["state"] == STATE_ALIGNED


def test_rebuild_unknown_run_raises(db):
    with pytest.raises(DomainError) as exc:
        rebuild_run_projection(db, uuid4())
    assert exc.value.status_code == 404


def test_all_health_includes_wiped_run_and_sorts_unhealthy_first(db):
    healthy = _make_completed_run(db, name="healthy")
    wiped = _make_completed_run(db, name="wiped")
    db.execute(delete(RunProjection).where(RunProjection.id == wiped.id))
    db.commit()

    health = all_projection_health(db)
    by_id = {h["run_id"]: h for h in health}
    assert set(by_id) == {healthy.id, wiped.id}
    assert by_id[healthy.id]["state"] == STATE_ALIGNED
    assert by_id[wiped.id]["state"] == STATE_MISSING
    # 不健康的排在最前，便于在页面醒目提示
    assert health[0]["run_id"] == wiped.id


# ---------- API 层 ----------

@pytest.fixture()
def client_db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    def _override():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    # 不用 with 触发 lifespan（否则会连配置里的 Postgres 建表）
    client = TestClient(app)
    try:
        yield client, session
    finally:
        app.dependency_overrides.clear()
        session.close()


def _token(client, username, password):
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_health_endpoints_and_rbac(client_db):
    client, db = client_db
    researcher = _token(client, "researcher", "lab123456")
    auditor = _token(client, "auditor", "audit123456")

    run = _make_completed_run(db)

    # 审计员只读：可观测健康
    res = client.get("/api/projection-health", headers=_auth(auditor))
    assert res.status_code == 200
    assert len(res.json()) == 1

    res = client.get(f"/api/runs/{run.id}/projection-health", headers=_auth(auditor))
    assert res.status_code == 200
    assert res.json()["state"] == "aligned"

    # 制造滞后
    proj = db.get(RunProjection, run.id)
    proj.version = 2
    db.commit()

    res = client.get("/api/projection-health", headers=_auth(auditor))
    assert res.json()[0]["state"] == "lagging"
    assert res.json()[0]["lag"] == 2

    # 审计员触发重建 -> 403
    res = client.post(f"/api/runs/{run.id}/rebuild", headers=_auth(auditor))
    assert res.status_code == 403

    # 未登录 -> 401
    assert client.post(f"/api/runs/{run.id}/rebuild").status_code == 401


def test_rebuild_endpoint_realigns_and_details_readable(client_db):
    client, db = client_db
    researcher = _token(client, "researcher", "lab123456")

    run = _make_completed_run(db)
    # 清空投影：详情 / 血缘一度 404
    db.execute(delete(RunProjection).where(RunProjection.id == run.id))
    db.commit()
    assert client.get(f"/api/runs/{run.id}", headers=_auth(researcher)).status_code == 404
    assert client.get(f"/api/runs/{run.id}/lineage", headers=_auth(researcher)).status_code == 404

    # 事件时间线仍可读
    events = client.get(f"/api/runs/{run.id}/events", headers=_auth(researcher)).json()
    assert len(events) == 4

    # 研究员重建
    res = client.post(f"/api/runs/{run.id}/rebuild", headers=_auth(researcher))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["state"] == "aligned"
    assert body["lag"] == 0
    assert body["event_version"] == body["projection_version"] == 4
    assert body["replayed_events"] == 4
    assert body["run"]["id"] == str(run.id)

    # 重建后详情 / 血缘可读，且与事件时间线一致
    detail = client.get(f"/api/runs/{run.id}", headers=_auth(researcher))
    assert detail.status_code == 200
    detail_json = detail.json()
    assert detail_json["version"] == 4
    assert detail_json["status"] == "completed"
    assert len(detail_json["metrics_json"]) == 1
    assert len(detail_json["artifacts_json"]) == 1

    lineage = client.get(f"/api/runs/{run.id}/lineage", headers=_auth(researcher)).json()
    assert lineage["version"] == detail_json["version"] == len(events)


def test_rebuild_unknown_run_404(client_db):
    client, db = client_db
    researcher = _token(client, "researcher", "lab123456")
    res = client.post(f"/api/runs/{uuid4()}/rebuild", headers=_auth(researcher))
    assert res.status_code == 404
