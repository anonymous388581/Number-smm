import concurrent.futures
import os
import sqlite3
import tempfile
import unittest

from utils.stock_filters import claim_stock_account


class StockClaimTests(unittest.TestCase):
    def setUp(self):
        self.database_file = tempfile.NamedTemporaryFile(delete=False)
        self.database_file.close()
        connection = sqlite3.connect(self.database_file.name)
        connection.execute(
            """
            CREATE TABLE stock (
                phone TEXT PRIMARY KEY,
                session_file TEXT,
                country_name TEXT,
                account_year INTEGER,
                category TEXT,
                available INTEGER,
                twofa TEXT
            )
            """
        )
        connection.commit()
        connection.close()

    def tearDown(self):
        os.unlink(self.database_file.name)

    def add_account(self, phone, country="India", year=2026, category="Good", available=1):
        connection = sqlite3.connect(self.database_file.name)
        connection.execute(
            "INSERT INTO stock VALUES (?, ?, ?, ?, ?, ?, ?)",
            (phone, "session", country, year, category, available, "None"),
        )
        connection.commit()
        connection.close()

    def claim(self, mode="bulk", country="India", year=None):
        connection = sqlite3.connect(self.database_file.name, timeout=10)
        try:
            account = claim_stock_account(connection, mode, country=country, year=year)
            connection.commit()
            return account
        finally:
            connection.close()

    def test_one_available_account_is_claimed(self):
        self.add_account("one")

        account = self.claim()

        self.assertEqual(account[0], "one")
        connection = sqlite3.connect(self.database_file.name)
        self.assertEqual(connection.execute("SELECT available FROM stock").fetchone()[0], 0)
        connection.close()

    def test_two_buyers_cannot_claim_one_account(self):
        self.add_account("one")

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            accounts = list(executor.map(lambda _: self.claim(), range(2)))

        self.assertEqual([account for account in accounts if account], [("one", "session", "None")])

    def test_two_buyers_claim_different_accounts(self):
        self.add_account("one")
        self.add_account("two")

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            accounts = list(executor.map(lambda _: self.claim(), range(2)))

        self.assertEqual({account[0] for account in accounts}, {"one", "two"})

    def test_country_spam_and_year_filters_are_preserved(self):
        self.add_account("spam", category="spam")
        self.add_account("fresh", year=2026)
        self.add_account("other-country", country="Brazil")

        self.assertEqual(self.claim("nonspam")[0], "fresh")
        self.assertIsNone(self.claim("nonspam"))
        self.assertEqual(self.claim("bulk", year=2025), None)
        self.assertEqual(self.claim("bulk", country="Brazil")[0], "other-country")
        self.assertEqual(self.claim("spam")[0], "spam")

    def test_unavailable_account_cannot_be_claimed(self):
        self.add_account("sold", available=0)

        self.assertIsNone(self.claim())

    def test_rollback_releases_claim(self):
        self.add_account("one")
        connection = sqlite3.connect(self.database_file.name)
        try:
            self.assertIsNotNone(claim_stock_account(connection, "bulk", country="India"))
            connection.rollback()
        finally:
            connection.close()

        self.assertEqual(self.claim()[0], "one")


if __name__ == "__main__":
    unittest.main()