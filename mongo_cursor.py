"""Small legacy-shape adapter backed entirely by MongoDB.

Handlers historically consume tuple-shaped rows from ``database.cur``. This
adapter preserves those return shapes while translating the supported query
surface into Mongo operations. It never opens SQLite or evaluates SQL through
a local database engine.
"""

import re
from dataclasses import dataclass

from pymongo import ASCENDING, DESCENDING, ReturnDocument


TABLE_KEYS = {
    "users": "user_id", "settings": "key", "stock": "phone", "auto_prices": ("country", "year"),
    "spamfree_prices": "country", "deposits": "id", "upi_orders": "order_id", "orders": "id",
    "custom_payments": "id", "admins": "user_id", "custom_countries": "code", "smm_orders": "id",
    "source_codes": "id", "panels": "id", "redeemed_transactions": "email_msg_id",
}

SCHEMA_COLUMNS = {
    "users": ["user_id", "balance", "referred_by", "total_deposited", "joined_date", "banned", "discount", "terms_accepted"],
    "settings": ["key", "value"],
    "stock": ["phone", "session_file", "country_name", "country_icon", "account_year", "category", "price", "available", "twofa", "added_date"],
    "auto_prices": ["country", "year", "price"], "spamfree_prices": ["country", "price"],
    "deposits": ["id", "user_id", "amount", "method_name", "status", "date"],
    "upi_orders": ["order_id", "user_id", "amount", "status", "date"],
    "orders": ["id", "user_id", "country", "year", "price", "phone", "otp", "date"],
    "custom_payments": ["id", "name", "caption", "qr_file_id"],
    "admins": ["user_id", "p_add_stock", "p_manage_stock", "p_stats", "p_bal", "p_settings"],
    "custom_countries": ["code", "name", "flag"],
    "smm_orders": ["id", "user_id", "server", "service_id", "service_name", "target_link", "quantity", "price", "smm_order_id", "status", "date"],
    "source_codes": ["id", "title", "description", "price", "file_content", "available"],
    "panels": ["id", "title", "description", "price", "panel_content", "available"],
    "redeemed_transactions": ["email_msg_id", "utr", "txn_id", "amount", "user_id", "date"],
}


def _clean(value):
    return value.strip().strip("'").strip('"')


def _value(token, params, index):
    token = token.strip()
    if token == "?":
        return params[index], index + 1
    if token.upper() == "NULL":
        return None, index
    try:
        return int(token), index
    except ValueError:
        try:
            return float(token), index
        except ValueError:
            return _clean(token), index


def _field_value(document, field):
    value = document.get(field.strip().split(".")[-1])
    return value


def _matches(document, expression, params):
    expression = expression.strip().strip("()")
    if expression in ("1=1", "TRUE"):
        return True
    if expression == "1=0":
        return False
    parts = re.split(r"\s+AND\s+", expression, flags=re.I)
    if len(parts) > 1:
        pos = 0
        for part in parts:
            used = _matches(document, part, params[pos:])
            if not used:
                return False
            pos += len(re.findall(r"\?", part))
        return True
    parts = re.split(r"\s+OR\s+", expression, flags=re.I)
    if len(parts) > 1:
        pos = 0
        for part in parts:
            if _matches(document, part, params[pos:]):
                return True
            pos += len(re.findall(r"\?", part))
        return False

    match = re.match(r"LOWER\(\s*(\w+)\s*\)\s*(=|!=)\s*'([^']*)'", expression, re.I)
    if match:
        value = str(_field_value(document, match.group(1)) or "").lower()
        return (value == match.group(3).lower()) if match.group(2) == "=" else value != match.group(3).lower()
    match = re.match(r"(?:TRIM\()?\s*(\w+)\s*\)?\s+IS\s+(NOT\s+)?NULL", expression, re.I)
    if match:
        present = _field_value(document, match.group(1)) is not None
        return not present if match.group(2) else present
    match = re.match(r"(\w+)\s+IN\s*\((.+)\)", expression, re.I)
    if match:
        values = [_clean(item) for item in match.group(2).split(",")]
        return str(_field_value(document, match.group(1))) in values
    match = re.match(r"(\w+)\s*(=|!=|>=|<=|>|<)\s*(\?|[^\s]+)", expression, re.I)
    if not match:
        return False
    actual = _field_value(document, match.group(1))
    expected, _ = _value(match.group(3), params, 0)
    if actual is None:
        return match.group(2) == "=" and expected is None
    try:
        if match.group(2) == "=": return actual == expected
        if match.group(2) == "!=": return actual != expected
        if match.group(2) == ">=": return actual >= expected
        if match.group(2) == "<=": return actual <= expected
        if match.group(2) == ">": return actual > expected
        return actual < expected
    except TypeError:
        return str(actual) == str(expected)


