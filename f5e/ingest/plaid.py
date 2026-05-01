"""Ingest a Plaid transactions JSON dump into SQLite.

Expected input shape:
  {
    "institution": {"name": "..."},
    "accounts": [...],
    "transactions": [...]
  }

Amounts are normalized to the repo convention:
  positive = inflow, negative = outflow.
Plaid uses the inverse sign, so values are multiplied by -1 on ingest.
"""
import json
import sys
from pathlib import Path

from f5e import db as f5e_db


def _currency(account: dict, txn: dict | None = None) -> str:
    for candidate in (
        (txn or {}).get("iso_currency_code"),
        (txn or {}).get("unofficial_currency_code"),
        account.get("balances", {}).get("iso_currency_code"),
        account.get("balances", {}).get("unofficial_currency_code"),
    ):
        if candidate:
            return candidate
    return "USD"


def _category(txn: dict) -> str | None:
    pfc = txn.get("personal_finance_category") or {}
    return pfc.get("primary")


def _description(txn: dict) -> str | None:
    return txn.get("merchant_name") or txn.get("name")


def ingest(
    con,
    path: Path | str,
    *,
    institution: str | None = None,
) -> tuple[int, int]:
    """Returns (rows_added, rows_updated)."""
    path = Path(path)
    payload = json.loads(path.read_text())

    institution_name = institution or payload.get("institution", {}).get("name") or "Plaid"
    account_ids: dict[str, int] = {}

    for account in payload.get("accounts", []):
        external_id = account["account_id"]
        account_ids[external_id] = f5e_db.upsert_account(
            con,
            source="plaid",
            institution=institution_name,
            external_id=external_id,
            currency=_currency(account),
            account_type=account.get("subtype") or account.get("type"),
            nickname=account.get("official_name") or account.get("name"),
        )

    added = 0
    updated = 0
    for txn in payload.get("transactions", []):
        external_id = txn["account_id"]
        if external_id not in account_ids:
            raise ValueError(f"transaction {txn['transaction_id']} references unknown account {external_id}")

        was_insert = f5e_db.upsert_transaction(
            con,
            account_id=account_ids[external_id],
            source_uid=txn["transaction_id"],
            posted_date=txn["date"],
            amount=-float(txn["amount"]),
            currency=_currency({"balances": {}}, txn),
            description=_description(txn),
            category=_category(txn),
            raw=txn,
        )
        if was_insert:
            added += 1
        else:
            updated += 1

    f5e_db.log_ingestion(con, "plaid", added, updated, notes=str(path.name))
    con.commit()
    return added, updated


def _cli(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m f5e.ingest.plaid <path-to-transactions.json>", file=sys.stderr)
        return 2
    path = argv[1]
    con = f5e_db.connect()
    f5e_db.apply_schema(con)
    added, updated = ingest(con, path)
    print(f"plaid: +{added} new, ~{updated} updated")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
