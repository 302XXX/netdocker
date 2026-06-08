"""
Тесты транспортов DoT/DoQ и логики выбора/fallback транспортов в resolve_via_xbox.

Сетевые вызовы мокаются. Есть один опциональный интеграционный тест DoT против
публичного сервера — он пропускается, если сети нет.
"""
import os
import struct

import pytest
from dnslib import DNSRecord, QTYPE, RR, A

import dns_server
import dns_transports
import config_utils
import profile_utils


def req(d, t="A"):
    return DNSRecord.question(d, t)


def resp(d, ip):
    r = req(d)
    rep = r.reply()
    rep.add_answer(RR(d, QTYPE.A, rdata=A(ip), ttl=60))
    return rep


def answers(reply):
    return [str(rr.rdata) for rr in reply.rr]


CFG = {
    "upstream_mode": "sequential",
    "active_dns_profile": "builtin-xbox-dns",
    "user_dns_profiles": [],
    # эти тесты проверяют цепочку транспортов В ОДНОМ провайдере,
    # поэтому failover между провайдерами выключаем
    "provider_failover": False,
}


@pytest.fixture
def restore_transports():
    saved = {
        "udp": dns_server.resolve_via_xbox_udp,
        "doh": dns_server.resolve_via_xbox_doh,
        "dot": dns_server.resolve_via_xbox_dot,
        "doq": dns_server.resolve_via_xbox_doq,
    }
    yield
    dns_server.resolve_via_xbox_udp = saved["udp"]
    dns_server.resolve_via_xbox_doh = saved["doh"]
    dns_server.resolve_via_xbox_dot = saved["dot"]
    dns_server.resolve_via_xbox_doq = saved["doq"]


# ── выбор транспорта по режиму ───────────────────────────────────────────────

def test_mode_dot_uses_dot(restore_transports):
    dns_server.resolve_via_xbox_dot = lambda r, c, profile=None: resp("chatgpt.com", "1.1.1.1")
    out = dns_server.resolve_via_xbox(req("chatgpt.com"), {**CFG, "xbox_dns_mode": "dot"})
    assert answers(out) == ["1.1.1.1"]


def test_mode_doq_uses_doq(restore_transports):
    dns_server.resolve_via_xbox_doq = lambda r, c, profile=None: resp("chatgpt.com", "2.2.2.2")
    out = dns_server.resolve_via_xbox(req("chatgpt.com"), {**CFG, "xbox_dns_mode": "doq"})
    assert answers(out) == ["2.2.2.2"]


def test_doq_falls_back_to_doh(restore_transports):
    dns_server.resolve_via_xbox_doq = lambda r, c, profile=None: None
    dns_server.resolve_via_xbox_doh = lambda r, c, profile=None: resp("chatgpt.com", "3.3.3.3")
    out = dns_server.resolve_via_xbox(req("chatgpt.com"), {**CFG, "xbox_dns_mode": "doq"})
    assert answers(out) == ["3.3.3.3"]


def test_dot_falls_back_through_chain(restore_transports):
    # dot и doh падают, udp отвечает → должен дойти до udp
    dns_server.resolve_via_xbox_dot = lambda r, c, profile=None: None
    dns_server.resolve_via_xbox_doh = lambda r, c, profile=None: None
    dns_server.resolve_via_xbox_udp = lambda r, c, profile=None: resp("chatgpt.com", "4.4.4.4")
    out = dns_server.resolve_via_xbox(req("chatgpt.com"), {**CFG, "xbox_dns_mode": "dot"})
    assert answers(out) == ["4.4.4.4"]


def test_all_transports_fail_returns_none(restore_transports):
    for name in ("udp", "doh", "dot", "doq"):
        setattr(dns_server, f"resolve_via_xbox_{name}", lambda r, c, profile=None: None)
    out = dns_server.resolve_via_xbox(req("chatgpt.com"), {**CFG, "xbox_dns_mode": "doq"})
    assert out is None


def test_unknown_mode_defaults_to_doh(restore_transports):
    # неизвестный режим → дефолт DoH (надёжнее всего по доменному имени)
    dns_server.resolve_via_xbox_doh = lambda r, c, profile=None: resp("chatgpt.com", "5.5.5.5")
    out = dns_server.resolve_via_xbox(req("chatgpt.com"), {**CFG, "xbox_dns_mode": "weird"})
    assert answers(out) == ["5.5.5.5"]


