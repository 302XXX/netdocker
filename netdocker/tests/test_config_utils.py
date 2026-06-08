import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config_utils import DEFAULT_CONFIG, load_config_file, sanitize_config, save_config_file


class TestConfigUtils(unittest.TestCase):
    def test_sanitize_non_dict_returns_defaults(self):
        cfg, warnings = sanitize_config([1, 2, 3])
        self.assertEqual(cfg, DEFAULT_CONFIG)
        self.assertTrue(warnings)

    def test_secondary_builtin_profile_can_be_active(self):
        # comss.one (второй встроенный) должен сохраняться как активный,
        # а не сбрасываться на xbox-dns (регрессия).
        cfg, _ = sanitize_config({"active_dns_profile": "builtin-comss", "user_dns_profiles": []})
        self.assertEqual(cfg["active_dns_profile"], "builtin-comss")

    def test_invalid_active_profile_falls_back_to_xbox(self):
        cfg, warnings = sanitize_config({"active_dns_profile": "does-not-exist", "user_dns_profiles": []})
        self.assertEqual(cfg["active_dns_profile"], "builtin-xbox-dns")
        self.assertTrue(any("active_dns_profile" in w for w in warnings))

    def test_sanitize_normalizes_domains_and_protects_fallbacks(self):
        raw = {
            "fallback_dns": "127.0.0.1",
            "fallback_dns6": "::1",
            "routed_domains": [
                "https://www.openai.com/path",
                "CHATGPT.COM",
                "chatgpt.com.",
                "",
                None,
            ],
            "routed_processes": ["Chrome.exe", "chrome.exe", "  msedge.exe  "],
        }
        cfg, warnings = sanitize_config(raw)
        self.assertEqual(cfg["fallback_dns"], DEFAULT_CONFIG["fallback_dns"])
        self.assertEqual(cfg["fallback_dns6"], DEFAULT_CONFIG["fallback_dns6"])
        self.assertEqual(cfg["routed_domains"], ["openai.com", "chatgpt.com"])
        self.assertEqual(cfg["routed_processes"], ["chrome.exe", "msedge.exe"])
        self.assertTrue(warnings)

    def test_save_config_file_normalizes_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            raw = {
                "listen_port": "53",
                "routed_domains": ["https://www.openai.com/test"],
                "routed_processes": "oops",
            }
            saved = save_config_file(path, raw)
            with open(path, "r", encoding="utf-8") as f:
                on_disk = json.load(f)
            self.assertEqual(saved, on_disk)
            self.assertEqual(on_disk["listen_port"], 53)
            self.assertEqual(on_disk["routed_domains"], ["openai.com"])
            self.assertEqual(on_disk["routed_processes"], [])

    def test_load_config_file_creates_default_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            cfg = load_config_file(path)
            self.assertTrue(os.path.exists(path))
            self.assertEqual(cfg, DEFAULT_CONFIG)

    def test_load_config_file_recovers_broken_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("{ broken json")

            cfg = load_config_file(path)

            self.assertEqual(cfg, DEFAULT_CONFIG)
            backups = [name for name in os.listdir(tmp) if name.startswith("config.json.broken-")]
            self.assertTrue(backups)
            with open(path, "r", encoding="utf-8") as f:
                restored = json.load(f)
            self.assertEqual(restored, DEFAULT_CONFIG)


if __name__ == "__main__":
    unittest.main()
