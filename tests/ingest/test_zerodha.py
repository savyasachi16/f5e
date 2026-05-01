from pathlib import Path

from f5e.ingest import zerodha as zi

FIXTURE = Path(__file__).parent.parent / "fixtures" / "zerodha_trades_sample.json"


def test_ingest_creates_account_and_trades(con):
    added, updated = zi.ingest(con, FIXTURE, external_id="ZX1234")
    assert added == 4
    assert updated == 0

    accounts = con.execute("SELECT * FROM accounts").fetchall()
    assert len(accounts) == 1
    assert accounts[0]["source"] == "zerodha"
    assert accounts[0]["external_id"] == "ZX1234"
    assert accounts[0]["currency"] == "INR"

    trades = con.execute(
        "SELECT symbol, side, quantity, price, segment FROM trades ORDER BY source_uid"
    ).fetchall()
    assert len(trades) == 4
    assert [t["side"] for t in trades] == ["buy", "buy", "sell", "sell"]
    assert all(t["symbol"] == "TESTCO" for t in trades)
    assert all(t["segment"] == "EQ" for t in trades)


def test_ingest_idempotent(con):
    a1, _ = zi.ingest(con, FIXTURE, external_id="ZX1234")
    a2, u2 = zi.ingest(con, FIXTURE, external_id="ZX1234")
    assert a1 == 4
    assert a2 == 0
    assert u2 == 4
    n = con.execute("SELECT COUNT(*) AS n FROM trades").fetchone()["n"]
    assert n == 4


def test_ingest_writes_log_row(con):
    zi.ingest(con, FIXTURE, external_id="ZX1234")
    log = con.execute("SELECT source, rows_added, rows_updated FROM ingestion_log").fetchall()
    assert len(log) == 1
    assert log[0]["source"] == "zerodha"
    assert log[0]["rows_added"] == 4
