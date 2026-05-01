from pathlib import Path
import json

from f5e.ingest import plaid as pi

TXN_FIXTURE = Path(__file__).parent.parent / "fixtures" / "plaid_transactions_sample.json"
HOLDINGS_FIXTURE = Path(__file__).parent.parent / "fixtures" / "plaid_holdings_sample.json"


def test_ingest_creates_accounts_and_transactions(con):
    added, updated = pi.ingest(con, TXN_FIXTURE)
    assert added == 3
    assert updated == 0

    accounts = con.execute(
        """
        SELECT source, institution, external_id, account_type, currency, nickname
        FROM accounts
        ORDER BY external_id
        """
    ).fetchall()
    assert len(accounts) == 2
    assert [a["external_id"] for a in accounts] == ["acc_checking_123", "acc_credit_456"]
    assert all(a["source"] == "plaid" for a in accounts)
    assert all(a["institution"] == "Chase" for a in accounts)
    assert [a["account_type"] for a in accounts] == ["checking", "credit card"]
    assert all(a["currency"] == "USD" for a in accounts)
    assert [a["nickname"] for a in accounts] == [
        "Chase Total Checking",
        "Chase Sapphire Reserve",
    ]

    txns = con.execute(
        """
        SELECT source_uid, posted_date, amount, currency, description, category
        FROM transactions
        ORDER BY source_uid
        """
    ).fetchall()
    assert len(txns) == 3
    assert [t["source_uid"] for t in txns] == ["txn_001", "txn_002", "txn_003"]
    assert [t["amount"] for t in txns] == [-42.5, 1200.0, -95.25]
    assert all(t["currency"] == "USD" for t in txns)
    assert [t["category"] for t in txns] == ["FOOD_AND_DRINK", "INCOME", "TRAVEL"]


def test_ingest_idempotent(con):
    a1, _ = pi.ingest(con, TXN_FIXTURE)
    a2, u2 = pi.ingest(con, TXN_FIXTURE)
    assert a1 == 3
    assert a2 == 0
    assert u2 == 3
    n = con.execute("SELECT COUNT(*) AS n FROM transactions").fetchone()["n"]
    assert n == 3


def test_ingest_writes_log_row(con):
    pi.ingest(con, TXN_FIXTURE)
    log = con.execute("SELECT source, rows_added, rows_updated FROM ingestion_log").fetchall()
    assert len(log) == 1
    assert log[0]["source"] == "plaid"
    assert log[0]["rows_added"] == 3


def test_ingest_creates_holdings(con):
    added, updated = pi.ingest(con, HOLDINGS_FIXTURE)
    assert added == 2
    assert updated == 0

    account = con.execute(
        """
        SELECT source, institution, external_id, account_type, currency, nickname
        FROM accounts
        """
    ).fetchone()
    assert account["source"] == "plaid"
    assert account["institution"] == "Schwab"
    assert account["external_id"] == "acc_brokerage_789"
    assert account["account_type"] == "brokerage"
    assert account["currency"] == "USD"
    assert account["nickname"] == "Schwab Individual Brokerage"

    holdings = con.execute(
        """
        SELECT as_of_date, symbol, quantity, avg_cost, market_value, currency
        FROM holdings
        ORDER BY symbol
        """
    ).fetchall()
    assert len(holdings) == 2
    assert [h["symbol"] for h in holdings] == ["US Treasury Bill 5.43% 31/10/2025", "VTI"]
    assert [h["as_of_date"] for h in holdings] == ["2025-04-10", "2025-04-10"]
    assert [h["quantity"] for h in holdings] == [10.0, 20.0]
    assert [h["avg_cost"] for h in holdings] == [94.808, 210.0]
    assert [h["market_value"] for h in holdings] == [948.08, 5005.0]
    assert all(h["currency"] == "USD" for h in holdings)


def test_ingest_holdings_idempotent(con):
    a1, _ = pi.ingest(con, HOLDINGS_FIXTURE)
    a2, u2 = pi.ingest(con, HOLDINGS_FIXTURE)
    assert a1 == 2
    assert a2 == 0
    assert u2 == 2
    n = con.execute("SELECT COUNT(*) AS n FROM holdings").fetchone()["n"]
    assert n == 2


def test_ingest_accepts_cli_ndjson_output(con, tmp_path):
    payload = json.loads(TXN_FIXTURE.read_text())
    wrapped = tmp_path / "plaid-transactions-cli.ndjson"
    wrapped.write_text(
        json.dumps({"diagnostic": {"code": "FETCHING_TRANSACTIONS"}})
        + "\n"
        + json.dumps(payload)
        + "\n"
    )

    added, updated = pi.ingest(con, wrapped)
    assert added == 3
    assert updated == 0
