"""Schema + upsert helper tests."""
from f5e import db as f5e_db


def test_apply_schema_creates_expected_tables(con):
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {r["name"] for r in rows}
    assert {"accounts", "transactions", "trades", "holdings", "ingestion_log"} <= names


def test_upsert_account_is_idempotent(con):
    a1 = f5e_db.upsert_account(
        con, source="zerodha", institution="Zerodha",
        external_id="ZX1234", currency="INR", account_type="brokerage",
    )
    a2 = f5e_db.upsert_account(
        con, source="zerodha", institution="Zerodha",
        external_id="ZX1234", currency="INR", account_type="brokerage",
    )
    assert a1 == a2
    n = con.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()["n"]
    assert n == 1


def test_upsert_account_updates_mutable_fields(con):
    a1 = f5e_db.upsert_account(
        con, source="plaid", institution="Chase", external_id="acct_1",
        currency="USD", nickname="Chase Checking",
    )
    f5e_db.upsert_account(
        con, source="plaid", institution="Chase", external_id="acct_1",
        currency="USD", nickname="Chase Total Checking",
    )
    row = con.execute("SELECT nickname FROM accounts WHERE id = ?", (a1,)).fetchone()
    assert row["nickname"] == "Chase Total Checking"


def test_upsert_trade_idempotent(con):
    aid = f5e_db.upsert_account(
        con, source="zerodha", institution="Zerodha",
        external_id="ZX1234", currency="INR",
    )
    inserted_first = f5e_db.upsert_trade(
        con, account_id=aid, source_uid="T-1", symbol="TESTCO",
        side="buy", quantity=10, price=100.0, currency="INR",
        executed_at="2025-01-15T09:30:00",
    )
    inserted_second = f5e_db.upsert_trade(
        con, account_id=aid, source_uid="T-1", symbol="TESTCO",
        side="buy", quantity=10, price=100.0, currency="INR",
        executed_at="2025-01-15T09:30:00",
    )
    assert inserted_first is True
    assert inserted_second is False
    n = con.execute("SELECT COUNT(*) AS n FROM trades").fetchone()["n"]
    assert n == 1


def test_upsert_trade_rejects_bad_side(con):
    aid = f5e_db.upsert_account(
        con, source="zerodha", institution="Zerodha",
        external_id="ZX1234", currency="INR",
    )
    import sqlite3
    import pytest as _pytest
    with _pytest.raises(sqlite3.IntegrityError):
        f5e_db.upsert_trade(
            con, account_id=aid, source_uid="T-2", symbol="TESTCO",
            side="hold", quantity=1, price=1.0, currency="INR",
            executed_at="2025-01-15T09:30:00",
        )


def test_upsert_transaction_idempotent(con):
    aid = f5e_db.upsert_account(
        con, source="plaid", institution="Chase", external_id="acct_1",
        currency="USD",
    )
    a = f5e_db.upsert_transaction(
        con, account_id=aid, source_uid="plaid_txn_1",
        posted_date="2025-01-10", amount=-42.50, currency="USD",
        description="Coffee", category="Food and Drink",
    )
    b = f5e_db.upsert_transaction(
        con, account_id=aid, source_uid="plaid_txn_1",
        posted_date="2025-01-10", amount=-42.50, currency="USD",
        description="Coffee", category="Food and Drink",
    )
    assert a is True and b is False
    n = con.execute("SELECT COUNT(*) AS n FROM transactions").fetchone()["n"]
    assert n == 1


def test_upsert_holding_idempotent(con):
    aid = f5e_db.upsert_account(
        con, source="plaid", institution="Schwab", external_id="acct_inv_1",
        currency="USD",
    )
    a = f5e_db.upsert_holding(
        con, account_id=aid, as_of_date="2025-04-10", symbol="VTI",
        quantity=20, avg_cost=210.0, market_value=5005.0, currency="USD",
    )
    b = f5e_db.upsert_holding(
        con, account_id=aid, as_of_date="2025-04-10", symbol="VTI",
        quantity=20, avg_cost=210.0, market_value=5005.0, currency="USD",
    )
    assert a is True and b is False
    n = con.execute("SELECT COUNT(*) AS n FROM holdings").fetchone()["n"]
    assert n == 1
