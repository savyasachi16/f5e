from pathlib import Path

from f5e.ingest import kotak as ki

TEXT_FIXTURE = Path(__file__).parent.parent / "fixtures" / "kotak_statement_sample.txt"
MULTILINE_FIXTURE = Path(__file__).parent.parent / "fixtures" / "kotak_statement_multiline_sample.txt"


def test_ingest_creates_account_and_transactions(con, monkeypatch, tmp_path):
    pdf_path = tmp_path / "kotak-apr-2024.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(ki, "_extract_text", lambda _: TEXT_FIXTURE.read_text())

    added, updated = ki.ingest(con, pdf_path)
    assert added == 3
    assert updated == 0

    accounts = con.execute(
        """
        SELECT source, institution, external_id, account_type, currency
        FROM accounts
        """
    ).fetchall()
    assert len(accounts) == 1
    assert dict(accounts[0]) == {
        "source": "kotak",
        "institution": "Kotak Mahindra Bank",
        "external_id": "XX1234",
        "account_type": "savings",
        "currency": "INR",
    }

    transactions = con.execute(
        """
        SELECT posted_date, amount, currency, description
        FROM transactions
        ORDER BY posted_date
        """
    ).fetchall()
    assert len(transactions) == 3
    assert [row["posted_date"] for row in transactions] == [
        "2024-04-02",
        "2024-04-05",
        "2024-04-08",
    ]
    assert [row["amount"] for row in transactions] == [-649.0, 50000.0, -5000.0]
    assert all(row["currency"] == "INR" for row in transactions)
    assert [row["description"] for row in transactions] == [
        "UPI/NETFLIX/240402/12345",
        "SALARY APR",
        "ATM CASH WDL",
    ]


def test_ingest_idempotent(con, monkeypatch, tmp_path):
    pdf_path = tmp_path / "kotak-apr-2024.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(ki, "_extract_text", lambda _: TEXT_FIXTURE.read_text())

    a1, _ = ki.ingest(con, pdf_path)
    a2, u2 = ki.ingest(con, pdf_path)
    assert a1 == 3
    assert a2 == 0
    assert u2 == 3

    row = con.execute("SELECT COUNT(*) AS n FROM transactions").fetchone()
    assert row["n"] == 3


def test_ingest_accepts_numbered_multiline_statement_layout(con, monkeypatch, tmp_path):
    pdf_path = tmp_path / "kotak-q1-2024.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(ki, "_extract_text", lambda _: MULTILINE_FIXTURE.read_text())

    added, updated = ki.ingest(con, pdf_path)
    assert added == 2
    assert updated == 0

    account = con.execute(
        "SELECT external_id FROM accounts WHERE source = 'kotak'"
    ).fetchone()
    assert account["external_id"] == "1234567890"

    rows = con.execute(
        """
        SELECT posted_date, amount, description
        FROM transactions
        ORDER BY source_uid
        """
    ).fetchall()
    assert len(rows) == 2
    assert sorted(row["amount"] for row in rows) == [-300000.0, 300000.0]
    assert all(row["posted_date"] == "2024-03-12" for row in rows)
    descriptions = [row["description"] for row in rows]
    assert any("07:32 PM 9876543210" in description for description in descriptions)
    assert any("07:31 PM L/KKBK/X0132/RDA r 407219912203" in description for description in descriptions)


def test_ingest_writes_log_row(con, monkeypatch, tmp_path):
    pdf_path = tmp_path / "kotak-apr-2024.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(ki, "_extract_text", lambda _: TEXT_FIXTURE.read_text())

    ki.ingest(con, pdf_path)

    rows = con.execute(
        "SELECT source, rows_added, rows_updated, notes FROM ingestion_log"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["source"] == "kotak"
    assert rows[0]["rows_added"] == 3
    assert rows[0]["rows_updated"] == 0
    assert rows[0]["notes"] == "kotak-apr-2024.pdf"
