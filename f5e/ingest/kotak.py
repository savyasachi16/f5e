"""Ingest a Kotak statement PDF into SQLite transactions.

Current parser target: statement text that extracts into rows shaped like:
  DD/MM/YYYY  DESCRIPTION  DEBIT|-  CREDIT|-  BALANCE
"""
from __future__ import annotations

import hashlib
import re
import sys
from datetime import datetime
from pathlib import Path

from f5e import db as f5e_db

ACCOUNT_PATTERNS = [
    re.compile(r"Account Statement Account #\s*([A-Z0-9*xX-]+)"),
    re.compile(r"Account(?:\s+No\.?|\s+Number)?\s*:?\s*([A-Z0-9*xX-]+)"),
]
ROW_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(.+)$")
NUMBERED_ROW_RE = re.compile(
    r"^(\d+)\s+(\d{2}\s+[A-Za-z]{3}\s+\d{4})\s+(\d{2}\s+[A-Za-z]{3}\s+\d{4})\s+"
    r"(.+?)\s+([+-][\d,]+\.\d{2})\s+([\d,]+\.\d{2})$"
)


def _extract_text(path: Path) -> str:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("pdfplumber is required for Kotak PDF ingestion") from exc

    parts: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if text:
                parts.append(text)
    return "\n".join(parts)


def _parse_amount(value: str) -> float | None:
    value = value.strip()
    if not value or value == "-":
        return None
    return float(value.replace(",", ""))


def _iso_date(value: str) -> str:
    if "/" in value:
        day, month, year = value.split("/")
        return f"{year}-{month}-{day}"
    return datetime.strptime(value, "%d %b %Y").strftime("%Y-%m-%d")


def _build_transaction(
    *,
    posted_date: str,
    description: str,
    amount: float,
    balance_amount: float | None,
    raw: object,
) -> dict[str, object]:
    digest = hashlib.sha1(
        f"{posted_date}|{description}|{amount}|{balance_amount}".encode()
    ).hexdigest()
    return {
        "source_uid": digest[:16],
        "posted_date": posted_date,
        "amount": amount,
        "currency": "INR",
        "description": description,
        "raw": {
            "source": raw,
            "balance": balance_amount,
        },
    }


def _extract_account_id(text: str) -> str:
    for pattern in ACCOUNT_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            return match.group(1)
    raise ValueError("could not find Kotak account number in statement text")


def _append_numbered_transaction(
    transactions: list[dict[str, object]],
    current: dict[str, object],
) -> None:
    description = " ".join(str(current["description"]).split())
    amount = _parse_amount(str(current["amount"]))
    transactions.append(
        _build_transaction(
            posted_date=_iso_date(str(current["posted_date"])),
            description=description,
            amount=amount,
            balance_amount=_parse_amount(str(current["balance"])),
            raw={
                "row_number": current["row_number"],
                "value_date": current["value_date"],
                "lines": current["lines"],
            },
        )
    )


def _parse_transactions(text: str) -> tuple[str, list[dict[str, object]]]:
    external_id = _extract_account_id(text)
    transactions: list[dict[str, object]] = []
    current_numbered: dict[str, object] | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        numbered_match = NUMBERED_ROW_RE.match(line)
        if numbered_match is not None:
            if current_numbered is not None:
                _append_numbered_transaction(transactions, current_numbered)
            row_number, posted_date, value_date, description, amount, balance = numbered_match.groups()
            current_numbered = {
                "row_number": row_number,
                "posted_date": posted_date,
                "value_date": value_date,
                "description": description,
                "amount": amount,
                "balance": balance,
                "lines": [raw_line],
            }
            continue

        if current_numbered is not None:
            if line.startswith("Statement generated on") or line.startswith("Account Statement "):
                _append_numbered_transaction(transactions, current_numbered)
                current_numbered = None
                continue
            if line.startswith("# TRANSACTION DATE") or line.startswith("Branch ") or line.startswith("CRN "):
                continue
            current_numbered["description"] = f"{current_numbered['description']} {line}"
            current_numbered["lines"].append(raw_line)
            continue

        match = ROW_RE.match(line)
        if match is None:
            continue

        posted_date, remainder = match.groups()
        columns = [part.strip() for part in re.split(r"\s{2,}", remainder) if part.strip()]
        if len(columns) < 4:
            continue

        description = " ".join(columns[:-3])
        debit, credit, balance = columns[-3:]
        debit_amount = _parse_amount(debit)
        credit_amount = _parse_amount(credit)
        balance_amount = _parse_amount(balance)

        if debit_amount is None and credit_amount is None:
            continue

        transactions.append(
            _build_transaction(
                posted_date=_iso_date(posted_date),
                description=description,
                amount=credit_amount if credit_amount is not None else -debit_amount,
                balance_amount=balance_amount,
                raw={"line": raw_line},
            )
        )

    if current_numbered is not None:
        _append_numbered_transaction(transactions, current_numbered)

    return external_id, transactions


def ingest(
    con,
    path: Path | str,
    *,
    institution: str = "Kotak Mahindra Bank",
    account_type: str = "savings",
) -> tuple[int, int]:
    path = Path(path)
    external_id, transactions = _parse_transactions(_extract_text(path))

    account_id = f5e_db.upsert_account(
        con,
        source="kotak",
        institution=institution,
        external_id=external_id,
        currency="INR",
        account_type=account_type,
    )

    added = 0
    updated = 0
    for txn in transactions:
        was_insert = f5e_db.upsert_transaction(con, account_id=account_id, **txn)
        if was_insert:
            added += 1
        else:
            updated += 1

    f5e_db.log_ingestion(con, "kotak", added, updated, notes=path.name)
    con.commit()
    return added, updated


def _cli(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m f5e.ingest.kotak <path-to-statement.pdf>", file=sys.stderr)
        return 2

    con = f5e_db.connect()
    f5e_db.apply_schema(con)
    added, updated = ingest(con, argv[1])
    print(f"kotak: +{added} new, ~{updated} updated")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
