"""
Тесты детектора утечки DNS. Сеть/Windows мокаются.
"""
import dns_leak


def _ps_ipv6(present):
    def runner(cmd, timeout=15):
        if "Get-NetIPAddress" in cmd:
            return ("1" if present else "0", "", 0)
        return ("OK:Ethernet", "", 0)
    return runner


def _dns(adapters):
    return lambda: adapters


def _check(cfg, running, ipv6_present, adapters):
    # форсим Windows-логику
    dns_leak.IS_WINDOWS = True
    return dns_leak.check_dns_leak(
        cfg, server_running=running,
        ps_runner=_ps_ipv6(ipv6_present), dns_getter=_dns(adapters))


def test_no_leak_when_all_local_no_ipv6():
    r = _check({"enable_ipv6": True}, True, False,
               {"Ethernet": {"ipv4": ["127.0.0.1"], "ipv6": []}})
    assert r["status"] == "ok"


def test_ipv6_leak_detected():
    r = _check({"enable_ipv6": True}, True, True,
               {"Ethernet": {"ipv4": ["127.0.0.1"], "ipv6": ["2001:4860:4860::8888"]}})
    assert r["status"] == "risk"
    assert any("IPv6" in d for d in r["details"])
    assert r["ipv6_present"] is True


def test_ipv6_ok_when_pointed_to_localhost():
    r = _check({"enable_ipv6": True}, True, True,
               {"Ethernet": {"ipv4": ["127.0.0.1"], "ipv6": ["::1"]}})
    assert r["status"] == "ok"


def test_ipv4_leak_when_server_running():
    r = _check({"enable_ipv6": True}, True, False,
               {"Wi-Fi": {"ipv4": ["192.168.1.1"], "ipv6": []}})
    assert r["status"] == "risk"
    assert any("192.168.1.1" in d for d in r["details"])


def test_ipv4_not_checked_when_server_stopped():
    # сервер выключен → IPv4-DNS чужой это нормально, не риск
    r = _check({"enable_ipv6": True}, False, False,
               {"Wi-Fi": {"ipv4": ["192.168.1.1"], "ipv6": []}})
    assert r["status"] == "ok"


def test_fec0_stubs_are_not_a_leak():
    """Служебные fec0::ffff:* заглушки Microsoft — это НЕ утечка."""
    r = _check({"enable_ipv6": True}, True, True,
               {"Беспроводная сеть": {"ipv4": ["127.0.0.1"],
                "ipv6": ["fec0:0:0:ffff::1", "fec0:0:0:ffff::2", "fec0:0:0:ffff::3"]}})
    assert r["status"] == "ok"


def test_service_adapters_ignored():
    """Loopback/ISATAP/Bluetooth не должны давать ложную утечку."""
    r = _check({"enable_ipv6": True}, True, True,
               {"Loopback Pseudo-Interface 1": {"ipv4": ["127.0.0.1"],
                "ipv6": ["2001:4860:4860::8888"]}})
    assert r["status"] == "ok"


def test_real_ipv6_dns_on_normal_adapter_is_leak():
    """Реальный провайдерский IPv6-DNS на обычном адаптере — это утечка."""
    r = _check({"enable_ipv6": True}, True, True,
               {"Ethernet": {"ipv4": ["127.0.0.1"], "ipv6": ["2001:4860:4860::8888"]}})
    assert r["status"] == "risk"
    assert any("IPv6" in d for d in r["details"])


def test_non_windows_returns_unknown(monkeypatch):
    monkeypatch.setattr(dns_leak, "IS_WINDOWS", False)
    r = dns_leak.check_dns_leak({}, server_running=True)
    assert r["status"] == "unknown"
    assert r["can_fix"] is False


def test_fix_requires_windows(monkeypatch):
    monkeypatch.setattr(dns_leak, "IS_WINDOWS", False)
    ok, _ = dns_leak.fix_ipv6_leak()
    assert ok is False


def test_fix_disable_ipv6_resolves_leak(monkeypatch):
    """После «Нет» (отключить IPv6) повторная проверка должна показать OK."""
    monkeypatch.setattr(dns_leak, "IS_WINDOWS", True)
    import process_monitor
    monkeypatch.setattr(process_monitor, "is_admin", lambda: True)

    state = {"ipv6_disabled": False, "ipv6_dns": ["2001:4860:4860::8888"]}

    def ps(cmd, timeout=15):
        if "Get-NetIPAddress" in cmd:
            return ("0" if state["ipv6_disabled"] else "1", "", 0)
        if "Disable-NetAdapterBinding" in cmd:
            state["ipv6_disabled"] = True
            return ("OK:Ethernet", "", 0)
        return ("OK:Ethernet", "", 0)

    dns = lambda: {"Ethernet": {"ipv4": ["127.0.0.1"], "ipv6": state["ipv6_dns"]}}
    cfg = {"enable_ipv6": True}

    before = dns_leak.check_dns_leak(cfg, True, ps_runner=ps, dns_getter=dns)
    assert before["status"] == "risk"
    ok, _ = dns_leak.fix_ipv6_leak(disable_ipv6=True, ps_runner=ps)
    assert ok is True
    after = dns_leak.check_dns_leak(cfg, True, ps_runner=ps, dns_getter=dns)
    assert after["status"] == "ok"


def test_fix_point_to_localhost_resolves_leak(monkeypatch):
    """После «Да» (IPv6 на ::1) повторная проверка должна показать OK."""
    monkeypatch.setattr(dns_leak, "IS_WINDOWS", True)
    import process_monitor
    monkeypatch.setattr(process_monitor, "is_admin", lambda: True)

    state = {"ipv6_dns": ["2001:4860:4860::8888"]}

    def ps(cmd, timeout=15):
        if "Get-NetIPAddress" in cmd:
            return ("1", "", 0)
        if "ServerAddresses @('::1')" in cmd:
            state["ipv6_dns"] = ["::1"]
            return ("OK:Ethernet", "", 0)
        return ("OK:Ethernet", "", 0)

    dns = lambda: {"Ethernet": {"ipv4": ["127.0.0.1"], "ipv6": state["ipv6_dns"]}}
    cfg = {"enable_ipv6": True}

    ok, _ = dns_leak.fix_ipv6_leak(disable_ipv6=False, ps_runner=ps)
    assert ok is True
    after = dns_leak.check_dns_leak(cfg, True, ps_runner=ps, dns_getter=dns)
    assert after["status"] == "ok"
