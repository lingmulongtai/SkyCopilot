"""
utils/llm_providers/groq_provider.py
--------------------------------------
LLM provider backed by the Groq API (OpenAI-compatible endpoint).

Uses plain ``aiohttp`` – no Groq-specific SDK required.

Required environment variables
-------------------------------
GROQ_API_KEY   Your Groq API key.
               Obtain a free-tier key at https://console.groq.com/keys

Optional environment variables
--------------------------------
GROQ_MODEL     Model name (default: ``llama3-8b-8192``).
               Free-tier choices: ``llama3-8b-8192``, ``llama3-70b-8192``,
               ``mixtral-8x7b-32768``, ``gemma2-9b-it``
"""

import logging
import os

import aiohttp

from .base import LLMProvider, RetryableError

logger = logging.getLogger(__name__)

_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# HTTP status codes that are safe to retry.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


class GroqProvider(LLMProvider):
    """Groq (OpenAI-compatible) REST API provider."""

    name = "groq"

    def __init__(self) -> None:
        self._api_key = os.environ.get("GROQ_API_KEY", "")
        self._model = os.environ.get("GROQ_MODEL", "llama3-8b-8192")

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def chat(self, messages: list[dict], max_tokens: int) -> str:
        if not self._api_key:
            raise RetryableError("Groq is not configured (missing GROQ_API_KEY)")

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
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    _API_URL,
                    json=payload,
                    headers=headers,
                    timeout=_REQUEST_TIMEOUT,
                ) as resp:
                    if resp.status in _RETRYABLE_STATUS:
                        body = await resp.text()
                        logger.warning("Groq HTTP %s: %s", resp.status, body[:200])
                        raise RetryableError(f"Groq HTTP {resp.status}")
                    resp.raise_for_status()
                    data = await resp.json()
        except aiohttp.ServerTimeoutError as exc:
            raise RetryableError(f"Groq request timed out: {exc}") from exc
        except aiohttp.ClientConnectionError as exc:
            raise RetryableError(f"Groq network error: {exc}") from exc
        except RetryableError:
            raise
        except aiohttp.ClientError as exc:
            raise RetryableError(f"Groq client error: {exc}") from exc

        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            logger.error("Unexpected Groq response shape: %s", data)
            raise ValueError(f"Unexpected Groq response: {data}") from exc
