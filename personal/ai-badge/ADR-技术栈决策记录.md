# AI 工牌 — 架构决策记录 (ADR)

> 记录时间：2026-06-11  
> 决策人：大头（jasper.lijia@gmail.com）  
> 设计原则：Agent-first，专家技能沉淀，信任优先  
> 范围：仅软件层，不含硬件

---

## ADR-001：后端语言 — Python (FastAPI)

### 选择
**Python 3.11 + FastAPI** 作为后端主语言和 API 框架。

### 放弃项
- **Node.js (Express / Hono)**：JavaScript 生态成熟，但 LLM Agent 领域 Python 生态碾压性领先。
- **Go (Gin / Fiber)**：高性能，但 AI SDK（Whisper、OpenAI、LangChain）生态薄弱，写状态机不够自然。

### 选择理由
1. **LLM/Agent 生态不可替代**：OpenAI SDK、Whisper、Pydantic、LangChain/LangGraph 都是 Python 一等公民。用 Node.js 意味着每个 AI 能力都要找替代品或自己封装。
2. **Pydantic 是 Agent-first 的基石**：你 PRD 里所有「结构化输出」——转写文本、工件 JSON、状态机事件——都需要严格的 Schema 约束。Pydantic 的 `BaseModel` + `Validation` 是这件事的最佳工具。Node.js 的 Zod 虽然也能做到，但和 AI SDK 的集成远不如 Pydantic。
3. **团队认知成本最低**：Python 是 AI 工程师的默认语言，招聘、外包、开源贡献都最顺畅。
4. **FastAPI 异步原生**：Agent 的核心流程是 `采集 → 转写 → LLM处理 → 生成工件 → 人审核`，全程 I/O 密集，FastAPI 的 `async/await` 天然匹配。

### 风险
- **性能天花板**：Python 在极端并发场景（>10K QPS）不如 Go，但 MVP 阶段根本碰不到这个瓶颈。
- **GIL 限制**：CPU 密集型任务（如本地 Whisper）需走子进程。MVP 阶段走云端 API 可规避。

### 替代方案
- Go：如果未来工牌网关需要极低延迟的边缘推理，用 Go 重写网关模块。但那是 1.0 之后的事。

### 未来迁移成本
- **低**。Agent 核心逻辑是「编排 + 调 API」，语言无关。换语言主要是重写 HTTP 路由和 Schema 定义。Microservice 拆分后，性能敏感模块可以单独用 Go。

### MVP 是否必须引入
**是，必须**。MVP 从后端到 Agent 引擎都基于 Python。

---

## ADR-002：Agent 框架 — 自研状态机

### 选择
**自研状态机**（基于 Python `transitions` 库或纯手写），不引入 LangGraph。

### 放弃项
- **LangGraph**：LangChain 生态的一部分，提供 Agent 编排和状态管理。
- **CrewAI / AutoGen**：多 Agent 协作框架。
- **Dify / Coze**：低代码 Agent 搭建平台。

### 选择理由
1. **LangGraph 对你的场景是过度抽象**。你的 4 个 Agent 之间的通信方式是**结构化工件（JSON）**，不是 Agent-to-Agent 自然语言对话。LangGraph 最擅长的是「LLM 调用 → 观察结果 → 决定下一步」的 ReAct 循环。你的 Agent 不需要这个——随行记录 Agent 的下一步不是「想想再决定」，而是「转写完了，交给提炼 Agent」。这是线性 DAG，不是动态推理图。
2. **状态对你来说是审计要求，不是推理机制**。你和微软最重要的差异是信任。状态机是你的审计骨架——`Idle → Capturing → Processing → NeedApproval → Synced`。这用 20 行 Python 的状态枚举就能表达，不需要一个有向图引擎。
3. **LangGraph 的学习曲线和版本迭代风险**。LangChain 生态 API 变化极快，你今天写的 LangGraph 代码 6 个月后大概率需要重写。你的产品核心逻辑不应该绑在一个还在剧烈变化的框架上。
4. **你是 Agent-first，不是 Framework-first**。你的 Agent 设计由产品需求驱动，不是由框架能力驱动。自研状态机让你完全掌控每个状态转换的审计、权限检查、红线校验。

