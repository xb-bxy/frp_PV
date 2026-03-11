"""熔断器 (Circuit Breaker)."""

from __future__ import annotations

import logging
import time
from enum import Enum

log = logging.getLogger(__name__)


class State(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """轻量级熔断器: 连续失败 → 自动熔断 → 冷却后半开探测."""

    def __init__(self, name: str, *,
                 max_failures: int = 3,
                 cooldown: float = 300) -> None:
        self.name = name
        self.max_failures = max_failures
        self.cooldown = cooldown
        self._state = State.CLOSED
        self._fail_count = 0
        self._last_fail_time = 0.0

    @property
    def state(self) -> State:
        if (self._state is State.OPEN
                and time.time() - self._last_fail_time >= self.cooldown):
            self._state = State.HALF_OPEN
        return self._state

    @property
    def allow(self) -> bool:
        return self.state is not State.OPEN

    def record_success(self) -> None:
        if self._fail_count > 0 or self._state is not State.CLOSED:
            old = self._state
            self._fail_count = 0
            self._state = State.CLOSED
            if old is not State.CLOSED:
                log.info("[%s] 熔断恢复", self.name)

    def record_failure(self) -> None:
        self._fail_count += 1
        self._last_fail_time = time.time()
        if (self._fail_count >= self.max_failures
                and self._state is not State.OPEN):
            self._state = State.OPEN
            log.warning(
                "[%s] 熔断触发, 连续失败 %d 次, %ds 后恢复",
                self.name, self._fail_count, int(self.cooldown),
            )

    def __repr__(self) -> str:
        return (f"CircuitBreaker({self.name!r}, "
                f"state={self.state.value}, "
                f"fails={self._fail_count}/{self.max_failures})")
