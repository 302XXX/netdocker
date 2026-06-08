"""
Тесты DNSCrypt: парсинг sdns-штампа, доступность, интеграция в транспорты.
Сеть не используется (кроме опционального теста с NETDOCKER_NET_TESTS=1).
"""
import os

import pytest

import dnscrypt
import dns_server
import profile_utils
import config_utils
from dnslib import DNSRecord, QTYPE, RR, A


# реальный публичный штамп AdGuard DNSCrypt (полный, валидный)
ADGUARD_STAMP = ("sdns://AQMAAAAAAAAAETk0LjE0MC4xNC4xNDo1NDQzINErR_JS3PLCu_iZ"
                 "EIbq95zkSV2LFsigxDIuUso_OQhzIjIuZG5zY3J5cHQuZGVmYXVsdC5uczEu"
                 "YWRndWFyZC5jb20")


def req(d="example.com"):
    return DNSRecord.question(d, "A")


def resp(d, ip):
    r = req(d)
    rep = r.reply()
    rep.add_answer(RR(d, QTYPE.A, rdata=A(ip), ttl=60))
    return rep


# ── парсинг штампа ───────────────────────────────────────────────────────────
def test_parse_stamp_basic():
    info = dnscrypt.parse_stamp(ADGUARD_STAMP)
    assert info["port"] == 5443
    assert "adguard" in info["provider_name"]
    assert len(info["provider_pk"]) == 32
    assert info["addr"]


def test_parse_stamp_rejects_non_sdns():
    with pytest.raises(ValueError):
        dnscrypt.parse_stamp("https://example.com/dns-query")


def test_parse_stamp_rejects_non_dnscrypt_type():
    # тип 0x02 (DoH) — должен отвергаться как не-DNSCrypt
    import base64
    raw = bytes([0x02]) + b"\x00" * 8 + b"\x09" + b"1.0.0.1:1"
    stamp = "sdns://" + base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    with pytest.raises(ValueError):
        dnscrypt.parse_stamp(stamp)


def test_dnscrypt_available_is_bool():
    assert isinstance(dnscrypt.dnscrypt_available(), bool)


def test_query_raises_clear_error_when_unavailable(monkeypatch):
    monkeypatch.setattr(dnscrypt, "dnscrypt_available", lambda: False)
    with pytest.raises(RuntimeError) as ei:
        dnscrypt.query_dnscrypt(ADGUARD_STAMP, req())
    assert "pynacl" in str(ei.value).lower()


# ── интеграция в транспорты dns_server ───────────────────────────────────────
@pytest.fixture
def restore():
    saved = {n: getattr(dns_server, f"resolve_via_xbox_{n}")
             for n in ("udp", "doh", "dot", "doq", "dnscrypt")}
    yield
    for n, fn in saved.items():
        setattr(dns_server, f"resolve_via_xbox_{n}", fn)


def test_mode_dnscrypt_uses_dnscrypt(restore):
    dns_server.resolve_via_xbox_dnscrypt = lambda r, c, timeout=5.0, profile=None: resp("chatgpt.com", "1.2.3.4")
    cfg = {"xbox_dns_mode": "dnscrypt", "provider_failover": False,
           "active_dns_profile": "builtin-xbox-dns", "user_dns_profiles": [],
           "upstream_mode": "sequential"}
    out = dns_server.resolve_via_xbox(req("chatgpt.com"), cfg)
    assert [str(x.rdata) for x in out.rr] == ["1.2.3.4"]


def test_dnscrypt_falls_back_to_doh(restore):
    dns_server.resolve_via_xbox_dnscrypt = lambda r, c, timeout=5.0, profile=None: None
    dns_server.resolve_via_xbox_doh = lambda r, c, profile=None: resp("chatgpt.com", "9.9.9.9")
    cfg = {"xbox_dns_mode": "dnscrypt", "provider_failover": False,
           "active_dns_profile": "builtin-xbox-dns", "user_dns_profiles": [],
           "upstream_mode": "sequential"}
    out = dns_server.resolve_via_xbox(req("chatgpt.com"), cfg)
    assert [str(x.rdata) for x in out.rr] == ["9.9.9.9"]


# ── профиль и конфиг ─────────────────────────────────────────────────────────
def test_profile_keeps_valid_stamp():
    p = profile_utils.sanitize_dns_profile({"name": "x", "dnscrypt_stamp": ADGUARD_STAMP})
    assert p["dnscrypt_stamp"] == ADGUARD_STAMP


def test_profile_rejects_bad_stamp():
    p = profile_utils.sanitize_dns_profile({"name": "x", "dnscrypt_stamp": "http://nope"})
    assert p["dnscrypt_stamp"] == ""


def test_config_accepts_dnscrypt_mode():
    cfg, _ = config_utils.sanitize_config({"xbox_dns_mode": "dnscrypt"})
    assert cfg["xbox_dns_mode"] == "dnscrypt"


# ── опциональный реальный тест ───────────────────────────────────────────────
@pytest.mark.skipif(os.environ.get("NETDOCKER_NET_TESTS") != "1",
                    reason="сетевой тест выключен")
def test_dnscrypt_real_adguard():
    out = dnscrypt.query_dnscrypt(ADGUARD_STAMP, req("example.com"), timeout=10)
    assert out is not None and len(out.rr) >= 1
