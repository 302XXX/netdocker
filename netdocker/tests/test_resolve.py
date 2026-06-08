"""
Тесты центральной resolve()-логики NetDockerResolver.

Стратегия: НЕ ходим в сеть. Мокаем модульные функции dns_server.resolve_via_xbox /
resolve_via_system (и при необходимости _query_*), возвращая настоящие dnslib
DNS-ответы. Проверяем итоговый reply (rcode, ответы) и выбранный путь.

Покрываем:
  • маршрутизация routed → xbox, non-routed → system
  • SERVFAIL когда апстрим не ответил
  • bogus→bogus → NXDOMAIN
  • bogus(system)→real(xbox) → используем реальный
  • кэш: fresh-ответ отдаётся без повторного похода в апстрим
  • транспортный fallback UDP→DoH и DoH→UDP в resolve_via_xbox
"""
import pytest
from dnslib import DNSRecord, QTYPE, RCODE, RR, A, AAAA

import dns_server
from dns_cache import DNSCache


# ── helpers ─────────────────────────────────────────────────────────────────

def make_request(domain, qtype="A"):
    return DNSRecord.question(domain, qtype)


def make_response(domain, ip="1.2.3.4", qtype="A", ttl=60, rcode=0):
    req = make_request(domain, qtype)
    rep = req.reply()
    rep.header.rcode = rcode
    if ip:
        if qtype == "AAAA":
            rep.add_answer(RR(domain, QTYPE.AAAA, rdata=AAAA(ip), ttl=ttl))
        else:
            rep.add_answer(RR(domain, QTYPE.A, rdata=A(ip), ttl=ttl))
    return rep


def answers(reply):
    return [str(rr.rdata) for rr in reply.rr]


def rcode(reply):
    return RCODE[reply.header.rcode]


BOGUS_IP = "212.188.4.10"   # из BUILTIN_BOGUS_IPS


@pytest.fixture
def restore_resolvers():
    """Сохраняет и восстанавливает модульные функции, чтобы тесты не влияли
    друг на друга."""
    saved = {
        "xbox": dns_server.resolve_via_xbox,
        "system": dns_server.resolve_via_system,
        "udp": dns_server._query_udp_dns,
        "doh": dns_server._query_doh_dns,
        "r_dot": dns_server.resolve_via_xbox_dot,
        "r_doq": dns_server.resolve_via_xbox_doq,
    }
    yield
    dns_server.resolve_via_xbox = saved["xbox"]
    dns_server.resolve_via_system = saved["system"]
    dns_server._query_udp_dns = saved["udp"]
    dns_server._query_doh_dns = saved["doh"]
    dns_server.resolve_via_xbox_dot = saved["r_dot"]
    dns_server.resolve_via_xbox_doq = saved["r_doq"]


def make_resolver(cfg=None):
    base = {
        "routed_domains": ["openai.com"],
        "routed_processes": [],
        "routed_cache_enabled": True,
        "routed_cache_ttl": 5,
        "routed_reply_ttl": 1,
        "optimistic_cache_enabled": False,
        "bogus_detection_enabled": True,
        "bogus_ips_use_builtin": True,
    }
    if cfg:
        base.update(cfg)
    return dns_server.NetDockerResolver([base], DNSCache())


# ── маршрутизация ────────────────────────────────────────────────────────────

def test_routed_domain_uses_xbox(restore_resolvers):
    res = make_resolver()
    dns_server.resolve_via_xbox = lambda rq, c: make_response("openai.com", "104.18.0.1")
    dns_server.resolve_via_system = lambda rq, c: make_response("openai.com", "0.0.0.0")
    reply = res.resolve(make_request("openai.com"), None)
    assert rcode(reply) == "NOERROR"
    assert answers(reply) == ["104.18.0.1"]   # пришло от xbox, не от system


def test_subdomain_of_routed_uses_xbox(restore_resolvers):
    res = make_resolver()
    dns_server.resolve_via_xbox = lambda rq, c: make_response("api.openai.com", "104.18.9.9")
    reply = res.resolve(make_request("api.openai.com"), None)
    assert answers(reply) == ["104.18.9.9"]


