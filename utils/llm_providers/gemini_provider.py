"""
utils/llm_providers/gemini_provider.py
---------------------------------------
LLM provider backed by the Google Gemini ``generateContent`` REST API.

Uses plain ``aiohttp`` – no Google-specific SDK required.

Required environment variables
-------------------------------
GEMINI_API_KEY   Your Google AI Studio API key.
                 Obtain a free-tier key at https://aistudio.google.com/app/apikey

Optional environment variables
--------------------------------
GEMINI_MODEL     Model name (default: ``gemini-1.5-flash``).
                 Free-tier friendly choices: ``gemini-1.5-flash``, ``gemini-1.5-flash-8b``
"""

import logging
import os

import aiohttp

from .base import LLMProvider, RetryableError

logger = logging.getLogger(__name__)

_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models"
    "/{model}:generateContent"
)

# HTTP status codes that are safe to retry.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


class GeminiProvider(LLMProvider):
    """Google Gemini REST API provider."""

    name = "gemini"

    def __init__(self) -> None:
        self._api_key = os.environ.get("GEMINI_API_KEY", "")
        self._model = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def chat(self, messages: list[dict], max_tokens: int) -> str:
        if not self._api_key:
            raise RetryableError("Gemini is not configured (missing GEMINI_API_KEY)")

        contents = _convert_messages(messages)
        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": 0.7,
            },
        }
        url = _API_URL.format(model=self._model)
        params = {"key": self._api_key}

        try:
            # A new session is created per request.  For a low-throughput Discord
            # bot this is acceptable and avoids async lifecycle management.
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, params=params, timeout=_REQUEST_TIMEOUT
                ) as resp:
                    if resp.status in _RETRYABLE_STATUS:
                        body = await resp.text()
                        logger.warning("Gemini HTTP %s: %s", resp.status, body[:200])
                        raise RetryableError(f"Gemini HTTP {resp.status}")
                    resp.raise_for_status()
                    data = await resp.json()
        except aiohttp.ServerTimeoutError as exc:
            raise RetryableError(f"Gemini request timed out: {exc}") from exc
        except aiohttp.ClientConnectionError as exc:
            raise RetryableError(f"Gemini network error: {exc}") from exc
        except RetryableError:
            raise
        except aiohttp.ClientError as exc:
            raise RetryableError(f"Gemini client error: {exc}") from exc

        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.error("Unexpected Gemini response shape: %s", data)
            raise ValueError(f"Unexpected Gemini response: {data}") from exc


def _convert_messages(messages: list[dict]) -> list[dict]:
    """Convert OpenAI-style messages to the Gemini ``contents`` format.

    Gemini does not have a dedicated system role.  We prepend the system
    message text to the first user turn so the instruction is not lost.
    """
    system_text = ""
    contents: list[dict] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "system":
            system_text = content
        elif role == "user":
            # Inject system prompt into the first user turn.
            if system_text:
                content = f"{system_text}\n\n{content}"
                system_text = ""  # only prepend once
            contents.append({"role": "user", "parts": [{"text": content}]})
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": content}]})

    return contents
