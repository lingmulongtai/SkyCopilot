"""
tests/test_llm_router.py
------------------------
Unit tests for the multi-provider LLM routing layer.

Covers:
  - Provider selection order
  - Fallback behaviour when the first provider rate-limits
  - Circuit-breaker behaviour
  - Output-format enforcement (llm_format.py)

All network calls are mocked; no real API keys are required.
"""

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.llm_providers.base import LLMProvider, RetryableError
from utils.llm_router import CircuitBreaker, LLMRouter, LLMUnavailableError
from utils.llm_format import enforce_format


# ---------------------------------------------------------------------------
# Helper: controllable mock provider
# ---------------------------------------------------------------------------


class _MockProvider(LLMProvider):
    """A provider whose responses / errors can be scripted per call."""

    def __init__(
        self,
        name: str = "mock",
        *,
        responses: list[str] | None = None,
        side_effects: list[Exception] | None = None,
    ) -> None:
        self.name = name
        self._responses = responses or ["mock response"]
        self._side_effects = side_effects or []
        self.call_count = 0

    async def chat(self, messages: list[dict], max_tokens: int) -> str:
        idx = self.call_count
        self.call_count += 1

        if idx < len(self._side_effects):
            raise self._side_effects[idx]

        resp_idx = idx - len(self._side_effects)
        if resp_idx < len(self._responses):
            return self._responses[resp_idx]
        return self._responses[-1]


