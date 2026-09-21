import sqlite3
import tempfile
import unittest

from migrate_sqlite_to_mongo import make_document


class MongoMigrationUnitTests(unittest.TestCase):
    def test_legacy_ids_are_preserved(self):
        document = make_document("orders", ["id", "user_id", "price"], [7, 42, 100])
        self.assertEqual(document["_id"], 7)
        self.assertEqual(document["user_id"], 42)

    def test_composite_price_id_is_stable(self):
        document = make_document("auto_prices", ["country", "year", "price"], ["India", "2026", 100])
        self.assertEqual(document["_id"], "India::2026")

    def test_migrator_opens_sqlite_read_only(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as database_file:
            connection = sqlite3.connect(database_file.name)
            connection.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
            connection.execute("INSERT INTO settings VALUES ('k', 'v')")
            connection.commit()
            connection.close()
            read_only = sqlite3.connect(f"file:{database_file.name}?mode=ro", uri=True)
            self.assertEqual(read_only.execute("SELECT value FROM settings").fetchone()[0], "v")
            with self.assertRaises(sqlite3.OperationalError):
                read_only.execute("INSERT INTO settings VALUES ('x', 'y')")
            read_only.close()


if __name__ == "__main__":
    unittest.main()