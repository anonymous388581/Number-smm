import unittest

import mongomock

from mongo_cursor import MongoCursor
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

    def test_manual_stock_survives_repository_restart(self):
        self.repository.upsert_stock_account({
            "phone": "restart-stock",
            "session_file": "sessions/restart-stock.session",
            "country_name": "India",
            "country_icon": "",
            "account_year": 2026,
            "category": "Good",
            "price": 100,
            "available": 1,
            "twofa": "None",
        })

        restarted = MongoRepository(client=self.client, database_name="runtime_test")
        account = restarted.db.stock.find_one({"phone": "restart-stock"})
        self.assertIsNotNone(account)
        self.assertEqual(account["category"], "Good")
        self.assertEqual(account["country_name"], "India")
        self.assertEqual(account["account_year"], 2026)
        self.assertEqual(account["available"], 1)
        self.assertIn("added_date", account)

    def test_stock_category_filters_preserve_country_year_and_availability(self):
        self.repository.db.stock.insert_many([
            {"_id": "clean-india", "phone": "clean-india", "country_name": "India", "account_year": 2026,
             "category": "Good", "available": 1, "twofa": "None"},
            {"_id": "clean-brazil", "phone": "clean-brazil", "country_name": "Brazil", "account_year": 2025,
             "category": "Good", "available": 1, "twofa": "None"},
            {"_id": "spam-india", "phone": "spam-india", "country_name": "India", "account_year": 2026,
             "category": "spam", "available": 1, "twofa": "None"},
            {"_id": "spam-brazil", "phone": "spam-brazil", "country_name": "Brazil", "account_year": 2025,
             "category": "spam", "available": 1, "twofa": "None"},
            {"_id": "unavailable-clean", "phone": "unavailable-clean", "country_name": "India", "account_year": 2026,
             "category": "Good", "available": 0, "twofa": "None"},
        ])

        cursor = MongoCursor(self.repository)
        nonspam_where = "available=1 AND category IS NOT NULL AND LOWER(category) != 'spam'"
        spam_where = "available=1 AND LOWER(category) = 'spam'"
        self.assertEqual(
            {row[0] for row in cursor.execute(f"SELECT phone FROM stock WHERE {nonspam_where}").fetchall()},
            {"clean-india", "clean-brazil"},
        )
        self.assertEqual(
            {row[0] for row in cursor.execute(f"SELECT phone FROM stock WHERE {spam_where}").fetchall()},
            {"spam-india", "spam-brazil"},
        )
        self.assertEqual(
            {row[0] for row in cursor.execute(f"SELECT phone FROM stock WHERE {nonspam_where} AND country_name=? AND account_year=?", ("India", 2026)).fetchall()},
            {"clean-india"},
        )
        self.assertEqual(
            {row[0] for row in cursor.execute(f"SELECT phone FROM stock WHERE {spam_where} AND country_name=? AND account_year=?", ("Brazil", 2025)).fetchall()},
            {"spam-brazil"},
        )

    def test_settings_and_lzt_settings_persist(self):
        self.repository.set_setting("bot_mode", "hybrid")
        self.repository.set_setting("lzt_api_key", "stored-key")
        restarted = MongoRepository(client=self.client, database_name="runtime_test")
        self.assertEqual(restarted.get_setting("bot_mode"), "hybrid")
        self.assertEqual(restarted.get_setting("lzt_api_key"), "stored-key")


if __name__ == "__main__":
    unittest.main()
