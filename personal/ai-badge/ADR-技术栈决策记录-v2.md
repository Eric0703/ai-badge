# AI 工牌 — 架构决策记录 ADR（v2.3）

> 修订时间：2026-06-11  
> 决策人：大头  
> 设计原则：Agent-first，专家技能沉淀，信任优先  
> 范围：仅软件层  
> 版本历史：v1（初版）→ v2（两轮评审重写 ADR-002，新增 011~015）→ v2.1（一致性 cleanup）→ v2.2（文档细节冻结）→ v2.3（streaming 模式 total=0 残留修复）

---

## 1. 总体架构图

```
┌──────────────────────────────────────────────────────────────┐
│                      工牌硬件（用户自理）                       │
│  BLE 音频 / 控制指令 / 指纹认证结果 / 状态灯                   │
└──────────────┬───────────────────────────────────────────────┘
               │ BLE
┌──────────────▼───────────────────────────────────────────────┐
│              手机端 BLE Bridge（最小原生/Flutter）              │
│  BLE 连接管理 / 音频接收重组 / 上传后端 / 配网                │
└──────────────┬───────────────────────────────────────────────┘
               │ HTTPS
┌──────────────▼───────────────────────────────────────────────┐
│                    API 服务 (FastAPI)                         │
│                                                               │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐   │
│  │ 认证与权限    │  │ Workflow     │  │ 信任守护           │   │
│  │ (policy      │  │ Orchestrator │  │ (rule engine +     │   │
│  │  engine)     │  │ (state       │  │  LLM advisor +     │   │
│  │              │  │  machine)    │  │  hard constraint)  │   │
│  └─────────────┘  └──────┬───────┘  └────────────────────┘   │
│                           │                                    │
│              ┌────────────┼────────────┐                      │
│              │            │            │                      │
│     ┌────────▼───┐ ┌─────▼──────┐ ┌───▼──────────┐           │
│     │ Capture    │ │ Distiller  │ │ Integration  │           │
│     │ Service    │ │ Service    │ │ Service      │           │
│     │ (LLM       │ │ (LLM       │ │ (connector)  │           │
│     │  Agent)    │ │  Agent)    │ │              │           │
│     └────────────┘ └────────────┘ └──────────────┘           │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │                Background Worker                      │    │
│  │  jobs 表轮询 / 转写 / LLM 调用 / 重试 / 超时         │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────┬───────────────────────────────────────────────┘
               │
   ┌───────────┼───────────┬──────────────┐
   │           │           │              │
┌──▼──┐  ┌────▼────┐ ┌───▼────┐  ┌──────▼──────┐
│ PG  │  │   S3    │ │ Whisper│  │ 飞书 API    │
│     │  │         │ │  API   │  │             │
└─────┘  └─────────┘ └────────┘  └─────────────┘

┌──────────────────────────────────────────────────────────────┐
│               桌面控制台 (Next.js Web)                        │
│  工件审核 / 修改 / 驳回 / 版本对比 / 权限管理 / 审计查看       │
└──────────────────────────────────────────────────────────────┘
```

### 模块角色定义（非全部是 Agent）

| 模块 | 类型 | 说明 |
|---|---|---|
| **Capture Service** | LLM Agent | 语音→转写→标注不确定项。唯一含有 LLM 调用的采集环节 |
| **Distiller Service** | LLM Agent | 转写文本→结构化工件（MD/FAQ/SOP）。LLM 推理核心 |
| **Integration Service** | Connector | 工件→飞书/Skill库。确定性 API 调用，无 LLM |
| **Workflow Orchestrator** | State Machine | 跨 Session 的作业编排、重试、幂等、补偿。确定性 |
| **Trust Guardian** | Policy Engine + LLM Advisor | 红线规则引擎（确定性）+ 敏感内容辅助识别（LLM）+ 不可绕过约束 |
| **Background Worker** | Background Worker | jobs 表轮询执行，独立进程 |
| **Auth & Permission** | Policy Engine | JWT + RBAC，确定性 |
| **BLE Bridge (手机端)** | Client | BLE 连接、音频重组、上传 |

---

## 2. MVP 技术栈总表

| 层 | 选型 | 类型 | MVP |
|---|---|---|---|
| 后端语言 | Python 3.11 + FastAPI | — | ✅ |
| Workflow 编排 | 自研持久化 Workflow Orchestrator | State Machine | ✅ |
| 后台任务 | PostgreSQL jobs 表 + 独立 worker 进程 | Background Worker | ✅ |
| 数据库 | PostgreSQL（唯一数据库） | — | ✅ |
| LLM | OpenAI API + provider adapter | — | ✅ |
| 语音转写 | OpenAI Whisper API | — | ✅ |
| 文件存储 | S3 兼容对象存储 | — | ✅ |
| 前端控制台 | Next.js (React) + Tailwind | — | ✅ |
| 手机端 | 最小 Flutter BLE Bridge | Client | ✅ |
| 部署 | Docker Compose 单机 | — | ✅ |
| 缓存/队列 | 无（MVP 不引入 Redis） | — | ❌ |
| 序列化 | JSON over BLE GATT（控制面） | — | ✅ |
| BLE 音频 | GATT Write/Notify + 自定义分片协议 | — | ✅ |
| 消息队列 | 无（Worker 轮询 jobs 表） | — | ❌ |
| Node.js 后端 | 不引入 | — | ❌ |
| Protobuf | 不引入 | — | ❌ |
| LangGraph | 不引入 | — | ❌ |
| K8s | 不引入 | — | ❌ |

---

## 3. 架构决策记录

---

### ADR-001：后端语言 — Python + FastAPI

**选择**：Python 3.11 + FastAPI

**放弃项**：Node.js (Express/Hono)、Go (Gin/Fiber)

**选择理由**：
1. LLM/Agent SDK 生态不可替代：OpenAI SDK、Whisper、Pydantic 都是 Python 一等公民
2. Pydantic 是结构化输出的基石：所有工件 schema、状态机事件都需要严格的类型约束
3. FastAPI async 原生匹配 Agent 的 I/O 密集链路
4. 团队认知成本最低

**风险**：性能天花板（GIL），但 MVP 并发量不触及瓶颈

**替代方案**：1.0 后性能敏感模块（如工牌网关）可单独用 Go

**未来迁移成本**：低。Agent 核心是编排逻辑，换语言主要是重写路由和 Schema

**MVP 是否必须引入**：是

**验收标准**：所有 API 端点返回 OpenAPI 3.0 文档，Pydantic 模型覆盖所有输入输出

---

### ADR-002（重点修订）：Workflow 编排 — 自研持久化 Workflow Orchestrator vs LangGraph

#### 重新评估

上一版说「20 行 Python 状态枚举就能表达」，这个判断**确实过轻**。AI 工牌的真实流程不是简单的 `Idle → Capturing → Done`，而是包含异步等待、LLM 调用、人工确认、失败补偿的多阶段流水线。

#### 两方案正面比较

**方案 A：LangGraph**

LangGraph 的核心能力：
- 有向图定义 Agent 工作流，节点可以是 LLM 调用或确定性函数
- 内置 `Checkpointer` 持久化状态（支持 PostgreSQL）
- 内置 `interrupt()` 实现人工确认点
- 内置节点级重试
- 支持 streaming 和分支/合并

**方案 B：自研持久化 Workflow Orchestrator**

自行实现基于 PostgreSQL 的作业编排器，含：
- `sessions` / `jobs` / `workflow_events` / `artifacts` / `audit_logs` 五张表
- 独立的 Background Worker 进程轮询 jobs 表执行
- 显式状态转移规则（确定性）
- 幂等键、失败重试、超时、人工确认点全部显式编码

#### 以 AI 工牌的真实工作流做对比

| 工作流步骤 | LangGraph 实现方式 | 自研 Orchestrator 实现方式 |
|---|---|---|
| 采集开始 | `add_node("start_capture")` → checkpointer 保存 | `INSERT INTO sessions` + `INSERT INTO workflow_events` |
| 声明确认 | `interrupt()` 暂停 → 用户确认后 `resume` | `sessions.status = 'awaiting_consent'` → 用户确认 → `'capturing'` |
| 停止采集 + 音频上传 | 节点完成后自动流转到 upload 节点 | Worker 检测 `session.status = 'stopped'` → 创建 `upload` job |
| 转写 | `add_node("transcribe")` 调用 Whisper API | Worker 取 `job_type='transcribe'` → 调 API → 更新 job status |
| LLM 提炼 | `add_node("distill", llm=...)` 调 LLM | Worker 取 `job_type='distill'` → 调 LLM → 写入 artifacts 表 |
| 人工审核 | `interrupt()` → 等待审核 → resume/reject | `sessions.status = 'needs_review'` → 审核 API → approve/reject → 状态转移 |
| 发布飞书 | `add_node("publish")` 调飞书 API | Worker 取 `job_type='publish'` → 调飞书 API → 更新状态 |
| 发布失败重试 | 节点异常 → 自动重试（配置 max_retries） | Worker 检测 failed → retry_count < max → backoff → 重试 |
| 用户撤回 + 级联删除 | 需自行实现删除逻辑 | 确定性规则：查所有下游 artifact → 逐条删除 → 写审计 |
| 审计日志 | 需在 LLM 节点中手动写日志 | 每个状态转移都写入 audit_logs 表，和业务逻辑解耦 |

#### 推荐选择

