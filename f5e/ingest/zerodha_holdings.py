"""Ingest a Zerodha holdings JSON dump into SQLite.

Expected input shape (matches Console / Kite Connect /portfolio/holdings):
  {
    "user_id": "<demat user id>",
    "as_of_date": "YYYY-MM-DD",
    "holdings": [
      {"tradingsymbol": "...", "quantity": N, "average_price": ...,
       "last_price": ..., "exchange": "NSE", ...},
      ...
    ]
  }

Each row lands in `holdings` keyed on (account_id, as_of_date, symbol).
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

from f5e import db as f5e_db


def ingest(con, path: Path | str) -> tuple[int, int]:
    path = Path(path)
    payload = json.loads(path.read_text())

    user_id = payload.get("user_id") or "unknown"
    as_of_date = payload.get("as_of_date") or dt.date.today().isoformat()

    account_id = f5e_db.upsert_account(
        con,
        source="zerodha",
        institution="Zerodha",
        external_id=user_id,
        currency="INR",
        account_type="demat",
        nickname=f"Zerodha {user_id}",
    )

    added = 0
    updated = 0
    for holding in payload.get("holdings", []):
        symbol = holding["tradingsymbol"]
        quantity = float(holding["quantity"])
        last_price = float(holding["last_price"])
        avg = holding.get("average_price")

        was_insert = f5e_db.upsert_holding(
            con,
            account_id=account_id,
            as_of_date=as_of_date,
            symbol=symbol,
            quantity=quantity,
            avg_cost=None if avg is None else float(avg),
            market_value=quantity * last_price,
            currency="INR",
            raw=holding,
        )
        if was_insert:
            added += 1
        else:
            updated += 1

    f5e_db.log_ingestion(con, "zerodha", added, updated, notes=path.name)
    con.commit()
    return added, updated


def _cli(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m f5e.ingest.zerodha_holdings <path>", file=sys.stderr)
        return 2
    con = f5e_db.connect()
    f5e_db.apply_schema(con)
    added, updated = ingest(con, argv[1])
    print(f"zerodha-holdings: +{added} new, ~{updated} updated")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
