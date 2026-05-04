from pathlib import Path

from f5e.ingest import zerodha_holdings as zh

FIXTURE = Path(__file__).parent.parent / "fixtures" / "zerodha_holdings_sample.json"


def test_ingest_creates_account_and_holdings(con):
    added, updated = zh.ingest(con, FIXTURE)
    assert added == 2
    assert updated == 0

    accounts = con.execute(
        "SELECT source, institution, external_id, currency, account_type FROM accounts"
    ).fetchall()
    assert len(accounts) == 1
    a = accounts[0]
    assert a["source"] == "zerodha"
    assert a["institution"] == "Zerodha"
    assert a["external_id"] == "ABC123"
    assert a["currency"] == "INR"
    assert a["account_type"] == "demat"

    holdings = con.execute(
        """
        SELECT symbol, quantity, avg_cost, market_value, currency, as_of_date
        FROM holdings ORDER BY symbol
        """
    ).fetchall()
    assert [h["symbol"] for h in holdings] == ["RELIANCE", "TCS"]
    assert all(h["currency"] == "INR" for h in holdings)
    assert all(h["as_of_date"] == "2026-05-03" for h in holdings)
    # market_value = quantity * last_price
    rel = next(h for h in holdings if h["symbol"] == "RELIANCE")
    assert rel["quantity"] == 10
    assert rel["avg_cost"] == 2300.50
    assert rel["market_value"] == 10 * 2640.75
    tcs = next(h for h in holdings if h["symbol"] == "TCS")
    assert tcs["market_value"] == 5 * 4100.00


def test_ingest_idempotent_same_day(con):
    a1, _ = zh.ingest(con, FIXTURE)
    a2, u2 = zh.ingest(con, FIXTURE)
    assert a1 == 2
    assert a2 == 0
    assert u2 == 2
    n = con.execute("SELECT COUNT(*) AS n FROM holdings").fetchone()["n"]
    assert n == 2


def test_ingest_writes_log_row(con):
    zh.ingest(con, FIXTURE)
    log = con.execute(
        "SELECT source, rows_added, rows_updated FROM ingestion_log"
    ).fetchall()
    assert len(log) == 1
    assert log[0]["source"] == "zerodha"
    assert log[0]["rows_added"] == 2
