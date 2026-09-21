import sqlite3
import unittest

from utils.stock_filters import stock_filter_clause


class StockFilterTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute(
            """
            CREATE TABLE stock (
                phone TEXT PRIMARY KEY,
                country_name TEXT,
                account_year INTEGER,
                category TEXT,
                available INTEGER,
                twofa TEXT,
                price INTEGER
            )
            """
        )
        self.connection.executemany(
            "INSERT INTO stock VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("a", "India", 2026, "Good", 1, "None", 100),
                ("b", "India", 2025, "spam", 1, "None", 80),
                ("c", "India", 2026, "Good", 1, "real-password", 100),
                ("d", "India", 2024, "Good", 0, "None", 100),
            ],
        )

    def tearDown(self):
        self.connection.close()

    def phones(self, mode, year=None):
        where, params = stock_filter_clause(mode, year=year, country="India")
        return {
            row[0]
            for row in self.connection.execute(
                f"SELECT phone FROM stock WHERE {where}", params
            )
        }

    def countries(self, mode, year=None):
        where, params = stock_filter_clause(mode, year=year)
        return self.connection.execute(
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
