"""Mongo-backed runtime handling for Telethon account session files."""

import hashlib
import logging
import os
import tempfile
import threading


logger = logging.getLogger(__name__)
_local_locks = {}
_local_locks_guard = threading.Lock()
RUNTIME_DIR = os.getenv("TELEGRAM_SESSION_RUNTIME_DIR", os.path.join(tempfile.gettempdir(), "number-smm-telegram-sessions"))


def session_id_for_account(account_key):
    normalized = str(account_key).strip().lstrip("+")
    return "tg-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _lock_for(session_id):
    with _local_locks_guard:
        return _local_locks.setdefault(str(session_id), threading.Lock())


def _runtime_file(session_id):
    return os.path.join(RUNTIME_DIR, str(session_id) + ".session")


def _write_file(path, data):
    temporary = path + ".tmp"
    with open(temporary, "wb") as target:
        target.write(data)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def materialize_session(repository, session_id, fallback_path=None, account_key=None):
    """Restore a Mongo session, importing a legacy local file on first encounter."""
    session_id = str(session_id)
    with _lock_for(session_id):
        record = repository.get_telegram_session(session_id)
        if record is None and fallback_path and os.path.isfile(fallback_path):
            repository.persist_telegram_session(session_id, fallback_path, account_key=account_key)
            record = repository.get_telegram_session(session_id)
        if record is None:
            raise FileNotFoundError("Telegram session is not persisted")
        files = record.get("files") or {}
        session_data = files.get("session")
        if not session_data:
            raise ValueError("Telegram session record has no session file")
        os.makedirs(RUNTIME_DIR, mode=0o700, exist_ok=True)
        runtime_path = _runtime_file(session_id)
        _write_file(runtime_path, session_data)
        for suffix in ("wal", "shm", "journal"):
            sidecar_path = runtime_path + "-" + suffix
            if files.get(suffix):
                _write_file(sidecar_path, files[suffix])
            elif os.path.exists(sidecar_path):
                os.remove(sidecar_path)
        return runtime_path


def persist_session(repository, session_id, source_path, account_key=None):
    """Persist the latest local working copy without logging its contents."""
    return repository.persist_telegram_session(session_id, source_path, account_key=account_key)


def restore_all_sessions(repository):
    restored = 0
    for record in repository.restore_telegram_sessions():
        try:
            materialize_session(repository, record["_id"], account_key=record.get("account_key"))
            restored += 1
        except (OSError, ValueError) as exc:
            logger.warning("Telegram session restore failed: error_type=%s", type(exc).__name__)
    return restored