import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from profile_utils import (
    BUILTIN_PROFILE_ID,
    MAX_PROFILE_NAME_LEN,
    get_active_dns_profile,
    get_all_dns_profiles,
    make_new_user_dns_profile,
    sanitize_dns_profile,
    sanitize_user_dns_profiles,
)


class TestProfileUtils(unittest.TestCase):
    def test_builtin_profile_is_available(self):
        profiles = get_all_dns_profiles({"user_dns_profiles": []})
        self.assertTrue(any(p["id"] == BUILTIN_PROFILE_ID for p in profiles))

    def test_profile_name_is_truncated_to_max_len(self):
        p = sanitize_dns_profile({"name": "X" * 50})
        self.assertEqual(len(p["name"]), MAX_PROFILE_NAME_LEN)

    def test_profile_name_within_limit_unchanged(self):
        p = sanitize_dns_profile({"name": "Мой профиль"})
        self.assertEqual(p["name"], "Мой профиль")

    def test_active_profile_falls_back_to_builtin(self):
        profile = get_active_dns_profile({"active_dns_profile": "missing", "user_dns_profiles": []})
        self.assertEqual(profile["id"], BUILTIN_PROFILE_ID)

    def test_new_user_profile_has_blank_dns_fields(self):
        profile = make_new_user_dns_profile([])
        self.assertTrue(profile["name"])
        self.assertEqual(profile["ipv4_primary"], "")
        self.assertEqual(profile["ipv4_secondary"], "")
        self.assertEqual(profile["ipv6_primary"], "")
        self.assertEqual(profile["ipv6_secondary"], "")
        self.assertEqual(profile["doh_url"], "")

    def test_sanitize_user_profiles_limits_amount(self):
        raw = [{"name": f"P{i}"} for i in range(20)]
        profiles = sanitize_user_dns_profiles(raw)
        self.assertLessEqual(len(profiles), 10)


if __name__ == "__main__":
    unittest.main()
