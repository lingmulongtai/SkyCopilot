"""
utils/llm_providers/base.py
---------------------------
Abstract base class and shared exception types for LLM providers.
"""

from abc import ABC, abstractmethod


class RetryableError(Exception):
    """Raised by a provider when the request should be retried.

    Examples: HTTP 429, request timeout, transient 5xx server errors,
    or network connectivity problems.
    """


class LLMProvider(ABC):
    """Abstract base for all LLM provider implementations."""

    #: Short identifier used for logging and circuit-breaker keys.
    name: str

    @abstractmethod
    async def chat(self, messages: list[dict], max_tokens: int) -> str:
        """Send *messages* to the LLM and return the assistant reply.

        Parameters
        ----------
        messages:
            List of ``{"role": ..., "content": ...}`` dicts in the same
            format as the OpenAI Chat Completions API.
        max_tokens:
            Maximum tokens to generate in the reply.

        Raises
        ------
        RetryableError
            When the failure is transient and the caller should retry
            (e.g. rate-limit, timeout, 5xx).
        Exception
            Any other exception is treated as non-retryable.
        """

    def is_configured(self) -> bool:
        """Return ``True`` when the provider has all required credentials."""
        return True