**选择**：自研持久化 Workflow Orchestrator

**放弃项**：LangGraph

#### 选择理由

1. **LangGraph 的核心价值在你的场景里用不上**。LangGraph 最擅长的是：LLM 动态决定下一步（ReAct 循环）、复杂的分支/合并推理图、多 Agent 协商。你的工作流是**确定性 DAG**——采集→转写→提炼→审核→发布。每一步的下一站是固定的，不需要 LLM 做路由决策。

2. **审计是安全需求，不是业务日志**。LangGraph 的 checkpointer 是为「恢复执行」设计的，不是为「合规审计」设计的。你需要知道谁在什么时间做了什么操作、之前状态是什么、之后状态是什么、谁审批的。用 LangGraph 的 checkpointer 做审计意味着你的合规数据锁在框架内部——审计查询、导出、保留策略都受限于 LangGraph 的实现。自研表直接查 SQL。

3. **人工确认点是显式的，不是框架黑盒**。LangGraph 的 `interrupt()` 把状态序列化到框架内部。你的需求是：审核者可以看到「这个工件在等待审核」的状态并可以在 UI 操作。自研表让前端直接 `SELECT * FROM sessions WHERE status = 'needs_review'`，不需要通过 LangGraph 的 API 间接查询。

4. **你的 Agent 不走 ReAct 循环**。提炼 Agent 是「一次 LLM 调用 → 结构化输出 → 结束」。它不需要「观察→思考→行动」的循环。LangGraph 的设计重心恰好是这个循环。

5. **框架风险**。LangChain/LangGraph API 在过去 12 个月经历了多次 breaking change。你的产品核心工作流不应该绑定一个仍在剧烈变化的框架。

#### 自研 Orchestrator 不是简单枚举——完整设计

##### 数据库表

```sql
-- sessions: 一次采集会话
CREATE TABLE sessions (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    device_id UUID NOT NULL,
    status VARCHAR(32) NOT NULL,  -- idle/capturing/paused/processing/processing_failed/needs_review/reviewing/approved/publishing/publish_failed/published/retracting/retracted/cancelled
    consent_granted BOOLEAN DEFAULT FALSE,
    consent_granted_at TIMESTAMPTZ,
    audio_key TEXT,               -- S3 key
    audio_duration_seconds INT,
    deleted_at TIMESTAMPTZ,       -- tombstone: 撤回后设置，保留最小元数据供 audit_logs JOIN
    retracted_by UUID,            -- tombstone: 谁撤回了
    retraction_reason TEXT,       -- tombstone: 撤回原因
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ═══════════════════════════════════════════════════════════
-- CANONICAL SCHEMA: jobs
-- 本文档唯一权威 jobs 表定义。其他章节（如 ADR-011）仅引用，不复述。
-- ═══════════════════════════════════════════════════════════
CREATE TABLE jobs (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES sessions(id),
    job_type VARCHAR(64) NOT NULL,  -- upload/transcribe/summarize/extract_artifact/publish
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    -- pending | running | succeeded | failed | permanently_failed | cancelled
    -- 注意：retrying 不是独立状态。retry 时 status 保持 failed，
    -- 由 retry_count 和 next_run_at 控制重新执行。这样：
    --   - 查询待执行：WHERE status = 'pending'
    --        OR (status = 'failed' AND retry_count < max_retries AND next_run_at <= now())
    --   - 永久失败：status = 'permanently_failed'（retry_count >= max_retries 时设置）
    input_payload JSONB,           -- 幂等输入
    output_payload JSONB,
    idempotency_key VARCHAR(128) UNIQUE,
    retry_count INT DEFAULT 0,
    max_retries INT DEFAULT 3,
    backoff_seconds INT DEFAULT 30,
    timeout_seconds INT DEFAULT 300,
    next_run_at TIMESTAMPTZ,        -- NULL = 立即执行；有值 = 等到该时间再取
    locked_by VARCHAR(64),          -- worker 实例标识
    locked_at TIMESTAMPTZ,          -- worker 取走任务的时间
    heartbeat_at TIMESTAMPTZ,       -- worker 最后心跳。超过 N 秒无心跳视为 worker 死亡，任务释放
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_jobs_fetch ON jobs(status, next_run_at)
    WHERE status IN ('pending') OR (status = 'failed' AND retry_count < max_retries);
CREATE INDEX idx_jobs_session ON jobs(session_id);
CREATE INDEX idx_jobs_heartbeat ON jobs(heartbeat_at)
    WHERE status = 'running';

-- workflow_events: 状态转移事件（用于重建时间线）
CREATE TABLE workflow_events (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES sessions(id),
    job_id UUID REFERENCES jobs(id),
    event_type VARCHAR(64) NOT NULL,  -- status_change/job_created/job_completed/retry/user_action etc.
    from_status VARCHAR(32),
    to_status VARCHAR(32),
    actor_id UUID,                     -- user or system
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- artifacts: 结构化工件
CREATE TABLE artifacts (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES sessions(id),
    artifact_type VARCHAR(32) NOT NULL,  -- meeting_minutes/decision_record/faq_draft/sop_draft
    status VARCHAR(16) NOT NULL DEFAULT 'draft',  -- draft/pending_review/approved/rejected/published/retracted
    title TEXT,
    content JSONB NOT NULL,
    reviewed_by UUID,
    reviewed_at TIMESTAMPTZ,
    feishu_doc_id TEXT,               -- 飞书发布后的 ID
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- audit_logs: 审计日志（不可篡改）
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY,
    session_id UUID,              -- 外键引用 sessions(id)。sessions 做 tombstone 后仍可 JOIN
    artifact_id UUID,
    actor_id UUID NOT NULL,
    actor_type VARCHAR(16) NOT NULL,  -- user/system/agent
    action VARCHAR(64) NOT NULL,       -- session_start/consent_grant/audio_upload/transcribe/distill/review_approve/publish/retract/delete etc.
    details JSONB NOT NULL,
    -- 🔴 审计日志内容规则（强制执行，代码 review 必须检查）：
    --   ✅ 允许：状态变化（from_status → to_status）
    --   ✅ 允许：操作元数据（job_id, artifact_id, session_id, actor_id）
    --   ✅ 允许：内容 hash（SHA256(transcript), SHA256(artifact_content)）
    --   ✅ 允许：操作原因、驳回理由（人工输入）
    --   ❌ 禁止：原始录音全文 / 片段 / URL
    --   ❌ 禁止：完整转写文本
    --   ❌ 禁止：工件内容全文（MD / FAQ / SOP body）
    --   ❌ 禁止：PII（手机号、邮箱、身份证号、人脸特征）
    --   ❌ 禁止：before / after 中的敏感内容快照
    --
    -- 正确示例：
    --   { "from_status": "needs_review", "to_status": "approved",
    --     "artifact_id": "abc-123", "content_hash": "sha256:7d9e...",
    --     "reviewer_id": "user-456", "reason": "会议纪要与录音一致" }
    --
    -- 原因：用户撤回后，审计日志是唯一不可删除的数据。
    -- 如果审计日志里存了完整转写/工件正文/PII，撤回就失去意义——
    -- 用户的敏感数据仍然"永久保留"在另一个表里。
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ DEFAULT now()  -- 不可修改，不可删除
);
```

##### 状态转移规则

```
IDLE ──[用户点击采集，声明确认]──▶ CAPTURING
CAPTURING ──[用户暂停]──▶ PAUSED
PAUSED ──[用户恢复]──▶ CAPTURING
CAPTURING ──[用户停止]──▶ PROCESSING

PROCESSING 阶段（由 Orchestrator 自动创建 jobs）:
  1. 创建 upload job (pending)
  2. upload 完成 → 创建 transcribe job (pending)
  3. transcribe 完成 → 创建 summarize + extract_artifact jobs (并发)
  4. 全部成功 → sessions.status = 'needs_review'
  5. 任一失败 → 自动重试（最多 3 次）→ 全部失败 → sessions.status = 'processing_failed'

NEEDS_REVIEW ──[用户开始审核]──▶ REVIEWING
REVIEWING ──[全部批准]──▶ APPROVED
REVIEWING ──[驳回某工件]──▶ 该工件 status = 'rejected'，创建新的 distill job
  → 全部批准后 → APPROVED

APPROVED ──[Orchestrator 创建 publish jobs]──▶ PUBLISHING
PUBLISHING ──[全部发布成功]──▶ PUBLISHED
PUBLISHING ──[部分失败]──▶ 重试 → 全部成功 → PUBLISHED
PUBLISHING ──[全部失败达上限]──▶ PUBLISH_FAILED

PUBLISHED ──[用户撤回]──▶ RETRACTING
RETRACTING ──[级联删除完成]──▶ RETRACTED

从 IDLE/CAPTURING/PAUSED/PROCESSING/NEEDS_REVIEW 均可 → CANCELLED
```

##### 幂等键设计

每个 job 的 `idempotency_key`：
- `upload`: `SHA256(session_id + audio_checksum)`
- `transcribe`: `SHA256(session_id + "transcribe" + audio_key)`
- `distill`: `SHA256(session_id + "distill" + transcript_version)`
- `publish`: `SHA256(session_id + artifact_id + "publish" + target)`

Worker 在开始执行前检查 `idempotency_key` 是否已有 succeeded job，有则跳过。

##### 失败重试策略

