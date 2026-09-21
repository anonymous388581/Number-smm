import asyncio
import importlib
import os
import re
import unittest
from unittest.mock import patch

os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "test-api-hash")

import utils.smm_client as smm_client


class SmmCredentialTests(unittest.TestCase):
    def reload_with_environment(self, values):
        with patch.dict(os.environ, values, clear=True):
            return importlib.reload(smm_client)

    def test_credentials_are_loaded_from_environment(self):
        module = self.reload_with_environment(
            {
                "SMM_SERVER_1_KEY": "test-key-one",
                "SMM_SERVER_2_KEY": "test-key-two",
            }
        )

        self.assertEqual(module.SMM_SERVERS[1]["key"], "test-key-one")
        self.assertEqual(module.SMM_SERVERS[2]["key"], "test-key-two")
        self.assertEqual(module.SMM_SERVERS[1]["url"], "https://fathersmm.com/api/v2")
        self.assertEqual(module.SMM_SERVERS[2]["url"], "https://best-smm.com/api/v2")

    def test_missing_credentials_fail_without_network_configuration(self):
        module = self.reload_with_environment({})

        self.assertEqual(module.SMM_SERVERS[1]["key"], "")
        self.assertEqual(asyncio.run(module.fetch_smm_services(1, force_refresh=True)), [])
        self.assertEqual(
            asyncio.run(module.create_smm_order(1, "https://target.invalid", 10, 1)),
            {"error": "SMM server 1 is not configured."},
        )
        self.assertEqual(
            asyncio.run(module.get_smm_order_status("order", 1)),
            {"error": "SMM server 1 is not configured."},
        )

    def test_client_has_no_hardcoded_api_key_literal(self):
        with open(smm_client.__file__, encoding="utf-8") as source_file:
            source = source_file.read()

        self.assertNotRegex(source, re.compile(r"['\"][0-9a-fA-F]{32}['\"]"))


if __name__ == "__main__":
    unittest.main()