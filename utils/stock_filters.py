"""Shared predicates for local account stock filtering."""

SUPPORTED_STOCK_FILTERS = {"bulk", "nonspam", "spam", "no_2fa", "with_2fa", "aged"}
UNSUPPORTED_STOCK_FILTERS = {"stars", "premium", "no_email", "with_email", "dc5"}


def stock_filter_clause(mode, year=None, country=None):
    """Return a SQL WHERE fragment and parameters for local stock queries."""
    if mode == "bulk":
        clauses = ["available=1"]
        params = []
    elif mode == "aged":
        clauses = ["available=1", "account_year IS NOT NULL"]
        params = []
    elif mode == "nonspam":
        clauses = ["available=1", "category IS NOT NULL", "LOWER(category) != 'spam'"]
        params = []
    elif mode == "spam":
        clauses = ["available=1", "LOWER(category) = 'spam'"]
        params = []
    elif mode == "no_2fa":
        clauses = [
            "available=1",
            "(twofa IS NULL OR TRIM(twofa) = '' OR LOWER(TRIM(twofa)) = 'none')",
        ]
        params = []
    elif mode == "with_2fa":
        clauses = [
            "available=1",
            "twofa IS NOT NULL",
            "TRIM(twofa) != ''",
            "LOWER(TRIM(twofa)) != 'none'",
        ]
        params = []
    elif mode in UNSUPPORTED_STOCK_FILTERS:
        return "1=0", []
    else:
        return "1=0", []

    if country is not None:
        clauses.append("country_name=?")
        params.append(country)
    if year is not None:
        clauses.append("account_year=?")
        params.append(int(year))
    return " AND ".join(clauses), params


def claim_stock_account(connection, mode, year=None, country=None):
    """Atomically claim the first available local account matching the filter."""
    where, params = stock_filter_clause(mode, year=year, country=country)
    candidates = connection.execute(
        f"SELECT phone, session_file, twofa FROM stock WHERE {where} ORDER BY rowid",
        params,
    ).fetchall()

    for candidate in candidates:
        phone = candidate[0]
        claimed = connection.execute(
            f"UPDATE stock SET available=0 WHERE phone=? AND {where}",
            (phone, *params),
        )
        if claimed.rowcount == 1:
            return candidate

    return None
