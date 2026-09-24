from io import BytesIO

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


async def send_banner(bot, event, key):
    banner = repository.get_banner(key, enabled_only=True)
    if not banner or not banner.get("file_id"):
        return False
    try:
        content = repository.get_banner_content(key)
        if content:
            await bot.send_file(event.chat_id, BytesIO(content), force_document=False)
        else:
            await bot.send_file(event.chat_id, banner["file_id"])
        return True
    except Exception:
        return False