"""SQLite connection + schema + upsert helpers. Stdlib-only."""
import json
import sqlite3
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "data" / "finances.db"
SCHEMA_PATH = REPO_ROOT / "db" / "schema.sql"


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    target = Path(path) if path is not None else DB_PATH
    if target != Path(":memory:") and str(target) != ":memory:":
        target.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(target)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def apply_schema(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA_PATH.read_text())


def _maybe_json(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    return json.dumps(raw, default=str, separators=(",", ":"))


def upsert_account(
    con: sqlite3.Connection,
    *,
    source: str,
    institution: str,
    external_id: str,
    currency: str,
    account_type: str | None = None,
    nickname: str | None = None,
) -> int:
    con.execute(
        """
        INSERT INTO accounts (source, institution, external_id, account_type, currency, nickname)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, external_id) DO UPDATE SET
          institution = excluded.institution,
          account_type = excluded.account_type,
          currency = excluded.currency,
          nickname = excluded.nickname
        """,
        (source, institution, external_id, account_type, currency, nickname),
    )
    row = con.execute(
        "SELECT id FROM accounts WHERE source = ? AND external_id = ?",
        (source, external_id),
    ).fetchone()
    return row["id"]


def _exists(con: sqlite3.Connection, table: str, account_id: int, source_uid: str) -> bool:
    row = con.execute(
        f"SELECT 1 FROM {table} WHERE account_id = ? AND source_uid = ?",
        (account_id, source_uid),
    ).fetchone()
    return row is not None


def upsert_trade(
    con: sqlite3.Connection,
    *,
    account_id: int,
    source_uid: str,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    currency: str,
    executed_at: str,
    segment: str | None = None,
    raw: Any = None,
) -> bool:
    """Returns True if a new row was inserted, False if it already existed."""
    inserted = not _exists(con, "trades", account_id, source_uid)
    con.execute(
        """
        INSERT INTO trades
          (account_id, source_uid, symbol, side, quantity, price, currency, executed_at, segment, raw)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_id, source_uid) DO UPDATE SET
          symbol = excluded.symbol,
          side = excluded.side,
          quantity = excluded.quantity,
          price = excluded.price,
          currency = excluded.currency,
          executed_at = excluded.executed_at,
          segment = excluded.segment,
          raw = excluded.raw
        """,
        (
            account_id, source_uid, symbol, side, float(quantity), float(price),
            currency, executed_at, segment, _maybe_json(raw),
        ),
    )
    return inserted


def upsert_transaction(
    con: sqlite3.Connection,
    *,
    account_id: int,
    source_uid: str,
    posted_date: str,
    amount: float,
    currency: str,
    description: str | None = None,
    category: str | None = None,
    raw: Any = None,
) -> bool:
    inserted = not _exists(con, "transactions", account_id, source_uid)
    con.execute(
        """
        INSERT INTO transactions
          (account_id, source_uid, posted_date, amount, currency, description, category, raw)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_id, source_uid) DO UPDATE SET
          posted_date = excluded.posted_date,
          amount = excluded.amount,
          currency = excluded.currency,
          description = excluded.description,
          category = excluded.category,
          raw = excluded.raw
        """,
        (
            account_id, source_uid, posted_date, float(amount), currency,
            description, category, _maybe_json(raw),
        ),
    )
    return inserted


def log_ingestion(con: sqlite3.Connection, source: str, added: int, updated: int, notes: str = "") -> None:
    con.execute(
        "INSERT INTO ingestion_log (source, rows_added, rows_updated, notes) VALUES (?, ?, ?, ?)",
        (source, added, updated, notes),
    )
