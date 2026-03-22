"""
utils/llm_providers/openrouter_provider.py
-------------------------------------------
LLM provider backed by the OpenRouter API (OpenAI-compatible endpoint).

Uses plain ``aiohttp`` – no additional SDK required.

Required environment variables
-------------------------------
OPENROUTER_API_KEY   Your OpenRouter API key.
                     Obtain a free-tier key at https://openrouter.ai/keys

Optional environment variables
--------------------------------
OPENROUTER_MODEL     Model name (default: ``openai/gpt-4o-mini``).
                     Free-tier choices: ``openai/gpt-4o-mini``,
                     ``meta-llama/llama-3-8b-instruct:free``,
                     ``google/gemma-3-12b-it:free``
"""

import logging
import os

import aiohttp

from .base import LLMProvider, RetryableError

logger = logging.getLogger(__name__)

_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# HTTP status codes that are safe to retry.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


class OpenRouterProvider(LLMProvider):
    """OpenRouter (OpenAI-compatible) REST API provider."""

    name = "openrouter"

    def __init__(self) -> None:
        self._api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self._model = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def chat(self, messages: list[dict], max_tokens: int) -> str:
        if not self._api_key:
            raise RetryableError(
                "OpenRouter is not configured (missing OPENROUTER_API_KEY)"
            )

        payload = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.7,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            # A new session is created per request.  For a low-throughput Discord
            # bot this is acceptable and avoids async lifecycle management.
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    _API_URL,
                    json=payload,
                    headers=headers,
                    timeout=_REQUEST_TIMEOUT,
                ) as resp:
                    if resp.status in _RETRYABLE_STATUS:
                        body = await resp.text()
                        logger.warning(
                            "OpenRouter HTTP %s: %s", resp.status, body[:200]
                        )
                        raise RetryableError(f"OpenRouter HTTP {resp.status}")
                    resp.raise_for_status()
                    data = await resp.json()
        except aiohttp.ServerTimeoutError as exc:
            raise RetryableError(f"OpenRouter request timed out: {exc}") from exc
        except aiohttp.ClientConnectionError as exc:
            raise RetryableError(f"OpenRouter network error: {exc}") from exc
        except RetryableError:
            raise
        except aiohttp.ClientError as exc:
            raise RetryableError(f"OpenRouter client error: {exc}") from exc

        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            logger.error("Unexpected OpenRouter response shape: %s", data)
            raise ValueError(f"Unexpected OpenRouter response: {data}") from exc
