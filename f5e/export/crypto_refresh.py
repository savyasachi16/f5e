"""Daily crypto refresh — re-prices existing crypto assets via CoinGecko.

Reads the latest snapshot per crypto asset from the DB, fetches today's
USD prices from CoinGecko's free public API (no key needed), and writes
an asset-snapshot JSON ready for `python -m f5e.ingest.assets`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from f5e import db as f5e_db

Fetcher = Callable[[list[str]], dict[str, float]]

# repo symbol → CoinGecko id (extend as new coins land in the DB)
SYMBOL_TO_COINGECKO_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "LTC": "litecoin",
    "LINK": "chainlink",
    "POL": "polygon-ecosystem-token",
    "MATIC": "matic-network",
    "SOL": "solana",
    "USDC": "usd-coin",
    "USDT": "tether",
}


def fetch_coingecko_prices(symbols: list[str]) -> dict[str, float]:
    ids = []
    id_to_symbol: dict[str, str] = {}
    for sym in symbols:
        cg_id = SYMBOL_TO_COINGECKO_ID.get(sym)
        if not cg_id:
            raise ValueError(f"no CoinGecko id mapping for symbol {sym}")
        ids.append(cg_id)
        id_to_symbol[cg_id] = sym
    params = urllib.parse.urlencode({"ids": ",".join(ids), "vs_currencies": "usd"})
    request = urllib.request.Request(
        f"https://api.coingecko.com/api/v3/simple/price?{params}",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode())
    return {id_to_symbol[cg_id]: float(quote["usd"]) for cg_id, quote in payload.items()}


def _latest_crypto_holdings(con) -> list[dict]:
    rows = con.execute(
        """
        SELECT a.id AS asset_id, a.name, a.source, a.external_id AS symbol, a.currency,
               s.quantity, s.as_of_date
        FROM assets a
        JOIN asset_snapshots s ON s.asset_id = a.id
        JOIN (
          SELECT asset_id, MAX(as_of_date) AS d FROM asset_snapshots GROUP BY 1
        ) latest ON latest.asset_id = a.id AND latest.d = s.as_of_date
        WHERE a.asset_class = 'crypto' AND a.external_id IS NOT NULL
        ORDER BY a.external_id
        """
    ).fetchall()
    return [dict(r) for r in rows]


def refresh(
    con,
    *,
    output_path: Path | str,
    fetcher: Fetcher = fetch_coingecko_prices,
    as_of_date: str | None = None,
) -> dict[str, int]:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    as_of_date = as_of_date or dt.date.today().isoformat()

    holdings = _latest_crypto_holdings(con)
    if not holdings:
        output_path.write_text(json.dumps({"assets": []}, separators=(",", ":")))
        return {"assets": 0}

    symbols = sorted({h["symbol"] for h in holdings})
    prices = fetcher(symbols)

    enriched: list[dict] = []
    for h in holdings:
        sym = h["symbol"]
        if sym not in prices:
            raise ValueError(f"no price returned for {sym}")
        price = float(prices[sym])
        qty = float(h["quantity"]) if h["quantity"] is not None else 0.0
        enriched.append({
            # preserve the existing asset's source so we update the same row
            # rather than creating a parallel "coingecko" asset
            "source": h["source"],
            "asset_class": "crypto",
            "name": h["name"],
            "external_id": sym,
            "as_of_date": as_of_date,
            "currency": "USD",
            "quantity": qty,
            "unit_price": price,
            "market_value": qty * price,
            "notes": "priced via CoinGecko",
        })

    output_path.write_text(json.dumps({"assets": enriched}, separators=(",", ":")))
    return {"assets": len(enriched)}


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m f5e.export.crypto_refresh")
    parser.add_argument("output_path")
    parser.add_argument("--as-of-date")
    args = parser.parse_args(argv[1:])

    con = f5e_db.connect()
    f5e_db.apply_schema(con)
    result = refresh(con, output_path=args.output_path, as_of_date=args.as_of_date)
    print(f"crypto-refresh: {result['assets']} assets priced via CoinGecko")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
