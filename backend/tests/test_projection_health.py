import hashlib
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cqrs import (
    get_projection_health,
    list_projection_health,
    rebuild_and_persist_projection,
    record_metric,
    start_run,
)
from app.database import Base, get_db
from app.main import app
from app.models import EventStore, RunProjection


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


@pytest.fixture()
def engine():
    from sqlalchemy import JSON
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.compiler import compiles

    @compiles(JSONB, "sqlite")
    def _compile_jsonb_sqlite(_type, compiler, **kw):
        return "JSON"

    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    return eng


@pytest.fixture()
def db(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(engine):
    Session = sessionmaker(bind=engine)

    def _override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    # 不进入 with 上下文，避免 lifespan 对生产 DATABASE_URL（Postgres）执行 create_all
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def _make_run_with_events(db, *, n_metrics=2):
    run = start_run(
        db,
        actor="researcher",
        project="p1",
        name="lag-test",
        dataset_content_sha256=sha("ds-lag"),
        code_commit_sha="abc1234",
        description=None,
        run_id=uuid4(),
    )
    for step in range(1, n_metrics + 1):
        run = record_metric(
            db,
            run_id=run.id,
            actor="researcher",
            name="loss",
            value=0.1 * step,
            step=step,
            expected_version=run.version,
        )
    return run


def test_health_reports_lag_when_projection_behind(db):
    run = _make_run_with_events(db, n_metrics=2)
    assert run.version == 3

    # 人为制造投影滞后：投影停留在 v2
    run.version = 2
    db.commit()

    health = get_projection_health(db, run.id)
    assert health is not None
    assert health.event_version == 3
    assert health.projection_version == 2
    assert health.lag == 1
    assert health.healthy is False


def test_health_reports_missing_projection_after_clear(db):
    run = _make_run_with_events(db, n_metrics=1)
    db.delete(db.get(RunProjection, run.id))
    db.commit()

    health = get_projection_health(db, run.id)
    assert health is not None
    assert health.projection_present is False
    assert health.projection_version == 0
    assert health.event_version == 2
    assert health.lag == 2
    assert health.healthy is False

    all_health = list_projection_health(db)
    assert len(all_health) == 1
    assert all_health[0].healthy is False


def test_rebuild_restores_cleared_projection_and_versions_align(db):
    run = _make_run_with_events(db, n_metrics=2)
    metrics_before = len(run.metrics_json)
    db.delete(db.get(RunProjection, run.id))
    db.commit()
    assert db.get(RunProjection, run.id) is None

    rebuilt = rebuild_and_persist_projection(db, run.id)
    assert rebuilt.version == 3
    assert rebuilt.status == "running"
    assert len(rebuilt.metrics_json) == metrics_before

    stored = db.get(RunProjection, run.id)
    assert stored is not None
    assert stored.version == 3

    health = get_projection_health(db, run.id)
    assert health.healthy is True
    assert health.lag == 0
    # 事件未被重建改动
    assert len(db.query(EventStore).filter_by(aggregate_id=run.id).all()) == 3


def test_rebuild_repairs_lagging_projection(db):
    run = _make_run_with_events(db, n_metrics=3)
    run.version = 1
    run.metrics_json = []
    db.commit()

    rebuilt = rebuild_and_persist_projection(db, run.id)
    assert rebuilt.version == 4
    assert len(rebuilt.metrics_json) == 3
    assert get_projection_health(db, run.id).healthy is True


def test_rebuild_unknown_run_404(db):
    from app.cqrs import DomainError

    with pytest.raises(DomainError) as exc:
        rebuild_and_persist_projection(db, uuid4())
    assert exc.value.status_code == 404


def _token(client, username, password):
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_api_researcher_rebuild_after_clear(client, db):
    run = _make_run_with_events(db, n_metrics=2)
    run_id = str(run.id)
    db.delete(db.get(RunProjection, run.id))
    db.commit()

    token = _token(client, "researcher", "lab123456")
    headers = {"Authorization": f"Bearer {token}"}

    # 清空后详情 404，但健康检查可见缺失
    assert client.get(f"/api/runs/{run_id}", headers=headers).status_code == 404
    health_resp = client.get(f"/api/runs/{run_id}/projection-health", headers=headers)
    assert health_resp.status_code == 200
    assert health_resp.json()["projection_present"] is False

    # 研究员重建
    resp = client.post(f"/api/runs/{run_id}/rebuild", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == 3
    assert len(body["metrics_json"]) == 2

    # 重建后详情 / 血缘 / 健康全部对齐可读
    assert client.get(f"/api/runs/{run_id}", headers=headers).json()["version"] == 3
    lineage = client.get(f"/api/runs/{run_id}/lineage", headers=headers)
    assert lineage.status_code == 200
    assert lineage.json()["version"] == 3
    health = client.get(f"/api/runs/{run_id}/projection-health", headers=headers).json()
    assert health["healthy"] is True
    overview = client.get("/api/projection-health", headers=headers).json()
    assert all(h["healthy"] for h in overview)


def test_api_auditor_is_read_only(client, db):
    run = _make_run_with_events(db, n_metrics=1)
    run_id = str(run.id)
    # 制造滞后
    run.version = 1
    db.commit()

    token = _token(client, "auditor", "audit123456")
    headers = {"Authorization": f"Bearer {token}"}

    # 审计员可看健康状态（含滞后提示）
    health = client.get(f"/api/runs/{run_id}/projection-health", headers=headers)
    assert health.status_code == 200
    assert health.json()["lag"] == 1

    overview = client.get("/api/projection-health", headers=headers)
    assert overview.status_code == 200

    # 审计员触发重建被拒
    resp = client.post(f"/api/runs/{run_id}/rebuild", headers=headers)
    assert resp.status_code == 403

    # 投影仍未被修复
    assert client.get(f"/api/runs/{run_id}", headers=headers).json()["version"] == 1
