# 科学实验溯源工作台（Experiment Provenance Workbench）

CQRS + Event Sourcing 全栈示例：命令追加 `event_store`，查询走投影表；Vue 前端查看 Run、事件时间线与血缘。

## How to Run

```bash
cd projects/03-experiment-provenance
docker compose up --build
```

> 镜像默认走 `docker.m.daocloud.io`（便于国内拉取）；前端 npm 使用 `npmmirror`。若你可直连 Docker Hub，可将 Dockerfile / compose 中的镜像前缀改回官方名。

首次启动会：

1. 拉起 PostgreSQL
2. 启动 FastAPI 后端并建表
3. `seed` 写入 2 条已完成 Run + 1 条进行中 Run
4. 构建并启动前端（nginx）

停止：

```bash
docker compose down
```

本地后端测试（可选，需 Python 3.11+）：

```bash
cd backend
pip install -r requirements.txt
pytest -q
```

## Services / 端口

| 服务 | 地址 |
|------|------|
| Frontend | http://localhost:3173 |
| Backend API | http://localhost:8173 |
| PostgreSQL | localhost:54373 |

容器内：

- `db`：Postgres `provenance/provenance`，库名 `provenance`
- `backend`：Uvicorn `:8000`
- `seed`：一次性灌数后退出
- `frontend`：nginx `:80`，`/api` 反代到 backend

## 账号

| 用户名 | 密码 | 角色 |
|--------|------|------|
| researcher | lab123456 | 可发命令（Start/Metric/Artifact/Complete/Abort） |
| auditor | audit123456 | 只读事件与投影 |

## Verification

1. 打开 http://localhost:3173 ，使用 `researcher` / `lab123456` 登录
2. 在 Run 列表看到 seed 数据（含进行中与已完成）
3. 点击「新建 Run」，填写 project/name、dataset sha、code commit，启动
4. 在详情页记录指标、挂载产物，再 Complete（或 Abort）
5. 打开「事件时间线」确认 version 递增的原始事件
6. 打开「血缘」确认 code_commit、dataset 指纹、artifacts、metrics
7. 健康检查：`GET http://localhost:8173/api/health`
8. 用 `auditor` 登录：可看列表/事件/血缘，命令按钮不可用

终态或 `expected_version` 不匹配时，API 返回 **409**。

## 架构要点

- **命令**：`StartRun` / `RecordMetric` / `AttachArtifact` / `CompleteRun` / `AbortRun`
- **事件**：`RunStarted` / `MetricRecorded` / `ArtifactAttached` / `RunCompleted` / `RunAborted`
- **event_store**：`(aggregate_id, version)` 唯一；冲突 → 409
- **run_projections**：查询侧投影（状态、指标、产物等）

## 投影健康与按 Run 重建

查询侧投影可能滞后于 `event_store`（如投影写入失败、被误清）。系统以事件流为准做健康观测与重建：

- **观测**：对比每个 Run 在 `event_store` 的最高 version 与投影 version，得出
  `aligned`（对齐）/ `lagging`（滞后）/ `missing`（投影整行缺失）/ `corrupt`（投影版本反超，异常）。
- **重建**：研究员可对单个 Run 触发，删除该 Run 旧投影后按 `event_store` 全量重放重建；
  只追加过事件、不修改事件流。审计员只读：能看健康状态，但重建返回 **403**。
- **入口**：顶部导航「投影健康」（不健康时显示红色角标）；Run 详情、事件时间线、血缘页也会就地提示对齐/滞后。
- **接口**（端口、前缀不变，均挂在既有 `/api` 下，非独立运维中心）：
  - `GET  /api/projection-health` 全部 Run 的投影健康
  - `GET  /api/runs/{id}/projection-health` 单个 Run 的投影健康
  - `POST /api/runs/{id}/rebuild` 按 event_store 全量重放重建（仅研究员）

### 验收：人为制造滞后 / 清空后重建

1. 用 `researcher` 登录，进入某个已完成 Run（seed 的 Run 例如
   `11111111-1111-1111-1111-111111111111`，其事件最高 version 为 4）。
2. 直接在 Postgres 人为制造投影滞后（二选一）：

   ```sql
   -- 方式 A：让投影回退一档
   UPDATE run_projections SET version = version - 1
   WHERE id = '11111111-1111-1111-1111-111111111111';

   -- 方式 B：整行清空投影（事件仍在 event_store）
   DELETE FROM run_projections
   WHERE id = '11111111-1111-1111-1111-111111111111';
   ```

   可用 `docker compose exec db psql -U provenance -d provenance -c "<SQL>"` 执行。
3. 刷新页面：
   - 顶部导航「投影健康」出现红色角标；进入健康页，该 Run 被红色标记为 **滞后 / 投影缺失**，
     并显示「事件最高 version」与「投影 version」、滞后量。
   - Run 详情页（方式 B 时进入会看到「投影缺失」兜底卡片）、事件时间线、血缘页均出现醒目红色告警。
4. 点「重建投影」（仅研究员可见）。重建完成后提示重放事件数，页面刷新为 **已对齐**，
   事件 version 与投影 version 相等，详情/血缘恢复可读且与事件时间线一致。
5. 改用 `auditor` 登录：健康页与各页面的告警仍可见，但只显示「审计员只读」，无重建按钮，
   直接 `POST /api/runs/{id}/rebuild` 返回 403。

> 后端可用 `pytest -q` 复现同一套场景（滞后、清空、重建、权限），见
> `backend/tests/test_projection_health.py`。
