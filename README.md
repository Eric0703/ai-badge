# 🎫 AI 工牌 (AI Badge) — Phase 1A

> Agent-first AI 工牌后端。采集 → 转写 → LLM 提炼 → 结构化工件 → 人工审核 → 发布。

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│  FastAPI REST API (port 8000)                               │
│  ┌──────────┬──────────┬───────────┬──────────┬──────────┐ │
│  │  auth    │ sessions │ artifacts │  audit   │  health  │ │
│  └──────────┴──────────┴───────────┴──────────┴──────────┘ │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Workflow Orchestrator (自研)                         │  │
│  │  ┌──────┐  ┌────────────┐  ┌───────────────────┐    │  │
│  │  │ jobs │  │ workflow_   │  │  Worker (独立进程) │    │  │
│  │  │      │  │   events    │  │  FOR UPDATE SKIP   │    │  │
│  │  └──────┘  └────────────┘  │  LOCKED + 心跳     │    │  │
│  │                            │  7 handlers:        │    │  │
│  │  ┌──────────────┐          │  transcribe         │    │  │
│  │  │ deletion_jobs│          │  summarize          │    │  │
│  │  │ (Saga 撤回)  │          │  extract_artifact   │    │  │
│  │  └──────────────┘          │  publish            │    │  │
│  │                            │  delete_artifact_*  │    │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Trust Guardian                                      │  │
│  │  10 红线 (5 L1 硬约束 + 5 L2 警告)                     │  │
│  │  Policy Engine + Sensitive Check                     │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  PostgreSQL 16 (port 5432)                                   │
│                                                             │
│  organizations → users → devices → sessions                 │
│                       │                                     │
│                       ▼                                     │
│  jobs → workflow_events → artifacts → audit_logs            │
│                                                │            │
│  deletion_jobs ◄───────────────────────────────┘            │
└─────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Providers (可注入 Mock)                                     │
│  ┌──────────────────┐  ┌──────────────────────────────┐    │
│  │ Whisper (mock)   │  │ LLM (mock → GPT-4o)          │    │
│  │ → OpenAI Whisper │  │ → OpenAI Chat Completions    │    │
│  └──────────────────┘  └──────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

**9 张表**: `organizations` → `users` → `devices` → `sessions` → `jobs` → `workflow_events` → `artifacts` → `audit_logs` → `deletion_jobs`

**14 个 Session 状态**: `idle | capturing | paused | processing | processing_failed | needs_review | reviewing | approved | publishing | publish_failed | published | retracting | retracted | cancelled`

**核心约束**:
- 自研 Workflow Orchestrator（job 表 + FOR UPDATE SKIP LOCKED 轮询）
- audit_logs INSERT-only（无 UPDATE/DELETE）
- 撤回 Saga + deletion_jobs 模式
- Phase 1A 所有用户 Owner 角色
- Provider 适配层隔离外部 AI 依赖（mock / test / real）

---

## 快速启动

### 前置条件

- **Python 3.11+**
- Docker & Docker Compose
- curl

### 启动

```bash
# 1. 克隆项目后进入目录
cd ai-badge

# 2. 创建音频存储目录
mkdir -p data/audio

# 3. 启动全部服务（postgres 自动创建 ai_badge + ai_badge_test 数据库）
docker compose up -d

# 4. 等待 postgres 健康检查通过，然后运行 migration
docker compose exec backend alembic upgrade head

# 5. 验证
curl http://localhost:8000/api/v1/health
# → {"status":"ok","version":"0.1.0"}
```

### 停止

```bash
docker compose down
```

---

## curl 完整流程

> 所有示例可复制粘贴执行。`TOKEN` 变量在 login 步骤后自动设置。

