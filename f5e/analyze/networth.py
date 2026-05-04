"""Compute net worth from latest balances + asset snapshots + (fallback) holdings.

Combines per-account latest balance, per-asset latest snapshot, and per-account
holdings (only when no balance exists for that account, since balance.current
already includes the brokerage market value). FX-converts all rows to a single
display currency using a passed-in rates dict (default USD only).
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from typing import Any

from f5e import db as f5e_db


# Buckets, ordered for display
_ACCOUNT_TYPE_BUCKETS: dict[str, str] = {
    "checking": "cash",
    "savings": "cash",
    "money market": "cash",
    "cd": "cash",
    "cash management": "cash",
    "hsa": "cash",
    "credit card": "liabilities",
    "loan": "liabilities",
    "mortgage": "liabilities",
    "student": "liabilities",
    "brokerage": "brokerage",
    "stock plan": "brokerage",
    "ira": "retirement",
    "401k": "retirement",
    "403b": "retirement",
    "pension": "retirement",
}

_ASSET_CLASS_BUCKETS: dict[str, str] = {
    "vehicle": "vehicles",
    "private_equity": "private equity",
    "crypto": "crypto",
}

_BUCKET_ORDER = ["cash", "brokerage", "retirement", "vehicles", "private equity", "crypto", "liabilities", "other"]


def _bucket_for_account(account_type: str | None) -> str:
    if not account_type:
        return "other"
    return _ACCOUNT_TYPE_BUCKETS.get(account_type.lower(), "other")


def _convert(amount: float, currency: str, rates: dict[str, float], display: str) -> float:
    if currency == display:
        return amount
    rate = rates.get(currency)
    if rate is None:
        raise ValueError(f"missing FX rate for {currency} -> {display}")
    return amount * rate


def collect(con, *, rates: dict[str, float] | None = None, display_currency: str = "USD") -> dict[str, Any]:
    rates = rates or {}
    rows: list[dict] = []

    # latest balance per account
    balance_rows = con.execute(
        """
        SELECT a.id, a.institution, a.account_type, a.nickname, a.currency AS acct_ccy,
               b.current, b.currency AS bal_ccy, b.as_of_date
        FROM balances b
        JOIN accounts a ON a.id = b.account_id
        JOIN (
          SELECT account_id, MAX(as_of_date) AS d FROM balances GROUP BY 1
        ) latest ON latest.account_id = b.account_id AND latest.d = b.as_of_date
        WHERE b.current IS NOT NULL
        """
    ).fetchall()

    accounts_with_balance = set()
    for r in balance_rows:
        accounts_with_balance.add(r["id"])
        bucket = _bucket_for_account(r["account_type"])
        amount = float(r["current"])
        # credit-card "current" is debt → flip sign so liabilities subtract
        if bucket == "liabilities":
            amount = -amount
        rows.append({
            "bucket": bucket,
            "label": f"{r['institution']} — {r['nickname'] or r['account_type']}",
            "currency": r["bal_ccy"],
            "amount": amount,
            "amount_display": _convert(amount, r["bal_ccy"], rates, display_currency),
            "as_of": r["as_of_date"],
            "source": "balance",
        })

    # holdings — only for accounts WITHOUT a balance row (avoid double-count)
    holding_rows = con.execute(
        """
        SELECT a.id, a.institution, a.account_type, a.nickname,
               h.symbol, h.market_value, h.currency, h.as_of_date
        FROM holdings h
        JOIN accounts a ON a.id = h.account_id
        JOIN (
          SELECT account_id, symbol, MAX(as_of_date) AS d FROM holdings GROUP BY 1, 2
        ) latest ON latest.account_id = h.account_id AND latest.symbol = h.symbol AND latest.d = h.as_of_date
        WHERE h.market_value IS NOT NULL
        """
    ).fetchall()
    for r in holding_rows:
        if r["id"] in accounts_with_balance:
            continue
        bucket = _bucket_for_account(r["account_type"])
        amount = float(r["market_value"])
        rows.append({
            "bucket": bucket,
            "label": f"{r['institution']} — {r['symbol']}",
            "currency": r["currency"],
            "amount": amount,
            "amount_display": _convert(amount, r["currency"], rates, display_currency),
            "as_of": r["as_of_date"],
            "source": "holding",
        })

    # asset snapshots — latest per asset
    asset_rows = con.execute(
        """
        SELECT a.asset_class, a.name, s.market_value, s.currency, s.as_of_date
        FROM assets a
        JOIN asset_snapshots s ON s.asset_id = a.id
        JOIN (
          SELECT asset_id, MAX(as_of_date) AS d FROM asset_snapshots GROUP BY 1
        ) latest ON latest.asset_id = a.id AND latest.d = s.as_of_date
        """
    ).fetchall()
    for r in asset_rows:
        bucket = _ASSET_CLASS_BUCKETS.get(r["asset_class"], "other")
        amount = float(r["market_value"])
        rows.append({
            "bucket": bucket,
            "label": r["name"],
            "currency": r["currency"],
            "amount": amount,
            "amount_display": _convert(amount, r["currency"], rates, display_currency),
            "as_of": r["as_of_date"],
            "source": "asset",
        })

    by_bucket: dict[str, float] = defaultdict(float)
    for r in rows:
        by_bucket[r["bucket"]] += r["amount_display"]

    total = sum(by_bucket.values())
    return {
        "rows": rows,
        "by_bucket": dict(by_bucket),
        "total": total,
        "display_currency": display_currency,
    }


def render(report: dict[str, Any]) -> str:
    display = report["display_currency"]
    lines = []
    for bucket in _BUCKET_ORDER:
        bucket_rows = [r for r in report["rows"] if r["bucket"] == bucket]
        if not bucket_rows:
            continue
        subtotal = report["by_bucket"].get(bucket, 0.0)
        lines.append(f"\n[{bucket.upper()}]  subtotal: {subtotal:>14,.2f} {display}")
        for r in sorted(bucket_rows, key=lambda x: -abs(x["amount_display"])):
            ccy_note = "" if r["currency"] == display else f" ({r['amount']:,.2f} {r['currency']})"
            lines.append(f"  {r['amount_display']:>12,.2f}  {r['label']}  [{r['as_of']}]{ccy_note}")
    lines.append(f"\nNET WORTH: {report['total']:>14,.2f} {display}")
    return "\n".join(lines)


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m f5e.analyze.networth")
    parser.add_argument("--display", default="USD")
    parser.add_argument("--inr-per-usd", type=float, help="INR amount per 1 USD (e.g. 83.5)")
    args = parser.parse_args(argv[1:])

    rates: dict[str, float] = {}
    if args.inr_per_usd:
        rates["INR"] = 1.0 / args.inr_per_usd  # multiply INR amount by this to get USD

    con = f5e_db.connect()
    f5e_db.apply_schema(con)
    report = collect(con, rates=rates, display_currency=args.display)
    print(render(report))
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
