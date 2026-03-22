"""
utils/llm.py
------------
Multi-provider LLM gateway for the Discord bot.

``ask_llm`` is the single public entry-point used by cogs.  Internally it
delegates to :mod:`utils.llm_router` which handles provider selection,
retries, exponential back-off, and circuit breaking.

Usage
-----
from utils.llm import ask_llm

response_text = await ask_llm(user_message="...", stats_context="...")
"""

import logging
import os

from utils.llm_format import SYSTEM_PROMPT, enforce_format
from utils.llm_providers.gemini_provider import GeminiProvider
from utils.llm_providers.groq_provider import GroqProvider
from utils.llm_providers.openai_provider import OpenAIProvider
from utils.llm_router import LLMRouter

logger = logging.getLogger(__name__)

# Registry of provider name → class.  Add new providers here.
_PROVIDER_REGISTRY = {
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "groq": GroqProvider,
}

# Module-level router singleton; reset with _reset_router() in tests.
_router: LLMRouter | None = None


def _build_router() -> LLMRouter:
    """Construct an :class:`~utils.llm_router.LLMRouter` from env vars."""
    order_raw = os.environ.get("LLM_PROVIDER_ORDER", "openai")
    names = [n.strip().lower() for n in order_raw.split(",") if n.strip()]

    providers = []
    for name in names:
        cls = _PROVIDER_REGISTRY.get(name)
        if cls is None:
            logger.warning(
                "Unknown provider %r in LLM_PROVIDER_ORDER – skipping", name
            )
            continue
        provider = cls()
        if not provider.is_configured():
            logger.info(
                "Provider %s has no API key configured – skipping", name
            )
            continue
        providers.append(provider)

    if not providers:
        raise EnvironmentError(
            "No LLM providers are configured.  "
            "Set at least one of OPENAI_API_KEY, GEMINI_API_KEY, or GROQ_API_KEY "
            "and include the corresponding name in LLM_PROVIDER_ORDER."
        )

    return LLMRouter(providers)


def _get_router() -> LLMRouter:
    global _router
    if _router is None:
        _router = _build_router()
    return _router


def _reset_router() -> None:
    """Reset the cached router singleton (useful in tests)."""
    global _router
    _router = None


async def ask_llm(
    user_message: str,
    stats_context: str,
    *,
    model: str | None = None,  # kept for backward compatibility; use OPENAI_MODEL env var
    max_tokens: int = 1024,
) -> str:
    """Send *user_message* plus *stats_context* to the LLM and return the reply.

    Parameters
    ----------
    user_message:
        The question or instruction from the Discord user.
    stats_context:
        A formatted block describing the player's current Skyblock stats.
    model:
        Accepted for backward compatibility.  Set ``OPENAI_MODEL`` (or the
        equivalent env var for other providers) to control the model instead.
    max_tokens:
        Maximum tokens for the completion response.

    Raises
    ------
    utils.llm_router.LLMUnavailableError
        When every configured provider has been exhausted.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"{stats_context}\n\n---\n\n{user_message}",
        },
    ]

    router = _get_router()
    raw = await router.chat(messages, max_tokens)
    return enforce_format(raw)
