"""
Тесты невидимого failover между провайдерами и трекера здоровья.
Сеть не используется — мокаются транспортные резолверы.
"""
import pytest
from dnslib import DNSRecord, QTYPE, RR, A

import dns_server
import profile_utils
from provider_health import ProviderHealth, STATUS_UP, STATUS_DOWN, STATUS_UNKNOWN


def req(d):
    return DNSRecord.question(d, "A")


def resp(d, ip):
    r = req(d)
    rep = r.reply()
    rep.add_answer(RR(d, QTYPE.A, rdata=A(ip), ttl=60))
    return rep


def answers(reply):
    return [str(rr.rdata) for rr in reply.rr]


BASE_CFG = {
    "xbox_dns_mode": "doh",
    "upstream_mode": "sequential",
    "active_dns_profile": "builtin-xbox-dns",
    "user_dns_profiles": [],
    "provider_failover": True,
}


@pytest.fixture
def restore():
    saved = {n: getattr(dns_server, f"resolve_via_xbox_{n}") for n in ("udp", "doh", "dot", "doq")}
    hp = dns_server.get_provider_health()
    hp.reset()
    yield
    for n, fn in saved.items():
        setattr(dns_server, f"resolve_via_xbox_{n}", fn)
    hp.reset()


def _all_transports(fn):
    for n in ("udp", "doh", "dot", "doq"):
        setattr(dns_server, f"resolve_via_xbox_{n}", fn)


# ── provider ordering ────────────────────────────────────────────────────────

def test_failover_provider_order():
    provs = profile_utils.get_failover_providers(BASE_CFG)
    names = [p["name"] for p in provs]
    assert names[0] == "xbox-dns.ru"   # активный — первым
    assert "comss.one" in names        # запасной встроенный есть


def test_failover_disabled_returns_only_active():
    provs = profile_utils.get_failover_providers({**BASE_CFG, "provider_failover": False})
    assert len(provs) == 1
    assert provs[0]["id"] == "builtin-xbox-dns"


# ── failover behaviour ───────────────────────────────────────────────────────

def test_primary_works_no_failover_needed(restore):
    def by_provider(r, c, profile=None):
        return resp("chatgpt.com", "104.18.0.1")  # любой провайдер отвечает
    _all_transports(by_provider)
    out = dns_server.resolve_via_xbox(req("chatgpt.com"), BASE_CFG)
    assert answers(out) == ["104.18.0.1"]
    # активный помечен живым
    assert dns_server.get_provider_health().status_of("builtin-xbox-dns") == STATUS_UP


def test_primary_down_switches_to_backup(restore):
    def by_provider(r, c, profile=None):
        if profile and profile["id"] == "builtin-xbox-dns":
            return None   # основной мёртв
        return resp("chatgpt.com", "83.220.1.1")  # запасной отвечает
    _all_transports(by_provider)
    out = dns_server.resolve_via_xbox(req("chatgpt.com"), BASE_CFG)
    assert answers(out) == ["83.220.1.1"]   # ответ от запасного
    h = dns_server.get_provider_health()
    assert h.status_of("builtin-comss") == STATUS_UP
    assert h.overall_status() == STATUS_UP   # пользователь видит 🟢


def test_all_providers_down_returns_none(restore):
    _all_transports(lambda r, c, profile=None: None)
    out = dns_server.resolve_via_xbox(req("chatgpt.com"), BASE_CFG)
    assert out is None


def test_failover_disabled_does_not_try_backup(restore):
    tried = []

    def by_provider(r, c, profile=None):
        tried.append(profile["id"] if profile else "?")
        return None

    _all_transports(by_provider)
    dns_server.resolve_via_xbox(req("chatgpt.com"), {**BASE_CFG, "provider_failover": False})
    # пробовали только активного провайдера
    assert set(tried) == {"builtin-xbox-dns"}


# ── ProviderHealth unit ──────────────────────────────────────────────────────

def test_health_marks_down_after_threshold():
    h = ProviderHealth(fail_threshold=2)
    h.record_failure("p1", "P1")
    assert h.status_of("p1") != STATUS_DOWN   # одной мало
    h.record_failure("p1", "P1")
    assert h.status_of("p1") == STATUS_DOWN    # двух достаточно


def test_health_success_resets_fails():
    h = ProviderHealth(fail_threshold=2)
    h.record_failure("p1")
    h.record_success("p1")
    h.record_failure("p1")
    assert h.status_of("p1") != STATUS_DOWN    # счётчик сбросился


def test_overall_up_if_any_up():
    h = ProviderHealth(fail_threshold=1)
    h.record_failure("p1")        # down
    h.record_success("p2")        # up
    assert h.overall_status() == STATUS_UP


def test_overall_down_if_all_down():
    h = ProviderHealth(fail_threshold=1)
    h.record_failure("p1")
    h.record_failure("p2")
    assert h.overall_status() == STATUS_DOWN


def test_overall_unknown_when_empty():
    h = ProviderHealth()
    assert h.overall_status() == STATUS_UNKNOWN
