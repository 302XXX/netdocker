"""
Тесты per-app (по процессам) маршрутизации:
  - DnsProcessTracker: таблица домен→процесс, TTL, поддомены, парсинг событий
  - is_domain_routed: additive-логика (домен ИЛИ процесс), обратная совместимость
"""
import time

import process_dns_tracker as t
from routing_utils import is_domain_routed


# ── DnsProcessTracker ───────────────────────────────────────────────────────

def test_record_and_match_exact():
    tr = t.DnsProcessTracker(sticky_ttl=300)
    tr._record("chatgpt.com", "chrome.exe")
    assert tr.domain_requested_by("chatgpt.com", ["chrome.exe"]) is True


def test_match_is_case_insensitive():
    tr = t.DnsProcessTracker(sticky_ttl=300)
    tr._record("chatgpt.com", "chrome.exe")
    assert tr.domain_requested_by("CHATGPT.COM", ["Chrome.EXE"]) is True


def test_subdomain_inherits_parent_process():
    tr = t.DnsProcessTracker(sticky_ttl=300)
    tr._record("chatgpt.com", "chrome.exe")
    # поддомен должен маршрутизироваться, если родитель запрашивал процесс
    assert tr.domain_requested_by("ab.chatgpt.com", ["chrome.exe"]) is True


def test_other_process_does_not_match():
    tr = t.DnsProcessTracker(sticky_ttl=300)
    tr._record("chatgpt.com", "chrome.exe")
    assert tr.domain_requested_by("chatgpt.com", ["firefox.exe"]) is False


def test_empty_process_list_is_false():
    tr = t.DnsProcessTracker(sticky_ttl=300)
    tr._record("chatgpt.com", "chrome.exe")
    assert tr.domain_requested_by("chatgpt.com", []) is False


def test_ttl_expiry():
    tr = t.DnsProcessTracker(sticky_ttl=1)
    tr._record("x.com", "chrome.exe")
    assert tr.domain_requested_by("x.com", ["chrome.exe"]) is True
    time.sleep(1.1)
    assert tr.domain_requested_by("x.com", ["chrome.exe"]) is False


def test_prune_removes_stale():
    tr = t.DnsProcessTracker(sticky_ttl=1)
    tr._record("x.com", "chrome.exe")
    time.sleep(1.1)
    tr._prune()
    assert tr.stats()["domains_tracked"] == 0


# ── Парсинг событий журнала (через моки) ────────────────────────────────────

def _make_mocked_tracker(fetch_lines):
    """Создаёт трекер с замоканным PowerShell-раннером и pid-резолвером."""
    pid_map = {1111: "chrome.exe", 2222: "svchost.exe"}

    def fake_ps(cmd, timeout=15):
        if "IsEnabled" in cmd:
            return ("ENABLED", "", 0)
        return (fetch_lines, "", 0)

    def fake_pid(pid):
        return pid_map.get(int(pid))

    return t.DnsProcessTracker(ps_runner=fake_ps, pid_resolver=fake_pid)


def test_poll_parses_event_lines():
    lines = "10|1111|chatgpt.com\n11|1111|cdn.oaistatic.com\n12|2222|update.microsoft.com"
    tr = _make_mocked_tracker(lines)
    tr._poll_once()
    assert tr.domain_requested_by("chatgpt.com", ["chrome.exe"]) is True
    assert tr.domain_requested_by("cdn.oaistatic.com", ["chrome.exe"]) is True
    # svchost ≠ chrome
    assert tr.domain_requested_by("update.microsoft.com", ["chrome.exe"]) is False


def test_poll_tracks_last_record_id_incrementally():
    tr = _make_mocked_tracker("10|1111|a.com\n12|1111|b.com\n11|1111|c.com")
    tr._poll_once()
    assert tr._last_record_id == 12


def test_poll_ignores_malformed_lines():
    tr = _make_mocked_tracker("garbage\n\n10|1111|good.com\nno-pipe-here")
    tr._poll_once()
    assert tr.domain_requested_by("good.com", ["chrome.exe"]) is True
    assert tr.stats()["domains_tracked"] == 1


# ── is_domain_routed: additive-логика ───────────────────────────────────────

def test_routed_by_domain_without_tracker():
    cfg = {"routed_domains": ["openai.com"], "routed_processes": ["chrome.exe"]}
    assert is_domain_routed("openai.com", cfg) is True
    assert is_domain_routed("sub.openai.com", cfg) is True


def test_not_routed_when_nothing_matches():
    cfg = {"routed_domains": ["openai.com"], "routed_processes": ["chrome.exe"]}
    assert is_domain_routed("example.com", cfg) is False


def test_routed_by_process_via_tracker():
    cfg = {"routed_domains": ["openai.com"], "routed_processes": ["chrome.exe"]}
    tr = t.DnsProcessTracker(sticky_ttl=300)
    assert is_domain_routed("example.com", cfg, tr) is False
    tr._record("example.com", "chrome.exe")
    assert is_domain_routed("example.com", cfg, tr) is True


def test_process_routing_respects_routed_processes_list():
    # домен запрошен chrome, но chrome НЕ в routed_processes → не маршрутизируем
    cfg = {"routed_domains": [], "routed_processes": ["firefox.exe"]}
    tr = t.DnsProcessTracker(sticky_ttl=300)
    tr._record("example.com", "chrome.exe")
    assert is_domain_routed("example.com", cfg, tr) is False


def test_route_all_overrides_everything():
    cfg = {"route_all": True, "routed_domains": [], "routed_processes": []}
    assert is_domain_routed("anything.example", cfg) is True


def test_backward_compatible_signature():
    # старый вызов без tracker не должен падать
    cfg = {"routed_domains": ["openai.com"]}
    assert is_domain_routed("openai.com", cfg) is True
    assert is_domain_routed("nope.com", cfg) is False


# ── Graceful degradation ────────────────────────────────────────────────────

def test_tracker_status_text_non_windows():
    tr = t.DnsProcessTracker()
    # на не-Windows должен честно сообщить о недоступности
    txt = tr.status_text()
    assert isinstance(txt, str) and len(txt) > 0


def test_tracker_safe_when_unused():
    tr = t.DnsProcessTracker()
    # без записей — всегда False, не падает
    assert tr.domain_requested_by("any.com", ["chrome.exe"]) is False
