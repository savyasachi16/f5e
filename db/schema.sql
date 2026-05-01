-- f5e SQLite schema. Idempotent: safe to re-apply.

CREATE TABLE IF NOT EXISTS accounts (
  id              INTEGER PRIMARY KEY,
  source          TEXT NOT NULL,
  institution     TEXT NOT NULL,
  external_id     TEXT NOT NULL,
  account_type    TEXT,
  currency        TEXT NOT NULL,
  nickname        TEXT,
  UNIQUE(source, external_id)
);

CREATE TABLE IF NOT EXISTS transactions (
  id              INTEGER PRIMARY KEY,
  account_id      INTEGER NOT NULL REFERENCES accounts(id),
  source_uid      TEXT NOT NULL,
  posted_date     TEXT NOT NULL,
  amount          REAL NOT NULL,
  currency        TEXT NOT NULL,
  description     TEXT,
  category        TEXT,
  raw             TEXT,
  ingested_at     TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(account_id, source_uid)
);

CREATE TABLE IF NOT EXISTS trades (
  id              INTEGER PRIMARY KEY,
  account_id      INTEGER NOT NULL REFERENCES accounts(id),
  source_uid      TEXT NOT NULL,
  symbol          TEXT NOT NULL,
  side            TEXT NOT NULL CHECK(side IN ('buy','sell')),
  quantity        REAL NOT NULL,
  price           REAL NOT NULL,
  currency        TEXT NOT NULL,
  executed_at     TEXT NOT NULL,
  segment         TEXT,
  raw             TEXT,
  UNIQUE(account_id, source_uid)
);

CREATE TABLE IF NOT EXISTS holdings (
  id              INTEGER PRIMARY KEY,
  account_id      INTEGER NOT NULL REFERENCES accounts(id),
  as_of_date      TEXT NOT NULL,
  symbol          TEXT NOT NULL,
  quantity        REAL NOT NULL,
  avg_cost        REAL,
  market_value    REAL,
  currency        TEXT NOT NULL,
  raw             TEXT,
  UNIQUE(account_id, as_of_date, symbol)
);

CREATE TABLE IF NOT EXISTS ingestion_log (
  id              INTEGER PRIMARY KEY,
  source          TEXT NOT NULL,
  ran_at          TEXT NOT NULL DEFAULT (datetime('now')),
  rows_added      INTEGER,
  rows_updated    INTEGER,
  notes           TEXT
);

CREATE INDEX IF NOT EXISTS ix_txn_date    ON transactions(posted_date);
CREATE INDEX IF NOT EXISTS ix_txn_account ON transactions(account_id);
CREATE INDEX IF NOT EXISTS ix_trade_sym   ON trades(symbol, executed_at);
