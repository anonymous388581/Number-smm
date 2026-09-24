import os

os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "test-api-hash")
os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("MONGODB_URI", "mongomock://banner-tests")

import mongomock

from mongo_repository import MongoRepository
from utils.banners import BANNER_SECTIONS


def test_all_banner_sections_are_independent_and_persistent():
    client = mongomock.MongoClient()
    repository = MongoRepository(client=client, database_name="banner-tests")
    repository.ensure_indexes()

    for key in BANNER_SECTIONS:
        saved = repository.save_banner(key, f"{key}-image".encode(), f"telegram-{key}")
        assert saved["key"] == key
        assert saved["enabled"] is False
        assert saved["file_id"] == f"telegram-{key}"
        assert saved["created_at"]
        assert saved["updated_at"]
        assert repository.get_banner_content(key) is None
        assert repository.get_banner_content(key, enabled_only=False) == f"{key}-image".encode()

    repository.set_banner_enabled("buy", True)
    repository.set_banner_enabled("support", True)
    assert repository.get_banner_content("buy") == b"buy-image"
    assert repository.get_banner_content("support") == b"support-image"
    assert repository.get_banner_content("deposit") is None

    repository.save_banner("buy", b"replacement", "telegram-buy-new")
    assert repository.get_banner("buy")["enabled"] is True
    assert repository.get_banner("buy")["file_id"] == "telegram-buy-new"
    assert repository.get_banner_content("buy") == b"replacement"

    restarted = MongoRepository(client=client, database_name="banner-tests")
    assert restarted.get_banner("buy")["enabled"] is True
    assert restarted.get_banner_content("buy") == b"replacement"
    assert restarted.get_banner("deposit")["enabled"] is False
    assert restarted.get_banner_content("missing") is None
