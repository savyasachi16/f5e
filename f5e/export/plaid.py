"""Paginated Plaid CLI export helper."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

Runner = Callable[..., subprocess.CompletedProcess[str]]

PRODUCTS: dict[str, dict[str, Any]] = {
    "transactions": {
        "record_key": "transactions",
        "command": ["plaid", "transactions", "list"],
        "dedupe_keys": {"accounts": "account_id"},
    },
    "investment_transactions": {
        "record_key": "investment_transactions",
        "command": ["plaid", "investments", "transactions"],
        "dedupe_keys": {"accounts": "account_id", "securities": "security_id"},
    },
}


def _load_cli_payload_text(text: str) -> dict:
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
                key in obj for key in ("accounts", "transactions", "investment_transactions", "securities", "item")
            ):
                payload = obj
        if payload is None:
            raise
        return payload


def _dedupe_rows(rows: list[dict], key: str) -> list[dict]:
    seen: dict[str, dict] = {}
    for row in rows:
        seen[row[key]] = row
    return list(seen.values())


def _merge_payloads(product: str, payloads: list[dict]) -> dict:
    if not payloads:
        raise ValueError("no payloads to merge")

    config = PRODUCTS[product]
    record_key = config["record_key"]
    merged = dict(payloads[0])
    merged[record_key] = []

    for payload in payloads:
        merged[record_key].extend(payload.get(record_key, []))

    for field, key in config["dedupe_keys"].items():
        if field in merged:
            rows: list[dict] = []
            for payload in payloads:
                rows.extend(payload.get(field, []))
            merged[field] = _dedupe_rows(rows, key)

    if record_key == "transactions":
        merged["total_transactions"] = len(merged[record_key])

    return merged


def export_paginated(
    *,
    product: str,
    item: str,
    start_date: str,
    end_date: str,
    output_path: Path | str,
    page_size: int = 100,
    runner: Runner = subprocess.run,
) -> dict[str, int]:
    if product not in PRODUCTS:
        raise ValueError(f"unsupported product: {product}")

    config = PRODUCTS[product]
    record_key = config["record_key"]
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payloads: list[dict] = []
    offset = 0

    while True:
        args = [
            *config["command"],
            "--item", item,
            "--start-date", start_date,
            "--end-date", end_date,
            "--count", str(page_size),
            "--offset", str(offset),
            "--json",
        ]
        result = runner(args, capture_output=True, text=True, check=True)
        payload = _load_cli_payload_text(result.stdout)
        payloads.append(payload)

        page_records = payload.get(record_key, [])
        if len(page_records) < page_size:
            break
        offset += page_size

    merged = _merge_payloads(product, payloads)
    output_path.write_text(json.dumps(merged, separators=(",", ":")))
    return {"pages": len(payloads), "records": len(merged.get(record_key, []))}


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m f5e.export.plaid")
    parser.add_argument("product", choices=sorted(PRODUCTS))
    parser.add_argument("item")
    parser.add_argument("start_date")
    parser.add_argument("end_date")
    parser.add_argument("output_path")
    parser.add_argument("--page-size", type=int, default=100)
    args = parser.parse_args(argv[1:])

    result = export_paginated(
        product=args.product,
        item=args.item,
        start_date=args.start_date,
        end_date=args.end_date,
        output_path=args.output_path,
        page_size=args.page_size,
    )
    print(f"plaid-export: {result['records']} rows across {result['pages']} pages")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
