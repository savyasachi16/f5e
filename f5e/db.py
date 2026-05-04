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


def _asset_row(
    con: sqlite3.Connection,
    *,
    source: str,
    asset_class: str,
    name: str,
    external_id: str | None,
) -> sqlite3.Row | None:
    if external_id is not None:
        return con.execute(
            """
            SELECT id
            FROM assets
            WHERE source = ? AND asset_class = ? AND external_id = ?
            """,
            (source, asset_class, external_id),
        ).fetchone()
    return con.execute(
        """
        SELECT id
        FROM assets
        WHERE source = ? AND asset_class = ? AND name = ? AND external_id IS NULL
        """,
        (source, asset_class, name),
    ).fetchone()


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


def upsert_holding(
    con: sqlite3.Connection,
    *,
    account_id: int,
    as_of_date: str,
    symbol: str,
    quantity: float,
    avg_cost: float | None = None,
    market_value: float | None = None,
    currency: str,
    raw: Any = None,
) -> bool:
    row = con.execute(
        "SELECT 1 FROM holdings WHERE account_id = ? AND as_of_date = ? AND symbol = ?",
        (account_id, as_of_date, symbol),
    ).fetchone()
    inserted = row is None
    con.execute(
        """
        INSERT INTO holdings
          (account_id, as_of_date, symbol, quantity, avg_cost, market_value, currency, raw)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_id, as_of_date, symbol) DO UPDATE SET
          quantity = excluded.quantity,
          avg_cost = excluded.avg_cost,
          market_value = excluded.market_value,
          currency = excluded.currency,
          raw = excluded.raw
        """,
        (
            account_id, as_of_date, symbol, float(quantity),
            None if avg_cost is None else float(avg_cost),
            None if market_value is None else float(market_value),
            currency, _maybe_json(raw),
        ),
    )
    return inserted


def upsert_asset(
    con: sqlite3.Connection,
    *,
    source: str,
    asset_class: str,
    name: str,
    currency: str,
    external_id: str | None = None,
    notes: str | None = None,
) -> int:
    row = _asset_row(
        con,
        source=source,
        asset_class=asset_class,
        name=name,
        external_id=external_id,
    )
    if row is None:
        con.execute(
            """
            INSERT INTO assets (source, asset_class, name, external_id, currency, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (source, asset_class, name, external_id, currency, notes),
        )
    else:
        con.execute(
            """
            UPDATE assets
            SET name = ?, external_id = ?, currency = ?, notes = ?
            WHERE id = ?
            """,
            (name, external_id, currency, notes, row["id"]),
        )

    row = _asset_row(
        con,
        source=source,
        asset_class=asset_class,
        name=name,
        external_id=external_id,
    )
    return row["id"]


def upsert_asset_snapshot(
    con: sqlite3.Connection,
    *,
    asset_id: int,
    as_of_date: str,
    market_value: float,
    currency: str,
    quantity: float | None = None,
    unit_price: float | None = None,
    raw: Any = None,
) -> bool:
    row = con.execute(
        "SELECT 1 FROM asset_snapshots WHERE asset_id = ? AND as_of_date = ?",
        (asset_id, as_of_date),
    ).fetchone()
    inserted = row is None
    con.execute(
        """
        INSERT INTO asset_snapshots
          (asset_id, as_of_date, quantity, unit_price, market_value, currency, raw)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(asset_id, as_of_date) DO UPDATE SET
          quantity = excluded.quantity,
          unit_price = excluded.unit_price,
          market_value = excluded.market_value,
          currency = excluded.currency,
          raw = excluded.raw
        """,
        (
            asset_id,
            as_of_date,
            None if quantity is None else float(quantity),
            None if unit_price is None else float(unit_price),
            float(market_value),
            currency,
            _maybe_json(raw),
        ),
    )
    return inserted


def upsert_balance(
    con: sqlite3.Connection,
    *,
    account_id: int,
    as_of_date: str,
    currency: str,
    current: float | None = None,
    available: float | None = None,
    limit_amount: float | None = None,
    raw: Any = None,
) -> bool:
    row = con.execute(
        "SELECT 1 FROM balances WHERE account_id = ? AND as_of_date = ?",
        (account_id, as_of_date),
    ).fetchone()
    inserted = row is None
    con.execute(
        """
        INSERT INTO balances
          (account_id, as_of_date, current, available, limit_amount, currency, raw)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_id, as_of_date) DO UPDATE SET
          current = excluded.current,
          available = excluded.available,
          limit_amount = excluded.limit_amount,
          currency = excluded.currency,
          raw = excluded.raw
        """,
        (
            account_id, as_of_date,
            None if current is None else float(current),
            None if available is None else float(available),
            None if limit_amount is None else float(limit_amount),
            currency, _maybe_json(raw),
        ),
    )
    return inserted


def log_ingestion(con: sqlite3.Connection, source: str, added: int, updated: int, notes: str = "") -> None:
    con.execute(
        "INSERT INTO ingestion_log (source, rows_added, rows_updated, notes) VALUES (?, ?, ?, ?)",
        (source, added, updated, notes),
    )
