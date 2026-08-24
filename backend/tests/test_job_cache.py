"""Fetch-dedup cache: the same (source, query) is not re-fetched within the
window, so many users targeting one role share a single API call.

The cache layer is mocked (no live Redis needed) to prove the skip logic and
the fail-open guarantee.
"""

from __future__ import annotations

from app.services import job_cache


def test_key_is_stable_and_query_sensitive():
    k1 = job_cache._key("remotive", {"what": "SRE", "country": "us"})
    k2 = job_cache._key("remotive", {"country": "us", "what": "SRE"})  # reordered
    k3 = job_cache._key("remotive", {"what": "SRE", "country": "gb"})
    assert k1 == k2          # order-independent
    assert k1 != k3          # different query -> different key
    assert k1.startswith("jobfetch:")


def test_disabled_when_ttl_is_zero(monkeypatch):
    monkeypatch.setattr(job_cache.settings, "JOB_CACHE_TTL_HOURS", 0)
    # Never reports a hit, never touches Redis.
    assert job_cache.was_fetched_recently("remotive", {"what": "SRE"}) is False


def test_mark_then_hit(monkeypatch):
    monkeypatch.setattr(job_cache.settings, "JOB_CACHE_TTL_HOURS", 24)
    store: dict[str, str] = {}

    class _FakeRedis:
        def exists(self, k):
            return 1 if k in store else 0

        def set(self, k, v, ex=None):
            store[k] = v

    monkeypatch.setattr(job_cache, "_redis", lambda: _FakeRedis())

    q = {"what": "Platform Engineer", "country": "us"}
    assert job_cache.was_fetched_recently("remotive", q) is False
    job_cache.mark_fetched("remotive", q)
    assert job_cache.was_fetched_recently("remotive", q) is True
    # a different query is still a miss
    assert job_cache.was_fetched_recently("remotive", {"what": "Nurse"}) is False


def test_fails_open_when_redis_errors(monkeypatch):
    monkeypatch.setattr(job_cache.settings, "JOB_CACHE_TTL_HOURS", 24)

    def _boom():
        raise ConnectionError("redis down")

    monkeypatch.setattr(job_cache, "_redis", _boom)
    # A broken cache must never block discovery: report "not cached" so we fetch.
    assert job_cache.was_fetched_recently("remotive", {"what": "SRE"}) is False
    job_cache.mark_fetched("remotive", {"what": "SRE"})  # must not raise
