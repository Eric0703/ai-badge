# AI 工牌 — 第一阶段开发包（Vertical Slice）Cleanup 版

> 基于：ADR v2.3  
> 目标：不依赖工牌硬件，跑通「采集 → 转写 → 提炼 → 审核 → 发布」完整 Agent 闭环  
> 阶段：MVP Phase 1A（后端闭环）+ Phase 1B（前端 + 权限细化）

## Phase 1A vs Phase 1B 边界

| | Phase 1A（本期开发包） | Phase 1B（后续） |
|---|---|---|
| **后端闭环** | ✅ 全部 ticket（T1~T12） | — |
| **认证** | JWT login/register，单 role（Owner） | RBAC + Contributor/Reviewer 角色 |
| **存储** | Local filesystem stub（`storage/local.py`） | MinIO / S3 |
| **工件审核** | Owner 审核（自审） | Reviewer assignment + 分配模型 |
| **前端** | ❌ 本期不做。用 curl + pytest 验证 | Next.js 控制台 |
| **refresh token** | ❌ 不做。JWT 过期后重新登录 | 补 refresh token 表 + 策略 |

**Phase 1A 总结**：纯后端。`docker compose up` 后一个人用 curl 就能跑通完整闭环。

---

## 1. 项目目录结构

```
ai-badge/
├── backend/
│   ├── alembic/
│   │   ├── versions/
│   │   │   └── 001_initial.py
│   │   ├── env.py
│   │   └── alembic.ini
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                # FastAPI 入口
│   │   ├── config.py              # 配置（env/LLM/DB）
│   │   ├── dependencies.py        # DI：get_db, get_current_user
│   │   │
│   │   ├── auth/
│   │   │   ├── __init__.py
│   │   │   ├── models.py          # User
│   │   │   ├── router.py          # POST /auth/register, /auth/login
│   │   │   └── service.py         # JWT 签发/校验, bcrypt
│   │   │
│   │   ├── sessions/
│   │   │   ├── __init__.py
│   │   │   ├── models.py          # Session ORM
│   │   │   ├── router.py          # POST /sessions, PATCH /sessions/{id}
│   │   │   └── service.py         # 状态转移逻辑 + retract Saga
│   │   │
│   │   ├── orchestrator/
│   │   │   ├── __init__.py
│   │   │   ├── models.py          # Job, WorkflowEvent ORM（不含 Artifact）
│   │   │   ├── router.py          # GET /sessions/{id}/status
│   │   │   ├── service.py         # create_jobs, transition, retry
│   │   │   └── worker.py          # Worker 主循环 + deletion_jobs
│   │   │
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── capture.py         # Capture Service (transcribe via Whisper)
│   │   │   ├── distiller.py       # Distiller Service (LLM extract artifacts)
│   │   │   └── integration.py     # Integration Service (publish to Feishu stub)
│   │   │
│   │   ├── artifacts/
│   │   │   ├── __init__.py
│   │   │   ├── models.py          # Artifact ORM（唯一归属）
│   │   │   ├── router.py          # GET/PATCH /artifacts, review endpoints
│   │   │   └── schemas.py         # Pydantic: MeetingMinutes, DecisionRecord, FAQDraft, SOPDraft
│   │   │
│   │   ├── audit/
│   │   │   ├── __init__.py
│   │   │   ├── models.py          # AuditLog ORM
│   │   │   ├── router.py          # GET /audit-logs
│   │   │   └── service.py         # audit_write() — 只 INSERT
│   │   │
│   │   ├── trust/
│   │   │   ├── __init__.py
│   │   │   ├── policy_engine.py   # L1+L2: 硬约束 + 规则引擎
│   │   │   ├── sensitive_check.py # L3: LLM 辅助敏感信息检测
│   │   │   └── redlines.py        # 10 条红线规则编码
│   │   │
│   │   ├── storage/
│   │   │   ├── __init__.py
│   │   │   ├── base.py            # StorageProvider 接口
│   │   │   └── local.py           # Phase 1A: local filesystem stub
│   │   │   # └── s3.py            # Phase 1B: MinIO / S3 实现
│   │   │
│   │   └── providers/
│   │       ├── __init__.py
│   │       ├── base.py            # LLMProvider, TranscriptionProvider 接口
│   │       ├── openai_llm.py      # OpenAI LLM 实现
│   │       ├── openai_whisper.py  # OpenAI Whisper 实现
│   │       └── feishu_stub.py     # 飞书 API stub（Phase 1 打桩）
│   │
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_auth.py
│   │   ├── test_sessions.py
│   │   ├── test_orchestrator.py
│   │   ├── test_agents.py
│   │   ├── test_artifacts.py
│   │   ├── test_trust.py
│   │   ├── test_retract.py        # Retract Saga + deletion_jobs
│   │   └── integration/
│   │       └── test_e2e_vertical_slice.py
│   │
│   ├── pyproject.toml
│   ├── Dockerfile
│   └── requirements.txt
│
├── docker-compose.yml             # postgres + backend（Phase 1A 不加 MinIO/console）
├── .env.example
└── README.md
```

