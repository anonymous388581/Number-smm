import unittest

import mongomock

from mongo_repository import MongoRepository


class MongoRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.client = mongomock.MongoClient()
        self.repository = MongoRepository(client=self.client, database_name="runtime_test")
        self.repository.ensure_indexes()

    def test_user_balance_and_restart_persistence(self):
        self.repository.ensure_user(101)
        self.repository.update_balance(101, 250)
        self.assertEqual(self.repository.get_user(101)["balance"], 250)

        restarted = MongoRepository(client=self.client, database_name="runtime_test")
        self.assertEqual(restarted.get_user(101)["balance"], 250)

    def test_stock_filters_and_atomic_claim(self):
        self.repository.db.stock.insert_many([
            {"_id": "good", "phone": "good", "country_name": "India", "account_year": 2026,
             "category": "Good", "available": 1, "twofa": "None"},
            {"_id": "spam", "phone": "spam", "country_name": "India", "account_year": 2025,
             "category": "spam", "available": 1, "twofa": "pass"},
        ])
        claimed = self.repository.claim_stock_account("nonspam", country="India")
        self.assertEqual(claimed["phone"], "good")
        self.assertIsNone(self.repository.claim_stock_account("nonspam", country="India"))
        self.assertEqual(self.repository.claim_stock_account("spam", country="India")["phone"], "spam")

    def test_settings_and_lzt_settings_persist(self):
        self.repository.set_setting("bot_mode", "hybrid")
        self.repository.set_setting("lzt_api_key", "stored-key")
        restarted = MongoRepository(client=self.client, database_name="runtime_test")
        self.assertEqual(restarted.get_setting("bot_mode"), "hybrid")
        self.assertEqual(restarted.get_setting("lzt_api_key"), "stored-key")


if __name__ == "__main__":
    unittest.main()
