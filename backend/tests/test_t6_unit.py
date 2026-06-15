"""Unit tests for Capture service and Configuration validation.

Tests for:
  - config.py: API key validation
  - capture/service.py: transcriber singleton and mock injection
  - providers/openai_whisper.py: TranscriptResult serialization
"""

import os
import tempfile

import pytest

from app.capture.service import get_transcriber, set_transcriber, transcribe_audio
from app.config import Settings, settings
from app.providers.base import TranscriptResult
from app.providers.openai_whisper import OpenAIWhisperProvider


# ── Config Validation ────────────────────────────────────────────────


class TestConfigValidation:
    """Test configuration defaults and validation."""

    def test_default_api_key_is_placeholder(self):
        """Default OPENAI_API_KEY should be 'sk-placeholder' (not empty)."""
        s = Settings()
        assert s.openai_api_key == "sk-placeholder"

    def test_config_from_env(self, monkeypatch):
        """Settings should pick up environment variables."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-real-key-123")
        s = Settings()
        assert s.openai_api_key == "sk-real-key-123"

    def test_audio_storage_path_default(self):
        """Default audio storage path is /data/audio."""
        s = Settings()
        assert s.audio_storage_path == "/data/audio"

    def test_database_url_format(self):
        """Database URL should use asyncpg driver."""
        s = Settings()
        assert "asyncpg" in s.database_url
        assert s.database_url_sync.startswith("postgresql://")


# ── Capture Service ───────────────────────────────────────────────────


class MockTranscriber:
    """Mock transcription provider for unit tests."""

    def __init__(self):
        self.last_audio_path = None
        self.last_language = None
        self.call_count = 0

    async def transcribe(self, audio_path: str, language: str | None = None) -> TranscriptResult:
        self.call_count += 1
        self.last_audio_path = audio_path
        self.last_language = language
        return TranscriptResult(
            transcript="Mock transcript from unit test.",
            segments=[{"start": 0.0, "end": 1.0, "text": "Mock"}],
            language="ja",
        )


class TestCaptureService:
    """Unit tests for the capture service module."""

    @pytest.mark.asyncio
    async def test_set_and_get_transcriber(self):
        """get_transcriber should return the set_transcriber mock."""
        mock = MockTranscriber()
        set_transcriber(mock)
        result = get_transcriber()
        assert result is mock

        # Reset for other tests
        set_transcriber(None)

    @pytest.mark.asyncio
    async def test_transcribe_audio_calls_provider(self):
        """transcribe_audio should delegate to the configured provider."""
        mock = MockTranscriber()
        set_transcriber(mock)

        # Create a temporary audio file
        with tempfile.NamedTemporaryFile(suffix=".opus", delete=False, prefix="test_audio_") as f:
            f.write(b"fake audio data")
            audio_path = f.name

        try:
            # Override audio_storage_path temporarily
            import app.capture.service as cap_service
            import app.config as cfg

            # Use the parent dir of temp file as storage path
            parent_dir = os.path.dirname(audio_path)
            old_path = cfg.settings.audio_storage_path
            cfg.settings.audio_storage_path = parent_dir
            audio_key = os.path.basename(audio_path)

            result = await cap_service.transcribe_audio(audio_key, language="ja")

            assert mock.call_count == 1
            assert audio_path in mock.last_audio_path
            assert mock.last_language == "ja"
            assert result.transcript == "Mock transcript from unit test."
            assert len(result.segments) == 1
            assert result.language == "ja"
        finally:
            os.unlink(audio_path)
            if old_path:
                cfg.settings.audio_storage_path = old_path

    @pytest.mark.asyncio
    async def test_transcriber_singleton_cached(self):
        """get_transcriber should cache the instance after first call."""
        set_transcriber(None)  # Reset
        t1 = get_transcriber()
        t2 = get_transcriber()
        assert t1 is t2

        set_transcriber(None)  # Reset for other tests


# ── OpenAI Whisper Provider (unit) ────────────────────────────────────


class TestOpenAIWhisperProvider:
    """Unit tests for OpenAIWhisperProvider (no real API calls)."""

    def test_provider_init_with_client(self):
        """Provider should accept a pre-built client."""
        import openai
        client = openai.AsyncOpenAI(api_key="test-key")
        provider = OpenAIWhisperProvider(client=client)
        assert provider.client is client
        assert provider.client.api_key == "test-key"

    def test_transcript_result_dataclass(self):
        """TranscriptResult should serialize correctly."""
        result = TranscriptResult(
            transcript="Hello world.",
            segments=[{"start": 0, "end": 1, "text": "Hello"}],
            language="en",
        )
        assert result.transcript == "Hello world."
        assert len(result.segments) == 1
        assert result.language == "en"
