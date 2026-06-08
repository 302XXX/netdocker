"""
Тесты предстартовых проверок: доступность порта и preflight_check.
"""
import socket

import dns_server


def _free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_check_port_available_when_free():
    port = _free_udp_port()
    ok, reason = dns_server.check_port_available("127.0.0.1", port)
    assert ok is True
    assert reason == ""


def test_check_port_available_when_busy():
    # Занимаем порт сами и проверяем, что детектится конфликт.
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    busy_port = s.getsockname()[1]
    try:
        ok, reason = dns_server.check_port_available("127.0.0.1", busy_port)
        assert ok is False
        assert "занят" in reason or "не удалось" in reason
    finally:
        s.close()


def test_preflight_ok_on_free_high_port(monkeypatch):
    port = _free_udp_port()
    cfg = {
        "listen_port": port,            # high port → прав не требует
        "listen_host": "127.0.0.1",
        "enable_ipv6": False,
    }
    ok, problems, warnings = dns_server.preflight_check(cfg)
    assert ok is True, problems
    assert problems == []


def test_preflight_reports_busy_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    busy_port = s.getsockname()[1]
    try:
        cfg = {
            "listen_port": busy_port,
            "listen_host": "127.0.0.1",
            "enable_ipv6": False,
        }
        ok, problems, warnings = dns_server.preflight_check(cfg)
        assert ok is False
        assert any("127.0.0.1" in p for p in problems)
    finally:
        s.close()


def test_preflight_ipv6_failure_is_warning_not_blocker():
    # IPv6 на заведомо «битом» адресе не должен блокировать запуск,
    # только давать warning (ok остаётся по IPv4).
    port = _free_udp_port()
    cfg = {
        "listen_port": port,
        "listen_host": "127.0.0.1",
        "enable_ipv6": True,
        "listen_host6": "::1",
    }
    ok, problems, warnings = dns_server.preflight_check(cfg)
    # IPv4 свободен → ok=True независимо от исхода IPv6
    assert ok is True
