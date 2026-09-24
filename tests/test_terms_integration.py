import asyncio
import os
import unittest
from urllib.parse import urlparse

os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "test-api-hash")
os.environ.setdefault("MONGODB_URI", "mongomock://")

from aiohttp.test_utils import TestClient, TestServer
from config import TERMS_URL
from utils.health import create_health_app
from utils.keyboards import get_terms_buttons


class TermsIntegrationTests(unittest.TestCase):
    def test_terms_route_is_public_html(self):
        async def check():
            async with TestClient(TestServer(create_health_app())) as client:
                response = await client.get("/terms/")
                body = await response.text()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.content_type, "text/html")
                self.assertIn("Terms &amp; Conditions", body)
                self.assertIn("Global OTP Bot", body)

        asyncio.run(check())

    def test_terms_button_uses_absolute_public_route(self):
        terms_url = get_terms_buttons()[0][0].url
        parsed = urlparse(terms_url)
        self.assertEqual(parsed.scheme, "https")
        self.assertTrue(parsed.netloc)
        self.assertTrue(parsed.path.endswith("/terms/"))
        self.assertEqual(terms_url, TERMS_URL)


if __name__ == "__main__":
    unittest.main()
