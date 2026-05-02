import json
import subprocess
from pathlib import Path

from f5e.export import plaid as pe


def _completed(stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["plaid"], returncode=0, stdout=stdout, stderr="")


def test_export_transactions_paginates_until_short_page(tmp_path):
    offsets: list[int] = []

    def fake_run(args, capture_output, text, check):
        assert capture_output is True
        assert text is True
        assert check is True
        offset = int(args[args.index("--offset") + 1])
        offsets.append(offset)
        count = int(args[args.index("--count") + 1])
        size = {0: count, 100: count, 200: 10}[offset]
        payload = {
            "accounts": [{"account_id": "acct_1", "name": "Checking"}],
            "item": {"item_id": "item_1", "institution_id": "ins_1"},
            "total_transactions": size,
            "transactions": [
                {"transaction_id": f"txn_{offset + i}", "account_id": "acct_1", "amount": 1, "date": "2025-01-01"}
                for i in range(size)
            ],
        }
        return _completed(
            json.dumps({"diagnostic": {"code": "FETCHING_TRANSACTIONS"}}) + "\n" + json.dumps(payload) + "\n"
        )

    out = tmp_path / "transactions.json"
    result = pe.export_paginated(
        product="transactions",
        item="robinhood",
        start_date="2020-01-01",
        end_date="2026-05-02",
        output_path=out,
        page_size=100,
        runner=fake_run,
    )

    payload = json.loads(out.read_text())
    assert offsets == [0, 100, 200]
    assert result["pages"] == 3
    assert result["records"] == 210
    assert len(payload["transactions"]) == 210
    assert payload["transactions"][0]["transaction_id"] == "txn_0"
    assert payload["transactions"][-1]["transaction_id"] == "txn_209"


def test_export_investment_transactions_merges_and_dedupes_metadata(tmp_path):
    offsets: list[int] = []

    def fake_run(args, capture_output, text, check):
        offset = int(args[args.index("--offset") + 1])
        offsets.append(offset)
        if offset == 0:
            payload = {
                "accounts": [{"account_id": "acct_1", "name": "Brokerage"}],
                "item": {"item_id": "item_1", "institution_id": "ins_54"},
                "securities": [
                    {"security_id": "sec_1", "ticker_symbol": "QQQ"},
                    {"security_id": "sec_2", "ticker_symbol": "NVDA"},
                ],
                "investment_transactions": [
                    {"investment_transaction_id": "itx_1", "account_id": "acct_1", "security_id": "sec_1"},
                    {"investment_transaction_id": "itx_2", "account_id": "acct_1", "security_id": "sec_2"},
                ],
            }
        else:
            payload = {
                "accounts": [{"account_id": "acct_1", "name": "Brokerage"}],
                "item": {"item_id": "item_1", "institution_id": "ins_54"},
                "securities": [
                    {"security_id": "sec_2", "ticker_symbol": "NVDA"},
                    {"security_id": "sec_3", "ticker_symbol": "AMD"},
                ],
                "investment_transactions": [
                    {"investment_transaction_id": "itx_3", "account_id": "acct_1", "security_id": "sec_3"},
                ],
            }
        return _completed(
            json.dumps({"diagnostic": {"code": "FETCHING_INVESTMENTS_TRANSACTIONS"}})
            + "\n"
            + json.dumps(payload)
            + "\n"
        )

    out = tmp_path / "investment-transactions.json"
    result = pe.export_paginated(
        product="investment_transactions",
        item="robinhood",
        start_date="2020-01-01",
        end_date="2026-05-02",
        output_path=out,
        page_size=2,
        runner=fake_run,
    )

    payload = json.loads(out.read_text())
    assert offsets == [0, 2]
    assert result["pages"] == 2
    assert result["records"] == 3
    assert len(payload["investment_transactions"]) == 3
    assert len(payload["accounts"]) == 1
    assert sorted(s["security_id"] for s in payload["securities"]) == ["sec_1", "sec_2", "sec_3"]