### 风险
- 需要自己处理并发状态冲突。如果工牌离线时用户继续操作，恢复连接后的状态合并需要自己实现。
- 多 Agent 协调逻辑如果没有框架约束，可能写散。

### 替代方案
- 1.0 后如果 Agent 数量增长到 10+，且出现复杂的 Agent-to-Agent 协商场景（如多个 Agent 竞争访问同一工件），再评估 LangGraph 或类似框架。

### 未来迁移成本
- **低**。状态机是逻辑层，不是基础设施层。迁移到 LangGraph 本质上是把状态枚举改成图定义。Agent 的工具函数（transcribe、summarize、extract）不需要重写。

### MVP 是否必须引入
**否，MVP 不引入 LangGraph**。自研状态机是 MVP 的正确选择。

---

## ADR-003：数据库 — PostgreSQL（单库）

### 选择
**PostgreSQL** 作为唯一数据库。MVP 不引入 Redis。

### 放弃项
- **Redis**：内存缓存 / 消息队列 / 会话状态存储。
- **MongoDB**：文档数据库。
- **SQLite**：嵌入式数据库。

### 选择理由
1. **PostgreSQL 是 Swiss Army Knife**。你的数据结构是「会话 + 用户 + 工件 + 审计」，典型的 relational model。PostgreSQL 的 JSONB 字段可以处理工件的半结构化数据，不需要单独的文档数据库。
2. **不需要 Redis 的 MVP 理由**：
   - **缓存**：MVP 用户量是个位数（你自己 + 测试者），不需要缓存层。
   - **会话状态**：Agent 会话状态通过 PostgreSQL 行锁 + state 字段管理。工牌是单用户单会话（一个人一次只能开一个采集会话），不存在高并发状态竞争。
   - **消息队列**：Agent 之间的工件传递（采集 → 提炼 → 集成）是同步链路，不是异步消息。用 PostgreSQL 的 `status` + `updated_at` 做轮询足够。真要异步，用 PostgreSQL 的 `LISTEN/NOTIFY`。
3. **减少运维复杂度**。MVP 只需要 `docker run postgres`，不需要维护多套存储。

### 风险
- 用户量增长后，高频审计写入可能成为瓶颈。但那是 1000+ 用户之后的事。
- 如果未来需要 WebSocket 推送（如控制台实时显示采集状态），PostgreSQL 的轮询方式会有延迟。

### 替代方案
- Redis 在以下时机引入：① 需要 WebSocket + Pub/Sub 实时推送；② 会话并发超过 100；③ 需要分布式锁。这三个场景在 MVP 都不会发生。

### 未来迁移成本
- **低**。引入 Redis 是加一层，不是替换。核心的 ORM 模型和业务逻辑不受影响。Redis 只作为 PostgreSQL 之前的缓存/消息层。

### MVP 是否必须引入
**否，MVP 不引入 Redis**。一个 PostgreSQL 实例足够。

---

## ADR-004：语音转写 — 云端 Whisper API

### 选择
**OpenAI Whisper API**（或兼容的飞书语音 API）作为语音转写服务。

### 放弃项
- **本地 Whisper 部署**：在自有服务器上运行 whisper-large-v3。
- **边缘端 Whisper**：在工牌硬件上做推理。
- **飞书原生语音转写**：如果飞书 SDK 已提供。

