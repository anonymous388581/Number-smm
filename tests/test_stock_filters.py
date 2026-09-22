import unittest

import mongomock

from mongo_cursor import MongoCursor
from mongo_repository import MongoRepository
from utils.stock_filters import stock_filter_clause


class StockFilterTests(unittest.TestCase):
    def setUp(self):
        self.repository = MongoRepository(client=mongomock.MongoClient(), database_name="filters_test")
        self.repository.db.stock.insert_many([
            {"_id": "a", "phone": "a", "country_name": "India", "account_year": 2026,
             "category": "Good", "available": 1, "twofa": "None", "price": 100},
            {"_id": "b", "phone": "b", "country_name": "India", "account_year": 2025,
             "category": "spam", "available": 1, "twofa": "None", "price": 80},
            {"_id": "c", "phone": "c", "country_name": "India", "account_year": 2026,
             "category": "Good", "available": 1, "twofa": "real-password", "price": 100},
            {"_id": "d", "phone": "d", "country_name": "India", "account_year": 2024,
             "category": "Good", "available": 0, "twofa": "None", "price": 100},
        ])
        self.cursor = MongoCursor(self.repository)

    def phones(self, mode, year=None):
        where, params = stock_filter_clause(mode, year=year, country="India")
        return {
            row[0]
            for row in self.cursor.execute(f"SELECT phone FROM stock WHERE {where}", params).fetchall()
        }

    def countries(self, mode, year=None):
        where, params = stock_filter_clause(mode, year=year)
        return self.cursor.execute(
            f"SELECT country_name, COUNT(*) FROM stock WHERE {where} GROUP BY country_name",
            params,
        ).fetchall()

    def test_category_and_year_filters_are_exact(self):
        self.assertEqual(self.phones("nonspam"), {"a", "c"})
        self.assertEqual(self.phones("spam"), {"b"})
        self.assertEqual(self.phones("bulk"), {"a", "b", "c"})
        self.assertEqual(self.phones("aged"), {"a", "b", "c"})
        self.assertEqual(self.phones("bulk", 2026), {"a", "c"})
        self.assertEqual(self.phones("bulk", 2025), {"b"})
        self.assertEqual(self.phones("bulk", 2024), set())

    def test_twofa_filters_require_actual_metadata(self):
        self.assertEqual(self.phones("no_2fa"), {"a", "b"})
        self.assertEqual(self.phones("with_2fa"), {"c"})

    def test_country_counts_only_include_matching_stock(self):
        self.assertEqual(self.countries("nonspam", 2026), [("India", 2)])
        self.assertEqual(self.countries("spam", 2026), [])
        self.assertEqual(self.countries("spam", 2025), [("India", 1)])
        self.assertEqual(self.countries("bulk", 2024), [])

    def test_unsupported_metadata_filters_do_not_match_everything(self):
        for mode in ("stars", "premium", "no_email", "with_email", "dc5", "unknown"):
            self.assertEqual(self.phones(mode), set(), mode)


if __name__ == "__main__":
    unittest.main()
