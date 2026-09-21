import asyncio
import os
import sqlite3
import unittest
from unittest.mock import patch

os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "test-api-hash")

from plugins import admin_actions
from utils.stock_categories import category_value
from utils.stock_filters import stock_filter_clause


class StockCategoryTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute(
            """
            CREATE TABLE stock (
                phone TEXT PRIMARY KEY,
                session_file TEXT,
                country_name TEXT,
                country_icon TEXT,
                account_year INTEGER,
                category TEXT,
                price INTEGER,
                available INTEGER,
                twofa TEXT
            )
            """
        )

    def tearDown(self):
        self.connection.close()

    def add_account(self, phone, selection):
        category = category_value(selection)
        self.connection.execute(
            "INSERT INTO stock VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (phone, "session", "India", "", 2026, category, 100, 1, "None"),
        )
        self.connection.commit()

    def matching_phones(self, mode):
        where, params = stock_filter_clause(mode)
        return {
            row[0]
            for row in self.connection.execute(
                f"SELECT phone FROM stock WHERE {where}", params
            )
        }

    def test_explicit_nonspam_selection_stores_good(self):
        self.add_account("nonspam", "nonspam")
        self.assertEqual(
            self.connection.execute("SELECT category FROM stock WHERE phone='nonspam'").fetchone()[0],
            "Good",
        )

    def test_explicit_spam_selection_stores_spam(self):
        self.add_account("spam", "spam")
        self.assertEqual(
            self.connection.execute("SELECT category FROM stock WHERE phone='spam'").fetchone()[0],
            "spam",
        )

    def test_missing_selection_cannot_insert(self):
        with self.assertRaises(ValueError):
            category_value(None)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM stock").fetchone()[0], 0)

    def test_buy_filters_separate_selected_categories(self):
        self.add_account("nonspam", "nonspam")
        self.add_account("spam", "spam")
        self.assertEqual(self.matching_phones("nonspam"), {"nonspam"})
        self.assertEqual(self.matching_phones("spam"), {"spam"})

    def test_bulk_finalization_uses_one_category_for_every_account(self):
        connection = sqlite3.connect(":memory:")
        connection.execute(
            """
            CREATE TABLE stock (
                phone TEXT PRIMARY KEY,
                session_file TEXT,
                country_name TEXT,
                country_icon TEXT,
                account_year INTEGER,
                category TEXT,
                price INTEGER,
                available INTEGER,
                twofa TEXT
            )
            """
        )
        connection.commit()

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

        with patch.object(admin_actions, "cur", connection.cursor()), patch.object(admin_actions, "db", type("DB", (), {"commit": connection.commit})()):
            asyncio.run(admin_actions.finalize_stock_category(fake_event, token, "nonspam"))

        rows = connection.execute("SELECT phone, category FROM stock ORDER BY phone").fetchall()
        self.assertEqual(rows, [("998", "Good"), ("999", "Good")])

        admin_actions.pending_stock_categories[(fake_event.chat_id, fake_event.sender_id, "bulk-token-2")] = {
            "kind": "batch",
            "groups": [
                ("India", 2025, [{"phone": "997", "path": "/tmp/acc3"}, {"phone": "996", "path": "/tmp/acc4"}], "🇮🇳", 80, "None"),
            ],
            "zip_path": "/tmp/stock-batch-2.zip",
            "extracted_dir": "/tmp/stock-batch-2",
        }

        with patch.object(admin_actions, "cur", connection.cursor()), patch.object(admin_actions, "db", type("DB", (), {"commit": connection.commit})()):
            asyncio.run(admin_actions.finalize_stock_category(fake_event, "bulk-token-2", "spam"))

        rows = connection.execute("SELECT phone, category FROM stock WHERE phone IN ('997', '996') ORDER BY phone").fetchall()
        self.assertEqual(rows, [("996", "spam"), ("997", "spam")])
        connection.close()


if __name__ == "__main__":
    unittest.main()