### 选择理由
1. **MVP 不需要处理硬件异构**。MVP 阶段音频从工牌通过 BLE 传到手机，手机上传到后端。后端调 Whisper API 是最短路径。
2. **准确率第一**。Whisper API 是目前中文转写准确率最高的服务之一。MVP 阶段转写质量直接影响下游 Agent 的工件质量。
3. **飞书集成可能更优**。如果你们已经在用飞书，飞书的语音转写 API 可能更便宜且额度更高。MVP 可以先对接 OpenAI，再加飞书适配器。

### 风险
- 云端 API 延迟（2-10 秒）对实时转写场景不够快。但你的场景不是实时字幕，是「采集完 → 转写」，2 秒延迟完全可以接受。
- 音频数据传到云端有隐私顾虑。需要在传输层做端到端加密（TLS + 可选的应用层加密）。

### 替代方案
- 1.0 后如果用户对延迟或隐私有更高要求，在自有 GPU 服务器部署 Whisper。

### 未来迁移成本
- **低**。转写能力通过 `TranscriptionProvider` 接口封装，换服务不改 Agent 逻辑。

### MVP 是否必须引入
**是，必须**。转写是采集 Agent 的核心能力。

---

## ADR-005：BLE 通信协议 — JSON over BLE

### 选择
**JSON over BLE GATT**，不引入 Protobuf。

### 放弃项
- **Protobuf**：结构化二进制序列化协议。
- **MessagePack / CBOR**：二进制 JSON。

### 选择理由
1. **工牌传输的数据量极小**。一次会话的传输内容是：控制指令（start/stop/pause，几十字节）+ 音频流（唯一的大数据）+ 状态同步（几十字节）。只有音频流需要优化，指令和控制消息的序列化开销可以忽略不计。
2. **JSON 可调试性在 MVP 阶段无价**。用 `nRF Connect` 抓 BLE 包时，JSON 直接用肉眼读。Protobuf 需要 `.proto` 文件和专用工具才能解码。MVP 阶段你需要在工牌和手机之间反复调试，JSON 节省的时间远超它浪费的带宽。
3. **Protobuf 的收益点你现在没有**。Protobuf 的强大在于：① 不同语言客户端共用 schema；② 字段级别的向前兼容；③ 极小序列化体积。你的场景：只有一端（工牌）到一端（手机 App），体积极小（控制消息），向前兼容用小版本号就能处理。
4. **音频走独立的 BLE Audio 或专有通道**，不走 GATT JSON。JSON 只传控制面和状态面。

### 风险
- 如果未来工牌传感器数据量大增（如增加摄像头、心率和体温传感器），JSON 体积会膨胀。那是硬件 v2 的事。
- BLE GATT 的 MTU 限制（通常 20-512 字节），长 JSON 消息需要分包。但这只影响控制消息（很少超过 MTU）。

### 替代方案
- 当工牌需要传输 100KB+ 的结构化数据时，再引入 Protobuf 或 MessagePack。

### 未来迁移成本
- **中低**。Protobuf 可以和 JSON 并存——控制消息用 JSON（保持可调试性），传感器数据用 Protobuf（追求效率）。不需要一次性全切。

### MVP 是否必须引入
**否，MVP 不引入 Protobuf**。JSON over BLE 足够。

---

## ADR-006：前端控制台 — Next.js (React)

### 选择
**Next.js (React) + Tailwind CSS**，部署为 Web 应用。MVP 不引入 Flutter。

### 放弃项
- **Flutter**：Google 的跨平台移动端框架。
- **React Native**：Facebook 的跨平台移动端框架。
- **纯移动端原生（Swift/Kotlin）**。

### 选择理由
1. **控制台是桌面场景，不是移动场景**。用户审核工件（读长文档、对比版本、修改内容、批注）需要大屏幕和键盘。手机只是通知入口和采集启动器。控制台的核心体验在桌面浏览器。
2. **Next.js 和 Python 后端共用一人**。后端是 Python，前端是 Next.js，都是 AI 友好的技术栈。Flutter 需要 Dart，多一门语言，多一套工具链。
3. **Tailwind CSS 组件化快**。MVP 的控制台是表单和列表为主的「后台管理」风格，Tailwind + shadcn/ui 或类似组件库可以极速出 UI。
4. **手机端用 PWA 兜底**。如果确实需要手机上看工单状态，Next.js 做 PWA 加上推送通知足够。不需要原生 App 的性能。