```bash
BASE="http://localhost:8000/api/v1"

# ═══════════════════════════════════════════════════════════════
# 1. 注册
# ═══════════════════════════════════════════════════════════════
REGISTER=$(curl -s -X POST "$BASE/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "alice@example.com",
    "password": "test123456",
    "display_name": "Alice",
    "org_name": "AI Badge Team"
  }')
echo "$REGISTER" | python3 -m json.tool
# → {"access_token":"eyJ...","token_type":"bearer","user_id":"...","org_id":"...","role":"owner"}

# ═══════════════════════════════════════════════════════════════
# 2. 登录（或直接用注册返回的 token）
# ═══════════════════════════════════════════════════════════════
LOGIN=$(curl -s -X POST "$BASE/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "alice@example.com",
    "password": "test123456"
  }')
TOKEN=$(echo "$LOGIN" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "Token: ${TOKEN:0:20}..."

# ═══════════════════════════════════════════════════════════════
# 3. 创建 Session
# ═══════════════════════════════════════════════════════════════
SESSION=$(curl -s -X POST "$BASE/sessions" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title": "Phase 1A Kickoff Meeting"}')
SID=$(echo "$SESSION" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Session ID: $SID"

# ═══════════════════════════════════════════════════════════════
# 4. 授予 Consent
# ═══════════════════════════════════════════════════════════════
curl -s -X PATCH "$BASE/sessions/$SID/consent" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"consent": true}' | python3 -m json.tool
# → "consent_granted": true

# ═══════════════════════════════════════════════════════════════
# 5. 转为 Capturing
# ═══════════════════════════════════════════════════════════════
curl -s -X PATCH "$BASE/sessions/$SID/status" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "capturing"}' | python3 -m json.tool
# → "status": "capturing"

# ═══════════════════════════════════════════════════════════════
# 6. 上传音频文件
# ═══════════════════════════════════════════════════════════════
echo "test audio content" > /tmp/test-audio.opus
curl -s -X POST "$BASE/sessions/$SID/audio" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/test-audio.opus" | python3 -m json.tool
# → "audio_key": "...", "audio_format": "opus"

# ═══════════════════════════════════════════════════════════════
# 7. 转为 Processing（停止录制，启动转写→提炼 pipeline）
# ═══════════════════════════════════════════════════════════════
curl -s -X PATCH "$BASE/sessions/$SID/status" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "processing"}' | python3 -m json.tool
# → "status": "processing"（后台创建 transcribe→summarize→extract_artifact jobs）

# ═══════════════════════════════════════════════════════════════
# 8. 启动 Worker 处理 jobs
# ═══════════════════════════════════════════════════════════════
# 在另一个终端：
#   docker compose exec backend python -m app.orchestrator.worker
#
# Worker 会依次处理 transcribe → summarize → extract_artifact
# 完成后 session.status 自动变为 needs_review

# ═══════════════════════════════════════════════════════════════
# 9. 查看 Session 状态
# ═══════════════════════════════════════════════════════════════
curl -s "$BASE/sessions/$SID" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
# → "status": "needs_review"（Worker 处理完成后）

# ═══════════════════════════════════════════════════════════════
# 10. 查看 Artifacts
# ═══════════════════════════════════════════════════════════════
ARTIFACTS=$(curl -s "$BASE/artifacts" \
  -H "Authorization: Bearer $TOKEN")
echo "$ARTIFACTS" | python3 -m json.tool
AID=$(echo "$ARTIFACTS" | python3 -c "import sys,json; print(json.load(sys.stdin)['artifacts'][0]['id'])")
echo "Artifact ID: $AID"

# ═══════════════════════════════════════════════════════════════
# 11. 审核通过
# ═══════════════════════════════════════════════════════════════
curl -s -X PATCH "$BASE/artifacts/$AID/review" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "approve", "comment": "LGTM"}' | python3 -m json.tool
# → "status": "approved", session 自动变为 "approved"

# ═══════════════════════════════════════════════════════════════
# 12. 发布
# ═══════════════════════════════════════════════════════════════
curl -s -X POST "$BASE/artifacts/$AID/publish" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
# → 创建 publish job，session 状态变为 "publishing"
# Worker 执行后 → "published"

# ═══════════════════════════════════════════════════════════════
# 13. 撤回 (Retract Saga)
# ═══════════════════════════════════════════════════════════════
curl -s -X POST "$BASE/sessions/$SID/retract" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
# → "status": "retracting"
# 后台创建 3 个 deletion_jobs（delete_artifact_rows / delete_local_audio / delete_feishu_docs）
# Worker 处理后 → session tombstone + artifacts 硬删除

# ═══════════════════════════════════════════════════════════════
# 14. 查看审计日志
# ═══════════════════════════════════════════════════════════════
curl -s "$BASE/audit-logs?session_id=$SID" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
# → 返回该 session 的全部审计记录
```

