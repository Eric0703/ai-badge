"""Mock Whisper provider — returns fixed transcript for testing.

Does NOT call any real API. Used by default until OPENAI_API_KEY is configured.
"""

from app.providers.base import TranscriptionProvider, TranscriptResult


class MockWhisperProvider(TranscriptionProvider):
    """Mock transcription provider for testing and development."""

    async def transcribe(
        self, audio_path: str, language: str | None = None
    ) -> TranscriptResult:
        """Return a fixed transcript regardless of input."""
        return TranscriptResult(
            transcript="这是一段测试转写文本。今天会议讨论了AI工牌项目的Phase 1A开发计划，"
                       "团队决定采用FastAPI + PostgreSQL的技术栈，并使用自研Workflow Orchestrator。"
                       "下一步需要完成音频上传和转写功能。",
            segments=[
                {"start": 0.0, "end": 5.2, "text": "这是一段测试转写文本。"},
                {"start": 5.2, "end": 12.0, "text": "今天会议讨论了AI工牌项目的Phase 1A开发计划，"},
                {"start": 12.0, "end": 20.0, "text": "团队决定采用FastAPI + PostgreSQL的技术栈，"},
                {"start": 20.0, "end": 26.5, "text": "并使用自研Workflow Orchestrator。"},
                {"start": 26.5, "end": 32.0, "text": "下一步需要完成音频上传和转写功能。"},
            ],
            language="zh",
        )
