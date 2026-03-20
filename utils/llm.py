"""
utils/llm.py
------------
Thin async wrapper around the OpenAI Chat Completions API.

Usage
-----
from utils.llm import ask_llm

response_text = await ask_llm(user_message="...", stats_context="...")
"""

import logging
import os

from openai import AsyncOpenAI, RateLimitError, APITimeoutError, APIStatusError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
あなたは親身で優秀なHypixel Skyblockの専属サポーターです。
ユーザーの現在のステータス（後述）を考慮し、背伸びしすぎない現実的で具体的なアドバイスを提供してください。
回答は日本語で、Discord上で読みやすいようにMarkdownを活用して簡潔にまとめてください。
"""


def _get_client() -> AsyncOpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY environment variable is not set.")
    return AsyncOpenAI(api_key=api_key)


async def ask_llm(
    user_message: str,
    stats_context: str,
    *,
    model: str | None = None,
    max_tokens: int = 1024,
) -> str:
    """
    Send *user_message* plus *stats_context* to the LLM and return the
    assistant's reply as a plain string.

    Parameters
    ----------
    user_message:
        The question or instruction from the Discord user.
    stats_context:
        A formatted block describing the player's current Skyblock stats.
    model:
        Override the model (defaults to the ``OPENAI_MODEL`` env var or
        ``gpt-4o-mini``).
    max_tokens:
        Maximum tokens for the completion response.
    """
    chosen_model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"{stats_context}\n\n---\n\n{user_message}",
        },
    ]

    client = _get_client()
    try:
        response = await client.chat.completions.create(
            model=chosen_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
        )
        return response.choices[0].message.content or ""
    except RateLimitError:
        logger.warning("OpenAI rate limit reached")
        raise
    except APITimeoutError:
        logger.warning("OpenAI request timed out")
        raise
    except APIStatusError as exc:
        logger.error("OpenAI API error: %s", exc)
        raise
