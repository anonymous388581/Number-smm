import asyncio
import os
import unittest
from unittest.mock import patch

import mongomock

os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "test-api-hash")
os.environ.setdefault("MONGODB_URI", "mongomock://localhost")

from mongo_cursor import MongoCursor
from mongo_repository import MongoRepository
from plugins import admin_actions
from utils.stock_categories import category_value
from utils.stock_filters import stock_filter_clause


class StockCategoryTests(unittest.TestCase):
    def setUp(self):
        self.repository = MongoRepository(client=mongomock.MongoClient(), database_name="categories_test")
        self.cursor = MongoCursor(self.repository)

    def add_account(self, phone, selection):
        category = category_value(selection)
        self.repository.db.stock.insert_one({
            "_id": phone, "phone": phone, "session_file": "session", "country_name": "India",
            "country_icon": "", "account_year": 2026, "category": category, "price": 100,
            "available": 1, "twofa": "None",
        })

    def matching_phones(self, mode):
        where, params = stock_filter_clause(mode)
        return {
            row[0]
            for row in self.cursor.execute(f"SELECT phone FROM stock WHERE {where}", params).fetchall()
        }

    def test_explicit_nonspam_selection_stores_good(self):
        self.add_account("nonspam", "nonspam")
        self.assertEqual(self.repository.db.stock.find_one({"phone": "nonspam"})["category"], "Good")

    def test_explicit_spam_selection_stores_spam(self):
        self.add_account("spam", "spam")
        self.assertEqual(self.repository.db.stock.find_one({"phone": "spam"})["category"], "spam")

    def test_missing_selection_cannot_insert(self):
        with self.assertRaises(ValueError):
            category_value(None)
        self.assertEqual(self.repository.db.stock.count_documents({}), 0)

    def test_buy_filters_separate_selected_categories(self):
        self.add_account("nonspam", "nonspam")
        self.add_account("spam", "spam")
        self.assertEqual(self.matching_phones("nonspam"), {"nonspam"})
        self.assertEqual(self.matching_phones("spam"), {"spam"})

    def test_bulk_finalization_uses_one_category_for_every_account(self):
        class FakeEvent:
            def __init__(self):
                self.chat_id = 1
                self.sender_id = 2
                self.message = None

            async def edit(self, msg, buttons=None):
                self.message = msg

        fake_event = FakeEvent()
        token = "bulk-token"
        admin_actions.pending_stock_categories[(fake_event.chat_id, fake_event.sender_id, token)] = {
            "kind": "batch",
            "groups": [
                ("India", 2026, [{"phone": "999", "path": "/tmp/acc1"}, {"phone": "998", "path": "/tmp/acc2"}], "🇮🇳", 100, "None"),
            ],
            "zip_path": "/tmp/stock-batch.zip",
            "extracted_dir": "/tmp/stock-batch",
        }

        database = type("DB", (), {"commit": lambda self: None})()
        with patch.object(admin_actions, "cur", self.cursor), patch.object(admin_actions, "db", database):
            asyncio.run(admin_actions.finalize_stock_category(fake_event, token, "nonspam"))

        rows = list(self.repository.db.stock.find(
            {"phone": {"$in": ["998", "999"]}}, {"_id": 0, "phone": 1, "category": 1}
        ).sort("phone", 1))
        self.assertEqual([(row["phone"], row["category"]) for row in rows], [("998", "Good"), ("999", "Good")])

        admin_actions.pending_stock_categories[(fake_event.chat_id, fake_event.sender_id, "bulk-token-2")] = {
            "kind": "batch",
            "groups": [
                ("India", 2025, [{"phone": "997", "path": "/tmp/acc3"}, {"phone": "996", "path": "/tmp/acc4"}], "🇮🇳", 80, "None"),
            ],
            "zip_path": "/tmp/stock-batch-2.zip",
            "extracted_dir": "/tmp/stock-batch-2",
        }

        with patch.object(admin_actions, "cur", self.cursor), patch.object(admin_actions, "db", database):
            asyncio.run(admin_actions.finalize_stock_category(fake_event, "bulk-token-2", "spam"))

        rows = list(self.repository.db.stock.find(
            {"phone": {"$in": ["996", "997"]}}, {"_id": 0, "phone": 1, "category": 1}
        ).sort("phone", 1))
        self.assertEqual([(row["phone"], row["category"]) for row in rows], [("996", "spam"), ("997", "spam")])


if __name__ == "__main__":
    unittest.main()
