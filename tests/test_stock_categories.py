import sqlite3
import unittest

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


if __name__ == "__main__":
    unittest.main()