---

## 项目结构

```
ai-badge/
├── docker-compose.yml          # postgres:16 + backend
├── README.md
├── .gitignore
├── data/audio/                 # 音频文件挂载目录
└── backend/
    ├── Dockerfile
    ├── pyproject.toml           # 依赖声明
    ├── requirements.txt         # Docker 用
    ├── alembic.ini
    ├── alembic/
    │   ├── env.py
    │   └── versions/
    │       └── 001_initial.py   # 9 张表完整 DDL
    ├── app/
    │   ├── main.py              # FastAPI 入口
    │   ├── config.py            # pydantic-settings
    │   ├── dependencies.py      # get_current_user (JWT)
    │   ├── api/v1/health.py     # 健康检查
    │   ├── db/
    │   │   ├── base.py          # DeclarativeBase
    │   │   └── session.py       # async session factory
    │   ├── models/              # 9 张表 ORM
    │   │   ├── organization.py
    │   │   ├── user.py
    │   │   ├── device.py
    │   │   ├── session.py
    │   │   ├── job.py
    │   │   ├── workflow_event.py
    │   │   ├── artifact.py
    │   │   ├── audit_log.py
    │   │   └── deletion_job.py
    │   ├── auth/                # T3: 认证
    │   │   ├── models.py
    │   │   ├── schemas.py       # Register/Login request/response
    │   │   ├── service.py       # bcrypt + JWT
    │   │   └── router.py        # /auth/register, /auth/login
    │   ├── sessions/            # T4: Session 生命周期
    │   │   ├── models.py
    │   │   ├── schemas.py
    │   │   ├── service.py       # 状态机 + retract_session
    │   │   └── router.py        # /sessions 全部端点
    │   ├── storage/             # 文件存储
    │   │   ├── base.py          # StorageBackend ABC
    │   │   └── local.py         # /data/audio/{key}
    │   ├── providers/           # AI Provider 适配层
    │   │   ├── base.py          # TranscriptionProvider + LLMProvider ABC
    │   │   ├── mock_whisper.py  # Mock 转写
    │   │   ├── openai_whisper.py
    │   │   └── openai_llm.py
    │   ├── agents/              # Worker handler（7 个）
    │   │   ├── capture.py       # transcribe
    │   │   ├── distiller.py     # summarize + extract_artifact
    │   │   ├── integration.py   # publish
    │   │   └── deletion.py      # delete_artifact_rows/audio/feishu_docs
    │   ├── capture/             # T6: 转写服务
    │   │   └── service.py       # transcribe_audio()
    │   ├── artifacts/           # T7-T8: 工件
    │   │   ├── models.py
    │   │   ├── schemas.py       # 4 种工件类型 + ReviewRequest
    │   │   └── router.py        # /artifacts 全部端点
    │   ├── orchestrator/        # T5: 工作流引擎
    │   │   ├── models.py
    │   │   ├── service.py       # create_jobs, transition_job, retry_job
    │   │   └── worker.py        # 独立 Worker 进程
    │   ├── trust/               # T9: 信任守护
    │   │   ├── redlines.py      # 10 条红线
    │   │   ├── policy_engine.py # 4 个策略检查
    │   │   └── sensitive_check.py
    │   └── audit/               # T9: 审计
    │       ├── models.py
    │       ├── service.py       # audit_write() INSERT-only
    │       └── router.py        # /audit-logs
    └── tests/
        ├── conftest.py          # Mock provider + 事务回滚
        ├── mock_providers.py    # DeterministicMockLLM
        ├── unit/
        │   ├── test_auth.py
        │   ├── test_sessions.py
        │   ├── test_orchestrator.py
        │   ├── test_agents.py
        │   ├── test_artifacts.py
        │   ├── test_trust.py
        │   └── test_retract.py
        └── integration/
            └── test_e2e_vertical_slice.py  # 4 条完整 E2E 路径
```

