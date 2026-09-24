from io import BytesIO

from telethon import events, types

from database import repository


BANNER_SECTIONS = {
    "buy": "🛒 Buy Account",
    "deposit": "💳 Deposit",
    "profile": "👤 Profile",
    "orders": "📦 My Orders",
    "balance": "💰 Balance",
    "smm": "📱 Social Media Services",
    "support": "🆘 Support",
}


async def send_bannered_message(bot, event, key, caption, buttons=None, enabled_only=True):
    banner = repository.get_banner(key, enabled_only=enabled_only)
    if not banner or not banner.get("file_id"):
        return False
    try:
        content = repository.get_banner_content(key)
        if not content:
            return False
        image = BytesIO(content)
        image.name = banner.get("filename") or f"{key}.jpg"
        uploaded = await bot.upload_file(image)
        media = types.InputMediaUploadedPhoto(file=uploaded)
        if isinstance(event, events.CallbackQuery.Event):
            try:
                await event.delete()
            except Exception:
                return False
        await bot.send_file(
            event.chat_id, media, caption=caption, buttons=buttons,
            parse_mode="html", force_document=False,
        )
        return True
    except Exception:
        return False