```
retry_count 0 → 立即重试
retry_count 1 → 等待 backoff_seconds 后重试
retry_count 2 → 等待 backoff_seconds * 2 后重试
retry_count 3 → 标记 failed，不再重试
```

重试记录写入 `workflow_events`，event_type = `'retry'`。

##### 人工确认点

```
1. 采集声明确认：
   PATCH /sessions/{id}/consent → sessions.consent_granted = true
   → Orchestrator 放行才能进入 CAPTURING

2. 工件审核：
   PATCH /artifacts/{id}/review → { status: 'approved' | 'rejected', comment }
   → 全部审核通过 → sessions.status = 'approved'

3. 发布确认（可选 MVP 阶段自动发布，但保留手动触发接口）：
   POST /sessions/{id}/publish
```

##### Background Worker

独立进程，和 API 共享 PostgreSQL 连接池。

**取任务逻辑**（同时覆盖 pending 和等待重试的 failed）：
```python
while True:
    with db.transaction():
        job = db.execute("""
            SELECT * FROM jobs
            WHERE (
                status = 'pending'
                OR (status = 'failed'
                    AND retry_count < max_retries
                    AND next_run_at <= now())
            )
            ORDER BY next_run_at ASC NULLS FIRST, created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        """).first()
    if job:
        # 锁定任务
        db.execute("""
            UPDATE jobs SET
                status = 'running',
                locked_by = $1,
                locked_at = now(),
                heartbeat_at = now(),
                started_at = COALESCE(started_at, now())
            WHERE id = $2
        """, worker_id, job.id)
        execute_job(job)
    else:
        time.sleep(1)
```

**心跳机制**（在独立线程中运行）：
```python
# 每 30 秒更新一次心跳
db.execute("""
    UPDATE jobs SET heartbeat_at = now()
    WHERE locked_by = $1 AND status = 'running'
""", worker_id)

# 死 worker 检测（在取任务前执行）：
# 将超过 120 秒无心跳的 running 任务释放回队列
db.execute("""
    UPDATE jobs SET
        status = 'failed',
        next_run_at = now(),  -- 立即重试
        locked_by = NULL,
        locked_at = NULL,
        heartbeat_at = NULL
    WHERE status = 'running'
      AND heartbeat_at < now() - INTERVAL '120 seconds'
""")
```

#### 什么条件下需要切换到 LangGraph

- Agent 交互模式从「一次 LLM 调用→结构化输出」变为「LLM 多次调用→动态决策→工具调用→再决策」的 ReAct 循环时
- 工作流节点从现在的 ~8 个增长到 30+，且出现复杂的条件分支和并行汇聚时
- 需要 LLM 动态决定「下一步做什么」而非「下一步固定是什么」时

#### 风险

| 风险 | 缓解 |
|---|---|
| 自研编排器的重试逻辑可能有 bug | 单元测试覆盖所有状态转移路径 + 集成测试模拟失败注入 |
| Worker 单点故障 | Worker 无状态，jobs 表是真实状态。Worker 挂了重启即可，不会丢任务。`FOR UPDATE SKIP LOCKED` 保证不会重复执行 |
| 并发冲突（同一 session 创建重复 job） | `idempotency_key` UNIQUE 约束 + 创建 job 时检查 session 是否已有同类型 pending/running job |

#### 未来迁移成本

**低到中**。状态表（sessions、jobs、artifacts）是业务数据的标准表示。迁移到 LangGraph 需要：
1. 把自研状态转移逻辑翻译成 LangGraph 节点和边
2. 适配 LangGraph 的 PostgreSQL Checkpointer
3. 额外的集成测试验证行为一致

核心的 handler 函数（调 Whisper、调 LLM、调飞书 API）不需要重写。

#### MVP 是否必须引入

**是，必须**。Workflow Orchestrator 是整个系统的中枢。

#### 验收标准

1. 从「采集开始」到「工件发布到飞书」的完整链路可自动走通
2. 任一 job 失败后自动重试，3 次失败后标记 failed 并通知用户
3. 人工审核通过前，工件不会发布
4. 撤回操作级联删除所有下游工件
5. 每个状态转移写入 `workflow_events` 和 `audit_logs`
6. Worker 进程重启不丢任务

---

### ADR-003：数据库 — PostgreSQL 单库

**选择**：PostgreSQL，MVP 不引入 Redis

**放弃项**：Redis、MongoDB、SQLite

**选择理由**：
1. 数据结构是典型的关系模型：sessions、jobs、artifacts、audit_logs、users、devices
2. 工件的半结构化数据用 JSONB 字段处理
3. 单用户单会话，无高并发状态竞争
4. `FOR UPDATE SKIP LOCKED` 实现 worker 的任务分发，不需要 Redis 队列

**风险**：1000+ 用户后高频审计写入可能成为瓶颈

**未来迁移成本**：低。引入 Redis 是加层，不替换

**MVP 是否必须引入**：是

**验收标准**：所有表通过 Alembic migration 管理，JSONB 字段有 GIN 索引

---

### ADR-004：语音转写 — Whisper API

**选择**：OpenAI Whisper API

**放弃项**：本地部署 Whisper、边缘端推理

**选择理由**：
1. 中文转写准确率目前最高
2. MVP 不需要处理 GPU 运维
3. 2-10 秒延迟对「采集后转写」场景可接受

**风险**：音频上传到 OpenAI 的隐私问题；API 费用累积

**替代方案**：1.0 后数据隐私要求提高时可部署自有 Whisper

**未来迁移成本**：低。通过 `TranscriptionProvider` 接口隔离

**MVP 是否必须引入**：是

**验收标准**：30 分钟中文会议音频转写准确率 ≥ 95%

---

### ADR-005：BLE 控制面 — JSON over GATT

**选择**：控制指令和状态同步使用 JSON over BLE GATT

**放弃项**：Protobuf、MessagePack、CBOR

**选择理由**：
1. 控制消息体积极小（start/stop/pause 几十字节）
2. JSON 肉眼可调试，`nRF Connect` 直接读
3. 音频走独立通道，不在本 ADR 讨论范围
4. 向前兼容用小版本号处理

**未来迁移成本**：中低。控制消息可逐步迁移，不需要全量切换

**MVP 是否必须引入**：是

**验收标准**：所有控制指令在 MTU 512 字节内完成单包传输

---

### ADR-006（重评）：移动端 — 桌面控制台 + 最小 Flutter BLE Bridge

#### 重新审视

上一版说「控制台是桌面场景，手机只是通知入口，不需要移动端 App」。评审者指出这个判断**低估了移动端的必要性**——因为工牌必须通过手机 BLE 连接。

#### 关键事实

1. **工牌没有 Wi-Fi/LTE**（MVP 硬件设计），必须通过手机作为网络桥
2. **Web Bluetooth API 在 iOS 上不可用**，在 Android Chrome 上也有限制（后台时 BLE 扫描受限）
3. **PWA 不能做 BLE 后台传输**——用户锁屏后音频上传会中断
4. 因此，**手机端必须有一个原生能力来管理 BLE 连接和后台上传**

#### 推荐选择

**选择**：拆分为两层
- **手机端**：最小 Flutter BLE Bridge（仅负责：BLE 连接管理、音频接收重组、后台上传、配网、状态同步）
- **桌面端**：Next.js Web 控制台（工件审核、权限管理、审计查看）

**放弃项**：
- 纯 PWA 所有事情（iOS BLE 不可用）
- React Native（Flutter BLE 插件生态更稳定）
- 原生 Swift + Kotlin 双端（人力不够）

#### 选择理由

1. **Flutter 的 BLE 插件生态成熟**：`flutter_blue_plus` 在 iOS/Android 上都稳定，支持后台模式
2. **一套 Dart 代码覆盖双端**，不写两套原生
3. **分工清晰**：手机端只做 BLE 桥 + 上传，不做复杂 UI。控制台在桌面端做深度交互
4. Flutter BLE Bridge 不包含 Agent 逻辑、不包含工件审核——它就是通道

#### 手机端 Flutter Bridge 的最小职责

```
┌─────────────────────────────────────┐
│        Flutter BLE Bridge           │
│                                     │
│  ┌──────────┐  ┌──────────────────┐ │
│  │ BLE 管理  │  │ 音频接收与重组    │ │
│  │ 扫描/连接 │  │ chunk 重组       │ │
│  │ 状态监听  │  │ checksum 校验    │ │
│  │ 断线重连  │  │ 断点续传         │ │
│  └──────────┘  └──────────────────┘ │
│                                     │
│  ┌──────────┐  ┌──────────────────┐ │
│  │ 后台上传  │  │ 控制指令收发      │ │
│  │ HTTP/     │  │ start/stop/pause │ │
│  │ multipart │  │ 状态回传         │ │
│  └──────────┘  └──────────────────┘ │
│                                     │
│  ┌──────────────────────────────────┐ │
│  │ 最小 UI：设备配对 / 采集开关 /    │ │
│  │ 状态指示 / 通知                  │ │
│  └──────────────────────────────────┘ │
└─────────────────────────────────────┘
```

#### 桌面控制台 (Next.js)

- 工单审核列表、工件详情、修改/驳回/审批
- 权限管理、用户管理
- 审计日志查询
- 响应式设计，手机上也能看（但不需要 BLE 能力）

#### 风险