### 风险
- 如果未来工牌需要手机端的复杂交互（如实时 BLE 配网、固件升级进度），Web 应用在后台运行时 BLE 能力受限。这是硬件连调阶段才暴露的问题。

### 替代方案
- 当手机端成为「一等使用场景」（不只是通知入口）时，评估 Flutter 或 React Native。Flutter 的 BLE 插件生态比 Web Bluetooth API 更稳定。

### 未来迁移成本
- **中**。如果从 Web 迁移到 Flutter，前端代码需要重写。但 API 层和后端是解耦的，只重写 UI 层。而且 Next.js 的控制台逻辑（API 调用、状态管理）可以抽象为共享 SDK，供 Flutter 复用。

### MVP 是否必须引入
**否，MVP 不引入 Flutter**。Next.js Web 应用是最佳选择。

---

## ADR-007：LLM 服务 — OpenAI API（可替换）

### 选择
**OpenAI API (GPT-4o)** 作为 LLM 服务提供方，通过适配器模式支持替换。

### 放弃项
- **自部署开源模型（Llama/Qwen）**：需要 GPU 集群。
- **单一国产模型**：锁定一家不可取。
- **LangChain LLM 抽象层**：不必要的依赖。

### 选择理由
1. **结构化输出能力最强**。GPT-4o 的 JSON Schema 约束输出是目前主流服务中最稳定的。你的 Agent 输出必须是严格结构化的工件，不能是「大概能解析的 JSON」。
2. **中文能力**。GPT-4o 中文理解和生成能力在第一梯队。
3. **适配器解耦**。不直接在 Agent 代码里调 OpenAI SDK，而是通过 `LLMProvider` 接口。未来换 Claude、Qwen、或私有模型时，只改适配器。

### 风险
- API 费用在大量使用后会累积。一次 30 分钟会议的完整 Agent 处理（转写 + 提炼 + 同步）大概消耗 50K-100K tokens，按 GPT-4o 价格约 $0.25-0.50/次。
- 数据传到 OpenAI 的隐私问题。需要与 OpenAI 确认 API 数据不用于训练（默认已关闭）。

### 替代方案
- 当数据隐私要求提高时，切换到 Azure OpenAI Service（企业合规）或自部署 Qwen/Llama。

### 未来迁移成本
- **低**。`LLMProvider` 接口隔离。迁移只需要换一个适配器实现。

### MVP 是否必须引入
**是，必须**。LLM 是所有 Agent 的核心推理能力。

---

## ADR-008：音视频存储 — S3 兼容对象存储

### 选择
**S3 兼容对象存储**（阿里云 OSS / AWS S3 / MinIO）存储原始音频和工件。

### 放弃项
- 数据库存储大文件（PostgreSQL 的 BYTEA / Large Object）。
- 本地文件系统。

### 选择理由
1. **数据库不是文件系统**。原始音频 30 分钟 ≈ 30MB。存 PostgreSQL 会膨胀备份体积、拖慢查询。
2. **S3 自带 CDN**。工件中的音频引用链接直接是 CDN URL，用户点击就能播放。
3. **生命周期管理**。可以设置 Policy：原始音频 90 天后自动归档/删除，节省存储费。

### 未来迁移成本
- **低**。S3 兼容 API 是行业标准，换服务商几乎零改动。

### MVP 是否必须引入
**是，必须**。原始音频必须有地方存。

---

## ADR-009：部署 — Docker Compose（单机）

### 选择
**Docker Compose 单机部署**。MVP 不引入 Kubernetes 或云原生编排。

