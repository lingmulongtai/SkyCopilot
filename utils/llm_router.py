"""
utils/llm_router.py
--------------------
Fallback-first multi-LLM routing layer.

Features
--------
* Tries providers in the configured order.
* Retries each provider on retryable failures (HTTP 429, timeout, 5xx)
  using exponential back-off with jitter.
* Implements a simple circuit breaker per provider: after
  ``LLM_CB_FAILURE_THRESHOLD`` consecutive failures the provider is
  skipped for ``LLM_CB_RECOVERY_SECONDS`` before being tried again.

All tuning knobs are read from environment variables so free-tier limits
can be adjusted without touching code.

Environment variables
----------------------
LLM_RETRY_MAX              Max retries per provider (default: 3).
LLM_RETRY_BASE_SECONDS     Base delay for exponential back-off (default: 1.0).
LLM_CB_FAILURE_THRESHOLD   Failures before circuit opens (default: 3).
LLM_CB_RECOVERY_SECONDS    Seconds before a tripped circuit re-allows attempts
                           (default: 60).
"""

import asyncio
import logging
import os
import random
import time
from collections.abc import Sequence

from utils.llm_providers.base import LLMProvider, RetryableError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (ValueError, TypeError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


class CircuitBreaker:
    """Per-provider circuit breaker.

    States
    ------
    CLOSED  – healthy; all requests pass through.
    OPEN    – unhealthy; requests are skipped until *recovery_seconds* elapse.
    HALF-OPEN – one probe request is allowed after the recovery period; if it
              succeeds the breaker resets to CLOSED, otherwise it re-opens.
    """

    def __init__(self, failure_threshold: int, recovery_seconds: float) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_seconds = recovery_seconds
        self._failure_count: int = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        """Return ``True`` when the circuit is open and requests should be skipped."""
        if self._opened_at is None:
            return False
        elapsed = time.monotonic() - self._opened_at
        if elapsed >= self._recovery_seconds:
            # Recovery period elapsed → half-open: allow one probe attempt.
            return False
        return True

    def record_success(self) -> None:
        """Reset the breaker after a successful request."""
        self._failure_count = 0
        self._opened_at = None

    def record_failure(self) -> None:
        """Record a failed attempt; open the circuit when the threshold is hit."""
        self._failure_count += 1
        if self._failure_count >= self._failure_threshold:
            self._opened_at = time.monotonic()
            logger.warning(
                "Circuit breaker opened after %d consecutive failures",
                self._failure_count,
            )


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------


class LLMUnavailableError(Exception):
    """Raised when every configured LLM provider has been exhausted."""


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class LLMRouter:
    """Routes LLM requests across multiple providers with fallback.

    Parameters
    ----------
    providers:
        Ordered list of :class:`LLMProvider` instances.  Providers are
        tried from first to last; the first successful response is returned.
    """

    def __init__(self, providers: Sequence[LLMProvider]) -> None:
        self._providers = list(providers)
        cb_threshold = _env_int("LLM_CB_FAILURE_THRESHOLD", 3)
        cb_recovery = _env_float("LLM_CB_RECOVERY_SECONDS", 60.0)
        self._circuit_breakers: dict[str, CircuitBreaker] = {
            p.name: CircuitBreaker(cb_threshold, cb_recovery)
            for p in self._providers
        }
        self._max_retries = _env_int("LLM_RETRY_MAX", 3)
        self._retry_base = _env_float("LLM_RETRY_BASE_SECONDS", 1.0)

    async def chat(self, messages: list[dict], max_tokens: int) -> str:
        """Try each provider in order and return the first successful reply.

        Raises
        ------
        LLMUnavailableError
            When every provider has failed or been skipped by its circuit breaker.
        """
        last_error: Exception | None = None

        for provider in self._providers:
            cb = self._circuit_breakers[provider.name]
            if cb.is_open:
                logger.info(
                    "Skipping provider %s: circuit breaker is open", provider.name
                )
                continue

            for attempt in range(self._max_retries):
                try:
                    result = await provider.chat(messages, max_tokens)
                    cb.record_success()
                    logger.info(
                        "Provider %s succeeded on attempt %d",
                        provider.name,
                        attempt + 1,
                    )
                    return result

                except RetryableError as exc:
                    last_error = exc
                    logger.warning(
                        "Provider %s attempt %d/%d – retryable error: %s",
                        provider.name,
                        attempt + 1,
                        self._max_retries,
                        exc,
                    )
                    if attempt < self._max_retries - 1:
                        # Full-jitter exponential back-off: wait = base * 2^attempt * U(0.5, 1.0)
                        # Using [0.5, 1.0) ensures at least half the exponential delay is kept.
                        wait = self._retry_base * (2**attempt) * (
                            0.5 + random.random() * 0.5
                        )
                        await asyncio.sleep(wait)

                except Exception as exc:
                    last_error = exc
                    logger.error(
                        "Provider %s non-retryable error: %s", provider.name, exc
                    )
                    break  # Skip remaining retries for this provider.

            else:
                # Loop exhausted all retries (only RetryableErrors were raised).
                cb.record_failure()
                continue  # Try the next provider.

            # Reached here via ``break`` (non-retryable error).
            cb.record_failure()

        raise LLMUnavailableError(
            "All LLM providers are currently unavailable. "
            "Please try again later."
        ) from last_error
