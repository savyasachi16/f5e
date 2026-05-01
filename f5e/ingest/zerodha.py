"""Ingest a Zerodha Console tradebook JSON dump into SQLite.

Input shape: list of trade dicts as produced by Console's
`/api/reports/tradebook?...` endpoint. Each trade has at minimum:
  trade_id, trade_type ('buy'|'sell'), tradingsymbol, quantity, price,
  order_execution_time, segment.
"""
import json
import sys
from pathlib import Path

from f5e import db as f5e_db


def ingest(
    con,
    path: Path | str,
    *,
    external_id: str = "default",
    institution: str = "Zerodha",
) -> tuple[int, int]:
    """Returns (rows_added, rows_updated)."""
    path = Path(path)
    trades = json.loads(path.read_text())

    account_id = f5e_db.upsert_account(
        con,
        source="zerodha",
        institution=institution,
        external_id=external_id,
        currency="INR",
        account_type="brokerage",
    )

    added = 0
    updated = 0
    for t in trades:
        # trade_id alone collides across orders in Zerodha exports; combine with order_id.
        was_insert = f5e_db.upsert_trade(
            con,
            account_id=account_id,
            source_uid=f"{t['order_id']}:{t['trade_id']}",
            symbol=t["tradingsymbol"],
            side=t["trade_type"],
            quantity=t["quantity"],
            price=t["price"],
            currency="INR",
            executed_at=t["order_execution_time"],
            segment=t.get("segment"),
            raw=t,
        )
        if was_insert:
            added += 1
        else:
            updated += 1

    f5e_db.log_ingestion(con, "zerodha", added, updated, notes=str(path.name))
    con.commit()
    return added, updated


def _cli(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m f5e.ingest.zerodha <path-to-trades.json> [external_id]", file=sys.stderr)
        return 2
    path = argv[1]
    external_id = argv[2] if len(argv) > 2 else "default"
    con = f5e_db.connect()
    f5e_db.apply_schema(con)
    added, updated = ingest(con, path, external_id=external_id)
    print(f"zerodha: +{added} new, ~{updated} updated")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