| 风险 | 缓解 |
|---|---|
| Flutter + Next.js 两套代码维护成本 | Flutter Bridge 功能极少（~5 个页面），只做通道，不膨胀 |
| 团队需要 Dart 技能 | MVP 阶段 Flutter 代码量很小（BLE 桥 + 最小 UI），可由一个开发者完成 |
| iOS BLE 后台限制 | 配置 `UIBackgroundModes` (bluetooth-central)，有限时间内可后天传输 |

#### 替代方案

- 如果团队无法 cover Dart，退一步用 React Native + `react-native-ble-plx`。但 RN 的 BLE 插件维护情况不稳定。

#### 未来迁移成本

**中**。Flutter Bridge 替换为原生或 RN 需要重写，但功能少、代码量小。

#### MVP 是否必须引入

**是，必须**。没有手机端 BLE Bridge，工牌无法联网。

#### 验收标准

1. iOS 和 Android 均可扫描并连接工牌 BLE 设备
2. 30 分钟音频通过 BLE 分片接收、重组、上传，无丢包
3. App 退到后台后音频上传不中断（至少支持 5 分钟后台传输）
4. BLE 断连后自动重连，session 不丢失

---

### ADR-007：LLM 服务 — OpenAI API + provider adapter

**选择**：OpenAI API (GPT-4o)，通过 `LLMProvider` 接口隔离

**放弃项**：自部署开源模型（MVP 不上 GPU 集群）、单一国产模型锁定

**选择理由**：
1. JSON Schema 约束输出最稳定
2. 中文能力在一梯队
3. adapter 解耦，未来换模型只改实现

**风险**：API 费用（约 $0.25-0.50/次 30 分钟会议）；数据隐私

**未来迁移成本**：低。接口隔离

**MVP 是否必须引入**：是

**验收标准**：`LLMProvider` 接口定义完成，支持 OpenAI 和至少一个 mock 实现用于测试

---

### ADR-008：音视频存储 — S3 兼容对象存储

**选择**：S3 兼容对象存储（阿里云 OSS / AWS S3 / MinIO）

**放弃项**：数据库存储大文件、本地文件系统

**选择理由**：
1. 30 分钟音频 ≈ 30MB，数据库不是文件存储
2. S3 自带 CDN，工件引用链接可直接播放
3. 生命周期管理：90 天自动归档/删除

**未来迁移成本**：低。S3 API 是行业标准

**MVP 是否必须引入**：是

**验收标准**：音频上传/下载正常，CDN URL 可直接在浏览器播放

---

### ADR-009：部署 — Docker Compose 单机

**选择**：Docker Compose（3 容器：API + Web + PG）

**放弃项**：Kubernetes、裸机部署、Serverless

**选择理由**：
1. 服务数只有 3-4 个，K8s 是杀鸡用牛刀
2. `docker compose up -d` 一键启动
3. 开发/生产环境一致

**未来迁移成本**：低。应用无状态，未来迁移 K8s 主要写 Helm Chart

**MVP 是否必须引入**：是

**验收标准**：`docker compose up -d` 后所有服务健康，`docker compose logs` 无错误

---

### ADR-010：Node.js 后端 — 不引入

**选择**：MVP 不引入 Node.js 作为后端。Next.js 仅前端构建使用 Node.js

**放弃项**：Node.js 作为独立后端 API 服务

**选择理由**：Python 能做所有事，两套运行时增加运维成本

**未来迁移成本**：N/A

**MVP 是否必须引入**：否

**验收标准**：后端仅 Python 一个运行时

---

### ADR-011（新增）：后台任务与异步执行

**选择**：PostgreSQL jobs 表 + 独立 Worker 进程轮询

**放弃项**：
- FastAPI BackgroundTasks（绑定 HTTP 请求生命周期，不适合长任务）
- Celery / RQ / Arq（需要 Redis，MVP 不引入）
- APScheduler（定时调度，不是作业编排）

**选择理由**：
1. **转写和 LLM 处理不能绑定 HTTP 请求**。停止采集的 API 响应应该 <200ms 返回 `session.status = 'processing'`，实际转写和提炼在后台异步执行。
2. **Worker 无状态**。jobs 表是唯一真实状态。Worker 挂了重启不丢任务。`FOR UPDATE SKIP LOCKED` 保证多 Worker 不会重复执行。
3. **不需要 Redis**。MVP 单 Worker 足够，jobs 表轮询延迟 1 秒可接受。
4. **审计友好**。每个 job 的生命周期都在 PostgreSQL 里，和 sessions、audit_logs 在同一个事务上下文中。

#### jobs 表

使用 ADR-002 的 canonical jobs schema，此处不复述完整 DDL。
关键字段摘要：
- `status VARCHAR(32)`：pending / running / succeeded / failed / permanently_failed / cancelled
- `next_run_at TIMESTAMPTZ`：NULL = 立即执行；retry 时设为 now() + backoff
- `locked_by` / `locked_at` / `heartbeat_at`：worker 锁与心跳
- `idempotency_key`：UNIQUE，防止重复创建
- 查询待执行任务：`WHERE status = 'pending' OR (status = 'failed' AND retry_count < max_retries AND next_run_at <= now())`

**完整 DDL 和索引见 ADR-002。**

#### 任务状态转换

```
PENDING ──▶ RUNNING ──▶ SUCCEEDED
  │            │
  │            ├──▶ FAILED
  │            │      │
  │            │      ├── retry_count < max_retries
  │            │      │   → 设 next_run_at = now() + backoff
  │            │      │   → Worker 到时重新取走并设为 RUNNING
  │            │      │
  │            │      └── retry_count >= max_retries
  │            │          → PERMANENTLY_FAILED（终态）
  │            │
  │            └──▶ CANCELLED（用户取消）
  │
  └──▶ CANCELLED（用户取消或撤回）
```

#### retry/backoff 策略

```
retry_count 0 → 立即重试（next_run_at = now()）
retry_count 1 → next_run_at = now() + backoff_seconds * 2^0 = 30s 后
retry_count 2 → next_run_at = now() + backoff_seconds * 2^1 = 60s 后
retry_count 3 → 放弃，status 改为 permanently_failed
```

重试时 job 保持 `failed` 状态，仅更新 `retry_count` 和 `next_run_at`。Worker 查询条件为：
```sql
WHERE status = 'pending'
   OR (status = 'failed' AND retry_count < max_retries AND next_run_at <= now())
```
这样 retry 不引入单独的 `retrying` 状态，查询一个 WHERE 覆盖所有待执行任务。

#### 幂等策略

每个 job 创建时计算 `idempotency_key`：
```python
def idempotency_key(session_id, job_type, input_hash):
    return hashlib.sha256(
        f"{session_id}:{job_type}:{input_hash}".encode()
    ).hexdigest()
```

Worker 创建 job 时，先 `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING`。如果 job 已存在且 `succeeded`，跳过。如果 `failed` 且 `retry_count < max_retries`，重置为 `pending`。

#### 超时策略

`timeout_seconds` 默认 300 秒（转写和 LLM 足够）。Worker 定期检查 `running` 状态的 jobs，如果 `started_at + timeout_seconds < now()` 且 `heartbeat_at` 超过 120 秒未更新，标记 `failed` 并设 `next_run_at = now()` 触发重试。

#### 同一 session 并发处理冲突

**规则：同一 session 的同一类型 job，同一时间最多只能有一个 running。**

创建 job 前检查：
```sql
SELECT COUNT(*) FROM jobs
WHERE session_id = $1
  AND job_type = $2
  AND (
    status IN ('pending', 'running')
    OR (status = 'failed' AND retry_count < max_retries)
  )
```
如果 > 0，不创建新 job。

对于**可并行的 job 类型**（如 `summarize` 和 `extract_artifact` 可同时运行），它们在 `job_type` 层面不同，不会冲突。

#### 用户取消/撤回时，正在执行的任务如何处理

```python
def cancel_session_jobs(session_id):
    # 1. 将 pending 和等待重试的 failed 立即标记为 cancelled
    db.execute(
        "UPDATE jobs SET status = 'cancelled' "
        "WHERE session_id = $1 "
        "AND (status = 'pending' "
        "     OR (status = 'failed' AND retry_count < max_retries))",
        session_id
    )
    # 2. 对 running 的 job，设 timeout_seconds = 1 触发快速失败
    db.execute(
        "UPDATE jobs SET timeout_seconds = 1 "
        "WHERE session_id = $1 AND status = 'running'",
        session_id
    )
```

Worker 在执行 job 的每个耗时步骤前检查 `session.status NOT IN ('cancelled', 'retracting')`。

#### 风险

| 风险 | 缓解 |
|---|---|
| Worker 单点故障 | 无状态，重启即可。`FOR UPDATE SKIP LOCKED` 防止重复执行 |
| 轮询延迟（1s） | 对转写/LLM 场景完全可接受。真需要实时推送时用 SSE/WebSocket |
| 多 Worker 竞争 | `FOR UPDATE SKIP LOCKED` 保证每条 job 只有一个 worker 拿 |

#### 未来迁移成本

**中低**。未来引入 Redis + Celery 时，jobs 表的 handler 函数可以复用。迁移主要改调度层。

#### MVP 是否必须引入

**是，必须**。没有后台任务，HTTP 请求会超时。

#### 验收标准

1. 停止采集后 API 200ms 内返回，转写和提炼在后台异步完成
2. Worker 重启不丢任务
3. 同一 job 不会执行两次（幂等验证）
4. 用户撤回后 3 秒内所有相关 job 被取消
5. 失败 job 自动重试，3 次后停止并通知用户