def test_non_routed_uses_system(restore_resolvers):
    res = make_resolver()
    dns_server.resolve_via_system = lambda rq, c: make_response("example.com", "93.184.216.34")
    dns_server.resolve_via_xbox = lambda rq, c: make_response("example.com", "104.18.0.1")
    reply = res.resolve(make_request("example.com"), None)
    assert answers(reply) == ["93.184.216.34"]   # пришло от system


# ── SERVFAIL ─────────────────────────────────────────────────────────────────

def test_routed_servfail_when_xbox_down(restore_resolvers):
    res = make_resolver()
    dns_server.resolve_via_xbox = lambda rq, c: None
    reply = res.resolve(make_request("openai.com"), None)
    assert rcode(reply) == "SERVFAIL"


def test_system_servfail_when_upstream_down(restore_resolvers):
    res = make_resolver()
    dns_server.resolve_via_system = lambda rq, c: None
    dns_server.resolve_via_xbox = lambda rq, c: None
    reply = res.resolve(make_request("example.com"), None)
    assert rcode(reply) == "SERVFAIL"


# ── bogus detection ──────────────────────────────────────────────────────────

def test_bogus_both_sides_returns_nxdomain(restore_resolvers):
    res = make_resolver()
    dns_server.resolve_via_system = lambda rq, c: make_response("blocked.com", BOGUS_IP)
    dns_server.resolve_via_xbox = lambda rq, c: make_response("blocked.com", BOGUS_IP)
    reply = res.resolve(make_request("blocked.com"), None)
    assert rcode(reply) == "NXDOMAIN"


def test_bogus_system_then_real_xbox_uses_real(restore_resolvers):
    res = make_resolver()
    dns_server.resolve_via_system = lambda rq, c: make_response("blocked.com", BOGUS_IP)
    dns_server.resolve_via_xbox = lambda rq, c: make_response("blocked.com", "104.18.5.5")
    reply = res.resolve(make_request("blocked.com"), None)
    assert rcode(reply) == "NOERROR"
    assert answers(reply) == ["104.18.5.5"]


def test_clean_system_answer_passes_through(restore_resolvers):
    res = make_resolver()
    dns_server.resolve_via_system = lambda rq, c: make_response("clean.com", "93.184.216.34")
    reply = res.resolve(make_request("clean.com"), None)
    assert rcode(reply) == "NOERROR"
    assert answers(reply) == ["93.184.216.34"]


def test_bogus_detection_disabled_lets_fake_through(restore_resolvers):
    res = make_resolver({"bogus_detection_enabled": False})
    dns_server.resolve_via_system = lambda rq, c: make_response("blocked.com", BOGUS_IP)
    reply = res.resolve(make_request("blocked.com"), None)
    # при выключенной детекции фейк проходит как есть
    assert rcode(reply) == "NOERROR"
    assert answers(reply) == [BOGUS_IP]


# ── кэш ──────────────────────────────────────────────────────────────────────

def test_routed_cache_hit_avoids_second_upstream_call(restore_resolvers):
    res = make_resolver()
    calls = {"n": 0}

    def counting_xbox(rq, c):
        calls["n"] += 1
        return make_response("openai.com", "104.18.0.1", ttl=300)

    dns_server.resolve_via_xbox = counting_xbox

    r1 = res.resolve(make_request("openai.com"), None)
    r2 = res.resolve(make_request("openai.com"), None)
    assert answers(r1) == ["104.18.0.1"]
    assert answers(r2) == ["104.18.0.1"]
    assert calls["n"] == 1   # второй ответ — из кэша, апстрим не дёргали


def test_system_cache_hit_avoids_second_upstream_call(restore_resolvers):
    res = make_resolver()
    calls = {"n": 0}

    def counting_system(rq, c):
        calls["n"] += 1
        return make_response("example.com", "93.184.216.34", ttl=300)

    dns_server.resolve_via_system = counting_system

    res.resolve(make_request("example.com"), None)
    res.resolve(make_request("example.com"), None)
    assert calls["n"] == 1


def test_different_qtypes_cached_separately(restore_resolvers):
    res = make_resolver()
    calls = {"n": 0}

    def counting_system(rq, c):
        calls["n"] += 1
        qn = str(rq.q.qname).rstrip(".")
        if rq.q.qtype == QTYPE.AAAA:
            return make_response(qn, "2606:2800::1", qtype="AAAA", ttl=300)
        return make_response(qn, "93.184.216.34", ttl=300)

    dns_server.resolve_via_system = counting_system
    res.resolve(make_request("example.com", "A"), None)
    res.resolve(make_request("example.com", "AAAA"), None)
    # A и AAAA — разные ключи кэша, значит два похода в апстрим
    assert calls["n"] == 2


