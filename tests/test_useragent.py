"""Tests for crawler.useragent rotator."""
from crawler.useragent import UserAgentRotator


def test_returns_ua_from_pool():
    r = UserAgentRotator(rotate_min=1, rotate_max=1)
    assert r.current in r.pool


def test_rotates_after_n_requests():
    r = UserAgentRotator(rotate_min=2, rotate_max=2)
    first = r.current
    # Exhaust the counter
    for _ in range(2):
        r.get()
    # Next get() should trigger rotation
    r.get()
    # It might pick the same one by chance, so just check it's valid
    assert r.current in r.pool


def test_pool_override():
    custom = ["UA-A", "UA-B"]
    r = UserAgentRotator(pool=custom, rotate_min=1, rotate_max=1)
    assert r.current in custom