---

### ADR-012（新增）：权限、认证与组织模型

**选择**：最小 RBAC 模型 + JWT 认证 + API Key for webhook

**放弃项**：OAuth2 完整授权码流程、SAML/SSO、复杂的多租户 RBAC

**选择理由**：MVP 阶段用户数 < 10，不是企业级平台。

#### 实体关系

```
Organization (1) ──▶ (*) User
User (*) ──▶ (*) Device (工牌)
User (1) ──▶ (*) Session (采集会话)
Session (1) ──▶ (*) Artifact (工件)
Artifact (1) ──▶ (*) AuditLog
```

#### 角色设计

| 角色 | 权限 |
|---|---|
| **Owner** | 查看/审核/修改/删除/发布所有工件，管理用户，查看审计日志，撤回任意工件 |
| **Contributor** | 开始采集，查看自己的会话和工件，申请审核 |
| **Reviewer** | 查看被分配的工件，审核（批准/驳回），不能修改|

MVP 阶段就只有这三个角色。

#### 谁可以做什么

| 操作 | Owner | Contributor | Reviewer |
|---|---|---|---|
| 开始采集 | ✅ | ✅ | ❌ |
| 查看自己 Session 的转写 | ✅ | ✅ | 被分配的可看 |
| 审核工件 | ✅ | ❌ | ✅ (被分配) |
| 发布到飞书 | ✅ | ❌ | ❌ |
| 撤回和删除 | ✅ | 仅自己的 draft | ❌ |
| 管理用户 | ✅ | ❌ | ❌ |
| 查看审计日志 | ✅ | ❌ | ❌ |

#### API 鉴权方式

```
Authorization: Bearer <JWT_TOKEN>
```

JWT payload：
```json
{
  "sub": "<user_id>",
  "org_id": "<org_id>",
  "role": "owner|contributor|reviewer",
  "exp": 1234567890
}
```

JWT 通过 `/auth/login` 获取。登录方式：用户名 + 密码（MVP 最简单）。未来可拓展飞书 OAuth。

#### Webhook / API Key 存储

- 飞书 API 的 app_id + app_secret 存储在 Moxt Secret Store（`FEISHU_APP_ID`、`FEISHU_APP_SECRET`）
- 后端通过 Secret Store 的 placeholder 机制访问，不落盘
- 若未来需要外部 webhook 接入（如飞书事件回调），验证签名不存 token

#### 多租户隔离

**MVP 不做多租户**。单个 Organization。10 以内用户，物理隔离（一人一组织在 MVP 阶段 = 一组织）。

数据隔离通过 `org_id` 列实现（为未来多租户预留），但 MVP 不暴露多组织切换 UI。

#### 风险

| 风险 | 缓解 |
|---|---|
| 密码存储 | Argon2id 或 bcrypt 哈希，每个密码使用唯一随机 salt，禁止明文存储 |
| JWT 泄露 | 短期过期（1h），refresh token 单独存储 |

#### 未来迁移成本

**低**。RBAC 表结构设计支持扩展到 ABAC 或更细粒度权限。JWT → OAuth2 迁移是加登录方式，不改权限模型。

#### MVP 是否必须引入

**是，必须**。没有认证无法区分用户。

#### 验收标准

1. Owner 能创建 Contributor 和 Reviewer 账号
2. Contributor 只能查看自己的 sessions 和 artifacts
3. Reviewer 只能审核被分配给的 artifacts
4. 未登录请求返回 401

---

### ADR-013（新增）：信任守护与审计日志

**选择**：确定性规则引擎 + LLM 辅助建议 + 不可绕过的系统约束 + 不可变的审计日志

**放弃项**：纯 LLM Agent 做信任守护、事后审计、无硬约束的「建议式」红线

**选择理由**：

> 「信任守护」不能只是一个 LLM Agent。LLM 可以被 prompt injection 绕过、可以产生幻觉、可以被说服。红线的执行必须是确定性的。

#### 分层架构

```
┌─────────────────────────────────────────────┐
│           Layer 1: 硬约束（不可绕过）          │
│  采集前必须声明确认 → 无声明则 API 直接拒绝    │
│  未审核工件不得发布 → publish job 强制检查     │
│  审计日志 append-only → 无 delete/update 权限  │
│  撤回后级联删除 → Saga + outbox + deletion_jobs  │
│  权限检查每个 API 端点 → middleware 强制执行   │
└─────────────────────────────────────────────┘
                    ↑
┌─────────────────────────────────────────────┐
│       Layer 2: 确定性规则引擎                  │
│  规则用代码表达，不用 LLM 判断                 │
│  e.g. session.status != 'capturing' → 拒绝采集│
│  e.g. artifact.status != 'approved' → 拒绝发布 │
│  e.g. 非 Owner 且非本人物件 → 拒绝删除         │
└─────────────────────────────────────────────┘
                    ↑
┌─────────────────────────────────────────────┐
│    Layer 3: LLM 辅助判断（建议，不决策）        │
│  "这段文本是否含敏感信息？" → 标记 + 建议脱敏   │
│  "这个工件是否和已有知识冲突？" → 标记 + 建议   │
│  最终决策权：人类审核者                        │
└─────────────────────────────────────────────┘
```

#### 10 条红线的落实方式

| # | 红线 | 落实层 | 实现 |
|---|---|---|---|
| 1 | 不后台录音 | L1 硬约束 | 采集必须用户主动触发，API 端检查 consent_granted |
| 2 | 不可绕过采集声明 | L1 硬约束 | `POST /sessions/start` 强制要求 consent 参数 |
| 3 | 未审核不得发布 | L1 硬约束 | publish job 创建前检查 artifact.status == 'approved' |
| 4 | 不可做数字分身 | L3 LLM 辅助 | LLM 检测「用我的语气回复」类指令，标记 + 拒绝 |
| 5 | 不可用于绩效监控 | L2 规则引擎 | 数据模型不含「绩效」字段 |
| 6 | 删除权利（撤回） | L1 硬约束 | 撤回 API 级联删除所有下游 artifact + 审计记录 |
| 7 | 敏感信息脱敏 | L3 LLM 辅助 | LLM 检测 PII/机密 → 标记 → 人工决定脱敏还是保留 |
| 8 | 本人确认原则 | L1 硬约束 | 采集的 session 只属于触发者，他人不能代确认 |
| 9 | 不可对第三方提供原始录音 | L2 规则引擎 | 工件外发仅发结构化工件，不发原始音频 |
| 10 | 数据所有权归属用户 | L2 规则引擎 + L1 | 导出 API 提供全部数据，撤回后全部删除 |

#### 审计日志设计

```sql
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID,              -- 外键引用 sessions(id)。sessions 做 tombstone 后仍可 JOIN
    artifact_id UUID,
    actor_id UUID NOT NULL,
    actor_type VARCHAR(16) NOT NULL,  -- user | system | agent
    action VARCHAR(64) NOT NULL,
    -- session_start | consent_grant | consent_deny | audio_upload
    -- transcribe_start | transcribe_complete | transcribe_fail
    -- distill_start | distill_complete | distill_fail
    -- artifact_draft | artifact_submit_review | artifact_approve | artifact_reject
    -- publish_start | publish_complete | publish_fail
    -- retract_request | retract_complete | cascade_delete
    details JSONB NOT NULL,
    -- 🔴 审计日志内容规则（强制执行，代码 review 必须检查）：
    --   ✅ 允许：状态变化（from_status → to_status）
    --   ✅ 允许：操作元数据（job_id, artifact_id, session_id, actor_id）
    --   ✅ 允许：内容 hash（SHA256(transcript), SHA256(artifact_content)）
    --   ✅ 允许：操作原因、驳回理由（人工输入）
    --   ❌ 禁止：原始录音全文 / 片段 / URL
    --   ❌ 禁止：完整转写文本
    --   ❌ 禁止：工件内容全文（MD / FAQ / SOP body）
    --   ❌ 禁止：PII（手机号、邮箱、身份证号、人脸特征）
    --   ❌ 禁止：before / after 中的敏感内容快照
    --
    -- 原因：用户撤回后，审计日志是唯一不可删除的数据。
    -- 如果审计日志里存了完整转写，撤回就失去意义——
    -- 用户的敏感数据仍然"永久保留"在另一个表里。
    --
    -- 审计日志的角色是"谁在什么时间做了什么操作，结果是什么状态"，
    -- 不是"操作涉及的数据全文副本"。
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()  -- 不可修改，不可删除
);

-- 审计表特殊约束（通过数据库权限实现）：
-- GRANT INSERT ON audit_logs TO app_user;
-- REVOKE UPDATE, DELETE ON audit_logs FROM app_user;
-- 即：app 代码只能 INSERT，不能修改也不能删除
```

**details 字段的正确与错误示例**：
```json
// ✅ 正确：元数据 + hash + 状态变化
{
    "from_status": "needs_review",
    "to_status": "approved",
    "artifact_id": "abc-123",
    "artifact_type": "meeting_minutes",
    "content_hash": "sha256:7d9e3a...",
    "reviewer_id": "user-456",
    "reason": "会议纪要与录音一致，批准发布"
}

// ❌ 错误：包含完整文本
{
    "before": {"content": "今天会议讨论了Q3预算分配方案..."},  // 禁止！
    "after": {"content": "今天会议讨论了Q3预算分配方案（修订版）..."}   // 禁止！
}
```

