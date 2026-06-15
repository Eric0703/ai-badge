# <comment-start data-id="WF7BPACCNK06CM9JOY8BT" />🚀 AI 工牌 Phase 1A 开工令<comment-end data-id="WF7BPACCNK06CM9JOY8BT" />

> 发令时间：2026-06-11  
> 协调员：大头's momo  
> 决策人：[@大头](mention://member/177823736614000)

---

## 项目背景

我们要做一个 **Agent-first** 的 AI 工牌。不是「把 Copilot 塞进可穿戴设备」，而是「从 Agent 的责任范围和决策权限出发，反向设计整个系统」。核心闭环：采集 → 转写 → LLM 提炼 → 结构化工件 → 人工审核 → 发布。

Phase 1A 的目标：**纯后端闭环**。不依赖工牌硬件，`docker compose up` 后一个人用 curl 就能跑通完整链路。

---

## 三个队友，初始分工

[@后端工程师](mention://agent/178119067182000)  
负责 Phase 1A 全部后端开发（T1~T9, T11）。技术栈：Python 3.11 + FastAPI + PostgreSQL + SQLAlchemy async。  
核心约束：自研 Workflow Orchestrator（不用 LangGraph）、jobs 表轮询 Worker（不用 Redis/Celery）、audit_logs 只 INSERT、撤回用 Saga + deletion_jobs。

[@测试工程师](mention://agent/178119091065000)  
<comment-start data-id="K5MMBM10O06JUBDA9SPQF" />负责所有测试（T10 + 各模块单元测试）。所有测试使用 Mock LLM/Whisper provider，不调真实 API。<comment-end data-id="K5MMBM10O06JUBDA9SPQF" />  
覆盖：Happy Path + Failure（失败→重试） + Review Cycle（驳回→重提炼） + Retract Path（撤回→级联删除）。

[@技术文档工程师](mention://agent/178119099277000)  
负责 README（T12）+ 模块 docstring。  
核心要求：README 里的 curl 示例必须可直接复制粘贴执行，让一个新人 10 分钟内跑通全流程。

---

## 参考文档（必读）

- **ADR v2.3**：`personal/ai-badge/ADR-技术栈决策记录-v2.md` — 所有技术决策的权威来源
- **Phase1 开发包**：`personal/ai-badge/Phase1-开发包.md` — ticket 列表、验收标准、测试计划、API 列表

---

## 开发顺序

```
T1 (骨架) → T2 (migration) → T3 (认证)
                                  │
                ┌─────────────────┤
                ▼                 ▼
          T4 (sessions)    T5 (orchestrator+worker)
                │                 │
                └────────┬────────┘
                         ▼
                  T6 (capture: Whisper)
                         │
                         ▼
                  T7 (distiller: LLM)
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
                  T12 (docs/README)
```

---

## 工作约定

1. **每个 ticket 开始前**：读 Phase1 开发包中该 ticket 的验收标准
2. **代码规范**：所有 Pydantic model 有类型注解，async SQLAlchemy session，API 返回 OpenAPI 3.0 兼容
3. **阻塞时**：在文档上留 comment `[@大头](mention://member/177823736614000)` 说明卡在哪
4. **完成后**：@测试工程师 说「Ticket X 完成，请写测试」
5. **测试通过后**：@大头 + 留 comment 说「Ticket X 已完成，请审核」

---

## 第一个动作

[@后端工程师](mention://agent/178119067182000)：请从 **Ticket 1（项目骨架 + Docker Compose）** 开始。先读 ADR v2.3 和 Phase1 开发包，然后搭建 `ai-badge/backend/` 目录结构。目标：`docker compose up -d` 后 `/api/v1/health` 返回 200。

开始吧。
