"""Random user-agent rotation every N requests."""
from __future__ import annotations

import random
from typing import Optional

# Desktop UA pool only — avoids mobile fingerprints that don't match our stack.
USER_AGENTS: list[str] = [
    # Chrome on Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36",
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36",
    # Firefox on Linux
    "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Safari/605.1.15",
]


class UserAgentRotator:
    def __init__(self, rotate_min: int = 20, rotate_max: int = 50,
                 pool: Optional[list[str]] = None):
        self.pool = pool or USER_AGENTS
        self.rotate_min = rotate_min
        self.rotate_max = rotate_max
        self._current: Optional[str] = None
        self._requests_until_rotate = 0
        self._total_requests = 0
        self._rotate()

    def _rotate(self) -> None:
        self._current = random.choice(self.pool)
        self._requests_until_rotate = random.randint(self.rotate_min, self.rotate_max)

    def get(self) -> str:
        """Return current UA and decrement counter, rotating when it hits zero."""
        if self._requests_until_rotate <= 0:
            self._rotate()
        self._requests_until_rotate -= 1
        self._total_requests += 1
        assert self._current is not None
        return self._current

    @property
    def current(self) -> str:
        assert self._current is not None
        return self._current

    @property
    def rotations_performed(self) -> int:
        return self._total_requests // max(1, (self.rotate_min + self.rotate_max) // 2)
