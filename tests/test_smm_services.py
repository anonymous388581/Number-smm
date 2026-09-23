import asyncio
import importlib
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "test-api-hash")
os.environ.setdefault("MONGODB_URI", "mongomock://")

import utils.smm_client as smm_client


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status = status
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def json(self, content_type=None):
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def post(self, url, data, timeout):
        self.requests.append((url, data, timeout))
        return self.response


class SmmServiceTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.reload(smm_client)
        self.module._services_cache = {1: None, 2: None}
        self.module._cache_time = {1: 0, 2: 0}

    def run_async(self, awaitable):
        return asyncio.run(awaitable)

    def fetch_with(self, server, payload, status=200):
        session = FakeSession(FakeResponse(status, payload))
        with patch.object(self.module.aiohttp, "ClientSession", return_value=session):
            result = self.run_async(self.module.fetch_smm_services(server, force_refresh=True))
        return result, session

    def test_server_callbacks_map_to_their_own_provider(self):
        self.module.SMM_SERVERS[1]["key"] = "vip-test-key"
        self.module.SMM_SERVERS[2]["key"] = "budget-test-key"
        vip, vip_session = self.fetch_with(1, [{"service": 101, "category": "Telegram VIP", "name": "VIP"}])
        budget, budget_session = self.fetch_with("2", [{"service": 202, "category": "Instagram Budget", "name": "Budget"}])

        self.assertEqual(vip[0]["service"], 101)
        self.assertEqual(budget[0]["service"], 202)
        self.assertEqual(vip_session.requests[0][0], self.module.SMM_SERVERS[1]["url"])
        self.assertEqual(budget_session.requests[0][0], self.module.SMM_SERVERS[2]["url"])
        self.assertEqual(self.run_async(self.module.get_services_for_category("Telegram VIP", 1))[0]["service"], 101)
        self.assertEqual(self.run_async(self.module.get_services_for_category("Instagram Budget", 2))[0]["service"], 202)

    def test_empty_response_and_provider_failure_are_safe(self):
        self.module.SMM_SERVERS[1]["key"] = "vip-test-key"
        empty, _ = self.fetch_with(1, [])
        failed, _ = self.fetch_with(1, {"error": "provider unavailable"}, status=503)
        self.assertEqual(empty, [])
        self.assertEqual(failed, [])

    def test_service_details_accept_string_or_integer_service_ids(self):
        self.module.SMM_SERVERS[1]["key"] = "vip-test-key"
        self.fetch_with(1, [{"service": 101, "category": "Telegram VIP", "name": "VIP"}])
        self.assertEqual(self.run_async(self.module.get_smm_service_details("101", "1"))["name"], "VIP")


if __name__ == "__main__":
    unittest.main()