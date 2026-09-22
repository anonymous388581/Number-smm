"""MongoDB persistence primitives used by the bot runtime."""

import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone

from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError


COLLECTIONS = (
    "users", "settings", "stock", "auto_prices", "spamfree_prices", "deposits",
    "upi_orders", "orders", "custom_payments", "admins", "custom_countries",
    "smm_orders", "source_codes", "panels", "redeemed_transactions",
)


class MongoRepository:
    """Small repository for Mongo-native operations used by the bot runtime."""

    def __init__(self, uri=None, database_name=None, client=None):
        self.uri = uri or os.getenv("MONGODB_URI") or os.getenv("MONGO_URI")
        self.database_name = database_name or os.getenv("MONGODB_DB_NAME", "numbott")
        if client is None:
            if not self.uri:
                raise RuntimeError("MONGODB_URI is required")
            if self.uri.startswith("mongomock://"):
                try:
                    import mongomock
                except ImportError as exc:
                    raise RuntimeError("mongomock is required for mongomock:// test URIs") from exc
                client = mongomock.MongoClient()
            else:
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
        self.db.deposits.create_index([("source_key", ASCENDING)], unique=True, sparse=True)

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

    def upsert_stock_account(self, account):
        """Persist one manual account directly in the Mongo stock collection."""
        document = dict(account)
        document["_id"] = document["phone"]
        document.setdefault("added_date", self._now())
        self.db.stock.replace_one({"_id": document["_id"]}, document, upsert=True)
        return document

    def claim_stock_account(self, mode="bulk", country=None, year=None):
        query = {"available": 1}
        if country is not None:
            query["country_name"] = country
        if year is not None:
            query["account_year"] = int(year)
        if mode == "aged":
            query["account_year"] = {"$ne": None}
        elif mode == "nonspam":
            query["category"] = {"$exists": True, "$not": re.compile("^spam$", re.IGNORECASE)}
        elif mode == "spam":
            query["category"] = re.compile("^spam$", re.IGNORECASE)
        elif mode == "no_2fa":
            query["$or"] = [{"twofa": None}, {"twofa": ""}, {"twofa": re.compile("^none$", re.IGNORECASE)}]
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
        try:
            with self.transaction() as session:
                return self._approve_deposit(deposit_id, amount, session=session)
        except NotImplementedError as exc:
            if "sessions" not in str(exc).lower():
                raise
            return self._approve_deposit_without_session(deposit_id, amount)

    def _approve_deposit(self, deposit_id, amount, session=None):
        find_kwargs = {"session": session} if session is not None else {}
        deposit_query = {"_id": int(deposit_id), "status": "pending"}
        deposit = self.db.deposits.find_one(deposit_query, **find_kwargs)
        if deposit is None:
            existing = self.db.deposits.find_one({"_id": int(deposit_id)}, **find_kwargs)
            if existing:
                return {"approved": False, "already_processed": True,
                        "user_id": existing.get("user_id"), "amount": existing.get("amount")}
            raise ValueError(f"deposit {deposit_id} does not exist")

        user_id = deposit.get("user_id")
        if not isinstance(user_id, int) or user_id <= 0:
            raise ValueError(f"invalid user ID {user_id!r}")
        amount = int(amount)
        if amount <= 0:
            raise ValueError(f"invalid deposit amount {amount!r}")
        user = self.db.users.find_one_and_update(
            {"_id": user_id}, {"$inc": {"balance": amount, "total_deposited": amount}},
            session=session, return_document=ReturnDocument.AFTER,
        )
        if user is None:
            raise ValueError(f"user {user_id} does not exist")
        status_result = self.db.deposits.update_one(
            deposit_query, {"$set": {"status": "approved", "amount": amount}}, **find_kwargs,
        )
        if status_result.matched_count != 1:
            raise RuntimeError(f"deposit {deposit_id} status update was not applied")
        return {"approved": True, "already_processed": False, "user_id": user_id,
                "previous_balance": user["balance"] - amount,
                "balance": user["balance"], "amount": amount, "status": "approved"}

    def _approve_deposit_without_session(self, deposit_id, amount):
        """Support clients without sessions while keeping the production path transactional."""
        deposit = self.db.deposits.find_one_and_update(
            {"_id": int(deposit_id), "status": "pending"},
            {"$set": {"status": "processing"}},
            return_document=ReturnDocument.BEFORE,
        )
        if deposit is None:
            existing = self.db.deposits.find_one({"_id": int(deposit_id)})
            if existing:
                return {"approved": False, "already_processed": True,
                        "user_id": existing.get("user_id"), "amount": existing.get("amount")}
            raise ValueError(f"deposit {deposit_id} does not exist")
        user_id = deposit.get("user_id")
        amount = int(amount)
        try:
            if not isinstance(user_id, int) or user_id <= 0:
                raise ValueError(f"invalid user ID {user_id!r}")
            if amount <= 0:
                raise ValueError(f"invalid deposit amount {amount!r}")
            user = self.db.users.find_one_and_update(
                {"_id": user_id}, {"$inc": {"balance": amount, "total_deposited": amount}},
                return_document=ReturnDocument.AFTER,
            )
            if user is None:
                raise ValueError(f"user {user_id} does not exist")
            status_result = self.db.deposits.update_one(
                {"_id": int(deposit_id), "status": "processing"},
                {"$set": {"status": "approved", "amount": amount}},
            )
            if status_result.matched_count != 1:
                raise RuntimeError(f"deposit {deposit_id} status update was not applied")
            return {"approved": True, "already_processed": False, "user_id": user_id,
                    "previous_balance": user["balance"] - amount,
                    "balance": user["balance"], "amount": amount, "status": "approved"}
        except Exception:
            self.db.deposits.update_one(
                {"_id": int(deposit_id), "status": "processing"},
                {"$set": {"status": "pending"}},
            )
            raise

    def get_deposit(self, deposit_id):
        """Find a deposit by its integer callback ID."""
        try:
            normalized_id = int(deposit_id)
        except (TypeError, ValueError):
            return None
        return self.db.deposits.find_one({"_id": normalized_id})

    def reject_deposit(self, deposit_id):
        with self.transaction() as session:
            deposit = self.db.deposits.find_one_and_update(
                {"_id": int(deposit_id), "status": "pending"},
                {"$set": {"status": "rejected"}},
                session=session, return_document=ReturnDocument.BEFORE,
            )
            if deposit is None:
                existing = self.db.deposits.find_one({"_id": int(deposit_id)}, session=session)
                if existing:
                    return {"rejected": False, "already_processed": True,
                            "user_id": existing.get("user_id"), "amount": existing.get("amount")}
                raise ValueError(f"deposit {deposit_id} does not exist")
            return {"rejected": True, "already_processed": False,
                    "user_id": deposit.get("user_id"), "amount": deposit.get("amount"),
                    "status": "rejected"}

    def create_manual_deposit(self, user_id, amount, method, screenshot_file_id,
                              source_chat_id, source_message_id):
        """Create one pending manual deposit, deduplicated by Telegram update."""
        source_key = f"{int(source_chat_id)}:{int(source_message_id)}"
        existing = self.db.deposits.find_one({"source_key": source_key})
        if existing is not None:
            return existing, False

        document = {
            "_id": self.next_id("deposits"),
            "id": None,
            "user_id": int(user_id),
            "amount": int(amount),
            "method_name": method,
            "payment_method": method,
            "screenshot_file_id": screenshot_file_id,
            "source_chat_id": int(source_chat_id),
            "source_message_id": int(source_message_id),
            "source_key": source_key,
            "status": "pending",
            "created_at": self._now(),
            "date": self._now(),
        }
        document["id"] = document["_id"]
        try:
            self.db.deposits.insert_one(document)
        except DuplicateKeyError:
            return self.db.deposits.find_one({"source_key": source_key}), False
        return document, True

    def set_setting(self, key, value):
        self.db.settings.update_one({"_id": key}, {"$set": {"key": key, "value": value}}, upsert=True)

    def get_setting(self, key, default=None):
        row = self.db.settings.find_one({"_id": key})
        return row.get("value", default) if row else default

    def next_id(self, collection):
        result = self.db["_sequences"].find_one_and_update(
            {"_id": collection}, {"$inc": {"value": 1}},
            upsert=True, return_document=ReturnDocument.AFTER,
        )
        return result["value"]