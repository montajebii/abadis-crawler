"""AIMD rate controller: additive increase, multiplicative decrease.

States:
- NORMAL: delay in [min_delay, max_delay], increasing on success streak
- BACKOFF: after 429/503, sleeping for a scheduled duration
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AIMDConfig:
    initial_min_delay: float = 2.0
    initial_max_delay: float = 5.0
    absolute_min_delay: float = 1.0
    absolute_max_delay: float = 30.0
    success_streak_threshold: int = 50
    decrease_factor: float = 0.9
    increase_factor: float = 1.5
    backoff_schedule_seconds: list[int] = field(
        default_factory=lambda: [30, 120, 300]
    )
    max_consecutive_429: int = 3

    @classmethod
    def from_dict(cls, data: dict) -> "AIMDConfig":
        aimd = data.get("aimd", {}) if data else {}
        defaults = cls()
        return cls(
            initial_min_delay=float(aimd.get("initial_min_delay", defaults.initial_min_delay)),
            initial_max_delay=float(aimd.get("initial_max_delay", defaults.initial_max_delay)),
            absolute_min_delay=float(aimd.get("absolute_min_delay", defaults.absolute_min_delay)),
            absolute_max_delay=float(aimd.get("absolute_max_delay", defaults.absolute_max_delay)),
            success_streak_threshold=int(aimd.get("success_streak_threshold", defaults.success_streak_threshold)),
            decrease_factor=float(aimd.get("decrease_factor", defaults.decrease_factor)),
            increase_factor=float(aimd.get("increase_factor", defaults.increase_factor)),
            backoff_schedule_seconds=list(aimd.get("backoff_schedule_seconds", defaults.backoff_schedule_seconds)),
            max_consecutive_429=int(aimd.get("max_consecutive_429", defaults.max_consecutive_429)),
        )


class BackoffExhausted(Exception):
    """Raised when 429 has occurred too many times consecutively."""


class AIMDController:
    def __init__(self, config: AIMDConfig, initial_min: Optional[float] = None,
                 initial_max: Optional[float] = None):
        self.config = config
        self.min_delay = initial_min if initial_min is not None else config.initial_min_delay
        self.max_delay = initial_max if initial_max is not None else config.initial_max_delay
        self.success_streak = 0
        self.consecutive_429 = 0
        self.total_requests = 0

    def _clamp(self) -> None:
        # Clamp min_delay to [absolute_min, absolute_max]
        self.min_delay = max(
            self.config.absolute_min_delay,
            min(self.config.absolute_max_delay, self.min_delay),
        )
        # Clamp max_delay to [min_delay, absolute_max]
        self.max_delay = max(
            self.min_delay,
            min(self.config.absolute_max_delay, self.max_delay),
        )

    async def wait(self) -> None:
        """Sleep for a random duration in [min_delay, max_delay]."""
        delay = random.uniform(self.min_delay, self.max_delay)
        await asyncio.sleep(delay)

    def on_success(self) -> None:
        self.total_requests += 1
        self.success_streak += 1
        self.consecutive_429 = 0
        if self.success_streak >= self.config.success_streak_threshold:
            self._decrease_delay()
            self.success_streak = 0

    def on_rate_limited(self) -> int:
        """Return seconds to sleep before next attempt. Raise if exhausted."""
        self.total_requests += 1
        self.consecutive_429 += 1
        self.success_streak = 0
        if self.consecutive_429 > self.config.max_consecutive_429:
            raise BackoffExhausted(
                f"Consecutive 429s: {self.consecutive_429} > "
                f"{self.config.max_consecutive_429}"
            )
        idx = min(self.consecutive_429 - 1, len(self.config.backoff_schedule_seconds) - 1)
        sleep_for = self.config.backoff_schedule_seconds[idx]
        self._increase_delay()
        return sleep_for

    def _decrease_delay(self) -> None:
        """Speed up: reduce delays by decrease_factor (multiplicative decrease of delay)."""
        self.min_delay *= self.config.decrease_factor
        self.max_delay *= self.config.decrease_factor
        self._clamp()

    def _increase_delay(self) -> None:
        """Slow down: increase delays by increase_factor."""
        self.min_delay *= self.config.increase_factor
        self.max_delay *= self.config.increase_factor
        self._clamp()

    def snapshot(self) -> dict:
        return {
            "min_delay": round(self.min_delay, 3),
            "max_delay": round(self.max_delay, 3),
            "success_streak": self.success_streak,
            "consecutive_429": self.consecutive_429,
            "total_requests": self.total_requests,
        }
