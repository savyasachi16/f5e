"""Ingest manual asset snapshots into SQLite."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from f5e import db as f5e_db

ASSET_CLASSES = {
    "vehicle",
    "private_equity",
    "crypto",
    "brokerage",   # aggregated holdings without per-position detail
    "ulip",        # insurance-linked investment plan
    "cash",        # cash account snapshot (no transaction-level detail)
    "real_estate",
}


def _load_payload(path: Path) -> list[dict]:
    payload = json.loads(path.read_text())
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("assets"), list):
        return payload["assets"]
    raise ValueError("asset payload must be a list or an object with an 'assets' list")


def _normalize_snapshot(record: dict) -> dict:
    asset_class = record["asset_class"]
    if asset_class not in ASSET_CLASSES:
        raise ValueError(f"unsupported asset_class: {asset_class}")

    name = record["name"]
    as_of_date = record["as_of_date"]
    currency = record["currency"]
    quantity = record.get("quantity")
    unit_price = record.get("unit_price")
    market_value = record.get("market_value")

    if asset_class == "crypto" and quantity is None:
        raise ValueError(f"crypto asset {name} is missing quantity")
    if market_value is None:
        if quantity is not None and unit_price is not None:
            market_value = float(quantity) * float(unit_price)
        else:
            raise ValueError(f"asset {name} is missing market_value")

    return {
        "source": record.get("source") or "manual",
        "asset_class": asset_class,
        "name": name,
        "external_id": record.get("external_id"),
        "currency": currency,
        "notes": record.get("notes"),
        "as_of_date": as_of_date,
        "quantity": None if quantity is None else float(quantity),
        "unit_price": None if unit_price is None else float(unit_price),
        "market_value": float(market_value),
        "raw": record,
    }


def ingest(con, path: Path | str) -> tuple[int, int]:
    path = Path(path)
    snapshots = [_normalize_snapshot(record) for record in _load_payload(path)]

    added = 0
    updated = 0
    for snapshot in snapshots:
        asset_id = f5e_db.upsert_asset(
            con,
            source=snapshot["source"],
            asset_class=snapshot["asset_class"],
            name=snapshot["name"],
            external_id=snapshot["external_id"],
            currency=snapshot["currency"],
            notes=snapshot["notes"],
        )
        was_insert = f5e_db.upsert_asset_snapshot(
            con,
            asset_id=asset_id,
            as_of_date=snapshot["as_of_date"],
            quantity=snapshot["quantity"],
            unit_price=snapshot["unit_price"],
            market_value=snapshot["market_value"],
            currency=snapshot["currency"],
            raw=snapshot["raw"],
        )
        if was_insert:
            added += 1
        else:
            updated += 1

    f5e_db.log_ingestion(con, "assets", added, updated, notes=path.name)
    con.commit()
    return added, updated


def _cli(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m f5e.ingest.assets <path-to-assets.json>", file=sys.stderr)
        return 2
    con = f5e_db.connect()
    f5e_db.apply_schema(con)
    added, updated = ingest(con, argv[1])
    print(f"assets: +{added} new, ~{updated} updated")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
