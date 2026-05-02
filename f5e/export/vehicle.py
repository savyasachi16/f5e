"""MarketCheck price enrichment for manual US vehicle snapshots."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

Fetcher = Callable[..., dict[str, Any]]


def _load_assets(path: Path) -> list[dict]:
    payload = json.loads(path.read_text())
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("assets"), list):
        return payload["assets"]
    raise ValueError("vehicle payload must be a list or an object with an 'assets' list")


def _fetch_marketcheck_price(vin: str, mileage: int, zip_code: str, *, api_key: str) -> dict[str, Any]:
    params = urllib.parse.urlencode({
        "vin": vin,
        "miles": mileage,
        "car_zip": zip_code,
        "api_key": api_key,
    })
    request = urllib.request.Request(
        f"https://mc-api.marketcheck.com/v2/predict/car/marketcheck_price?{params}",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode())


def enrich_vehicles(
    *,
    input_path: Path | str,
    output_path: Path | str,
    api_key: str | None = None,
    fetcher: Fetcher = _fetch_marketcheck_price,
    as_of_date: str | None = None,
) -> dict[str, int]:
    api_key = api_key or os.getenv("MARKETCHECK_API_KEY")
    if not api_key:
        raise ValueError("MARKETCHECK_API_KEY is required")

    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    as_of_date = as_of_date or dt.date.today().isoformat()
    assets = _load_assets(input_path)

    enriched: list[dict] = []
    for asset in assets:
        vin = asset["vin"]
        mileage = int(asset["mileage"])
        zip_code = str(asset["zip"])
        response = fetcher(vin, mileage, zip_code, api_key=api_key)
        price = response.get("price")
        if price is None:
            raise ValueError(f"missing price in MarketCheck response for vin {vin}")
        price = float(price)
        enriched.append({
            "source": "marketcheck",
            "asset_class": "vehicle",
            "name": asset["name"],
            "external_id": vin,
            "as_of_date": as_of_date,
            "currency": asset.get("currency", "USD"),
            "quantity": 1,
            "unit_price": price,
            "market_value": price,
            "notes": asset.get("notes"),
            "raw": {"input": asset, "response": response},
        })

    output_path.write_text(json.dumps({"assets": enriched}, separators=(",", ":")))
    return {"assets": len(enriched)}


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m f5e.export.vehicle")
    parser.add_argument("input_path")
    parser.add_argument("output_path")
    parser.add_argument("--api-key")
    parser.add_argument("--as-of-date")
    args = parser.parse_args(argv[1:])

    result = enrich_vehicles(
        input_path=args.input_path,
        output_path=args.output_path,
        api_key=args.api_key,
        as_of_date=args.as_of_date,
    )
    print(f"vehicle-export: {result['assets']} vehicles priced")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