# ── конфиг и профиль ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("mode", ["udp", "doh", "dot", "doq"])
def test_config_accepts_all_modes(mode):
    cfg, warns = config_utils.sanitize_config({"xbox_dns_mode": mode})
    assert cfg["xbox_dns_mode"] == mode


def test_config_rejects_bad_mode():
    cfg, warns = config_utils.sanitize_config({"xbox_dns_mode": "telepathy"})
    assert cfg["xbox_dns_mode"] in ("udp", "doh")  # дефолт
    assert any("xbox_dns_mode" in w for w in warns)


def test_builtin_profile_has_dot_doq_fields():
    p = profile_utils.BUILTIN_DNS_PROFILE
    assert p["dot_host"] and p["dot_port"] == 853
    assert p["doq_host"] and p["doq_port"] == 853


def test_user_profile_sanitizes_dot_doq():
    raw = {
        "name": "My DoT",
        "dot_host": "dns.example.com",
        "dot_ip": "9.9.9.9",
        "dot_port": "853",
        "doq_host": "dns.example.com",
        "doq_ip": "9.9.9.9",
        "doq_port": "99999",   # некорректный → дефолт 853
    }
    p = profile_utils.sanitize_dns_profile(raw)
    assert p["dot_host"] == "dns.example.com"
    assert p["dot_ip"] == "9.9.9.9"
    assert p["dot_port"] == 853
    assert p["doq_port"] == 853   # 99999 невалиден → дефолт


# ── DoQ graceful degradation ─────────────────────────────────────────────────

def test_doq_raises_clear_error_when_unavailable(monkeypatch):
    monkeypatch.setattr(dns_transports, "doq_available", lambda: False)
    with pytest.raises(RuntimeError) as ei:
        dns_transports.query_doq("1.2.3.4", req("a.com"))
    assert "aioquic" in str(ei.value)


# ── DoT wire-format (без сети) ───────────────────────────────────────────────

def test_dot_sends_length_prefixed_query(monkeypatch):
    """Проверяем, что DoT шлёт 2-байтный префикс длины + корректно парсит ответ,
    мокая ssl-сокет (без реальной сети)."""
    request = req("example.com")
    expected = resp("example.com", "1.2.3.4").pack()

    sent = {}

    class FakeTLS:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def sendall(self, data): sent["data"] = data
        def recv(self, n):
            # отдаём по кускам: сперва длина, затем тело
            buf = sent.setdefault("_outbuf", struct.pack("!H", len(expected)) + expected)
            chunk, rest = buf[:n], buf[n:]
            sent["_outbuf"] = rest
            return chunk

    class FakeCtx:
        check_hostname = True
        verify_mode = None
        def wrap_socket(self, sock, server_hostname=None): return FakeTLS()

    class FakeSock:
        def __init__(self, *a, **k): pass
        def settimeout(self, t): pass
        def connect(self, addr): pass
        def close(self): pass

    monkeypatch.setattr(dns_transports.ssl, "create_default_context", lambda: FakeCtx())
    monkeypatch.setattr(dns_transports.socket, "socket", lambda *a, **k: FakeSock())

    out = dns_transports.query_dot("1.2.3.4", request, server_hostname="x", verify=False)
    # проверяем, что отправили префикс длины
    assert struct.unpack("!H", sent["data"][:2])[0] == len(request.pack())
    # и распарсили ответ
    assert [str(rr.rdata) for rr in out.rr] == ["1.2.3.4"]


# ── опциональный интеграционный тест (реальная сеть) ─────────────────────────

@pytest.mark.skipif(
    os.environ.get("NETDOCKER_NET_TESTS") != "1",
    reason="сетевой тест выключен (NETDOCKER_NET_TESTS!=1)",
)
def test_dot_real_cloudflare():
    out = dns_transports.query_dot(
        "1.1.1.1", req("example.com"), timeout=8,
        server_hostname="cloudflare-dns.com", verify=True,
    )
    assert out is not None and len(out.rr) >= 1
