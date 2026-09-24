import asyncio
from unittest.mock import patch

from utils import helpers


def test_valid_home_banner_is_sent_as_dashboard_photo():
    class FakeBot:
        async def send_file(self, peer, url, **kwargs):
            return (peer, url, kwargs)

        async def send_message(self, *args, **kwargs):
            raise AssertionError("text fallback should not run for a valid banner")

    result = asyncio.run(
        helpers.send_preview_on_top(
            FakeBot(), 123, "<b>Dashboard</b>", "https://images.example/banner.jpg",
            buttons=[["buy", "profile"]],
        )
    )

    assert result[0] == 123
    assert result[1] == "https://images.example/banner.jpg"
    assert result[2]["caption"] == "<b>Dashboard</b>"
    assert result[2]["force_document"] is False
    assert result[2]["buttons"] == [["buy", "profile"]]


def test_failed_home_banner_sends_text_dashboard_without_url():
    class FakeBot:
        def __init__(self):
            self.messages = []

        async def send_file(self, *args, **kwargs):
            raise RuntimeError("Telegram could not fetch banner")

        async def send_message(self, peer, message, **kwargs):
            self.messages.append((peer, message, kwargs))
            return "text-dashboard"

    bot = FakeBot()
    result = asyncio.run(
        helpers.send_preview_on_top(
            bot, 123, "<b>Dashboard</b>", "https://invalid.example/banner.jpg",
            buttons=[["buy", "profile"]],
        )
    )

    assert result == "text-dashboard"
    assert bot.messages == [
        (123, "<b>Dashboard</b>", {
            "buttons": [["buy", "profile"]],
            "parse_mode": "html",
        })
    ]
    assert "https://invalid.example/banner.jpg" not in bot.messages[0][1]


def test_failed_banner_on_text_message_edits_dashboard_in_place():
    class FakeBot:
        def __init__(self):
            self.calls = []

        async def edit_message(self, peer, message_id, message, **kwargs):
            self.calls.append((peer, message_id, message, kwargs))
            if "file" in kwargs:
                raise RuntimeError("Telegram could not fetch banner")
            return "edited-text-dashboard"

        async def send_message(self, *args, **kwargs):
            raise AssertionError("existing text dashboard should be edited in place")

        async def delete_messages(self, *args, **kwargs):
            raise AssertionError("existing text dashboard should not be deleted")

    bot = FakeBot()
    result = asyncio.run(
        helpers.send_preview_on_top(
            bot, 123, "<b>Dashboard</b>", "https://invalid.example/banner.jpg",
            buttons=[["buy", "profile"]], edit_msg_id=456,
        )
    )

    assert result == "edited-text-dashboard"
    assert len(bot.calls) == 2
    assert "file" in bot.calls[0][3]
    assert "file" not in bot.calls[1][3]


def test_failed_banner_on_media_message_replaces_it_with_text():
    class FakeBot:
        def __init__(self):
            self.deleted = []
            self.sent = []

        async def edit_message(self, *args, **kwargs):
            raise RuntimeError("Telegram could not fetch banner")

        async def delete_messages(self, peer, message_id):
            self.deleted.append((peer, message_id))

        async def send_message(self, peer, message, **kwargs):
            self.sent.append((peer, message, kwargs))
            return "text-dashboard"

    bot = FakeBot()
    result = asyncio.run(
        helpers.send_preview_on_top(
            bot, 123, "<b>Dashboard</b>", "https://invalid.example/banner.jpg",
            buttons=[["buy", "profile"]], edit_msg_id=456, edit_has_media=True,
        )
    )

    assert result == "text-dashboard"
    assert bot.deleted == [(123, 456)]
    assert bot.sent[0][1] == "<b>Dashboard</b>"
    assert bot.sent[0][2]["buttons"] == [["buy", "profile"]]


def test_hung_banner_fetch_times_out_and_falls_back_to_text():
    class FakeBot:
        async def send_file(self, *args, **kwargs):
            await asyncio.sleep(1)

        async def send_message(self, peer, message, **kwargs):
            return "text-dashboard"

    with patch.object(helpers, "_DASHBOARD_PHOTO_TIMEOUT_SECONDS", 0.01):
        result = asyncio.run(
            helpers.send_preview_on_top(
                FakeBot(), 123, "<b>Dashboard</b>", "https://slow.example/banner.jpg",
                buttons=[["buy", "profile"]],
            )
        )

    assert result == "text-dashboard"