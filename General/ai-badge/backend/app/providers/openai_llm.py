"""OpenAI LLM provider — GPT-4o with JSON Schema structured output."""

import json

from openai import AsyncOpenAI

from app.config import settings
from app.providers.base import LLMProvider


class OpenAILLMProvider(LLMProvider):
    """OpenAI Chat Completions with structured output support."""

    def __init__(self, client: AsyncOpenAI | None = None):
        self._client = client

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
            )
        return self._client

    async def complete(
        self,
        prompt: str,
        schema: dict | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> dict:
        """Send a prompt and return structured output.

        When schema is provided, uses OpenAI's structured outputs
        (response_format with json_schema) to constrain the response.
        """
        kwargs: dict = {
            "model": model or "gpt-4o",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_output",
                    "strict": True,
                    "schema": schema,
                },
            }

        response = await self.client.chat.completions.create(**kwargs)
        text = response.choices[0].message.content or "{}"

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw_text": text}

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ):
        """Stream a chat completion response."""
        stream = await self.client.chat.completions.create(
            model=model or "gpt-4o",
            messages=messages,
            temperature=temperature,
            stream=True,
            max_tokens=max_tokens,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
