import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routing_utils import is_domain_routed


class TestRoutingUtils(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "route_all": False,
            "routed_domains": ["chatgpt.com", "openai.com"],
        }

    def test_exact_domain_match(self):
        self.assertTrue(is_domain_routed("chatgpt.com", self.cfg))

    def test_subdomain_match(self):
        self.assertTrue(is_domain_routed("api.openai.com", self.cfg))

    def test_unrelated_domain_not_routed(self):
        self.assertFalse(is_domain_routed("example.org", self.cfg))

    def test_route_all_overrides_list(self):
        cfg = dict(self.cfg)
        cfg["route_all"] = True
        self.assertTrue(is_domain_routed("anything.example", cfg))


if __name__ == "__main__":
    unittest.main()
