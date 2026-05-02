"""CoinMarketCap quote enrichment for manual crypto holdings snapshots."""
from __future__ import annotations

import argparse
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
    raise ValueError("crypto holdings payload must be a list or an object with an 'assets' list")


def _fetch_quotes(symbols: list[str], *, api_key: str, convert: str) -> dict[str, Any]:
    params = urllib.parse.urlencode({"symbol": ",".join(symbols), "convert": convert})
    request = urllib.request.Request(
        f"https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest?{params}",
        headers={"X-CMC_PRO_API_KEY": api_key, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request) as response:
        payload = json.loads(response.read().decode())
    return payload["data"]


def _quote_entry(data: dict[str, Any], symbol: str) -> dict[str, Any]:
    entry = data.get(symbol)
    if entry is None:
        raise ValueError(f"missing quote for symbol {symbol}")
    if isinstance(entry, list):
        if not entry:
            raise ValueError(f"missing quote for symbol {symbol}")
        return entry[0]
    return entry


def enrich_holdings(
    *,
    input_path: Path | str,
    output_path: Path | str,
    api_key: str | None = None,
    fetcher: Fetcher = _fetch_quotes,
    convert: str = "USD",
) -> dict[str, int]:
    api_key = api_key or os.getenv("CMC_API_KEY")
    if not api_key:
        raise ValueError("CMC_API_KEY is required")

    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    assets = _load_assets(input_path)
    symbols = sorted({asset["symbol"] for asset in assets})
    quotes = fetcher(symbols, api_key=api_key, convert=convert)

    enriched: list[dict] = []
    for asset in assets:
        symbol = asset["symbol"]
        entry = _quote_entry(quotes, symbol)
        unit_price = float(entry["quote"][convert]["price"])
        quantity = float(asset["quantity"])
        enriched.append(
            {
                **asset,
                "source": "cmc",
                "currency": convert,
                "unit_price": unit_price,
                "market_value": quantity * unit_price,
                "raw": {"input": asset, "quote": entry},
            }
        )

    output_path.write_text(json.dumps({"assets": enriched}, separators=(",", ":")))
    return {"assets": len(enriched), "symbols": len(symbols)}


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m f5e.export.cmc")
    parser.add_argument("input_path")
    parser.add_argument("output_path")
    parser.add_argument("--api-key")
    parser.add_argument("--convert", default="USD")
    args = parser.parse_args(argv[1:])

    result = enrich_holdings(
        input_path=args.input_path,
        output_path=args.output_path,
        api_key=args.api_key,
        convert=args.convert,
    )
    print(f"cmc-export: {result['assets']} assets across {result['symbols']} symbols")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
