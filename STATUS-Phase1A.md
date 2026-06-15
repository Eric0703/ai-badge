# Phase 1A 进度快照 — 2026-06-15（已冻结 ❄️）

## 整体状态：✅ T1~T12 全部完成 · 全量测试 154 passed · **已冻结**

- **冻结 commit**：`bcdb480`
- **测试结果**：`PYTHONPATH=. python -m pytest tests/ -v` → **154 passed in 29.97s**
- **冻结说明**：Phase 1A 代码不再变更，除文档/状态记录更新外。后续工作在 Phase 2 分支推进。

---

## ✅ 已完成 Ticket

| Ticket | 名称 | 状态 | 关键产出 |
|--------|------|------|----------|
| T1 | 项目骨架 + Docker Compose | ✅ 完成 | `docker-compose.yml`, `Dockerfile`, `pyproject.toml`, `main.py`, `config.py`, `dependencies.py`, `/api/v1/health` → 200 |
| T2 | 数据库 Migration | ✅ 完成 | 9 张表 DDL（`organizations → users → devices → sessions → jobs → workflow_events → artifacts → audit_logs → deletion_jobs`），Alembic 001_initial.py |
| T3 | 认证模块 | ✅ 完成 | `auth/` 模块：`POST /auth/register`（自动创建 org + user + virtual_phone_mic device）、`POST /auth/login`（JWT HS256 60min）、`get_current_user` 依赖 |
| T4 | Session 生命周期 + 音频上传 | ✅ 完成 | 7 个端点含 retract，14 状态状态机对齐 DDL，`storage/local.py` → `/data/audio/`，`consent_granted` 布尔字段 |
| T5 | Orchestrator + Worker | ✅ 完成 | `orchestrator/worker.py` 独立进程，`FOR UPDATE SKIP LOCKED` 轮询，30s 心跳 + 120s 超时释放，`register_handler` 装饰器 |
| T6 | Capture Service（Whisper 转写） | ✅ 完成 | `providers/base.py` → `TranscriptionProvider` ABC，`mock_whisper.py` / `openai_whisper.py`，`agents/capture.py` handler |
| T7 | Distiller Service（LLM 提炼） | ✅ 完成 | `LLMProvider` ABC，`agents/distiller.py`（summarize + extract_artifact），`artifacts/schemas.py` 4 种工件类型 |
| T8 | 工件审核 + 发布 | ✅ 完成 | `artifacts/router.py`：5 端点（list/get/edit/review/publish），`agents/integration.py` publish handler（飞书 stub） |
| T9 | Trust 规则引擎 | ✅ 完成 | 10 条红线（5 L1 + 5 L2），`policy_engine.py`，`sensitive_check.py`，`audit/` INSERT-only |
| T10 | 端到端测试 | ✅ 完成 | 7 模块单元测试 + 4 条 E2E 路径，全程 Mock provider，conftest.py 事务回滚 |
| T11 | Retract Saga | ✅ 完成 | `sessions/service.py` → `retract_session()`（软删 tombstone + 3 deletion_jobs），`agents/deletion.py` handler |
| T12 | README + 文档 | ✅ 完成 | README.md 420 行：架构图 + 快速启动 + 14 步 curl 流程 + API 速查 + Phase 1B 路线图 |

---

## 🔧 收口修复记录

### 第一轮收口（2026-06-14）

| # | 修复项 | 变更 |
|---|--------|------|
| 1 | 测试一键跑通 | `docker/init-test-db.sh` 自动创建 `ai_badge_test`；conftest.py 增加 auto-create 逻辑；`openai_whisper.py` 增加 `client=` 参数 |
| 2 | sessions.device_id | 创建 session 时如未传 `device_id`，自动查找用户的 `virtual_phone_mic` device；ORM + migration 改为 `NOT NULL`，FK `ondelete=RESTRICT`（migration 003 处理已有库升级回填） |
| 3 | 统一状态变更入口 | 新增 `artifacts/service.py`：`approve_artifact/reject_artifact/request_publish/mark_published` + `_transition_session`；router 不再直接写 status |
| 4 | Worker 未知 handler | 未知 `job_type` 标记为 `failed`（含 `error_message`），不再 `completed`；deletion_job 同理 |
| 5 | 收敛事务边界 | `artifacts/router.py` reject 路径改用同一 `db` session，不再 `async_session_factory()` |
| 6 | workflow_events 扩展 | `job_id` 改 nullable，新增 `session_id/artifact_id/resource_type/resource_id`（migration 002），消除 FK 兜底冲突 |

### 第二轮：测试基础设施稳定化（2026-06-15）

经过多轮真实 PostgreSQL 复测，逐类定位并修复：

| # | 根因 | 最终方案 |
|---|------|----------|
| 1 | pytest/pytest-asyncio 版本漂移 | `pyproject.toml` 锁定 `pytest==8.3.4` + `pytest-asyncio==0.24.0`；`[tool.setuptools.packages.find] include=["app*"]` 修复 flat-layout |
| 2 | event loop scope mismatch | conftest 采用 **function-scoped engine + TRUNCATE 隔离模型**；HTTP override 与 db fixture 各自独立 connection/session，消除 asyncpg "another operation in progress" |
| 3 | agent handler 跨库 | capture/distiller/integration/deletion 全部改用 **Worker 传入的 session**，不再内部 `async_session_factory()`（生产侧也变成单事务原子） |
| 4 | consent 授权被红线拒绝 | consent 端点先校验 session 状态再设 `consent_granted`，不调 `redline_consent_required` |
| 5 | 终端态可重复操作 | `can_transition` 对 CANCELLED/RETRACTED 终端态拒绝 self-transition（返回 409） |
| 6 | approve 非法转换 | `approve_artifact` 走合法两步 `needs_review → reviewing → approved` |
| 7 | e2e 读到过期 ORM | e2e 断言查询前 `await db.rollback()` 结束旧事务 + 过期 identity map |
| 8 | publish handler 未注册 | `worker_loop()` 导入 `app.agents.integration`；e2e 测试顶部导入全部 agent，收集阶段即注册 |
| 9 | PolicyViolation → 500 | `main.py` 新增异常处理器，统一映射为 HTTP 403 |
| 10 | 仓库结构污染 | GitHub repo 恢复为根级布局（`backend/` `docker/` `docker-compose.yml` `README.md`），清除 workspace 目录残留 |