# ── транспортный fallback в resolve_via_xbox ─────────────────────────────────

def test_resolve_via_xbox_udp_falls_back_to_doh(restore_resolvers):
    cfg = {"xbox_dns_mode": "udp", "upstream_mode": "sequential", "provider_failover": False}

    def udp_down(ip, r, timeout=4.0):
        raise Exception("udp down")

    dns_server._query_udp_dns = udp_down
    dns_server._query_doh_dns = lambda url, r, timeout=5.0: make_response(
        str(r.q.qname).rstrip("."), "9.9.9.9"
    )
    out = dns_server.resolve_via_xbox(make_request("chatgpt.com"), cfg)
    assert out is not None
    assert answers(out) == ["9.9.9.9"]


def test_resolve_via_xbox_doh_falls_back_to_udp(restore_resolvers):
    cfg = {"xbox_dns_mode": "doh", "upstream_mode": "sequential", "provider_failover": False}

    def doh_down(url, r, timeout=5.0):
        raise Exception("doh blocked")

    dns_server._query_doh_dns = doh_down
    dns_server._query_udp_dns = lambda ip, r, timeout=4.0: make_response(
        str(r.q.qname).rstrip("."), "8.8.8.8"
    )
    # DoT/DoQ в цепочке fallback — глушим, чтобы не лезть в сеть
    dns_server.resolve_via_xbox_dot = lambda r, c, profile=None: None
    dns_server.resolve_via_xbox_doq = lambda r, c, profile=None: None
    out = dns_server.resolve_via_xbox(make_request("chatgpt.com"), cfg)
    assert out is not None
    assert answers(out) == ["8.8.8.8"]


def test_resolve_via_xbox_returns_none_when_both_transports_fail(restore_resolvers):
    cfg = {"xbox_dns_mode": "udp", "upstream_mode": "sequential", "provider_failover": False}

    def boom(*a, **k):
        raise Exception("down")

    dns_server._query_udp_dns = boom
    dns_server._query_doh_dns = boom
    # DoT/DoQ тоже «падают» → весь fallback-цепочкой None
    dns_server.resolve_via_xbox_dot = lambda r, c, profile=None: None
    dns_server.resolve_via_xbox_doq = lambda r, c, profile=None: None
    out = dns_server.resolve_via_xbox(make_request("chatgpt.com"), cfg)
    assert out is None


# ── optimistic cache (stale-while-revalidate) ────────────────────────────────

def test_stale_cache_served_and_triggers_bg_refresh(restore_resolvers, monkeypatch):
    """Просроченный (но в stale-окне) ответ отдаётся мгновенно, а в фоне
    запускается обновление."""
    res = make_resolver({
        "optimistic_cache_enabled": True,
        "stale_cache_ttl": 3600,
    })

    calls = {"n": 0}

    def counting_system(rq, c):
        calls["n"] += 1
        return make_response("example.com", "93.184.216.34", ttl=1)

    dns_server.resolve_via_system = counting_system

    # ловим фоновый refresh, чтобы тест был детерминированным (без потоков)
    refreshed = {"spawned": False}

    def fake_spawn(request, routed, resolver_callable, cache_kwargs):
        refreshed["spawned"] = True

    monkeypatch.setattr(res, "_spawn_background_refresh", fake_spawn)

    # 1) первый запрос — miss → апстрим, кладём в кэш с ttl=1
    res.resolve(make_request("example.com"), None)
    assert calls["n"] == 1

    # 2) принудительно «состариваем» запись (expires_at в прошлом, stale ещё жив)
    import time as _t
    with res.cache._lock:
        for entry in res.cache._entries.values():
            entry.expires_at = _t.monotonic() - 1   # уже не fresh
            # stale_until остаётся в будущем

    # 3) второй запрос — должен отдать stale из кэша и пнуть bg-refresh,
    #    НЕ ходя синхронно в апстрим
    reply = res.resolve(make_request("example.com"), None)
    assert rcode(reply) == "NOERROR"
    assert calls["n"] == 1               # синхронного похода не было
    assert refreshed["spawned"] is True  # фоновое обновление запланировано