@dataclass
class Result:
    rows: list
    rowcount: int = 0

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class MongoCursor:
    def __init__(self, repository):
        self.repository = repository
        self._result = Result([])
        self.rowcount = 0
        self.lastrowid = None

    def _docs(self, table):
        return list(self.repository.db[table].find({}))

    def execute(self, sql, params=()):
        statement = " ".join(sql.strip().split())
        upper = statement.upper()
        if upper.startswith("SELECT"):
            return self._select(statement, tuple(params))
        if upper.startswith("INSERT"):
            return self._insert(statement, tuple(params))
        if upper.startswith("UPDATE"):
            return self._update(statement, tuple(params))
        if upper.startswith("DELETE"):
            return self._delete(statement, tuple(params))
        self._result = Result([])
        self.rowcount = 0
        return self

    def _where(self, statement):
        match = re.search(r"\sWHERE\s(.+?)(?:\sORDER BY|\sGROUP BY|\sLIMIT|\sOFFSET|$)", statement, re.I)
        return match.group(1) if match else "1=1"

    def _select(self, statement, params):
        table_match = re.search(r"\sFROM\s+(\w+)", statement, re.I)
        table = table_match.group(1)
        where = self._where(statement)
        docs = [doc for doc in self._docs(table) if _matches(doc, where, list(params))]
        distinct = bool(re.search(r"SELECT\s+DISTINCT", statement, re.I))
        group_match = re.search(r"GROUP BY\s+([\w, ]+)", statement, re.I)
        order_match = re.search(r"ORDER BY\s+(\w+)(?:\s+(DESC|ASC))?", statement, re.I)
        if order_match:
            docs.sort(key=lambda d: (_field_value(d, order_match.group(1)) is None, _field_value(d, order_match.group(1))), reverse=order_match.group(2) == "DESC")
        offset_match = re.search(r"OFFSET\s+(\?|\d+)", statement, re.I)
        limit_match = re.search(r"LIMIT\s+(\?|\d+)", statement, re.I)
        if offset_match:
            offset = params[-2] if offset_match.group(1) == "?" and limit_match else int(offset_match.group(1))
            docs = docs[offset:]
        if limit_match:
            limit = params[-1] if limit_match.group(1) == "?" else int(limit_match.group(1))
            docs = docs[:limit]
        fields_text = re.search(r"SELECT\s+(.*?)\s+FROM", statement, re.I).group(1).strip()
        fields = [field.strip() for field in fields_text.replace("DISTINCT ", "").split(",")]
        if group_match:
            groups = {}
            group_fields = [f.strip() for f in group_match.group(1).split(",")]
            for doc in docs:
                key = tuple(_field_value(doc, f) for f in group_fields)
                groups.setdefault(key, []).append(doc)
            rows = []
            for key, members in groups.items():
                row = []
                for field in fields:
                    count = re.match(r"COUNT\(\*\)", field, re.I)
                    total = re.match(r"SUM\((\w+)\)", field, re.I)
                    if count: row.append(len(members))
                    elif total: row.append(sum((m.get(total.group(1)) or 0) for m in members) or None)
                    else: row.append(_field_value(members[0], field))
                rows.append(tuple(row))
        elif fields_text == "*":
            columns = SCHEMA_COLUMNS.get(table, list(docs[0].keys()) if docs else [])
            rows = [tuple(d.get(c) for c in columns) for d in docs]
        else:
            rows = []
            for doc in docs:
                row = []
                for field in fields:
                    count = re.match(r"COUNT\(\*\)", field, re.I)
                    total = re.match(r"SUM\((\w+)\)", field, re.I)
                    if count: row.append(len(docs))
                    elif total: row.append(sum((d.get(total.group(1)) or 0) for d in docs) or None)
                    else: row.append(_field_value(doc, field))
                rows.append(tuple(row))
            if any(re.match(r"COUNT|SUM", field, re.I) for field in fields):
                rows = rows[:1]
                if not rows:
                    rows = [tuple(0 if re.match(r"COUNT", field, re.I) else None for field in fields)]
        if distinct:
            rows = list(dict.fromkeys(rows))
        self.description = [(field,) for field in (SCHEMA_COLUMNS.get(table, fields) if fields_text == "*" else fields)]
        self._result = Result(rows)
        self.rowcount = len(rows)
        return self

    def _insert(self, statement, params):
        match = re.search(r"INTO\s+(\w+)\s*\((.*?)\)\s*VALUES\s*\((.*?)\)", statement, re.I)
        if not match:
            return self
        table, columns = match.group(1), [c.strip() for c in match.group(2).split(",")]
        document = dict(zip(columns, params))
        key = TABLE_KEYS.get(table)
        if key is None:
            document["_id"] = self.repository.next_id(table)
        elif isinstance(key, tuple):
            document["_id"] = "::".join(str(document[field]) for field in key)
        else:
            if key not in document or document[key] is None:
                document[key] = self.repository.next_id(table)
            document["_id"] = document[key]
        if "OR IGNORE" in statement.upper():
            self.repository.db[table].update_one({"_id": document["_id"]}, {"$setOnInsert": document}, upsert=True)
        else:
            self.repository.db[table].replace_one({"_id": document["_id"]}, document, upsert=True)
        self.lastrowid = document["_id"] if isinstance(document["_id"], int) else None
        self.rowcount = 1
        return self

    def _update(self, statement, params):
        match = re.match(r"UPDATE\s+(\w+)\s+SET\s+(.*?)\s+WHERE\s+(.+)$", statement, re.I)
        if not match:
            return self
        table, assignments, where = match.groups()
        updates = {}
        param_index = 0
        for assignment in assignments.split(","):
            field, expression = [part.strip() for part in assignment.split("=", 1)]
            if expression == "?":
                updates[field] = params[param_index]; param_index += 1
            elif re.match(rf"{re.escape(field)}\s*([+-])\s*\?", expression, re.I):
                sign = re.match(rf"{re.escape(field)}\s*([+-])\s*\?", expression, re.I).group(1)
                updates[field] = {"$inc": params[param_index] * (1 if sign == "+" else -1)}; param_index += 1
            elif re.match(r"CASE WHEN", expression, re.I):
                for doc in documents:
                    value = 0 if doc.get(field) == 1 else 1
                    self.repository.db[table].update_one({"_id": doc["_id"]}, {"$set": {field: value}})
            else:
                updates[field] = _clean(expression)
        where_params = list(params[param_index:])
        documents = [d for d in self._docs(table) if _matches(d, where, where_params)]
        if updates and not any(isinstance(v, dict) for v in updates.values()):
            self.repository.db[table].update_many({"_id": {"$in": [d["_id"] for d in documents]}}, {"$set": updates})
        elif updates:
            for doc in documents:
                for field, value in updates.items():
                    if isinstance(value, dict):
                        self.repository.db[table].update_one({"_id": doc["_id"]}, {"$inc": {field: value["$inc"]}})
        self.rowcount = len(documents)
        return self

    def _delete(self, statement, params):
        match = re.match(r"DELETE\s+FROM\s+(\w+)\s+WHERE\s+(.+)$", statement, re.I)
        if not match:
            return self
        table, where = match.groups()
        ids = [d["_id"] for d in self._docs(table) if _matches(d, where, list(params))]
        result = self.repository.db[table].delete_many({"_id": {"$in": ids}})
        self.rowcount = result.deleted_count
        return self

    def fetchone(self):
        return self._result.fetchone()

    def fetchall(self):
        return self._result.fetchall()