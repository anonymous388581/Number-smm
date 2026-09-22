import concurrent.futures
import unittest
from types import SimpleNamespace

import mongomock

from mongo_repository import MongoRepository
from mongo_cursor import MongoCursor
from utils.stock_filters import claim_stock_account


class StockClaimTests(unittest.TestCase):
    def setUp(self):
        self.repository = MongoRepository(client=mongomock.MongoClient(), database_name="claims_test")
        self.database = SimpleNamespace(repository=self.repository, execute=MongoCursor(self.repository).execute)

    def add_account(self, phone, country="India", year=2026, category="Good", available=1):
        self.repository.db.stock.insert_one({
            "_id": phone, "phone": phone, "session_file": "session", "country_name": country,
            "account_year": year, "category": category, "available": available, "twofa": "None",
        })

    def claim(self, mode="bulk", country="India", year=None):
        return claim_stock_account(self.database, mode, country=country, year=year)

    def test_one_available_account_is_claimed(self):
        self.add_account("one")

        account = self.claim()

        self.assertEqual(account["phone"], "one")
        self.assertEqual(self.repository.db.stock.find_one({"phone": "one"})["available"], 0)

    def test_two_buyers_cannot_claim_one_account(self):
        self.add_account("one")

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            accounts = list(executor.map(lambda _: self.claim(), range(2)))

        self.assertEqual([account["phone"] for account in accounts if account], ["one"])

    def test_two_buyers_claim_different_accounts(self):
        self.add_account("one")
        self.add_account("two")

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            accounts = list(executor.map(lambda _: self.claim(), range(2)))

        self.assertEqual({account["phone"] for account in accounts}, {"one", "two"})

    def test_country_spam_and_year_filters_are_preserved(self):
        self.add_account("spam", category="spam")
        self.add_account("fresh", year=2026)
        self.add_account("other-country", country="Brazil")

        self.assertEqual(self.claim("nonspam")["phone"], "fresh")
        self.assertIsNone(self.claim("nonspam"))
        self.assertIsNone(self.claim("bulk", year=2025))
        self.assertEqual(self.claim("bulk", country="Brazil")["phone"], "other-country")
        self.assertEqual(self.claim("spam")["phone"], "spam")

    def test_unavailable_account_cannot_be_claimed(self):
        self.add_account("sold", available=0)

        self.assertIsNone(self.claim())

    def test_claim_remains_unavailable_after_completion(self):
        self.add_account("one")

        self.assertIsNotNone(self.claim())
        self.assertIsNone(self.claim())


if __name__ == "__main__":
    unittest.main()
