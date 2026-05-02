"""Ingest a Plaid transactions or holdings JSON dump into SQLite.

Expected input shape:
  {
    "institution": {"name": "..."},
    "accounts": [...],
    "transactions": [...],   # optional
    "holdings": [...],       # optional
    "investment_transactions": [...],  # optional
    "securities": [...]      # optional, used with holdings
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


def _read_institution_sidecar(path: Path, institution_id: str | None) -> str | None:
    sidecar = path.parent / "institution.json"
    if not sidecar.exists():
        return None
    payload = json.loads(sidecar.read_text())
    institution = payload.get("institution") or {}
    if institution_id and institution.get("institution_id") not in (None, institution_id):
        return None
    return institution.get("name")


def _titleize_slug(text: str) -> str:
    return " ".join(part.capitalize() for part in text.replace("_", " ").replace("-", " ").split())


def _resolve_institution_name(path: Path, payload: dict, institution: str | None) -> str:
    if institution:
        return institution

    payload_name = payload.get("institution", {}).get("name")
    if payload_name:
        return payload_name

    institution_id = payload.get("item", {}).get("institution_id")
    sidecar_name = _read_institution_sidecar(path, institution_id)
    if sidecar_name:
        return sidecar_name

    parent_name = path.parent.name
    if parent_name and parent_name not in {"plaid", "raw", "data"}:
        return _titleize_slug(parent_name)

    return "Plaid"


def _executed_at(txn: dict) -> str:
    return txn.get("transaction_datetime") or txn["date"]


def _holding_symbol(holding: dict, securities: dict[str, dict]) -> str:
    security = securities.get(holding["security_id"], {})
    return security.get("ticker_symbol") or security.get("name") or holding["security_id"]


def _holding_date(holding: dict) -> str:
    if holding.get("institution_price_as_of"):
        return holding["institution_price_as_of"]
    if holding.get("institution_price_datetime"):
        return holding["institution_price_datetime"][:10]
    raise ValueError(f"holding {holding['security_id']} is missing an as-of date")


def _avg_cost(holding: dict) -> float | None:
    cost_basis = holding.get("cost_basis")
    if cost_basis is None:
        return None
    direct = float(cost_basis)
    quantity = holding.get("quantity")
    if quantity in (None, 0):
        return direct
    per_unit = direct / float(quantity)
    price = holding.get("institution_price")
    if price is None:
        return per_unit if quantity and abs(per_unit) <= abs(direct) else direct
    return per_unit if abs(per_unit - float(price)) < abs(direct - float(price)) else direct


def _load_payload(path: Path) -> dict:
    text = path.read_text()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        payload = None
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            obj = json.loads(stripped)
            if isinstance(obj, dict) and any(
                key in obj for key in ("accounts", "transactions", "holdings", "investment_transactions", "securities")
            ):
                payload = obj
        if payload is None:
            raise
        return payload


def ingest(
    con,
    path: Path | str,
    *,
    institution: str | None = None,
) -> tuple[int, int]:
    """Returns (rows_added, rows_updated)."""
    path = Path(path)
    payload = _load_payload(path)

    institution_name = _resolve_institution_name(path, payload, institution)
    account_ids: dict[str, int] = {}
    accounts_by_external_id = {account["account_id"]: account for account in payload.get("accounts", [])}
    securities_by_id = {security["security_id"]: security for security in payload.get("securities", [])}

    for external_id, account in accounts_by_external_id.items():
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

    for txn in payload.get("investment_transactions", []):
        external_id = txn["account_id"]
        if external_id not in account_ids:
            raise ValueError(
                f"investment transaction {txn['investment_transaction_id']} references unknown account {external_id}"
            )

        security = securities_by_id.get(txn["security_id"], {})
        txn_type = txn.get("type")
        txn_subtype = txn.get("subtype")

        if txn_type in {"buy", "sell"}:
            was_insert = f5e_db.upsert_trade(
                con,
                account_id=account_ids[external_id],
                source_uid=txn["investment_transaction_id"],
                symbol=security.get("ticker_symbol") or security.get("name") or txn["security_id"],
                side=txn_type,
                quantity=txn["quantity"],
                price=txn["price"],
                currency=_currency({"balances": security}, txn),
                executed_at=_executed_at(txn),
                segment=security.get("type"),
                raw={"investment_transaction": txn, "security": security},
            )
        else:
            was_insert = f5e_db.upsert_transaction(
                con,
                account_id=account_ids[external_id],
                source_uid=txn["investment_transaction_id"],
                posted_date=txn["date"],
                amount=-float(txn["amount"]),
                currency=_currency({"balances": security}, txn),
                description=txn.get("name"),
                category=txn_subtype or txn_type,
                raw={"investment_transaction": txn, "security": security},
            )

        if was_insert:
            added += 1
        else:
            updated += 1

    for holding in payload.get("holdings", []):
        external_id = holding["account_id"]
        if external_id not in account_ids:
            raise ValueError(f"holding {holding['security_id']} references unknown account {external_id}")

        account = accounts_by_external_id[external_id]
        security = securities_by_id.get(holding["security_id"], {})
        was_insert = f5e_db.upsert_holding(
            con,
            account_id=account_ids[external_id],
            as_of_date=_holding_date(holding),
            symbol=_holding_symbol(holding, securities_by_id),
            quantity=holding["quantity"],
            avg_cost=_avg_cost(holding),
            market_value=holding.get("institution_value"),
            currency=_currency(
                {"balances": security},
                {"iso_currency_code": holding.get("iso_currency_code"),
                 "unofficial_currency_code": holding.get("unofficial_currency_code")},
            ) or _currency(account),
            raw={"holding": holding, "security": security},
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
