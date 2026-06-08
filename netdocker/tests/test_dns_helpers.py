import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dns_helpers import cap_response_ttl, ordered_upstreams


class FakeRR:
    def __init__(self, ttl):
        self.ttl = ttl


class FakeResponse:
    def __init__(self):
        self.rr = [FakeRR(20)]
        self.auth = [FakeRR(10)]
        self.ar = [FakeRR(0)]


class TestDNSHelpers(unittest.TestCase):
    def test_ordered_upstreams_prefers_ipv4_for_a(self):
        result = ordered_upstreams("A", ["1.1.1.1"], ["2606:4700:4700::1111"])
        self.assertEqual(result, [("IPv4", "1.1.1.1"), ("IPv6", "2606:4700:4700::1111")])

    def test_ordered_upstreams_prefers_ipv6_for_aaaa(self):
        result = ordered_upstreams("AAAA", ["1.1.1.1"], ["2606:4700:4700::1111"])
        self.assertEqual(result, [("IPv6", "2606:4700:4700::1111"), ("IPv4", "1.1.1.1")])

    def test_ordered_upstreams_ignores_empty_values(self):
        result = ordered_upstreams("A", ["", None, "8.8.8.8"], [None])
        self.assertEqual(result, [("IPv4", "8.8.8.8")])

    def test_cap_response_ttl_caps_all_sections(self):
        response = FakeResponse()
        capped = cap_response_ttl(response, 5)
        self.assertIs(capped, response)
        self.assertEqual(response.rr[0].ttl, 5)
        self.assertEqual(response.auth[0].ttl, 5)
        self.assertEqual(response.ar[0].ttl, 5)


if __name__ == "__main__":
    unittest.main()
