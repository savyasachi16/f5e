"""MarketCheck price enrichment for manual US vehicle snapshots.

Cars use the VIN-based predict endpoint. Motorcycles fall back to the
average of active comparable listings (year/make/model), since the
predict endpoint doesn't support powersports VINs.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
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


def _http_get_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode())


def _fetch_car_price(asset: dict, *, api_key: str) -> dict[str, Any]:
    params = urllib.parse.urlencode({
        "vin": asset["vin"],
        "miles": int(asset["mileage"]),
        "car_zip": str(asset["zip"]),
        "car_type": asset.get("car_type", "used"),
        "api_key": api_key,
    })
    response = _http_get_json(f"https://mc-api.marketcheck.com/v2/predict/car/price?{params}")
    price = response.get("predicted_price")
    if price is None:
        raise ValueError(f"missing predicted_price in MarketCheck response for vin {asset['vin']}")
    return {"price": float(price), "raw": response}


def _fetch_motorcycle_price(asset: dict, *, api_key: str) -> dict[str, Any]:
    for field in ("year", "make", "model"):
        if field not in asset:
            raise ValueError(f"motorcycle asset {asset.get('name')} is missing {field}")
    params = urllib.parse.urlencode({
        "year": asset["year"],
        "make": asset["make"],
        "model": asset["model"],
        "rows": 50,
        "api_key": api_key,
    })
    response = _http_get_json(f"https://mc-api.marketcheck.com/v2/search/motorcycle/active?{params}")
    prices = [
        float(listing["price"]) for listing in response.get("listings", [])
        if listing.get("price") not in (None, 0)
    ]
    if not prices:
        raise ValueError(f"no comparable listings found for {asset.get('name')}")
    return {
        "price": statistics.median(prices),
        "raw": {"comparables": len(prices), "min": min(prices), "max": max(prices), "response_meta": {"num_found": response.get("num_found")}},
    }


def _default_fetcher(asset: dict, *, api_key: str) -> dict[str, Any]:
    vehicle_type = asset.get("vehicle_type", "car")
    if vehicle_type == "motorcycle":
        return _fetch_motorcycle_price(asset, api_key=api_key)
    if vehicle_type == "car":
        return _fetch_car_price(asset, api_key=api_key)
    raise ValueError(f"unsupported vehicle_type: {vehicle_type}")


def enrich_vehicles(
    *,
    input_path: Path | str,
    output_path: Path | str,
    api_key: str | None = None,
    fetcher: Fetcher = _default_fetcher,
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
        result = fetcher(asset, api_key=api_key)
        price = result.get("price")
        if price is None:
            raise ValueError(f"missing price for {asset.get('name')}")
        price = float(price)
        enriched.append({
            "source": "marketcheck",
            "asset_class": "vehicle",
            "name": asset["name"],
            "external_id": asset.get("vin"),
            "as_of_date": as_of_date,
            "currency": asset.get("currency", "USD"),
            "quantity": 1,
            "unit_price": price,
            "market_value": price,
            "notes": asset.get("notes"),
            "raw": {"input": asset, "fetch": result.get("raw")},
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