**GitHub 仓库**：https://github.com/Eric0703/ai-badge （根级布局，main 分支 `bcdb480`）

---

## 🏗️ 当前代码目录结构

```
ai-badge/
├── .gitignore
├── docker-compose.yml
├── docker/init-test-db.sh
├── README.md
├── STATUS-Phase1A.md
└── backend/
    ├── Dockerfile
    ├── pyproject.toml
    ├── requirements.txt
    ├── alembic.ini + alembic/
    ├── app/
    │   ├── main.py / config.py / dependencies.py
    │   ├── api/v1/health.py
    │   ├── auth/              # T3: register + login
    │   ├── sessions/          # T4: 状态机 + 音频上传
    │   ├── orchestrator/      # T5: Worker + Job 编排
    │   ├── artifacts/         # T8: service.py + router.py + schemas.py
    │   ├── agents/            # T6/T7/T8/T11: capture/distiller/integration/deletion
    │   ├── providers/         # T6: base + mock_whisper + openai_whisper + openai_llm
    │   ├── storage/           # T4: local.py stub
    │   ├── trust/             # T9: redlines + policy_engine + sensitive_check
    │   ├── audit/             # T9: INSERT-only 审计
    │   ├── capture/           # T6: service.py
    │   ├── db/                # base.py + session.py
    │   └── models/            # 9 张表 ORM
    └── tests/
        ├── conftest.py
        ├── mock_providers.py
        ├── unit/              # 7 模块
        └── integration/       # E2E 垂直切片
```

---

## 🤖 AI 队友状态

| 队友 | 完成工作 | 状态 |
|------|----------|------|
| [@后端工程师](mention://agent/178119067182000) | T1~T9 + T11 + T12（README） | ✅ 完工 |
| [@测试工程师](mention://agent/178119091065000) | T10（15 测试文件 + 4 E2E） | ✅ 完工 |
| [@技术文档工程师](mention://agent/178119099277000) | T12 由后端工程师完成 | ✅ 确认 |

---

## ✅ Phase 1A 冻结检查清单

| 项 | 状态 |
|------|------|
| T1~T12 全部交付 | ✅ |
| 全量测试 154 passed（真实 PostgreSQL UTF8） | ✅ |
| `alembic upgrade head` 001→002→003 通过 | ✅ |
| 代码已推 GitHub（根级布局） | ✅ |
| 所有 agent handler 统一用传入 session | ✅ |
| 状态变更集中在 service/orchestrator | ✅ |

---

## ⚠️ Phase 1A 遗留项（带入 Phase 2）

| 遗留项 | 说明 | Phase 2 处理 |
|------|------|------|
| OpenAI API Key 未配置 | `openai_whisper.py` / `openai_llm.py` 仍为 `NotImplementedError`，Mock provider 跑通全链路 | 接真实 provider或替换模型时配置 |
| local filesystem 存储 | `storage/local.py` stub，音频存 `/data/audio` | Phase 2 接 MinIO/S3 |
| 全员 owner 角色 | 无 RBAC，`artifacts.assigned_reviewer_id` 预留但未用 | Phase 2 做 RBAC + Reviewer 分配 |
| 无前端 | 仅 curl + pytest 验证 | Phase 2 做 Next.js 控制台 |
| 飞书发布为 stub | publish handler 返回 fake `feishu_doc_id` | Phase 2 接真实飞书 API |
| 无 refresh token | JWT 过期后重新登录 | Phase 2 补 refresh token |

---

## 🚀 Phase 2 开发前准备

**固化原则（从 Phase 1A 收口沉淀，Phase 2 必须延续）**：
- router 只调 service，不直接写状态
- 外部服务走 provider/connector 适配层
- 状态变更集中在 service/orchestrator，走合法状态机转换
- agent handler 统一用传入 session，不内部新开 `async_session_factory`
- 测试：TRUNCATE 隔离模型，HTTP 与 db fixture 独立 connection，Mock provider 优先
- PolicyViolation 统一映射 HTTP 状态，不吞异常

**Phase 2 待拆解 Ticket（开发包 1B-1~1B-5）**：
| # | 模块 | 依赖 |
|---|------|------|
| 1B-1 | Next.js 控制台（登录/Dashboard/审核/审计） | Phase 1A API |
| 1B-2 | RBAC 权限（Contributor/Reviewer + assigned_reviewer_id 分配） | Phase 1A |
| 1B-3 | MinIO/S3 storage provider 替换 local stub | Phase 1A |
| 1B-4 | Refresh token 表 + 策略 | Phase 1A |
| 1B-5 | Flutter BLE Bridge（独立 repo） | 工牌硬件就绪 |

> 下一步：确认 Phase 2 首批范围（建议先 1B-1 前端 + 1B-2 RBAC，或先 1B-3 存储），再出开发包与开工令。
