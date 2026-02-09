"""
Week 5: Bounded retries with backoff and simple circuit breaker.

- Centralized retry: max_attempts, base_delay, jitter, max_delay.
- Classify errors into retryable / non-retryable.
- Circuit breaker: N failures in M minutes for a dependency -> pause for cooldown, log decision=CIRCUIT_OPEN.
"""
from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timezone, timedelta
from typing import Callable, TypeVar, Optional, List, Set

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Defaults (can be overridden by config)
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_JITTER = 0.2
DEFAULT_MAX_DELAY = 60.0

# Non-retryable: do not retry
NON_RETRYABLE_CODES: Set[int] = {
    401,  # Unauthorized
    403,  # Forbidden
    404,  # Not found
    422,  # Validation
    400,  # Bad request (e.g. invalid symbol)
}
NON_RETRYABLE_EXCEPTIONS: Set[type] = {ValueError, TypeError, KeyError}


def is_retryable_error(exc: BaseException, http_code: Optional[int] = None) -> bool:
    """Classify errors: retryable (network, 5xx, rate limit) vs non-retryable (4xx auth/validation)."""
    if http_code is not None and http_code in NON_RETRYABLE_CODES:
        return False
    for cls in NON_RETRYABLE_EXCEPTIONS:
        if isinstance(exc, cls):
            return False
    # AttributeError often indicates programming error
    if isinstance(exc, AttributeError):
        return False
    return True


def retry_with_backoff(
    fn: Callable[..., T],
    *args,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    jitter: float = DEFAULT_JITTER,
    max_delay: float = DEFAULT_MAX_DELAY,
    is_retryable: Optional[Callable[[BaseException], bool]] = None,
    **kwargs,
) -> T:
    """
    Call fn(*args, **kwargs) with bounded retries and exponential backoff + jitter.
    Uses full jitter: delay = min(max_delay, base_delay * 2^attempt + random(0, jitter * base_delay)).
    """
    is_retryable_fn = is_retryable or (lambda e: is_retryable_error(e))
    last_exc: Optional[BaseException] = None
    for attempt in range(max_attempts):
        try:
            return fn(*args, **kwargs)
        except BaseException as e:
            last_exc = e
            if attempt == max_attempts - 1 or not is_retryable_fn(e):
                raise
            delay = min(
                max_delay,
                base_delay * (2 ** attempt) + random.uniform(0, jitter * base_delay),
            )
            logger.warning(
                "retry attempt=%s max_attempts=%s delay=%.2f error=%s",
                attempt + 1,
                max_attempts,
                delay,
                str(e)[:200],
            )
            time.sleep(delay)
    raise last_exc  # type: ignore[misc]


class CircuitBreaker:
    """
    Simple circuit breaker: if failure_count >= threshold within window_minutes,
    open the circuit for cooldown_minutes and log decision=CIRCUIT_OPEN.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        window_minutes: float = 5.0,
        cooldown_minutes: float = 2.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.window_minutes = window_minutes
        self.cooldown_minutes = cooldown_minutes
        self._failures: List[datetime] = []
        self._opened_at: Optional[datetime] = None

    def record_failure(self) -> None:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=self.window_minutes)
        self._failures = [t for t in self._failures if t >= cutoff]
        self._failures.append(now)
        if len(self._failures) >= self.failure_threshold and self._opened_at is None:
            self._opened_at = now
            logger.warning(
                "circuit_breaker=%s decision=CIRCUIT_OPEN failure_count=%s window_minutes=%s cooldown_minutes=%s",
                self.name,
                len(self._failures),
                self.window_minutes,
                self.cooldown_minutes,
            )

    def record_success(self) -> None:
        self._failures.clear()
        self._opened_at = None

    def is_open(self) -> bool:
        """True if circuit is open (within cooldown)."""
        if self._opened_at is None:
            return False
        now = datetime.now(timezone.utc)
        if now - self._opened_at >= timedelta(minutes=self.cooldown_minutes):
            self._opened_at = None
            self._failures.clear()
            return False
        return True

    def state(self) -> str:
        """OPEN or CLOSED for health snapshot."""
        return "OPEN" if self.is_open() else "CLOSED"

    def allow_call(self) -> bool:
        """Return False if circuit is open (caller should skip and log CIRCUIT_OPEN)."""
        return not self.is_open()


# Module-level breakers for exchange and telegram (optional use)
_exchange_circuit: Optional[CircuitBreaker] = None
_telegram_circuit: Optional[CircuitBreaker] = None


def get_exchange_circuit() -> CircuitBreaker:
    global _exchange_circuit
    if _exchange_circuit is None:
        _exchange_circuit = CircuitBreaker(
            name="exchange",
            failure_threshold=5,
            window_minutes=5.0,
            cooldown_minutes=2.0,
        )
    return _exchange_circuit


def get_telegram_circuit() -> CircuitBreaker:
    global _telegram_circuit
    if _telegram_circuit is None:
        _telegram_circuit = CircuitBreaker(
            name="telegram",
            failure_threshold=5,
            window_minutes=5.0,
            cooldown_minutes=2.0,
        )
    return _telegram_circuit