---

## 2. 数据库 Migration

### 2.1 DDL（PostgreSQL）

```sql
-- ============================================
-- Phase 1A migration: 001_initial.sql
-- ============================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(128) NOT NULL,
    role VARCHAR(16) NOT NULL DEFAULT 'owner',  -- Phase 1A 全员 owner
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_users_org ON users(org_id);

CREATE TABLE devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES users(id),
    device_name VARCHAR(128),
    device_key VARCHAR(64) UNIQUE NOT NULL,
    bound_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- CANONICAL: sessions
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    device_id UUID NOT NULL REFERENCES devices(id),  -- Phase 1A: 注册时自动创建 virtual_phone_mic 设备
    status VARCHAR(32) NOT NULL DEFAULT 'idle',
    -- idle | capturing | paused | processing | processing_failed |
    -- needs_review | reviewing | approved |
    -- publishing | publish_failed | published |
    -- retracting | retracted | cancelled
    consent_granted BOOLEAN DEFAULT FALSE,
    consent_granted_at TIMESTAMPTZ,
    audio_key TEXT,
    audio_source VARCHAR(16) DEFAULT 'phone_mic',  -- Phase 1A 默认手机直录
    audio_duration_seconds INT,
    deleted_at TIMESTAMPTZ,
    retracted_by UUID REFERENCES users(id),
    retraction_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_sessions_status ON sessions(status);

-- CANONICAL: jobs
CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id),
    job_type VARCHAR(64) NOT NULL,
    -- transcribe | summarize | extract_artifact | publish
    -- Phase 1A 无 upload job——音频上传是 API 同步完成
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    -- pending | running | succeeded | failed | permanently_failed | cancelled
    input_payload JSONB NOT NULL DEFAULT '{}',
    output_payload JSONB,
    idempotency_key VARCHAR(128) UNIQUE NOT NULL,
    retry_count INT NOT NULL DEFAULT 0,
    max_retries INT NOT NULL DEFAULT 3,
    backoff_seconds INT NOT NULL DEFAULT 30,
    timeout_seconds INT NOT NULL DEFAULT 300,
    next_run_at TIMESTAMPTZ,
    locked_by VARCHAR(64),
    locked_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_jobs_fetch ON jobs(status, next_run_at)
    WHERE status IN ('pending')
       OR (status = 'failed' AND retry_count < max_retries);
CREATE INDEX idx_jobs_session ON jobs(session_id);
CREATE INDEX idx_jobs_heartbeat ON jobs(heartbeat_at)
    WHERE status = 'running';

CREATE TABLE workflow_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id),
    job_id UUID REFERENCES jobs(id),
    event_type VARCHAR(64) NOT NULL,
    from_status VARCHAR(32),
    to_status VARCHAR(32),
    actor_id UUID,
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_wf_events_session ON workflow_events(session_id);

CREATE TABLE artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id),
    artifact_type VARCHAR(32) NOT NULL,
    -- meeting_minutes | decision_record | faq_draft | sop_draft
    status VARCHAR(16) NOT NULL DEFAULT 'draft',
    -- draft | pending_review | approved | rejected | published | retracted
    title TEXT,
    content JSONB NOT NULL,
    assigned_reviewer_id UUID REFERENCES users(id),  -- Phase 1B 使用；Phase 1A 为 NULL，Owner 自审
    reviewed_by UUID REFERENCES users(id),
    reviewed_at TIMESTAMPTZ,
    review_comment TEXT,
    feishu_doc_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_artifacts_session ON artifacts(session_id);
CREATE INDEX idx_artifacts_status ON artifacts(status);
CREATE INDEX idx_artifacts_reviewer ON artifacts(assigned_reviewer_id)
    WHERE status = 'pending_review';

CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID,
    artifact_id UUID,
    actor_id UUID NOT NULL,
    -- system/agent 写日志时，使用触发该 session 的 user_id 作为 actor_id（追踪责任链）
    actor_type VARCHAR(16) NOT NULL,  -- user | system | agent
    action VARCHAR(64) NOT NULL,
    details JSONB NOT NULL,
    -- ✅ status change, metadata, content_hash, reason
    -- ❌ raw audio, full transcript, artifact body, PII
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_session ON audit_logs(session_id);
CREATE INDEX idx_audit_created ON audit_logs(created_at);
-- Phase 1A: service 层强制只 INSERT。
-- 部署脚本配置 DB 层权限（CREATE ROLE app_runtime; GRANT INSERT; REVOKE UPDATE,DELETE）

CREATE TABLE deletion_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL,
    job_type VARCHAR(32) NOT NULL,
    -- delete_artifact_rows | delete_local_audio | delete_feishu_docs
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    payload JSONB NOT NULL,
    retry_count INT DEFAULT 0,
    max_retries INT DEFAULT 3,
    next_run_at TIMESTAMPTZ DEFAULT now(),
    error_message TEXT,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

### 2.2 Alembic migration（Python）

```python
# alembic/versions/001_initial.py
"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-06-11
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID, INET

