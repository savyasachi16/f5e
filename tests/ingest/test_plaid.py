from pathlib import Path

from f5e.ingest import plaid as pi

FIXTURE = Path(__file__).parent.parent / "fixtures" / "plaid_transactions_sample.json"


def test_ingest_creates_accounts_and_transactions(con):
    added, updated = pi.ingest(con, FIXTURE)
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
    a1, _ = pi.ingest(con, FIXTURE)
    a2, u2 = pi.ingest(con, FIXTURE)
    assert a1 == 3
    assert a2 == 0
    assert u2 == 3
    n = con.execute("SELECT COUNT(*) AS n FROM transactions").fetchone()["n"]
    assert n == 3


def test_ingest_writes_log_row(con):
    pi.ingest(con, FIXTURE)
    log = con.execute("SELECT source, rows_added, rows_updated FROM ingestion_log").fetchall()
    assert len(log) == 1
    assert log[0]["source"] == "plaid"
    assert log[0]["rows_added"] == 3