---

## 测试

> ⚠️ **测试有效性边界：本地 mock 通过 ≠ 真实 DB / 真实 provider 通过**
>
> 测试默认用 **Mock Provider**（不调真实 Whisper/LLM）跑通业务链路。这能验证状态机、
> 编排、权限、审计等逻辑，但**不能**证明以下几类问题已解决：
>
> 1. **真实 LLM/Whisper provider**：mock 返回固定结构化输出；真实 API 的延迟、限流、
>    JSON schema 偏差、错误处理都未被覆盖。接真实 Key 后必须单独做 smoke test。
> 2. **数据库编码 / 约束**：测试库**必须是 UTF8**。曾遇到 `SQL_ASCII` 库导致中文 JSONB
>    写入失败——mock 链路在 UTF8 下全绿，换库后才暴露。生产/CI 的 DB 编码、collation、
>    FK/NOT NULL/UNIQUE 约束需与 migration 完全一致。
> 3. **连接 / 事务语义**：测试用 function-scoped engine + TRUNCATE 隔离，HTTP 与 db fixture
>    各自独立 connection。真实 Worker 的并发轮询、`FOR UPDATE SKIP LOCKED`、心跳超时
>    在单测里只能部分模拟。
> 4. **存储 / 外部集成**：local filesystem stub、飞书 stub 都不代表 MinIO/S3、真实飞书 API。
>
> **结论**：CI 全绿是必要条件，不是充分条件。上生产前必须在贴近生产的环境
> （UTF8 DB + 真实 provider + 真实存储）跑一轮端到端 smoke test。

### Mock Provider 规则

所有测试使用 **Mock Provider**，不调真实 API：
- `MockWhisperProvider` — 返回固定中文转写文本
- `DeterministicMockLLM` — 返回 schema-compliant 结构化输出
- `pytest` 自动注入 mock（conftest.py `autouse=True`）

### Stub / TODO 清单

| 组件 | 状态 | 说明 |
|------|------|------|
| OpenAI Whisper | `NotImplementedError` | 等 OPENAI_API_KEY 配置后激活 |
| OpenAI LLM (GPT-4o) | `NotImplementedError` | 等 OPENAI_API_KEY 配置后激活 |
| 飞书集成 | Stub | publish handler 返回 fake doc ID |
| MinIO / S3 | Stub | 当前用 local filesystem (`storage/local.py`) |
| RBAC 权限 | Phase 1B | 当前全员 `role=owner` |

### 运行测试

```bash
# ── Docker 方式 ──────────────────────
# 0. 确保服务已启动（postgres 已自动创建 ai_badge_test）
docker compose up -d

# 1. 安装后端依赖（仅首次）
docker compose exec backend pip install -e .[dev]

# 2. 运行 migration
docker compose exec backend alembic upgrade head

# 3. 运行全部测试
docker compose exec backend python -m pytest tests/ -v

# ── 本地方式（无 Docker）──────────────
# 需本地运行 PostgreSQL 16，DATABASE_URL 指向你的实例

cd backend
pip install -e .[dev]

# 创建测试数据库（首次）
createdb -U ai_badge ai_badge_test

# 运行 migration + 测试
PYTHONPATH=. alembic upgrade head
PYTHONPATH=. python -m pytest tests/ -v
```

### 本地开发（不依赖 Docker）