revision = '001'
down_revision = None

def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table('organizations',
        sa.Column('id', UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )

    op.create_table('users',
        sa.Column('id', UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('org_id', UUID(), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('email', sa.String(255), unique=True, nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('display_name', sa.String(128), nullable=False),
        sa.Column('role', sa.String(16), nullable=False, server_default='owner'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('idx_users_org', 'users', ['org_id'])

    op.create_table('devices',
        sa.Column('id', UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('owner_id', UUID(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('device_name', sa.String(128)),
        sa.Column('device_key', sa.String(64), unique=True, nullable=False),
        sa.Column('bound_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )

    op.create_table('sessions',
        sa.Column('id', UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('device_id', UUID(), sa.ForeignKey('devices.id'), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='idle'),
        sa.Column('consent_granted', sa.Boolean(), server_default='false'),
        sa.Column('consent_granted_at', sa.DateTime(timezone=True)),
        sa.Column('audio_key', sa.Text()),
        sa.Column('audio_source', sa.String(16), server_default='phone_mic'),
        sa.Column('audio_duration_seconds', sa.Integer()),
        sa.Column('deleted_at', sa.DateTime(timezone=True)),
        sa.Column('retracted_by', UUID(), sa.ForeignKey('users.id')),
        sa.Column('retraction_reason', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('idx_sessions_user', 'sessions', ['user_id'])
    op.create_index('idx_sessions_status', 'sessions', ['status'])

    op.create_table('jobs',
        sa.Column('id', UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('session_id', UUID(), sa.ForeignKey('sessions.id'), nullable=False),
        sa.Column('job_type', sa.String(64), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='pending'),
        sa.Column('input_payload', JSONB(), nullable=False, server_default='{}'),
        sa.Column('output_payload', JSONB()),
        sa.Column('idempotency_key', sa.String(128), unique=True, nullable=False),
        sa.Column('retry_count', sa.Integer(), server_default='0'),
        sa.Column('max_retries', sa.Integer(), server_default='3'),
        sa.Column('backoff_seconds', sa.Integer(), server_default='30'),
        sa.Column('timeout_seconds', sa.Integer(), server_default='300'),
        sa.Column('next_run_at', sa.DateTime(timezone=True)),
        sa.Column('locked_by', sa.String(64)),
        sa.Column('locked_at', sa.DateTime(timezone=True)),
        sa.Column('heartbeat_at', sa.DateTime(timezone=True)),
        sa.Column('error_message', sa.Text()),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.execute("""
        CREATE INDEX idx_jobs_fetch ON jobs(status, next_run_at)
        WHERE status IN ('pending')
           OR (status = 'failed' AND retry_count < max_retries)
    """)
    op.create_index('idx_jobs_session', 'jobs', ['session_id'])
    op.execute("""
        CREATE INDEX idx_jobs_heartbeat ON jobs(heartbeat_at)
        WHERE status = 'running'
    """)

    op.create_table('workflow_events',
        sa.Column('id', UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('session_id', UUID(), sa.ForeignKey('sessions.id'), nullable=False),
        sa.Column('job_id', UUID(), sa.ForeignKey('jobs.id')),
        sa.Column('event_type', sa.String(64), nullable=False),
        sa.Column('from_status', sa.String(32)),
        sa.Column('to_status', sa.String(32)),
        sa.Column('actor_id', UUID()),
        sa.Column('payload', JSONB()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('idx_wf_events_session', 'workflow_events', ['session_id'])

    op.create_table('artifacts',
        sa.Column('id', UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('session_id', UUID(), sa.ForeignKey('sessions.id'), nullable=False),
        sa.Column('artifact_type', sa.String(32), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='draft'),
        sa.Column('title', sa.Text()),
        sa.Column('content', JSONB(), nullable=False),
        sa.Column('assigned_reviewer_id', UUID(), sa.ForeignKey('users.id')),
        sa.Column('reviewed_by', UUID(), sa.ForeignKey('users.id')),
        sa.Column('reviewed_at', sa.DateTime(timezone=True)),
        sa.Column('review_comment', sa.Text()),
        sa.Column('feishu_doc_id', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('idx_artifacts_session', 'artifacts', ['session_id'])
    op.create_index('idx_artifacts_status', 'artifacts', ['status'])
    op.execute("""
        CREATE INDEX idx_artifacts_reviewer ON artifacts(assigned_reviewer_id)
        WHERE status = 'pending_review'
    """)

    op.create_table('audit_logs',
        sa.Column('id', UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('session_id', UUID()),
        sa.Column('artifact_id', UUID()),
        sa.Column('actor_id', UUID(), nullable=False),
        sa.Column('actor_type', sa.String(16), nullable=False),
        sa.Column('action', sa.String(64), nullable=False),
        sa.Column('details', JSONB(), nullable=False),
        sa.Column('ip_address', INET()),
        sa.Column('user_agent', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('idx_audit_session', 'audit_logs', ['session_id'])
    op.create_index('idx_audit_created', 'audit_logs', ['created_at'])
    # Phase 1A: service 层强制只 INSERT。DB 层权限由部署脚本配置，不写在 migration 里。

    op.create_table('deletion_jobs',
        sa.Column('id', UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('session_id', UUID(), nullable=False),
        sa.Column('job_type', sa.String(32), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('payload', JSONB(), nullable=False),
        sa.Column('retry_count', sa.Integer(), server_default='0'),
        sa.Column('max_retries', sa.Integer(), server_default='3'),
        sa.Column('next_run_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('error_message', sa.Text()),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )


def downgrade():
    op.drop_table('deletion_jobs')
    op.drop_table('audit_logs')
    op.drop_table('artifacts')
    op.drop_table('workflow_events')
    op.drop_table('jobs')
    op.drop_table('sessions')
    op.drop_table('devices')
    op.drop_table('users')
    op.drop_table('organizations')
```

---

## 3. 完整 API 列表

### 3.1 认证（Auth）

| 方法 | 路径 | 角色 | 说明 |
|---|---|---|---|
| `POST` | `/api/v1/auth/register` | 无需认证 | 注册（创建 org + owner）。Phase 1A 所有用户均为 owner |
| `POST` | `/api/v1/auth/login` | 无需认证 | 登录，返回 JWT access_token（1h）。Phase 1A 不做 refresh token |

### 3.2 采集会话（Sessions）

| 方法 | 路径 | 角色 | 说明 |
|---|---|---|---|
| `POST` | `/api/v1/sessions` | Owner | 创建 session（idle），含 consent 声明 |
| `PATCH` | `/api/v1/sessions/{id}/status` | Owner | 状态转移：idle→capturing, capturing→processing（停止采集） |
| `PATCH` | `/api/v1/sessions/{id}/consent` | Owner | 声明确认 |
| `POST` | `/api/v1/sessions/{id}/audio` | Owner | 上传音频文件 → API 同步完成，写入 audio_key。Phase 1A 存到 local filesystem。**Worker 从 transcribe 开始，无 upload job** |
| `GET` | `/api/v1/sessions/{id}` | Owner | session 详情 + job 状态链 |
| `GET` | `/api/v1/sessions` | Owner | 列出我的 sessions |
| `POST` | `/api/v1/sessions/{id}/cancel` | Owner | 取消 session |
| `POST` | `/api/v1/sessions/{id}/retract` | Owner | 撤回 + 级联删除（→ 触发 Retract Saga，见 Ticket 11） |

### 3.3 工件（Artifacts）

| 方法 | 路径 | 角色 | 说明 |
|---|---|---|---|
| `GET` | `/api/v1/artifacts` | Owner | 所有工件列表。Phase 1A 无 Reviewer 分配，全部 Owner 自审 |
| `GET` | `/api/v1/artifacts/{id}` | Owner | 工件详情 |
| `PATCH` | `/api/v1/artifacts/{id}/review` | Owner | 审核：approve 或 reject（含理由） |
| `PATCH` | `/api/v1/artifacts/{id}` | Owner | 编辑工件内容 |
| `POST` | `/api/v1/artifacts/{id}/publish` | Owner | 手动触发 publish job（飞书 stub） |

### 3.4 审计（Audit）

| 方法 | 路径 | 角色 | 说明 |
|---|---|---|---|
| `GET` | `/api/v1/audit-logs` | Owner | 查询审计日志（分页 + 筛选） |
| `GET` | `/api/v1/audit-logs?session_id={id}` | Owner | 某 session 的完整审计链 |

### 3.5 系统（System）

| 方法 | 路径 | 角色 | 说明 |
|---|---|---|---|
| `GET` | `/api/v1/health` | 无需认证 | 健康检查 |
| `GET` | `/api/v1/me` | 任意 | 当前用户信息 |

---

## 4. Vertical Slice Tickets（Phase 1A）

### Ticket 1: 项目骨架与 Docker Compose

**描述**：搭建 backend 目录结构、pyproject.toml、FastAPI 入口、Dockerfile、docker-compose.yml。启动后健康检查通过。

**范围**：
- `backend/pyproject.toml`：依赖（fastapi, uvicorn, sqlalchemy, asyncpg, alembic, python-jose, bcrypt, openai, httpx, pytest, pytest-asyncio）
- `backend/app/main.py`：FastAPI app，CORS，router 注册
- `backend/app/config.py`：Settings class（DB_URL, OPENAI_API_KEY, STORAGE_DIR 等）
- `docker-compose.yml`：Phase 1A 仅 **postgres（16-alpine）+ backend**。backend 挂载 volume `./data/audio:/data/audio`（local storage stub 音频目录）。不加 MinIO/console
- `.env.example`

**验收标准**：
1. `docker compose up -d` 后 `/api/v1/health` 返回 `{"status": "ok"}`
2. PostgreSQL 容器启动，backend 可连接
3. `alembic upgrade head` 创建所有表

---

### Ticket 2: 数据库 Migration

**描述**：实现 Alembic migration `001_initial.py`，含 artifacts.assigned_reviewer_id（Phase 1B 使用，Phase 1A 为 NULL）。

**范围**：
- `alembic.ini` + `alembic/env.py`
- `alembic/versions/001_initial.py`

**验收标准**：
1. `alembic upgrade head` 成功创建 9 张表
2. `alembic downgrade -1` 成功删除所有表
3. `audit_logs` ORM model 只有 `create()`，无 `update()`/`delete()`

---

### Ticket 3: 认证模块

**描述**：User 模型、JWT 签发/校验、register/login。Phase 1A 所有用户 owner，无 refresh token。**注册时自动创建 virtual_phone_mic 设备**（device_key=`virtual-{user_id}`），解决 sessions.device_id NOT NULL 约束。

**范围**：
- `backend/app/auth/models.py`：User ORM
- `backend/app/auth/service.py`：hash_password(bcrypt)，verify_password，create_jwt(1h)，verify_jwt，**注册时同时 INSERT devices 表**
- `backend/app/auth/router.py`：POST /auth/register, POST /auth/login
- `backend/app/dependencies.py`：get_current_user

**验收标准**：
1. 注册创建用户 + org + virtual_phone_mic device，密码 bcrypt 哈希（Argon2id 或 bcrypt，唯一随机 salt）
2. 登录返回 JWT access_token，含 sub/org_id/role=owner
3. 无 JWT 返回 401；过期返回 401

---

### Ticket 4: Session 生命周期 + 音频上传

**描述**：Session CRUD、状态转移、声明确认、音频上传。音频 API 同步上传到 local filesystem stub，写入 audio_key。Worker 从 transcribe 开始。

**范围**：
- `backend/app/sessions/models.py`：Session ORM
- `backend/app/sessions/service.py`：can_transition
- `backend/app/sessions/router.py`：所有 session 端点
- `backend/app/storage/base.py`：StorageProvider 接口
- `backend/app/storage/local.py`：Phase 1A local stub（`/data/audio/`）

**验收标准**：
1. 创建 session 状态 idle，consent_granted=false
2. 无 consent 时 capturing 被拒（403）
3. consent 后可 idle→capturing→processing
4. 非法状态转移被拒
5. 上传音频 → audio_key 写入 → 文件存 `/data/audio/{uuid}.opus`

---

### Ticket 5: Workflow Orchestrator + Background Worker

**描述**：Job 创建/重试、Worker 主循环。Worker 从 transcribe 开始（Phase 1A 无 upload job）。orchestrator/models.py 不含 Artifact（归 artifacts/models.py）。

**范围**：
- `backend/app/orchestrator/models.py`：Job, WorkflowEvent ORM
- `backend/app/orchestrator/service.py`：create_jobs_for_session（transcribe→summarize+extract_artifact 链。**不含 publish——publish job 在 Ticket 8 审核通过后创建**），transition_job，retry_job
- `backend/app/orchestrator/worker.py`：主循环（FOR UPDATE SKIP LOCKED + 心跳 + job_type 分发）

**验收标准**：
1. 停止采集后，Worker 创建 transcribe job 并执行
2. 失败按指数退避重试，3 次后 permanently_failed
3. Worker 重启不丢任务
4. 120 秒无心跳的 running job 释放回队列
5. 同 session 同 job_type 不创建重复 job（并发检查含 retry 条件）

---

### Ticket 6: Capture Service（Whisper 转写）

**描述**：transcribe job handler，调 Whisper API。

**范围**：
- `backend/app/providers/base.py`：TranscriptionProvider 接口
- `backend/app/providers/openai_whisper.py`：实现
- `backend/app/agents/capture.py`：handle_transcribe_job

**验收标准**：
1. 音频→转写文本→job.output_payload: `{"transcript":"...","segments":[...],"language":"zh"}`
2. 失败自动重试
3. Mock provider 可用于测试

---

### Ticket 7: Distiller Service（LLM 提炼）

**描述**：distill job handler，调 LLM 提取结构化工件。

**范围**：
- `backend/app/providers/base.py`：LLMProvider 接口
- `backend/app/providers/openai_llm.py`：实现
- `backend/app/agents/distiller.py`：handle_distill_job → 创建 Artifact
- `backend/app/artifacts/schemas.py`：Pydantic schemas
- `backend/app/artifacts/models.py`：Artifact ORM（唯一归属）

**验收标准**：
1. 转写→LLM→结构化 JSON（meeting_minutes/decision_record/faq_draft/sop_draft）
2. Pydantic 校验失败自动重试
3. artifact.status=pending_review，session.status→needs_review
4. Mock provider 可用于测试

---

### Ticket 8: 工件审核 + 发布

**描述**：工件列表、审核（批准/驳回）、编辑、发布。Phase 1A Owner 自审。

**范围**：
- `backend/app/artifacts/router.py`：GET/PATCH /artifacts
- `backend/app/agents/integration.py`：handle_publish_job → 飞书 stub（返回 fake doc_id）
- `backend/app/orchestrator/service.py`：审核后 session 状态转移

**验收标准**：
1. Owner 列出所有 pending_review 工件
2. 批准→全部批准后 session→publishing
3. 驳回→记录理由→触发 distill 重跑
4. 未审核工件发布被拒
5. publish job 飞书 stub 成功

---

### Ticket 9: 信任守护（规则引擎 + 审计）

**描述**：L1+L2 硬约束规则引擎、L3 LLM 辅助敏感检测、审计日志。

**范围**：
- `backend/app/trust/policy_engine.py`：check_consent, check_reviewed, check_publish, check_retract
- `backend/app/trust/redlines.py`：10 条红线编码
- `backend/app/trust/sensitive_check.py`：LLM 标记敏感信息（不决策）
- `backend/app/audit/service.py`：audit_write（只 INSERT）
- `backend/app/audit/models.py`：AuditLog ORM
- `backend/app/audit/router.py`：GET /audit-logs

**验收标准**：
1. 无 consent→403
2. 未审核→publish 被拒
3. 非本人 artifact 不可删除
4. LLM 敏感标记 PII→工件仍 pending_review，不自动脱敏
5. audit_logs 只 INSERT（ORM 无 update/delete；部署脚本加 DB 权限）

---

### Ticket 10: 端到端集成测试

**描述**：完整 Vertical Slice 集成测试：mock 音频→Agent→审核→发布→撤回。

**范围**：
- `backend/tests/integration/test_e2e_vertical_slice.py`
- Mock LLM/Whisper provider
- 覆盖 Happy Path + Failure + Review Cycle + Retract

**验收标准**：
1. Happy Path：全链路通过
2. Failure：transcribe 失败→重试→成功
3. Review：驳回→重新提炼→再审核→通过
4. Retract：撤回→deletion_jobs→tombstone→audit 完整

---

### Ticket 11: Retract Saga + deletion_jobs Worker

**描述**：撤回完整 Saga 流程：软删→deletion_jobs→异步 Worker→tombstone。**这是独立的 ticket，不是 T9 的一句交代。**

**范围**：
- `backend/app/sessions/service.py`：retract_session → 软删（deleted_at）+ 创建 deletion_jobs
- `backend/app/orchestrator/worker.py` 新增：deletion_jobs 轮询 + 执行
- deletion_job types：`delete_artifact_rows`, `delete_local_audio`, `delete_feishu_docs`

**验收标准**：
1. `POST /sessions/{id}/retract` → 200，session.deleted_at 非空
2. deletion_jobs 异步执行完成后 session.status='retracted'
3. 飞书 stub 失败不阻断撤回（deletion_job 标记 failed，状态留在 deletion_jobs 表。Phase 1A 不新增 pending_deletion 表）
4. session tombstone 保留 id/user_id/device_id/deleted_at/retracted_by/retraction_reason
5. artifacts 硬删除
6. audit_logs 完整记录 retract_request→retract_complete

---

### Ticket 12: README + 开发者指南

**描述**：README.md，含项目概述、快速启动、API curl 示例、测试说明。

**验收标准**：
1. `docker compose up` 后新人 curl 跑通 register→login→session→upload→review→publish→retract 全流程
2. 包含运行测试的命令

---

## 4b. Phase 1B 预留 Tickets（本次不分配）

| Ticket | 内容 | 前置 |
|---|---|---|
| 1B-1 | Next.js 控制台（登录/Dashboard/审核/审计） | Phase 1A 完成 |
| 1B-2 | RBAC 权限（Contributor/Reviewer + assigned_reviewer_id 分配） | Phase 1A 完成 |
| 1B-3 | MinIO/S3 storage provider 替换 local stub | Phase 1A 完成 |
| 1B-4 | Refresh token 表 + 策略 | Phase 1A 完成 |
| 1B-5 | Flutter BLE Bridge（独立 repo） | 工牌硬件就绪 |

---

## 5. 验收标准总表

| # | 验收项 | 对应 Ticket |
|---|---|---|
| AC-01 | `docker compose up` 后 `/api/v1/health` 返回 200 | T1 |
| AC-02 | Alembic migration 可正反执行 | T2 |
| AC-03 | JWT login/register 完整 | T3 |
| AC-04 | Session 状态转移正确 | T4 |
| AC-05 | 无 consent 时采集被拒 | T4+T9 |
| AC-06 | Worker 从 transcribe 开始执行 job 链 | T5 |
| AC-07 | Job 失败自动重试，3 次后 permanently_failed | T5 |
| AC-08 | Worker 重启不丢任务 | T5 |
| AC-09 | 音频→转写→job.output_payload | T6 |
| AC-10 | 转写→LLM→结构化工件（Schema 校验通过） | T7 |
| AC-11 | 工件审核：批准/驳回/重提炼 | T8 |
| AC-12 | 未审核工件无法发布 | T8+T9 |
| AC-13 | 撤回后 session tombstone + artifacts 硬删除 + audit 完整 | T11 |
| AC-14 | audit_logs 只 INSERT | T9 |
| AC-15 | 端到端测试通过（Happy+Failure+Review+Retract） | T10 |
| AC-16 | README 覆盖 curl 全流程 | T12 |

---

## 6. 测试计划

### 6.1 单元测试

| 模块 | 文件 | 重点 |
|---|---|---|
| Auth | `test_auth.py` | bcrypt、JWT 签发/过期/篡改 |
| Sessions | `test_sessions.py` | 状态转移、consent 检查 |
| Orchestrator | `test_orchestrator.py` | Job 创建/幂等/重试/心跳/Worker |
| Agents | `test_agents.py` | Mock provider 转写/提炼、Schema 校验 |
| Artifacts | `test_artifacts.py` | 审核状态转移、发布 stub |
| Trust | `test_trust.py` | 10 条红线、L1+L2 拦截、敏感检测 |
| Retract | `test_retract.py` | Saga 步骤、deletion_jobs、tombstone |

### 6.2 集成测试

| 测试 | 文件 | 重点 |
|---|---|---|
| E2E Happy Path | `test_e2e_vertical_slice.py` | 全链路 |
| E2E Failure | 同上 | Transcribe 失败→重试→成功 |
| E2E Review | 同上 | 驳回→重提炼→再审核 |
| E2E Retract | 同上 | 撤回→deletion_jobs→tombstone |
| Worker Resilience | `test_worker.py` | Worker 重启不丢任务；心跳超时释放 |

### 6.3 测试基础设施

```python
# conftest.py 关键 fixtures

@pytest.fixture
def test_db():
    """每个测试独立事务，自动回滚"""
    ...

@pytest.fixture
def test_client(test_db):
    """FastAPI TestClient，注入 test_db"""
    ...

@pytest.fixture
def mock_whisper_provider():
    """固定转写文本，不调真实 API"""
    ...

@pytest.fixture
def mock_llm_provider():
    """固定结构化 JSON，不调真实 API"""
    ...

@pytest.fixture
def auth_headers(test_client):
    """创建测试用户并返回 JWT header"""
    ...

# Mock 规则：单元测试+集成测试默认用 mock provider。仅 manual smoke test 用真实 API。
```

### 6.4 CI（GitHub Actions，Phase 1B 配置）

```yaml
name: Test
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_DB: ai_badge_test
          POSTGRES_PASSWORD: test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: alembic upgrade head
      - run: pytest --cov=app --cov-report=term
```

---

## 7. Ticket 依赖关系

```
T1 (骨架) ──▶ T2 (migration) ──▶ T3 (认证)
                                      │
                    ┌─────────────────┤
                    ▼                 ▼
              T4 (sessions)    T5 (orchestrator+worker)
                    │                 │
                    └────────┬────────┘
                             ▼
                      T6 (capture)
                             │
                             ▼
                      T7 (distiller)
                             │
                             ▼
                      T8 (review+publish)
                             │
                    ┌────────┴────────┐
                    ▼                 ▼
              T9 (trust+audit)   T11 (retract saga)
                    │                 │
                    └────────┬────────┘
                             ▼
                      T10 (e2e tests)
                             │
                             ▼
                      T12 (docs)
```

建议开发顺序：T1→T2→T3→T4+T5（可并行）→T6→T7→T8→T9+T11（可并行）→T10→T12。
