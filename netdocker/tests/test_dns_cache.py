import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dns_cache import DNSCache


class FakeQuestion:
    def __init__(self, qname="example.com.", qtype=1, qclass=1):
        self.qname = qname
        self.qtype = qtype
        self.qclass = qclass


class FakeRequest:
    def __init__(self, qname="example.com.", qtype=1, qclass=1):
        self.q = FakeQuestion(qname, qtype, qclass)


class FakeRR:
    def __init__(self, ttl):
        self.ttl = ttl


class FakeResponse:
    def __init__(self, answer_ttl=10, auth_ttl=20, add_ttl=30):
        self.rr = [FakeRR(answer_ttl)] if answer_ttl is not None else []
        self.auth = [FakeRR(auth_ttl)] if auth_ttl is not None else []
        self.ar = [FakeRR(add_ttl)] if add_ttl is not None else []


class TestDNSCache(unittest.TestCase):
    def test_set_and_get_returns_copy_with_adjusted_ttl(self):
        cache = DNSCache()
        request = FakeRequest()
        response = FakeResponse(answer_ttl=10, auth_ttl=12, add_ttl=15)

        with patch("dns_cache.time.monotonic", side_effect=[100.0]):
            self.assertTrue(cache.set(request, False, response))

        with patch("dns_cache.time.monotonic", side_effect=[102.0, 102.0]):
            cached = cache.get(request, False)

        self.assertIsNotNone(cached)
        self.assertIsNot(cached, response)
        self.assertEqual(cached.rr[0].ttl, 8)
        self.assertEqual(cached.auth[0].ttl, 10)
        self.assertEqual(cached.ar[0].ttl, 13)
        self.assertEqual(response.rr[0].ttl, 10)

    def test_expired_entry_returns_none(self):
        cache = DNSCache()
        request = FakeRequest()
        response = FakeResponse(answer_ttl=3, auth_ttl=None, add_ttl=None)

        with patch("dns_cache.time.monotonic", side_effect=[50.0]):
            cache.set(request, False, response)

        with patch("dns_cache.time.monotonic", side_effect=[54.0]):
            cached = cache.get(request, False)

        self.assertIsNone(cached)

    def test_ttl_override_limits_cache_lifetime(self):
        cache = DNSCache()
        request = FakeRequest()
        response = FakeResponse(answer_ttl=20, auth_ttl=None, add_ttl=None)

        with patch("dns_cache.time.monotonic", side_effect=[10.0]):
            cache.set(request, True, response, ttl_override=5)

        with patch("dns_cache.time.monotonic", side_effect=[14.0, 14.0]):
            cached = cache.get(request, True)
        self.assertIsNotNone(cached)
        self.assertEqual(cached.rr[0].ttl, 16)

        with patch("dns_cache.time.monotonic", side_effect=[16.0]):
            cached = cache.get(request, True)
        self.assertIsNone(cached)

    def test_clear_removes_entries(self):
        cache = DNSCache()
        request = FakeRequest()
        response = FakeResponse(answer_ttl=10, auth_ttl=None, add_ttl=None)
        with patch("dns_cache.time.monotonic", side_effect=[1.0]):
            cache.set(request, False, response)
        cache.clear()
        with patch("dns_cache.time.monotonic", side_effect=[2.0]):
            self.assertIsNone(cache.get(request, False))


if __name__ == "__main__":
    unittest.main()
