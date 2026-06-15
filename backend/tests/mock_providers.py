"""Mock providers for testing — no real API calls.

DeterministicMockLLM returns structured outputs matching artifact schemas.
Used by all tests to avoid real OpenAI/Whisper calls.
"""

from typing import AsyncIterator

from app.providers.base import LLMProvider


class DeterministicMockLLM(LLMProvider):
    """Returns deterministic, schema-compliant outputs for testing.

    Detects the type of request from the schema and returns matching data.
    """

    async def complete(
        self,
        prompt: str,
        schema: dict | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> dict:
        """Return a deterministic JSON payload matching the requested schema."""
        # Summarize job
        if schema and "summary" in schema.get("properties", {}):
            return {
                "summary": "本次会议讨论了AI工牌Phase 1A的开发计划，决定使用FastAPI+PostgreSQL技术栈，采用自研Workflow Orchestrator。",
                "artifact_type": "meeting_minutes",
                "title": "AI工牌Phase 1A开发计划讨论",
            }

        # Sensitive content check
        if schema and "findings" in schema.get("properties", {}):
            return {"findings": []}

        # MeetingMinutes
        if schema and "participants" in schema.get("properties", {}):
            return {
                "title": "AI工牌Phase 1A开发计划讨论",
                "date": "2026-06-11",
                "participants": ["张三", "李四", "王五"],
                "summary": "团队讨论了AI工牌Phase 1A的开发计划，确定了技术栈和架构方案。",
                "key_points": [
                    "采用FastAPI + PostgreSQL技术栈",
                    "自研Workflow Orchestrator替代LangGraph",
                    "Saga模式处理撤回操作",
                ],
                "decisions": [
                    {
                        "decision": "使用FastAPI作为Web框架",
                        "rationale": "高性能异步支持",
                    },
                ],
                "action_items": [
                    {
                        "action": "搭建项目骨架",
                        "assignee": "后端工程师",
                        "deadline": "2026-06-12",
                    },
                ],
            }

        # DecisionRecord
        if schema and "context" in schema.get("properties", {}):
            return {
                "title": "技术栈选型决策",
                "context": "Phase 1A需要选定后端技术栈",
                "decision": "采用FastAPI + PostgreSQL + SQLAlchemy async",
                "rationale": "全异步支持，社区活跃，文档完善",
                "alternatives_considered": ["Django", "Flask", "Express.js"],
                "implications": "需要团队熟悉异步编程模式",
            }

        # FAQDraft or SOPDraft fallback
        return {
            "title": "默认文档标题",
            "questions": [{"q": "如何使用？", "a": "请参考文档"}],
        }

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream stub — yields a single chunk."""
        yield '{"summary": "测试摘要", "artifact_type": "meeting_minutes", "title": "测试标题"}'
