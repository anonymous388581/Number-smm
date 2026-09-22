import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import mongomock

from mongo_repository import MongoRepository
from utils.telegram_sessions import materialize_session, persist_session, restore_all_sessions, session_id_for_account


class TelegramSessionPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.repository = MongoRepository(client=mongomock.MongoClient(), database_name="telegram_sessions_test")
        self.repository.ensure_indexes()
        self.runtime_dir = tempfile.mkdtemp()
        self.source_dir = tempfile.mkdtemp()
        self.source = os.path.join(self.source_dir, "account.session")
        with open(self.source, "wb") as session_file:
            session_file.write(b"session-binary")

    def tearDown(self):
        shutil.rmtree(self.runtime_dir, ignore_errors=True)
        shutil.rmtree(self.source_dir, ignore_errors=True)

    def test_persist_remove_and_restore_from_mongodb(self):
        session_id = session_id_for_account("+919999")
        with patch("utils.telegram_sessions.RUNTIME_DIR", self.runtime_dir):
            persist_session(self.repository, session_id, self.source, account_key="+919999")
            runtime_path = materialize_session(self.repository, session_id, account_key="+919999")
            os.remove(runtime_path)
            restored = materialize_session(self.repository, session_id, account_key="+919999")

        with open(restored, "rb") as session_file:
            self.assertEqual(session_file.read(), b"session-binary")
        self.assertEqual(self.repository.db.telegram_sessions.count_documents({}), 1)

    def test_first_encounter_imports_legacy_file(self):
        session_id = session_id_for_account("legacy")
        with patch("utils.telegram_sessions.RUNTIME_DIR", self.runtime_dir):
            restored = materialize_session(self.repository, session_id, self.source, account_key="legacy")
        self.assertTrue(os.path.exists(restored))
        self.assertIsNotNone(self.repository.get_telegram_session(session_id))

    def test_multiple_accounts_and_duplicate_upsert_are_isolated(self):
        first = session_id_for_account("one")
        second = session_id_for_account("two")
        with patch("utils.telegram_sessions.RUNTIME_DIR", self.runtime_dir):
            persist_session(self.repository, first, self.source, account_key="one")
            with open(self.source, "wb") as session_file:
                session_file.write(b"different-session")
            persist_session(self.repository, second, self.source, account_key="two")
            persist_session(self.repository, first, self.source, account_key="one")
        self.assertEqual(self.repository.db.telegram_sessions.count_documents({}), 2)
        self.assertEqual(self.repository.get_telegram_session(first)["account_key"], "one")
        self.assertEqual(self.repository.get_telegram_session(second)["account_key"], "two")

    def test_missing_and_corrupt_records_fail_without_exposing_data(self):
        with patch("utils.telegram_sessions.RUNTIME_DIR", self.runtime_dir):
            with self.assertRaises(FileNotFoundError):
                materialize_session(self.repository, "missing")
            self.repository.db.telegram_sessions.insert_one({"_id": "corrupt", "files": {}})
            with self.assertRaises(ValueError):
                materialize_session(self.repository, "corrupt")

    def test_startup_restores_every_persisted_session(self):
        with patch("utils.telegram_sessions.RUNTIME_DIR", self.runtime_dir):
            persist_session(self.repository, "one", self.source, account_key="one")
            persist_session(self.repository, "two", self.source, account_key="two")
            self.assertEqual(restore_all_sessions(self.repository), 2)


if __name__ == "__main__":
    unittest.main()