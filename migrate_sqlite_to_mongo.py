"""One-time, non-destructive SQLite to MongoDB migration.

Usage: MONGODB_URI='mongodb+srv://...' python migrate_sqlite_to_mongo.py
The default is insert-only: existing Mongo documents are never overwritten.
"""

import argparse
import logging
import os
import sqlite3
from collections import Counter

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

COLLECTIONS = (
    "users", "settings", "stock", "auto_prices", "spamfree_prices", "deposits",
    "upi_orders", "orders", "custom_payments", "admins", "custom_countries",
    "smm_orders", "source_codes", "panels", "redeemed_transactions",
)

TABLE_KEYS = {
    "users": "user_id", "settings": "key", "stock": "phone", "auto_prices": ("country", "year"),
    "spamfree_prices": "country", "deposits": "id", "upi_orders": "order_id", "orders": "id",
    "custom_payments": "id", "admins": "user_id", "custom_countries": "code", "smm_orders": "id",
    "source_codes": "id", "panels": "id", "redeemed_transactions": "email_msg_id",
}


def normalize_value(value):
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def make_document(table, columns, values):
    document = {column: normalize_value(value) for column, value in zip(columns, values)}
    key = TABLE_KEYS[table]
    document["_id"] = ("::".join(str(document[field]) for field in key)
                       if isinstance(key, tuple) else normalize_value(document[key]))
    return document


def migrate(sqlite_path, repository):
    summary = Counter()
    sqlite = sqlite3.connect(f"file:{os.path.abspath(sqlite_path)}?mode=ro", uri=True)
    try:
        for table in COLLECTIONS:
            columns = [row[1] for row in sqlite.execute(f'PRAGMA table_info("{table}")')]
            if not columns:
                summary[f"skipped_{table}"] += 1
                logger.warning("table %s does not exist", table)
                continue
            for values in sqlite.execute(f'SELECT * FROM "{table}"'):
                try:
                    document = make_document(table, columns, values)
                    result = repository.db[table].update_one(
                        {"_id": document["_id"]}, {"$setOnInsert": document}, upsert=True
                    )
                    if result.upserted_id is not None:
                        summary[table] += 1
                    else:
                        summary["skipped_existing"] += 1
                except Exception as exc:
                    summary["failed"] += 1
                    logger.error("table=%s key=%r reason=%s", table, values[0], exc)
    finally:
        sqlite.close()
    return summary


def sqlite_snapshot(path):
    conn = sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True)
    try:
        snapshot = {"counts": {}, "balance_total": 0, "deposited_total": 0,
                    "stock_by_country": {}, "stock_by_year": {}, "stock_by_category": {},
                    "stock_available": 0, "deposit_status": {}, "order_count": 0}
        for table in COLLECTIONS:
            snapshot["counts"][table] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        snapshot["balance_total"] = conn.execute("SELECT COALESCE(SUM(balance), 0) FROM users").fetchone()[0]
        snapshot["deposited_total"] = conn.execute("SELECT COALESCE(SUM(total_deposited), 0) FROM users").fetchone()[0]
        for field, target in (("country_name", "stock_by_country"), ("account_year", "stock_by_year"), ("category", "stock_by_category")):
            snapshot[target] = dict(conn.execute(f"SELECT {field}, COUNT(*) FROM stock GROUP BY {field}").fetchall())
        snapshot["stock_available"] = conn.execute("SELECT COUNT(*) FROM stock WHERE available=1").fetchone()[0]
        snapshot["deposit_status"] = dict(conn.execute("SELECT status, COUNT(*) FROM deposits GROUP BY status").fetchall())
        snapshot["order_count"] = snapshot["counts"]["orders"]
        return snapshot
    finally:
        conn.close()


def mongo_snapshot(repository):
    users = repository.db.users
    snapshot = {"counts": {},
                "balance_total": sum((row.get("balance", 0) or 0) for row in users.find({}, {"balance": 1})),
                "deposited_total": sum((row.get("total_deposited", 0) or 0) for row in users.find({}, {"total_deposited": 1})),
                "stock_by_country": {}, "stock_by_year": {}, "stock_by_category": {},
                "stock_available": repository.db.stock.count_documents({}),
                "deposit_status": {}, "order_count": repository.db.orders.count_documents({})}
    for table in COLLECTIONS:
        snapshot["counts"][table] = repository.db[table].count_documents({})
    snapshot["stock_available"] = repository.db.stock.count_documents({"available": 1})
    for field, target in (("country_name", "stock_by_country"), ("account_year", "stock_by_year"), ("category", "stock_by_category")):
        pipeline = [{"$group": {"_id": f"${field}", "count": {"$sum": 1}}}]
        snapshot[target] = {row["_id"]: row["count"] for row in repository.db.stock.aggregate(pipeline)}
    pipeline = [{"$group": {"_id": "$status", "count": {"$sum": 1}}}]
    snapshot["deposit_status"] = {row["_id"]: row["count"] for row in repository.db.deposits.aggregate(pipeline)}
    return snapshot


def main():
    from mongo_repository import MongoRepository

    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", default="otp_bot_final.db")
    args = parser.parse_args()
    repository = MongoRepository()
    repository.ping()
    repository.ensure_indexes()
    summary = migrate(args.sqlite, repository)
    print("Migration summary:")
    for key in sorted(summary):
        print(f"  {key}: {summary[key]}")
    before, after = sqlite_snapshot(args.sqlite), mongo_snapshot(repository)
    print("Verification:")
    print("  counts_match:", before["counts"] == after["counts"])
    print("  balance_total_match:", before["balance_total"] == after["balance_total"])
    print("  deposited_total_match:", before["deposited_total"] == after["deposited_total"])
    print("  stock_aggregates_match:", all(before[k] == after[k] for k in ("stock_by_country", "stock_by_year", "stock_by_category", "stock_available")))
    print("  deposit_status_match:", before["deposit_status"] == after["deposit_status"])
    print("  order_count_match:", before["order_count"] == after["order_count"])


if __name__ == "__main__":
    main()