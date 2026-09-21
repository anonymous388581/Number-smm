import asyncio
import os
import sqlite3
import unittest
from unittest.mock import patch

os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "test-api-hash")
os.environ.setdefault("MONGODB_URI", "mongomock://localhost")

from database import get_more_account_filters_enabled, set_more_account_filters_enabled
from plugins import buy


class FakeEvent:
    def __init__(self):
        self.message = None
        self.buttons = None

    async def respond(self, message, buttons=None):
        self.message = message
        self.buttons = buttons

    async def edit(self, message, buttons=None):
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

    def menu(self, bot_mode, enabled):
        event = FakeEvent()
        with patch.object(buy, "get_bot_mode", return_value=bot_mode), patch.object(
            buy, "get_more_account_filters_enabled", return_value=enabled
        ):
            asyncio.run(buy.show_buy_menu(event))
        callbacks = [
            button.data.decode() if isinstance(button.data, bytes) else button.data
            for row in event.buttons
            for button in row
        ]
        return event.message, callbacks

    @staticmethod
    def callbacks(buttons):
        if buttons and not isinstance(buttons[0], (list, tuple)):
            buttons = [buttons]
        return [
            button.data.decode() if isinstance(button.data, bytes) else button.data
            for row in buttons
            for button in row
        ]

    def render_countries(self, mode, back_target):
        event = FakeEvent()
        with patch.object(buy, "get_countries_list", return_value=[("India", 1)]):
            asyncio.run(buy.show_countries(event, mode, 1, back_target))
        return event

    def test_buy_navigation_row_separates_parent_and_dashboard_destinations(self):
        self.assertEqual(
            self.callbacks(buy.buy_navigation_row("buy_back_main")),
            ["buy_back_main", "dashboard_main"],
        )

    def test_manual_more_filters_button_is_present_when_on(self):
        message, callbacks = self.menu("manual", True)
        self.assertIn("pg_filters|1", callbacks)
        self.assertIn("𝐌ᴏʀᴇ 𝐅ɪʟᴛᴇʀs", message)

    def test_manual_more_filters_button_is_absent_when_off(self):
        message, callbacks = self.menu("manual", False)
        self.assertNotIn("pg_filters|1", callbacks)
        self.assertNotIn("𝐌ᴏʀᴇ 𝐅ɪʟᴛᴇʀs", message)
        self.assertIn("pg_c|bulk|1|menu", callbacks)

    def test_country_page_from_menu_has_back_and_dashboard(self):
        event = self.render_countries("nonspam", "menu")
        self.assertEqual(
            self.callbacks(event.buttons[-1]),
            ["buy_back_main", "dashboard_main"],
        )

    def test_country_page_from_filters_has_back_and_dashboard(self):
        event = self.render_countries("no_2fa", "filters")
        self.assertEqual(
            self.callbacks(event.buttons[-1]),
            ["pg_filters|1", "dashboard_main"],
        )

    def test_country_page_back_context_is_preserved_across_modes(self):
        for bot_mode in ("manual", "panel", "hybrid"):
            event = self.render_countries("nonspam", "menu")
            self.assertEqual(
                self.callbacks(event.buttons[-1]),
                ["buy_back_main", "dashboard_main"],
                bot_mode,
            )

    def test_aged_country_page_returns_to_year_selection(self):
        event = FakeEvent()
        with patch.object(buy, "get_countries_list", return_value=[("India", 1)]):
            asyncio.run(buy.show_countries_for_year(event, 2026, 1))
        self.assertEqual(
            self.callbacks(event.buttons[-1]),
            ["by_years_menu", "dashboard_main"],
        )

    def test_filter_catalog_has_back_and_dashboard(self):
        event = FakeEvent()
        asyncio.run(buy.show_filters_catalog(event))
        self.assertEqual(
            self.callbacks(event.buttons[-1]),
            ["buy_back_main", "dashboard_main"],
        )

    def test_aged_year_catalog_from_filters_returns_to_filters(self):
        event = FakeEvent()
        with patch.object(buy, "get_bot_mode", return_value="panel"):
            asyncio.run(buy.show_years_catalog(event, "filters"))
        self.assertEqual(
            self.callbacks(event.buttons[-1]),
            ["pg_filters|1", "dashboard_main"],
        )

    def test_aged_country_page_preserves_filter_parent(self):
        event = FakeEvent()
        with patch.object(buy, "get_countries_list", return_value=[("India", 1)]):
            asyncio.run(buy.show_countries_for_year(event, 2026, 1, "filters"))
        self.assertEqual(
            self.callbacks(event.buttons[-1]),
            ["by_years_menu|filters", "dashboard_main"],
        )

    def test_country_to_year_preserves_filter_back_context(self):
        event = FakeEvent()
        with patch.object(buy, "get_bot_mode", return_value="panel"), patch.object(
            buy, "get_lzt_key", return_value=""
        ), patch.object(buy, "get_panel_price", return_value=100):
            asyncio.run(buy.show_years(event, "no_2fa", "India", "filters"))
        self.assertEqual(
            self.callbacks(event.buttons[-1]),
            ["pg_c|no_2fa|1|filters", "dashboard_main"],
        )

    def test_panel_more_filters_button_is_present_when_off(self):
        message, callbacks = self.menu("panel", False)
        self.assertIn("pg_filters|1", callbacks)
        self.assertIn("𝐌ᴏʀᴇ 𝐅ɪʟᴛᴇʀs", message)

    def test_panel_more_filters_button_is_present_when_on(self):
        message, callbacks = self.menu("panel", True)
        self.assertIn("pg_filters|1", callbacks)
        self.assertIn("𝐌ᴏʀᴇ 𝐅ɪʟᴛᴇʀs", message)

    def test_hybrid_more_filters_button_is_present_when_off(self):
        message, callbacks = self.menu("hybrid", False)
        self.assertIn("pg_filters|1", callbacks)
        self.assertIn("𝐌ᴏʀᴇ 𝐅ɪʟᴛᴇʀs", message)

    def test_hybrid_more_filters_button_is_present_when_on(self):
        message, callbacks = self.menu("hybrid", True)
        self.assertIn("pg_filters|1", callbacks)
        self.assertIn("𝐌ᴏʀᴇ 𝐅ɪʟᴛᴇʀs", message)


if __name__ == "__main__":
    unittest.main()