```bash
# 安装依赖
cd backend && pip install -e .[dev]

# 确保 postgres 运行，设置环境变量
export DATABASE_URL=postgresql+asyncpg://ai_badge:ai_badge_dev@localhost:5432/ai_badge
export TEST_DATABASE_URL=postgresql+asyncpg://ai_badge:ai_badge_dev@localhost:5432/ai_badge_test

# 运行 migration
PYTHONPATH=. alembic upgrade head

# 启动 API
PYTHONPATH=. uvicorn app.main:app --reload

# 启动 Worker（另一个终端）
PYTHONPATH=. python -m app.orchestrator.worker

# 运行测试
PYTHONPATH=. python -m pytest tests/ -v
```

**测试覆盖**:
| 模块 | 内容 |
|------|------|
| `test_auth.py` | bcrypt、JWT 签发/过期/篡改、register/login API |
| `test_sessions.py` | 14 状态枚举、全部合法/非法转移、consent 403 |
| `test_orchestrator.py` | Job 创建/幂等/重试/事件、transition 全路径 |
| `test_agents.py` | transcribe/summarize/extract/publish handler |
| `test_artifacts.py` | CRUD、approve/reject、publish 403 |
| `test_trust.py` | 10 条红线 L1+L2、policy violation |
| `test_retract.py` | Saga + 3 deletion_jobs + tombstone |
| `test_e2e_vertical_slice.py` | Happy Path / Failure-Retry / Review Cycle / Retract |

---

## API 端点速查

| Method | Path | 说明 |
|--------|------|------|
| `GET` | `/api/v1/health` | 健康检查 |
| `POST` | `/api/v1/auth/register` | 注册（创建 org + user + device） |
| `POST` | `/api/v1/auth/login` | 登录（返回 JWT） |
| `POST` | `/api/v1/sessions` | 创建 Session |
| `GET` | `/api/v1/sessions` | 列出 Sessions |
| `GET` | `/api/v1/sessions/{id}` | 查看 Session 详情 |
| `PATCH` | `/api/v1/sessions/{id}/consent` | 授予/撤销 Consent |
| `PATCH` | `/api/v1/sessions/{id}/status` | 状态转移 |
| `POST` | `/api/v1/sessions/{id}/audio` | 上传音频 |
| `POST` | `/api/v1/sessions/{id}/cancel` | 取消 Session |
| `POST` | `/api/v1/sessions/{id}/retract` | 撤回（Saga） |
| `GET` | `/api/v1/artifacts` | 列出 Artifacts |
| `GET` | `/api/v1/artifacts/{id}` | 查看 Artifact 详情 |
| `PATCH` | `/api/v1/artifacts/{id}` | 编辑 Artifact |
| `PATCH` | `/api/v1/artifacts/{id}/review` | 审核（approve/reject） |
| `POST` | `/api/v1/artifacts/{id}/publish` | 发布 |
| `GET` | `/api/v1/audit-logs` | 审计日志（支持 `?session_id=`） |

---

## 技术栈

| 组件 | 选型 |
|------|------|
| 语言 | Python 3.11 |
| 框架 | FastAPI + Uvicorn |
| ORM | SQLAlchemy 2.0 (async) |
| 数据库 | PostgreSQL 16 + asyncpg |
| Migration | Alembic |
| 认证 | python-jose (JWT HS256) + bcrypt |
| LLM | OpenAI API（Provider 适配层隔离） |
| 转写 | OpenAI Whisper（Mock 先行） |
| 测试 | pytest + pytest-asyncio |
| 部署 | Docker Compose |

---

## Phase 1B 预留

Phase 1A 完成后，Phase 1B 计划引入：

- **MinIO / S3 存储** — 替代本地 `/data/audio`，支持分布式部署
- **RBAC 权限** — 从全员 Owner 改为多角色（admin/reviewer/viewer）
- **飞书集成** — 替换 publish handler 的 stub 为真实飞书文档 API
- **前端** — Web 管理界面 + 工牌硬件固件
- **Redis** — 可选引入，用于 Worker 分布式锁（当前 PostgreSQL FOR UPDATE SKIP LOCKED 足够）
