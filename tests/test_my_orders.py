import unittest
from datetime import datetime, timezone

import mongomock

from mongo_cursor import MongoCursor
from mongo_repository import MongoRepository


class MyOrdersTests(unittest.TestCase):
    def setUp(self):
        self.client = mongomock.MongoClient()
        self.repository = MongoRepository(client=self.client, database_name="my_orders_test")

    def add_order(self, order_id, user_id, phone, country="India", price=100, status="completed"):
        self.repository.db.orders.insert_one({
            "_id": order_id,
            "id": order_id,
            "user_id": user_id,
            "country": country,
            "year": 2026,
            "price": price,
            "phone": phone,
            "otp": "1234",
            "status": status,
            "date": datetime(2026, 9, order_id, tzinfo=timezone.utc),
        })

    def test_users_only_see_their_own_orders(self):
        self.add_order(1, 101, "a1")
        self.add_order(2, 202, "b1")

        self.assertEqual([order["phone"] for order in self.repository.get_orders_for_user(101)], ["a1"])
        self.assertEqual([order["phone"] for order in self.repository.get_orders_for_user(202)], ["b1"])

    def test_no_orders_returns_empty_list(self):
        self.assertEqual(self.repository.get_orders_for_user(303), [])

    def test_multiple_orders_keep_order_data_and_mongo_datetime(self):
        self.add_order(1, 101, "a1", price=100, status="completed")
        self.add_order(2, 101, "a2", country="Brazil", price=200, status="pending")

        orders = self.repository.get_orders_for_user(101)

        self.assertEqual([order["phone"] for order in orders], ["a2", "a1"])
        self.assertEqual(orders[0]["country"], "Brazil")
        self.assertEqual(orders[0]["price"], 200)
        self.assertEqual(orders[0]["status"], "pending")
        self.assertEqual(orders[0]["date"].strftime("%Y-%m-%d"), "2026-09-02")

    def test_purchase_insert_stores_integer_user_id_and_survives_restart(self):
        cursor = MongoCursor(self.repository)
        cursor.execute(
            "INSERT INTO orders (user_id, country, year, price, phone, otp) VALUES (?,?,?,?,?,?)",
            (101, "India", 2026, 250, "a1", "1234"),
        )

        stored = self.repository.db.orders.find_one({"phone": "a1"})
        self.assertEqual(stored["user_id"], 101)
        self.assertIsInstance(stored["date"], datetime)

        restarted = MongoRepository(client=self.client, database_name="my_orders_test")
        self.assertEqual([order["phone"] for order in restarted.get_orders_for_user("101")], ["a1"])


if __name__ == "__main__":
    unittest.main()
