import asyncio
import os
import sqlite3
import unittest
from unittest.mock import patch

os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "test-api-hash")

from database import get_more_account_filters_enabled, set_more_account_filters_enabled
from plugins import buy


class FakeEvent:
    def __init__(self):
        self.message = None
        self.buttons = None

    async def respond(self, message, buttons=None):
        self.message = message
        self.buttons = buttons


class MoreAccountFiltersTests(unittest.TestCase):
    def test_setting_defaults_on_and_persists_off_then_on(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")

        class Cursor:
            def execute(self, query, params=()):
                return connection.execute(query, params)

        class Database:
            def commit(self):
                connection.commit()

        with patch("database.cur", Cursor()), patch("database.db", Database()):
            self.assertTrue(get_more_account_filters_enabled())
            set_more_account_filters_enabled(False)
            self.assertFalse(get_more_account_filters_enabled())
            set_more_account_filters_enabled(True)
            self.assertTrue(get_more_account_filters_enabled())
        connection.close()

    def menu(self, enabled):
        event = FakeEvent()
        with patch.object(buy, "get_more_account_filters_enabled", return_value=enabled):
            asyncio.run(buy.show_buy_menu(event))
        callbacks = [
            button.data.decode() if isinstance(button.data, bytes) else button.data
            for row in event.buttons
            for button in row
        ]
        return event.message, callbacks

    def test_more_filters_button_is_present_when_on(self):
        message, callbacks = self.menu(True)
        self.assertIn("pg_filters|1", callbacks)
        self.assertIn("𝐌ᴏʀᴇ 𝐅ɪʟᴛᴇʀs", message)

    def test_more_filters_button_is_absent_when_off(self):
        message, callbacks = self.menu(False)
        self.assertNotIn("pg_filters|1", callbacks)
        self.assertNotIn("𝐌ᴏʀᴇ 𝐅ɪʟᴛᴇʀs", message)
        self.assertIn("pg_c|bulk|1", callbacks)


if __name__ == "__main__":
    unittest.main()
