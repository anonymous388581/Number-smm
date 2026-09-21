"""MongoDB persistence primitives for migration and the future runtime cutover."""

import os
from contextlib import contextmanager
from datetime import datetime, timezone

from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument


COLLECTIONS = (
    "users", "settings", "stock", "auto_prices", "spamfree_prices", "deposits",
    "upi_orders", "orders", "custom_payments", "admins", "custom_countries",
    "smm_orders", "source_codes", "panels", "redeemed_transactions",
)


class MongoRepository:
    """Small repository for Mongo-native operations used by migration and cutover."""

    def __init__(self, uri=None, database_name=None, client=None):
        self.uri = uri or os.getenv("MONGODB_URI") or os.getenv("MONGO_URI")
        self.database_name = database_name or os.getenv("MONGODB_DB_NAME", "numbott")
        if client is None:
            if not self.uri:
                raise RuntimeError("MONGODB_URI is required")
            client = MongoClient(self.uri, serverSelectionTimeoutMS=10000)
        self.client = client
        self.db = client[self.database_name]

    def ping(self):
        return self.client.admin.command("ping")

    def ensure_indexes(self):
        indexes = {
            "users": [("referred_by", ASCENDING)],
            "stock": [("available", ASCENDING), ("country_name", ASCENDING),
                      ("account_year", DESCENDING), ("category", ASCENDING),
                      ("twofa", ASCENDING)],
            "deposits": [("user_id", ASCENDING), ("status", ASCENDING), ("utr", ASCENDING)],
            "orders": [("user_id", ASCENDING), ("date", DESCENDING)],
            "upi_orders": [("user_id", ASCENDING), ("status", ASCENDING)],
            "smm_orders": [("user_id", ASCENDING), ("status", ASCENDING)],
            "redeemed_transactions": [("utr", ASCENDING), ("txn_id", ASCENDING)],
            "auto_prices": [("country", ASCENDING), ("year", ASCENDING)],
            "spamfree_prices": [("country", ASCENDING)],
            "custom_countries": [("name", ASCENDING)],
            "custom_payments": [("name", ASCENDING)],
        }
        for collection, fields in indexes.items():
            for field, direction in fields:
                self.db[collection].create_index([(field, direction)])

    @staticmethod
    def _now():
        return datetime.now(timezone.utc)

    def ensure_user(self, user_id):
        self.db.users.update_one(
            {"_id": int(user_id)},
            {"$setOnInsert": {"user_id": int(user_id), "balance": 0,
                              "total_deposited": 0, "banned": 0, "discount": 0,
                              "terms_accepted": 0, "joined_date": self._now()}},
            upsert=True,
        )

    def get_user(self, user_id):
        return self.db.users.find_one({"_id": int(user_id)})

    def update_balance(self, user_id, amount):
        result = self.db.users.find_one_and_update(
            {"_id": int(user_id)}, {"$inc": {"balance": amount}},
            return_document=ReturnDocument.AFTER,
        )
        if result is None:
            raise ValueError(f"user {user_id} does not exist")
        return result

    def debit_balance(self, user_id, amount):
        return self.db.users.find_one_and_update(
            {"_id": int(user_id), "balance": {"$gte": amount}},
            {"$inc": {"balance": -amount}},
            return_document=ReturnDocument.AFTER,
        )

    def claim_stock_account(self, mode="bulk", country=None, year=None):
        query = {"available": 1}
        if country is not None:
            query["country_name"] = country
        if year is not None:
            query["account_year"] = int(year)
        if mode == "aged":
            query["account_year"] = {"$ne": None}
        elif mode == "nonspam":
            query["category"] = {"$exists": True, "$not": {"$regex": "^spam$", "$options": "i"}}
        elif mode == "spam":
            query["category"] = {"$regex": "^spam$", "$options": "i"}
        elif mode == "no_2fa":
            query["$or"] = [{"twofa": None}, {"twofa": ""}, {"twofa": {"$regex": "^none$", "$options": "i"}}]
        elif mode == "with_2fa":
            query["twofa"] = {"$nin": [None, "", "None", "none"]}
        elif mode != "bulk":
            return None
        return self.db.stock.find_one_and_update(
            query, {"$set": {"available": 0}},
            sort=[("added_date", ASCENDING), ("_id", ASCENDING)],
            return_document=ReturnDocument.BEFORE,
        )

    @contextmanager
    def transaction(self):
        """Require a deployment that supports transactions for money operations."""
        with self.client.start_session() as session:
            with session.start_transaction():
                yield session

    def approve_deposit(self, deposit_id, amount):
        with self.transaction() as session:
            deposit = self.db.deposits.find_one_and_update(
                {"_id": int(deposit_id), "status": "pending"},
                {"$set": {"status": "approved", "amount": amount}},
                session=session, return_document=ReturnDocument.BEFORE,
            )
            if deposit is None:
                existing = self.db.deposits.find_one({"_id": int(deposit_id)}, session=session)
                if existing:
                    return {"approved": False, "already_processed": True,
                            "user_id": existing.get("user_id"), "amount": existing.get("amount")}
                raise ValueError(f"deposit {deposit_id} does not exist")
            user_id = deposit.get("user_id")
            if not isinstance(user_id, int) or user_id <= 0:
                raise ValueError(f"invalid user ID {user_id!r}")
            user = self.db.users.find_one_and_update(
                {"_id": user_id}, {"$inc": {"balance": amount, "total_deposited": amount}},
                session=session, return_document=ReturnDocument.AFTER,
            )
            if user is None:
                raise ValueError(f"user {user_id} does not exist")
            return {"approved": True, "already_processed": False, "user_id": user_id,
                    "previous_balance": user["balance"] - amount,
                    "balance": user["balance"], "amount": amount, "status": "approved"}

    def set_setting(self, key, value):
        self.db.settings.update_one({"_id": key}, {"$set": {"key": key, "value": value}}, upsert=True)

    def get_setting(self, key, default=None):
        row = self.db.settings.find_one({"_id": key})
        return row.get("value", default) if row else default