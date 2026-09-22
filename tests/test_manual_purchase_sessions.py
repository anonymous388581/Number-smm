import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import mongomock

from mongo_repository import MongoRepository
from utils.telegram_sessions import materialize_session, persist_session


class ManualPurchaseSessionTests(unittest.TestCase):
    def setUp(self):
        self.repository = MongoRepository(
            client=mongomock.MongoClient(), database_name="manual_purchase_sessions_test"
        )
        self.repository.ensure_indexes()
        self.source_dir = tempfile.mkdtemp()
        self.runtime_dir = tempfile.mkdtemp()
        self.source = os.path.join(self.source_dir, "manual.session")
        with open(self.source, "wb") as session_file:
            session_file.write(b"manual-session-binary")

    def tearDown(self):
        shutil.rmtree(self.source_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)

    def add_account(self, user_phone="919999"):
        session_id = self.repository.session_id_for_account(user_phone)
        persist_session(self.repository, session_id, self.source, account_key=user_phone)
        self.repository.db.stock.insert_one({
            "_id": user_phone,
            "phone": user_phone,
            "session_file": "sessions/" + user_phone + ".session",
            "session_id": session_id,
            "country_name": "India",
            "country_icon": "",
            "account_year": 2026,
            "category": "Good",
            "price": 100,
            "available": 1,
            "twofa": "None",
            "added_date": datetime.now(timezone.utc),
        })
        return session_id

    def test_purchase_restores_the_claimed_account_session_from_mongodb(self):
        session_id = self.add_account()
        stock = self.repository.db.stock.find_one({"_id": "919999"})
        stored_session = self.repository.db.telegram_sessions.find_one({"_id": session_id})
        self.assertEqual(stock["session_id"], stored_session["_id"])
        self.assertEqual(stored_session["account_key"], stock["phone"])
        self.assertEqual(stored_session["files"]["session"], b"manual-session-binary")

        claimed = self.repository.claim_stock_account("bulk", country="India", year=2026)
        os.remove(self.source)
        with patch("utils.telegram_sessions.RUNTIME_DIR", self.runtime_dir):
            restored_path = materialize_session(
                self.repository, claimed["session_id"], account_key=claimed["phone"]
            )

        with open(restored_path, "rb") as session_file:
            self.assertEqual(session_file.read(), b"manual-session-binary")
        self.assertEqual(claimed["session_id"], session_id)
        self.assertEqual(self.repository.db.stock.find_one({"_id": "919999"})["available"], 0)
        self.assertIsNotNone(self.repository.db.telegram_sessions.find_one({"_id": session_id}))

    def test_missing_session_releases_claimed_stock_without_deleting_mapping(self):
        session_id = self.add_account()
        self.repository.db.telegram_sessions.delete_one({"_id": session_id})

        claimed = self.repository.claim_stock_account("bulk", country="India", year=2026)
        with patch("utils.telegram_sessions.RUNTIME_DIR", self.runtime_dir):
            with self.assertRaises(FileNotFoundError):
                materialize_session(self.repository, claimed["session_id"], account_key=claimed["phone"])

        self.assertTrue(self.repository.release_stock_account(claimed))
        stock = self.repository.db.stock.find_one({"_id": "919999"})
        self.assertEqual(stock["available"], 1)
        self.assertEqual(stock["session_id"], session_id)
        self.assertIsNone(self.repository.db.telegram_sessions.find_one({"_id": session_id}))


if __name__ == "__main__":
    unittest.main()