def _run(coro):
    """Run a coroutine synchronously (helper for non-async test methods)."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Patch asyncio.sleep so retry tests don't actually wait.
# ---------------------------------------------------------------------------


async def _no_sleep(_delay):
    return


# ---------------------------------------------------------------------------
# CircuitBreaker tests
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def test_initially_closed(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_seconds=60.0)
        assert not cb.is_open

    def test_does_not_open_below_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_seconds=60.0)
        cb.record_failure()
        cb.record_failure()
        assert not cb.is_open

    def test_opens_at_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_seconds=60.0)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open

    def test_remains_open_within_recovery_period(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_seconds=60.0)
        for _ in range(3):
            cb.record_failure()
        # Pretend 30 s have passed (still within 60 s recovery window).
        with patch("utils.llm_router.time") as mock_time:
            mock_time.monotonic.return_value = time.monotonic() + 30
            assert cb.is_open

    def test_half_opens_after_recovery_period(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_seconds=60.0)
        for _ in range(3):
            cb.record_failure()
        assert cb.is_open
        # Pretend 70 s have passed → recovery period elapsed.
        with patch("utils.llm_router.time") as mock_time:
            mock_time.monotonic.return_value = time.monotonic() + 70
            assert not cb.is_open  # half-open: probe allowed

    def test_success_resets_circuit(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_seconds=60.0)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        # Counter reset; two more failures should NOT open the breaker.
        cb.record_failure()
        cb.record_failure()
        assert not cb.is_open

    def test_re_opens_after_half_open_failure(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_seconds=60.0)
        for _ in range(3):
            cb.record_failure()
        # Simulate recovery elapsed, then fail again.
        with patch("utils.llm_router.time") as mock_time:
            t0 = time.monotonic()
            mock_time.monotonic.return_value = t0 + 70
            assert not cb.is_open  # half-open
        # Record a fresh failure (threshold=3 means this won't re-open alone).
        # But the count is still at 3, so the 4th failure will trip it.
        cb.record_failure()  # count becomes 4 (>= 3) → re-opens
        assert cb.is_open


# ---------------------------------------------------------------------------
# LLMRouter – provider selection order
# ---------------------------------------------------------------------------


class TestProviderSelectionOrder:
    def test_first_provider_used_when_healthy(self):
        p1 = _MockProvider("p1", responses=["from p1"])
        p2 = _MockProvider("p2", responses=["from p2"])
        router = LLMRouter([p1, p2])

        result = _run(router.chat([], 100))

        assert result == "from p1"
        assert p1.call_count == 1
        assert p2.call_count == 0

    def test_second_provider_never_called_if_first_succeeds(self):
        p1 = _MockProvider("p1", responses=["ok"])
        p2 = _MockProvider("p2", responses=["backup"])
        router = LLMRouter([p1, p2])

        _run(router.chat([], 100))

        assert p2.call_count == 0

    def test_provider_order_is_preserved(self):
        """Results come from the first provider in the list."""
        p_a = _MockProvider("a", responses=["alpha"])
        p_b = _MockProvider("b", responses=["beta"])
        p_c = _MockProvider("c", responses=["gamma"])
        router = LLMRouter([p_a, p_b, p_c])

        result = _run(router.chat([], 100))
        assert result == "alpha"


# ---------------------------------------------------------------------------
# LLMRouter – fallback on rate-limit / retryable error
# ---------------------------------------------------------------------------


class TestFallbackBehaviour:
    def _make_router(self, p1_errors, p2_response="fallback answer"):
        """Build a two-provider router; p1 raises errors, p2 returns ok."""
        p1 = _MockProvider("p1", side_effects=p1_errors)
        p2 = _MockProvider("p2", responses=[p2_response])
        # Minimise retry count and delay for speed.
        with (
            patch.dict(
                "os.environ",
                {
                    "LLM_RETRY_MAX": str(len(p1_errors)),
                    "LLM_RETRY_BASE_SECONDS": "0.0",
                    "LLM_CB_FAILURE_THRESHOLD": "10",
                    "LLM_CB_RECOVERY_SECONDS": "60",
                },
            )
        ):
            router = LLMRouter([p1, p2])
        return router, p1, p2

    def test_falls_back_after_rate_limit_errors(self):
        errors = [RetryableError("429"), RetryableError("429")]
        router, p1, p2 = self._make_router(errors)

        with patch("asyncio.sleep", _no_sleep):
            result = _run(router.chat([], 100))

        assert result == "fallback answer"
        assert p2.call_count == 1

    def test_falls_back_after_timeout_errors(self):
        errors = [RetryableError("timeout"), RetryableError("timeout")]
        router, p1, p2 = self._make_router(errors)

        with patch("asyncio.sleep", _no_sleep):
            result = _run(router.chat([], 100))

        assert result == "fallback answer"

    def test_falls_back_immediately_on_non_retryable_error(self):
        """A non-retryable exception skips directly to the next provider."""
        p1 = _MockProvider("p1", side_effects=[ValueError("bad config")])
        p2 = _MockProvider("p2", responses=["from p2"])
        with patch.dict(
            "os.environ",
            {"LLM_RETRY_MAX": "3", "LLM_RETRY_BASE_SECONDS": "0.0"},
        ):
            router = LLMRouter([p1, p2])

        result = _run(router.chat([], 100))

        assert result == "from p2"
        # p1 was called exactly once (no retries for non-retryable).
        assert p1.call_count == 1

    def test_raises_llm_unavailable_when_all_fail(self):
        errors = [RetryableError("429"), RetryableError("429")]
        p1 = _MockProvider("p1", side_effects=errors)
        p2 = _MockProvider("p2", side_effects=[RetryableError("503"), RetryableError("503")])
        with patch.dict(
            "os.environ",
            {"LLM_RETRY_MAX": "2", "LLM_RETRY_BASE_SECONDS": "0.0"},
        ):
            router = LLMRouter([p1, p2])

        with patch("asyncio.sleep", _no_sleep):
            with pytest.raises(LLMUnavailableError):
                _run(router.chat([], 100))

    def test_partial_retry_then_success(self):
        """Second attempt succeeds after one retryable failure on the same provider."""
        p1 = _MockProvider(
            "p1",
            side_effects=[RetryableError("flaky")],
            responses=["recovered"],
        )
        with patch.dict(
            "os.environ",
            {"LLM_RETRY_MAX": "3", "LLM_RETRY_BASE_SECONDS": "0.0"},
        ):
            router = LLMRouter([p1])

        with patch("asyncio.sleep", _no_sleep):
            result = _run(router.chat([], 100))

        assert result == "recovered"
        assert p1.call_count == 2  # one failure + one success


# ---------------------------------------------------------------------------
# LLMRouter – circuit breaker integration
# ---------------------------------------------------------------------------


class TestCircuitBreakerIntegration:
    def test_circuit_breaker_skips_provider_after_threshold(self):
        """After threshold exhausted attempts, subsequent calls skip the broken provider."""
        threshold = 2
        # p1 will always raise retryable errors.
        p1 = _MockProvider(
            "p1",
            side_effects=[RetryableError("err") for _ in range(10)],
        )
        p2 = _MockProvider("p2", responses=["from p2"])
        with patch.dict(
            "os.environ",
            {
                "LLM_RETRY_MAX": "2",
                "LLM_RETRY_BASE_SECONDS": "0.0",
                "LLM_CB_FAILURE_THRESHOLD": str(threshold),
                "LLM_CB_RECOVERY_SECONDS": "9999",  # won't recover during test
            },
        ):
            router = LLMRouter([p1, p2])

        # First and second calls exhaust p1's retries → CB failure count reaches threshold.
        with patch("asyncio.sleep", _no_sleep):
            result1 = _run(router.chat([], 100))
            result2 = _run(router.chat([], 100))

        assert result1 == "from p2"
        assert result2 == "from p2"
        # CB should now be open (threshold failures recorded).
        assert router._circuit_breakers["p1"].is_open
        p1_count_before_third = p1.call_count

        # Third call: p1 skipped (CB open) → goes straight to p2.
        result3 = _run(router.chat([], 100))

        assert result3 == "from p2"
        # p1 must NOT have been called on the third request.
        assert p1.call_count == p1_count_before_third

    def test_circuit_breaker_allows_probe_after_recovery(self):
        """After recovery_seconds, the circuit half-opens and allows a probe."""
        p1_errors = [RetryableError("err"), RetryableError("err")]
        p1 = _MockProvider("p1", side_effects=p1_errors, responses=["p1 ok"])
        with patch.dict(
            "os.environ",
            {
                "LLM_RETRY_MAX": "2",
                "LLM_RETRY_BASE_SECONDS": "0.0",
                "LLM_CB_FAILURE_THRESHOLD": "1",
                "LLM_CB_RECOVERY_SECONDS": "60",
            },
        ):
            router = LLMRouter([p1])

        # Trip the circuit breaker (p1 fails, no fallback → LLMUnavailableError).
        with patch("asyncio.sleep", _no_sleep):
            with pytest.raises(LLMUnavailableError):
                _run(router.chat([], 100))

        cb = router._circuit_breakers["p1"]
        assert cb.is_open

        # Simulate recovery period elapsed.
        with patch("utils.llm_router.time") as mock_time:
            mock_time.monotonic.return_value = time.monotonic() + 70
            assert not cb.is_open  # half-open: probe allowed


# ---------------------------------------------------------------------------
# Output format enforcement (llm_format.py)
# ---------------------------------------------------------------------------


class TestOutputFormatEnforcement:
    def test_non_empty_response_passes_through(self):
        text = "## 次のステップ\n- スキル上げ\n- ダンジョン攻略"
        assert enforce_format(text) == text

    def test_strips_leading_and_trailing_whitespace(self):
        text = "  \n## 見出し\n- アドバイス\n  "
        result = enforce_format(text)
        assert result == "## 見出し\n- アドバイス"

    def test_empty_string_returns_fallback_message(self):
        result = enforce_format("")
        assert "⚠️" in result
        assert len(result) > 0

    def test_whitespace_only_returns_fallback_message(self):
        result = enforce_format("   \n\t  ")
        assert "⚠️" in result

    def test_non_empty_response_is_not_altered(self):
        text = "## タイトル\n- 点1\n- 点2"
        assert enforce_format(text) == text
