"""
Тесты для лимита размера кэша и фоновой чистки (DNSCache).
"""
import time

from dns_cache import DNSCache


class _FakeQ:
    def __init__(self, name, qtype=1, qclass=1):
        self.qname = name
        self.qtype = qtype
        self.qclass = qclass


class _FakeRR:
    def __init__(self, ttl=60):
        self.ttl = ttl
        self.rdata = "1.2.3.4"


class _FakeResponse:
    """Минимальная заглушка DNS-ответа, достаточная для DNSCache."""
    def __init__(self, name, ttl=60):
        self.q = _FakeQ(name)
        self.rr = [_FakeRR(ttl)]
        self.auth = []
        self.ar = []


class _FakeRequest:
    def __init__(self, name, qtype=1, qclass=1):
        self.q = _FakeQ(name, qtype, qclass)


def _put(cache, name, ttl=60, stale_ttl=0):
    req = _FakeRequest(name)
    resp = _FakeResponse(name, ttl)
    cache.set(req, routed=False, response=resp, stale_ttl=stale_ttl)


def test_max_entries_evicts_oldest():
    cache = DNSCache(max_entries=3)
    for i in range(5):
        _put(cache, f"d{i}.com", ttl=300)
        time.sleep(0.001)  # чтобы created_at отличался
    # не больше лимита
    with cache._lock:
        assert len(cache._entries) <= 3
        keys = {k[0] for k in cache._entries}
    # самые старые (d0, d1) должны быть вытеснены
    assert "d0.com" not in keys
    assert "d4.com" in keys


def test_no_limit_when_zero():
    cache = DNSCache(max_entries=0)
    for i in range(20):
        _put(cache, f"d{i}.com", ttl=300)
    with cache._lock:
        assert len(cache._entries) == 20


def test_prune_expired_removes_dead():
    cache = DNSCache(max_entries=0)
    _put(cache, "short.com", ttl=1, stale_ttl=0)
    _put(cache, "long.com", ttl=300, stale_ttl=0)
    time.sleep(1.2)
    removed = cache.prune_expired()
    assert removed >= 1
    with cache._lock:
        keys = {k[0] for k in cache._entries}
    assert "short.com" not in keys
    assert "long.com" in keys


def test_janitor_starts_and_stops():
    cache = DNSCache(max_entries=0, janitor_interval=1.0)
    cache.start_janitor()
    assert cache._janitor is not None and cache._janitor.is_alive()
    cache.stop_janitor()
    cache._janitor.join(timeout=3)
    assert not cache._janitor.is_alive()


def test_janitor_double_start_is_safe():
    cache = DNSCache(janitor_interval=1.0)
    cache.start_janitor()
    t1 = cache._janitor
    cache.start_janitor()  # повторный вызов не должен плодить потоки
    assert cache._janitor is t1
    cache.stop_janitor()
