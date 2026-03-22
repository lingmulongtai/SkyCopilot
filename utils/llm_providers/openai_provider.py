"""
utils/llm_providers/openai_provider.py
---------------------------------------
LLM provider backed by the OpenAI Chat Completions API.

Required environment variables
-------------------------------
OPENAI_API_KEY   Your OpenAI API key.

Optional environment variables
--------------------------------
OPENAI_MODEL     Model name (default: ``gpt-4o-mini``).
"""

import logging
import os

from openai import AsyncOpenAI, APIStatusError, APITimeoutError, RateLimitError

from .base import LLMProvider, RetryableError

logger = logging.getLogger(__name__)

# HTTP status codes that are safe to retry on the OpenAI side.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class OpenAIProvider(LLMProvider):
    """OpenAI Chat Completions provider."""

    name = "openai"

    def __init__(self) -> None:
        self._api_key = os.environ.get("OPENAI_API_KEY", "")
        self._model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self._client: AsyncOpenAI | None = (
            AsyncOpenAI(api_key=self._api_key) if self._api_key else None
        )

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def chat(self, messages: list[dict], max_tokens: int) -> str:
        if self._client is None:
            raise RetryableError("OpenAI is not configured (missing OPENAI_API_KEY)")

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.7,
            )
            return response.choices[0].message.content or ""
        except RateLimitError as exc:
            logger.warning("OpenAI rate limit: %s", exc)
            raise RetryableError(f"OpenAI rate limit: {exc}") from exc
        except APITimeoutError as exc:
            logger.warning("OpenAI request timed out: %s", exc)
            raise RetryableError(f"OpenAI timeout: {exc}") from exc
        except APIStatusError as exc:
            if exc.status_code in _RETRYABLE_STATUS:
                logger.warning("OpenAI server error %s: %s", exc.status_code, exc)
                raise RetryableError(
                    f"OpenAI server error {exc.status_code}: {exc}"
                ) from exc
            logger.error("OpenAI non-retryable error %s: %s", exc.status_code, exc)
            raise