**审计日志不可篡改的实现**：
1. 数据库层面：`REVOKE UPDATE, DELETE ON audit_logs FROM app_user`
2. 应用层面：audit_log 的 model 只有 `create()` 方法，没有 `update()` / `delete()`
3. 未来增强：定期将 audit_log 哈希链写入只读存储

#### 风险

| 风险 | 缓解 |
|---|---|
| LLM 辅助检测敏感信息漏报 | LLM 检测是辅助建议，最终由人决定。漏报不是系统故障 |
| 恶意管理员修改数据库 | 数据库权限分离 + 未来引入 immutable audit table（如 pg_tle） |

#### 未来迁移成本

**低**。审计日志表是独立模块，未来引入 SIEM 或合规系统（如 Splunk）时只需添加导出适配器。

#### MVP 是否必须引入

**是，必须**。信任是产品的核心差异化优势。

#### 验收标准

1. 采集前未声明确认 → API 返回 403
2. 未审核工件 → publish job 拒绝创建
3. 撤回后所有下游工件在 5 秒内删除
4. audit_log 表只能 INSERT，无法 UPDATE/DELETE
5. 每个关键操作都在 audit_log 中有记录

---

### ADR-014（新增）：BLE 音频传输方案

#### 控制面 vs 数据面

| 面 | 协议 | 传输内容 | 特点 |
|---|---|---|---|
| **控制面** | JSON over GATT | start/stop/pause/resume、状态查询、指纹认证结果、错误码 | <100 字节/条，低频 |
| **数据面** | 自定义分片协议 over GATT Write/Notify | 音频流（Opus 或 PCM） | 高频、大体积、需要可靠性 |

#### 音频传输方案

**选择**：GATT Write/Notify + 自定义分片协议

**放弃项**：
- BLE L2CAP CoC（Android 支持好，iOS 有限制，工牌固件不一定支持）
- BLE Audio / LC3（太新，芯片和手机兼容性参差）
- 纯 GATT 不做分片（MTU 限制 512 字节，一包不够）

#### 音频编码、码率与会话上限

| 参数 | 值 | 说明 |
|---|---|---|
| **编码格式** | Opus 16kHz mono | 工牌端硬件编码。Opus 在 16kbps 下语音质量优秀 |
| **目标码率** | 16 kbps（语音）或 32 kbps（音乐/多人） | 16kbps × 30min ≈ 3.6MB；32kbps × 30min ≈ 7.2MB |
| **最大会话时长** | 120 分钟 | 超出需明确用户确认。16kbps × 120min ≈ 14.4MB，仍在安全边界内 |
| **完整文件 hash** | SHA256（所有 segment 重组后） | streaming 模式下校验 segment_sha256（每 segment 结束时的 `segment_end` 消息携带）。全部 segment 上传后，后端计算最终 `file_sha256`。录完再传模式下，工牌可在 `audio_info` 中发送 `file_sha256` |
| **chunk payload 大小** | 256 bytes | 配合 16B header = 272B，在 iOS/Android 常见 512 MTU 内安全 |
| **seq/total 字段** | uint32（最大 4,294,967,295） | 256B × 4B = 1TB 上限，彻底消除边界问题。选择 uint32 而非 uint16 的理由见下文 |

**关于 seq/total 字段宽度的决策**：
- v2.1 使用 uint16，但 32kbps × 90min = ~28MB 已超出 uint16 上限（256B × 65535 ≈ 16.7MB），存在边界风险
- v2.1-cleanup 采用 **方案 A：seq 和 total 改为 uint32**
- 代价：header 从 12B 增加到 16B。4B 开销对 BLE 传输无实际影响
- 收益：彻底消除未来边界问题，无需为不同码率设置不同时长上限
- 固件端：uint32 解析成本与 uint16 几乎无差异（ARM Cortex-M 均原生支持）
- 迁移成本：协议版本号从 0x01 → 0x02。新旧版本不兼容，手机端需同时支持两个版本

#### 溢出与滚动文件策略

**场景**：用户忘记停止采集，会议超过 120 分钟。

```
工牌端行为：
1. 每 120 分钟（或 16.7MB）自动分段，创建新 audio segment
2. segment 通过 seq_base 字段区分偏移（控制面消息携带）
3. 手机端收到 segment_end 标志后，将当前 segment 封存上传
4. 超过 3 个 segment 仍未停止 → 工牌震动提醒 + 控制台通知
```

#### Wi-Fi / USB / 手机直录 Fallback

BLE 音频传输存在不可控因素（iOS 后台限制、2.4GHz 干扰、工牌天线性能）。以下 fallback 路径 MVP 应预留：

| Fallback | 优先级 | 触发条件 | 实现方式 |
|---|---|---|---|
| **BLE（主路径）** | 1 | 默认 | 分片协议 |
| **手机直录** | 2 | BLE 连接失败或持续丢包 | 手机端 App 直接用内置麦克风录音。用户手动标记"本次未用工牌"。session 标记 `audio_source = 'phone_mic'` |
| **USB 有线** | 3 | 工牌硬件支持 USB | 会议结束后工牌插 USB，手机/电脑从工牌导出音频文件。session 标记 `audio_source = 'usb_import'` |
| **Wi-Fi 直连** | 4 | 工牌 v2 硬件支持 | 工牌和手机在同一 Wi-Fi，音频通过 HTTP PUT 上传。MVP 不做 |

**MVP 必须实现 fallback 2（手机直录）**。原因：如果工牌硬件 BLE 性能不达标，整个系统的端到端测试会被阻塞。手机直录让 Agent 闭环完全脱离硬件依赖。

#### 音频传输模式

MVP 默认采用 **边录边传（streaming）** 模式：工牌编码 Opus → 分片 → BLE 发送，手机端实时接收重组。

此模式下，工牌在开始传输时**不知道完整文件的 hash 和 chunk 总数**。因此：
- **文件完整性验证**使用 **segment 级 hash**，而非全文件 hash
- **chunk header 中 `total` 字段**：streaming 模式下填 `0`（表示未知），手机端不依赖 total 做完整性检查
- segment 结束时由 `segment_end` 控制消息携带实际 `chunk_count`

具体流程：
1. 工牌每编码一段（约 30 秒或 256KB），作为一个 segment
2. segment 开始时发送 `segment_begin` 控制消息（含 segment_index、seq_base）
3. 该 segment 的所有 chunk 的 header 中 `total = 0`（streaming 未知总数）
4. segment 结束时发送 `segment_end` 控制消息（含 `segment_sha256` + `chunk_count` = 该 segment 的实际 chunk 数）
5. 手机端对每个 segment 独立校验 SHA256 → 校验失败则该 segment 请求重传
6. 全部 segment 上传后，后端可计算最终 `file_sha256` 并写入 session 元数据

**录完再传模式**（备选，用于 USB 导入等场景）：
- 此时工牌已知完整文件的 hash 和 chunk 总数
- chunk header 中 `total` 填实际总数（非零）
- 工牌端在 `audio_info` 控制消息中携带 `file_sha256`
- 手机端重组后比对 file_sha256
- MVP 保留此模式作为 USB fallback 路径

#### 分片协议设计（16 字节 header，协议版本 0x02）

```
┌──────────────────────────────────────────────┐
│              Audio Chunk Format               │
├──────────┬──────┬──────────┬─────────────────┤
│ Field    │ Size │ Type     │ Description     │
├──────────┼──────┼──────────┼─────────────────┤
│ version  │ 1B   │ uint8    │ 协议版本 (0x02)  │
│ seq      │ 4B   │ uint32   │ chunk 序号(从0起)│
│ total    │ 4B   │ uint32   │ 总 chunk 数。streaming 模式填 0，录完再传填实际值 │
│ size     │ 2B   │ uint16   │ 本 chunk 数据长度 │
│ checksum │ 4B   │ uint32   │ CRC32(数据部分)   │
│ flags    │ 1B   │ uint8    │ bit0: 最后一包    │
│          │      │          │ bit1: 重传包      │
│          │      │          │ bit2: segment_end │
│ data     │ N    │ bytes    │ Opus 裸数据       │
└──────────┴──────┴──────────┴─────────────────┘
Header: 16 bytes + data (最多 256 bytes = 272B total)
```

协议版本 0x02 与 0x01 不兼容（header 长度不同）。手机端同时支持两个版本的解析，根据 version 字段自动切换。工牌固件从 0x02 开始实现，0x01 不留。

**完整文件验证**（边录边传模式）：
- 不使用"第 0 个 chunk 携带 file_sha256"的设计（因为开始传输时未知完整 hash）
- 每个 `segment_end` 控制消息包含该 segment 的 `segment_sha256` 和 `chunk_count`
- 手机端对每个 segment 校验 SHA256 → 失败则请求该 segment 重传
- 全部 segment 上传后，后端计算 `file_sha256 = SHA256(segment_0 || segment_1 || ...)` 并写入 session 元数据

**控制面新增消息**（用于 segment 管理和 streaming）：
```json
{"cmd": "audio_info", "codec": "opus", "bitrate": 16000, "sample_rate": 16000, "mode": "streaming", "ver": 1}
{"cmd": "segment_begin", "segment_index": 0, "seq_base": 0, "ver": 1}
{"cmd": "segment_end", "segment_index": 0, "segment_sha256": "7d9e3a...", "chunk_count": 234, "ver": 1}
```

