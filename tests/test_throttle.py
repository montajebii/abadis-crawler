"""Tests for crawler.throttle AIMD controller."""
import pytest

from crawler.throttle import AIMDConfig, AIMDController, BackoffExhausted


def test_initial_state():
    c = AIMDController(AIMDConfig())
    assert c.min_delay == 2.0
    assert c.max_delay == 5.0
    assert c.success_streak == 0
    assert c.consecutive_429 == 0


def test_success_streak_decreases_delay():
    cfg = AIMDConfig(success_streak_threshold=3, decrease_factor=0.5)
    c = AIMDController(cfg)
    for _ in range(3):
        c.on_success()
    assert c.min_delay == pytest.approx(1.0)


def test_rate_limit_increases_delay():
    cfg = AIMDConfig(increase_factor=2.0)
    c = AIMDController(cfg)
    sleep_for = c.on_rate_limited()
    assert sleep_for == 30
    assert c.min_delay == pytest.approx(4.0)
    assert c.max_delay == pytest.approx(10.0)


def test_consecutive_429_backoff_sequence():
    cfg = AIMDConfig(backoff_schedule_seconds=[10, 20, 30], max_consecutive_429=3)
    c = AIMDController(cfg)
    assert c.on_rate_limited() == 10
    assert c.on_rate_limited() == 20
    assert c.on_rate_limited() == 30
    with pytest.raises(BackoffExhausted):
        c.on_rate_limited()


def test_success_resets_429_counter():
    c = AIMDController(AIMDConfig(max_consecutive_429=2))
    c.on_rate_limited()
    c.on_success()
    assert c.consecutive_429 == 0
    c.on_rate_limited()
    assert c.consecutive_429 == 1


def test_clamp_respects_absolute_bounds():
    """Clamp should keep delays within absolute bounds.

    We use a high max_consecutive_429 so we can exercise clamping
    without triggering BackoffExhausted.
    """
    cfg = AIMDConfig(
        absolute_min_delay=1.0,
        absolute_max_delay=20.0,
        increase_factor=10.0,
        max_consecutive_429=10,
    )
    c = AIMDController(cfg)
    for _ in range(5):
        c.on_rate_limited()
    assert c.min_delay <= 20.0
    assert c.max_delay <= 20.0
    assert c.min_delay >= 1.0