### 放弃项
- Kubernetes (K8s)。
- Serverless（如阿里云函数计算、AWS Lambda）。
- 裸机部署。

### 选择理由
1. **Docker Compose 三行命令启动**：`docker compose up -d`。PostgreSQL + FastAPI + Next.js 三个容器，一个 compose 文件搞定。
2. **开发/生产环境一致**。不会出现「我机器上能跑」的问题。
3. **服务数只有 3 个**（API + Web + DB），K8s 是杀鸡用牛刀。等你的服务拆成 8+ 个微服务后再上编排。

### 未来迁移成本
- **低到中**。Docker Compose → K8s 的迁移主要工作是写 Helm Chart 和 Ingress 配置。应用本身不需要改。

### MVP 是否必须引入
**是，必须**。Docker 是 MVP 最务实的部署方式。

---

## ADR-010：Node.js — 仅在需要时引入

### 选择
**在 MVP 阶段不引入 Node.js 作为后端运行时**。仅在前端（Next.js）中用到 Node.js 作为构建工具和 SSR。

### 放弃项
- Node.js 作为后端 API 服务。
- 同时维护 Python 和 Node.js 两套后端。

### 选择理由
1. **两套运行时 = 两套部署 + 两套监控 + 两套依赖管理**。MVP 阶段维护成本超过收益。
2. **Python 能做所有事**。API、Agent、LLM 调用、转写、数据库操作——不需要 Node.js。

### 什么时候引入 Node.js
- 如果前端需要 SSR + BFF（Backend for Frontend）模式，Next.js 的 API Routes 可以充当轻量 BFF。但这是「前端自己的后端」，不是核心服务的替代。

### MVP 是否必须引入
**否，MVP 不需要 Node.js 作为后端服务**。

---

## 汇总：MVP 技术栈全景

```
                     ┌──────────────────────┐
                     │   控制台 (Next.js)     │  ← Node.js (仅前端)
                     │   审核/修改/批注       │
                     │   Web 应用，非移动 App │
                     └──────────┬───────────┘
                                │ HTTP/SSE
                     ┌──────────▼───────────┐
                     │   API 服务 (FastAPI)   │
                     │   + 4 Agent 引擎       │  ← Python 3.11
                     │   + 自研状态机          │
                     └──────────┬───────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
     ┌────────▼────┐  ┌────────▼────┐  ┌─────────▼──────┐
     │ PostgreSQL   │  │ S3 兼容存储  │  │ 外部 API        │
     │              │  │              │  │ (Whisper/LLM)  │
     │ 会话/工件/    │  │ 原始音频/     │  │                │
     │ 审计/用户     │  │ 工件文件      │  │                │
     └─────────────┘  └─────────────┘  └────────────────┘

     ❌ 不引入的：Redis、LangGraph、Flutter、Protobuf、Node.js（后端）、K8s
```

| 层 | 选型 | 是否 MVP 必须 |
|---|---|---|
| **后端语言** | Python 3.11 + FastAPI | ✅ 是 |
| **Agent 框架** | 自研状态机 | ✅ 是 |
| **数据库** | PostgreSQL（唯一数据库） | ✅ 是 |
| **缓存/队列** | 无。MVP 不引入 Redis | ❌ 否 |
| **LLM** | OpenAI API（适配器隔离） | ✅ 是 |
| **语音转写** | OpenAI Whisper API | ✅ 是 |
| **BLE 协议** | JSON over BLE GATT | ✅ 是 |
| **序列化协议** | JSON。不引入 Protobuf | ❌ 否 |
| **前端** | Next.js (React) + Tailwind | ✅ 是 |
| **移动端** | 不引入 Flutter。Web PWA 兜底 | ❌ 否 |
| **文件存储** | S3 兼容对象存储 | ✅ 是 |
| **部署** | Docker Compose 单机 | ✅ 是 |
| **Node.js 后端** | 不引入。仅前端构建用 | ❌ 否 |