文件 hash 不再在 `audio_info` 中发送（streaming 模式下未知），保留字段为空或省略。



#### 工牌端 C 固件如何解析控制消息

控制面 JSON 格式：
```json
{"cmd": "start_capture", "ts": 1234567890, "ver": 1}
{"cmd": "stop_capture", "ts": 1234567895, "ver": 1}
```

固件端用轻量 JSON 解析器（如 `cJSON` 或 `jsmn`），解析 `cmd` 字段后分发到对应的处理函数。

#### 断点续传

```
1. 工牌记录最后成功发送的 chunk seq
2. BLE 断连后重连，手机端发送：
   {"cmd": "resume_upload", "last_seq": 42, "ver": 1}
3. 工牌从 seq 43 开始重新发送
```

手机端按 segment 收集 chunk：streaming 模式下根据 `segment_end.chunk_count` 判断 segment 完整性；录完再传模式下根据 header 中的 `total` 判断。每个 segment 收集完毕后校验 `segment_sha256`，通过后上传该 segment。

#### 重传策略

```
手机端维护一个 missing_chunks 集合。
每 500ms 检查一次，向工牌发送：
  {"cmd": "retransmit", "missing": [12, 17, 34], "ver": 1}
工牌重新发送请求的 chunk（flags bit1 标记为重传）。
最多重传 3 次，3 次后放弃该 session。
```

#### 加密

- BLE 链路层已有 AES-CCM 加密（BLE Security Mode 1 Level 3）
- 应用层不额外加密（降低工牌端 CPU 开销）
- 传输层：手机 → 后端使用 HTTPS

#### JSON vs Protobuf/CBOR/MessagePack 再次比较

| 维度 | JSON | Protobuf | MessagePack | CBOR |
|---|---|---|---|---|
| 解析复杂度（工牌 C 固件） | 中（需 JSON parser） | 高（需 protobuf-c 库） | 低 | 中 |
| 控制消息体积 | ~80 bytes | ~30 bytes | ~50 bytes | ~50 bytes |
| 可调试性 | 极好 | 差 | 差 | 差 |
| 固件 ROM 开销 | <5KB (jsmn) | ~20KB (nanopb) | <3KB | <5KB |
| **结论** | **MVP 选用** | 不选 | 备选 | 备选 |

JSON 多出来的 50 bytes 在 BLE 上不是什么问题——控制消息每秒不超过 1 条。

**但如果未来音频元数据（如 VAD 触发时间戳、分贝数据）需要高频传输**，那时应切换到 MessagePack（固件端解析开销最小）。

#### 风险

| 风险 | 缓解 |
|---|---|
| BLE 断连丢音频 | 断点续传，从 last_seq+1 恢复 |
| chunk 损坏 | CRC32 校验，损坏的 chunk 请求重传。重传 3 次失败则标记 session 损坏 |
| iOS BLE 后台限制 | 利用后台 BLE 模式。如传输中断，fallback 到手机直录 |
| 工牌 ROM 太小装不下 cJSON | 备选 jsmn（token-based，无需 malloc，ROM <5KB） |
| BLE 传输速度不达预期 | **此为高概率风险**。MVP 必须保留手机直录 fallback。传输速度要求放宽为 ≥ 1.5x 实时（即 30 分钟音频在 20 分钟内传完）。如果达不到，优先用手机直录完成 Agent 闭环验证 |

#### 验收标准（修订）

1. 30 分钟 16kbps Opus 音频通过 BLE 分片传输，CRC32 校验 100% 通过
2. 模拟 BLE 断连后重连，从断点恢复传输
3. 手机直录 fallback 可用：关闭工牌，手机 App 录音 → 完整 Agent 闭环可走通
4. 传输速度 ≥ 1.5x 实时（可接受的最低标准；2x 为优化目标）
5. 边录边传模式下，每个 segment 的 SHA256 校验通过后上传。全量上传后后端计算最终 file_sha256

---

### ADR-015（新增）：数据生命周期与删除策略

**选择**：分层保留 + 级联删除 + 飞书同步追踪

**放弃项**：无限保留、仅逻辑删除

**选择理由**：隐私合规（用户有权删除自己的数据）+ 存储成本控制

#### 分层保留策略

| 数据类型 | 存储位置 | 默认保留 | 可配置 | 删除触发 |
|---|---|---|---|---|
| 原始音频 | S3 | 90 天 | ✅ | 到期自动删除 / 用户撤回立即删除 |
| 转写文本 | PostgreSQL | 永久（工件发布后）或 90 天（未发布） | ✅ | 用户撤回立即删除 |
| 结构化工件 | PostgreSQL | 永久（已发布）或 90 天（draft） | ✅ | 用户撤回立即删除 |
| 飞书已发布副本 | 飞书 | 由飞书管理 | ❌ | 撤回时从飞书删除 |
| 审计日志 | PostgreSQL | 永久（不可删除） | ❌ | 不可删除 |

#### 撤回的级联删除流程（Saga 模式）

撤回操作涉及三个外部系统（PostgreSQL、S3、飞书 API），不可能在一个 DB 事务中原子完成。采用 **Saga + outbox + deletion_jobs** 模式：

```
用户触发撤回 session_id=X
     │
     ├── [步骤 1，DB 事务 A]
     │   ├── UPDATE sessions SET status = 'retracting', deleted_at = now()
     │   ├── 取消所有 pending/failed 状态的 jobs（UPDATE status = 'cancelled'）
     │   ├── 对 running 状态的 job：不直接杀，设 timeout_seconds = 1
     │   ├── UPDATE artifacts SET deleted_at = now() WHERE session_id = X
     │   ├── INSERT INTO deletion_jobs:
     │   │   ├── type='delete_artifact_rows'（级联 artifacts）
     │   │   ├── type='delete_s3_audio', payload={audio_key}
     │   │   └── type='delete_feishu_docs', payload=[{artifact_id, feishu_doc_id}]
     │   └── INSERT INTO audit_logs (action='retract_request', details={session_id, reason})
     │
     ├── [步骤 2，异步 Worker 执行 deletion_jobs]
     │   ├── delete_artifact_rows:
     │   │   DELETE FROM artifacts WHERE session_id = X AND deleted_at IS NOT NULL
     │   │   → 成功 → 标记 job succeeded
     │   │
     │   ├── delete_s3_audio:
     │   │   调 S3 API DeleteObject → 成功 → 标记 job succeeded
     │   │   → 失败 → 标记 retryable failed → 指数退避重试
     │   │
     │   └── delete_feishu_docs:
     │       逐个调飞书 API → 成功 → 标记 job succeeded
     │       → 失败 → 标记 retryable failed → 重试（飞书 API 可能 429 限流）
     │
     ├── [步骤 3，全部 deletion_jobs 完成]
     │   ├── UPDATE sessions SET status = 'retracted'
     │   └── INSERT INTO audit_logs (action='retract_complete', details={...})
     │
     └── [异常处理]
         ├── deletion_job 重试 3 次后仍失败 → 标记需要人工介入
         ├── 飞书文档删除失败的 → session 仍标记 retracted，feishu_doc 留在 pending_deletion 表
         └── 所有中间状态通过 deletion_jobs 和 audit_logs 可追踪
```

**关键设计决策**：
- **先软删后硬删**：步骤 1 立即设置 `deleted_at` 使数据不可被正常 API 访问（满足用户"立即删除"的感知），物理删除由后台异步完成
- **飞书删除失败不阻断**：飞书文档删除是 best-effort。如果飞书 API 失败，记录到 `pending_deletion` 表，后续运维可手动处理
- **S3 删除幂等**：S3 DeleteObject 本身幂等，重复删除不会出错

#### deletion_jobs 表（outbox）

```sql
CREATE TABLE deletion_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL,
    job_type VARCHAR(32) NOT NULL,  -- delete_artifact_rows | delete_s3_audio | delete_feishu_docs
    status VARCHAR(16) NOT NULL DEFAULT 'pending',  -- pending | running | succeeded | failed
    payload JSONB NOT NULL,
    retry_count INT DEFAULT 0,
    max_retries INT DEFAULT 3,
    next_run_at TIMESTAMPTZ DEFAULT now(),
    error_message TEXT,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

#### 飞书已发布副本追踪

`artifacts` 表的 `feishu_doc_id` 字段记录飞书文档 ID。撤回时通过此 ID 调飞书 API 删除。

如果飞书 API 删除失败（如文档已被手动删除），记录警告但不阻断撤回流程。

#### 备份中的数据

**PostgreSQL**：备份中必然包含被删除前的数据。备份保留策略独立管理（如 30 天），过期后自动清理。

**S3**：启用 versioning 的 bucket，撤回后 `DeleteObject` 创建 delete marker。90 天后通过 lifecycle policy 删除旧版本。

向用户说明：「撤回后数据将在主存储中立即删除。备份中的数据将在备份周期（30 天）后随备份过期而被清除。」

#### 硬删除 vs 软删除 vs Tombstone

| 数据 | 删除方式 | 原因 |
|---|---|---|
| artifacts | 硬删除 + audit_logs 记录删除原因（已有 audit_logs 记录） | 软删除会导致唯一约束冲突（如 FAQ 标题去重） |
| sessions | **Tombstone**：保留 id、deleted_at、retracted_by、retraction_reason | audit_logs 引用 session_id，硬删除会使审计日志变成孤儿记录。tombstone 只保留最小元数据，不保留 audio_key、转写、工件正文。 |
| audit_logs | **不可删除** | 合规要求 |
| S3 音频 | 硬删除（带 delete marker） | |

**sessions tombstone 实现**：
```sql
-- 撤回时，不 DELETE，而是清空敏感字段：
UPDATE sessions SET
    audio_key = NULL,              -- S3 引用已删除
    audio_duration_seconds = NULL,
    consent_granted = FALSE,       -- 撤回后采集声明时效
    consent_granted_at = NULL,
    status = 'retracted',
    deleted_at = now(),
    retracted_by = $user_id,
    retraction_reason = $reason
