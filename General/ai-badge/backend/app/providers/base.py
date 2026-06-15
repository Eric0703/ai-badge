"""Abstract provider interfaces for LLM and Transcription services.

All external AI services go through these interfaces so we can
swap implementations (OpenAI → local model) without touching business logic.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class TranscriptResult:
    """Result of a transcription request."""
    transcript: str
    segments: list[dict] = field(default_factory=list)
    language: str = ""


class TranscriptionProvider(ABC):
    """Transcription service (Whisper or equivalent)."""

    @abstractmethod
    async def transcribe(
        self, audio_path: str, language: str | None = None
    ) -> TranscriptResult:
        """Transcribe an audio file, returning transcript, segments, and language."""
        ...


class LLMProvider(ABC):
    """LLM service (OpenAI Chat or equivalent)."""

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        schema: dict | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> dict:
        """Send a prompt and return structured output.

        If schema is provided, the response is constrained to match
        the JSON Schema (via structured outputs / function calling).
        """
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream a chat completion response (for real-time UI)."""
        ...