WHERE id = $session_id;
```

**tombstone 后保留的字段**（满足 audit_logs JOIN 查询）：
- `id`、`user_id`、`device_id`、`status`（='retracted'）、`created_at`、`updated_at`
- `deleted_at`、`retracted_by`、`retraction_reason`

**tombstone 后必须清空的字段**（防止敏感数据在"不可删除"的表里残余）：
- `audio_key` → NULL（S3 音频已由 deletion_job 删除）
- `audio_duration_seconds` → NULL
- `consent_granted` → FALSE
- `consent_granted_at` → NULL

**关联 jobs 的 tombstone**：
```sql
UPDATE jobs SET
    input_payload = NULL,          -- 可能含敏感内容
    output_payload = NULL,         -- 含转写文本
    error_message = NULL
WHERE session_id = $session_id;
```

artifacts 仍然硬删除（工件操作历史由 audit_log 独立记录）。

#### 风险

| 风险 | 缓解 |
|---|---|
| 飞书 API 删除失败 | 记录失败，由运维手动处理。不阻断撤回主流程 |
| 备份恢复后数据"复活" | 文档明确告知用户备份保留期 |
| 审计日志无限增长 | 压缩 + 归档策略（>1 年的日志归档到对象存储） |

#### 未来迁移成本

**低**。生命周期策略是配置化的，换存储后端（如 OSS→S3）只需改 SDK 调用。

#### MVP 是否必须引入

**是**。无删除能力意味着无法合规。

#### 验收标准

1. 撤回请求后，主存储中所有相关数据在 30 秒内不可访问
2. 飞书已发布文档被成功删除（模拟环境中验证）
3. 审计日志完整记录撤回全过程
4. S3 音频文件 90 天后自动删除

---

## 4. MVP 必须引入 / 暂不引入清单

### 必须引入

| # | 模块 | 说明 |
|---|---|---|
| 1 | Python 3.11 + FastAPI | 后端 |
| 2 | PostgreSQL（单库） | 5 张核心表 + job 调度 |
| 3 | 自研 Workflow Orchestrator | 状态机 + session/job/event/artifact/audit |
| 4 | Background Worker | jobs 表轮询，独立进程 |
| 5 | OpenAI Whisper API | 语音转写 |
| 6 | OpenAI GPT-4o + provider adapter | LLM 推理 |
| 7 | S3 兼容对象存储 | 音频 + 文件 |
| 8 | Next.js 桌面控制台 | 审核/权限/审计查看 |
| 9 | 最小 Flutter BLE Bridge | iOS + Android，BLE 连接 + 音频上传 |
| 10 | JWT 认证 + RBAC | 3 角色 |
| 11 | 信任守护（规则引擎 + 审计日志） | 硬约束 + 不可改日志 |
| 12 | BLE 分片协议 | 16 字节 header (uint32 seq/total) + Opus payload，协议版本 0x02 |
| 13 | Docker Compose | 部署 |
| 14 | 数据生命周期 + 撤回 | 保留策略 + 级联删除 |

### 暂不引入

| # | 模块 | 何时引入 |
|---|---|---|
| 1 | Redis | 并发 > 100 session 或需要 WebSocket 实时推送时 |
| 2 | LangGraph | Agent 出现 ReAct 循环或 30+ 节点 DAG 时 |
| 3 | Flutter（全功能） | 手机端需要复杂 UI 时（MVP 只需 BLE Bridge） |
| 4 | Protobuf | BLE 传感器数据 >10KB/s 时 |
| 5 | Node.js 后端 | 不需要 |
| 6 | K8s | 服务数 >5 且需要滚动更新/自动扩缩时 |
| 7 | 多租户 | 客户 >1 组织时 |
| 8 | OAuth/SSO | 对接企业目录服务时 |
| 9 | 本地 Whisper 部署 | 隐私要求 > 成本考虑时 |
| 10 | 消息队列 (Celery/RQ) | Worker 需要分布式调度时 |
| 11 | 实时协作 | 多人同时审核时 |

---

## 5. 最大技术风险 Top 10

| # | 风险 | 严重度 | 缓解措施 |
|---|---|---|---|
| 1 | **BLE 音频传输不可靠**（丢包、断连、速度慢） | 🔴 致命 | 早期硬件原型阶段就测 BLE 吞吐量；分片 + CRC32 + 断点续传；如 BLE 不达标考虑临时 Wi-Fi 直连方案 |
| 2 | **工牌硬件延期** → 软件无法端到端测试 | 🔴 致命 | 第一阶段用手机录音模拟工牌，验证完整 Agent 闭环 |
| 3 | **LLM 结构化输出不稳定**（JSON 解析失败） | 🟡 高 | Pydantic 二次校验 + retry + 降级到宽松 JSON parser |
| 4 | **Workflow Orchestrator 状态机 bug**（状态卡死） | 🟡 高 | 每个状态转移有 unit test；定时巡检 stuck session；admin 工具手动修正 |
| 5 | **飞书 API 限流 / 变更** | 🟡 高 | 重试 + backoff；飞书 API 变化概率低但影响大 |
| 6 | **手机端 BLE 后台限制**（iOS 尤其） | 🟡 高 | 早期验证 iOS BLE 后台模式；预留通知用户「请保持 App 前台」的 UX |
| 7 | **Whisper 中文转写准确率不达 95%** | 🟡 中 | 准备飞书语音 API 作为备选方案 |
| 8 | **LLM 费用超出预期** | 🟡 中 | 用量监控 + 成本告警；提炼时发送摘要而非全文以节省 token |
| 9 | **用户不信任「采集声明」机制** | 🟡 中 | 状态灯物理可见（工牌硬件）；控制台实时显示采集状态；用户可随时暂停/停止/撤回 |
| 10 | **知识沉淀「冷启动」**（初期工件质量低） | 🟢 低 | 人类审核是必须环节；随着审核反馈积累可微调 prompt 提高质量 |

---

## 6. 第一阶段 Vertical Slice 建议

> **目标**：在不依赖工牌硬件的情况下，跑通「采集 → 转写 → 提炼 → 审核 → 发布」的完整 Agent 闭环。

### 范围

| 包含 | 不包含 |
|---|---|
| 手机麦克风录音代替工牌 BLE 音频 | 工牌硬件 |
| 自研 Workflow Orchestrator + 5 张表 | BLE 分片协议 |
| Whisper 转写 + LLM 提炼 | Flutter BLE Bridge |
| 结构化工件生成（会议纪要 / FAQ / SOP） | 飞书真实发布（可先打桩） |
| 人工审核（批准/驳回/修改/重跑） | 多用户 RBAC（先单用户） |
| 信任守护（硬约束 + 审计日志） | 撤回（先做删除，不做级联） |
| Docker Compose 单机部署 | 性能优化 |
| Next.js 控制台（最小审核 UI） | |

### 交付物

1. **API 服务**：4 个 Agent Service + Workflow Orchestrator + Background Worker
2. **数据库**：PostgreSQL，包含 sessions / jobs / workflow_events / artifacts / audit_logs
3. **控制台**：Next.js，工件列表 + 审核面板
4. **Docker Compose**：一键启动
5. **测试**：完整链路集成测试（模拟音频 → 发布工件）

### 不依赖硬件的测试方法

```
手机录音 .m4a → 手动上传到 API
    → Orchestrator 创建 session + job
    → Worker 处理转写 + 提炼
    → 工件出现在控制台审核列表
    → Reviewer 审核 → 批准/驳回
    → 批准后工件状态变为 'published'
```

---

## 附录：ADR 索引

| ADR | 标题 | 推荐 | 类型 |
|---|---|---|---|
| 001 | 后端语言 | Python + FastAPI | — |
| 002 | Workflow 编排 | 自研持久化 Orchestrator | State Machine |
| 003 | 数据库 | PostgreSQL 单库 | — |
| 004 | 语音转写 | OpenAI Whisper API | — |
| 005 | BLE 控制面 | JSON over GATT | — |
| 006 | 移动端 | 最小 Flutter BLE Bridge + Next.js 控制台 | Client |
| 007 | LLM 服务 | OpenAI + adapter | — |
| 008 | 文件存储 | S3 兼容 | — |
| 009 | 部署 | Docker Compose | — |
| 010 | Node.js 后端 | 不引入 | — |
| 011 | 后台任务 | PG jobs 表 + Worker | Background Worker |
| 012 | 权限认证 | JWT + 最小 RBAC | Policy Engine |
| 013 | 信任守护 | 规则引擎 + LLM 辅助 + 硬约束 | Policy Engine + LLM Advisor |
| 014 | BLE 音频 | 自定义分片协议 over GATT | — |
| 015 | 数据生命周期 | 分层保留 + 级联删除 | — |
