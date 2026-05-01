---
name: plaid-export
description: Pull US account data through Plaid's official CLI, persist raw JSON under data/raw/plaid, then ingest it into SQLite. Use when the user asks to sync Plaid, fetch US accounts, or import transactions from a linked US institution.
allowed-tools:
  - Bash
  - Read
  - Write
---

# /plaid-export — Plaid CLI Export + SQLite Ingest

Use Plaid's official CLI for the US side of this repo. Raw API responses go under `data/raw/plaid/`; normalized rows land in `data/finances.db` through `python -m f5e.ingest.plaid`.

## Prerequisites

- `plaid` CLI installed:
  `brew install plaid/plaid-cli/plaid`
- `op` CLI authed
- Plaid account registered:
  `plaid register`
- Plaid **Trial Plan** approved in the dashboard so real institutions are allowed
- 1Password entry titled `Plaid` with:
  - `client_id`
  - `secret`
  - one field per linked item access token, e.g. `chase_token`, `schwab_token`

## Link a new institution

1. Run `plaid link`
2. Complete the browser-based Link flow
3. Save the returned `access_token` into the `Plaid` 1Password item under a clear field name

## Export transactions

Suggested layout:

```text
data/raw/plaid/<institution>/<YYYY-MM-DD>-transactions.json
```

Example:

```bash
mkdir -p data/raw/plaid/chase
plaid transactions get \
  --access-token "$(op item get Plaid --vault Private --fields chase_token --reveal)" \
  > "data/raw/plaid/chase/$(date +%F)-transactions.json"
```

If the CLI needs explicit app credentials in your environment, pull them from 1Password first and export them in the current shell before running `plaid ...`.

## Ingest into SQLite

```bash
python -m f5e.ingest.plaid data/raw/plaid/chase/2026-05-01-transactions.json
```

Current ingester behavior:

- creates/updates `accounts` rows with `source='plaid'`
- ingests `transactions`
- flips Plaid amount signs to repo convention:
  - Plaid `+amount` = money out
  - repo `+amount` = money in
- preserves account/transaction currency at row level
- logs the run in `ingestion_log`

## Expected input shape

The ingester expects one JSON object containing:

```json
{
  "institution": {"name": "Chase"},
  "accounts": [...],
  "transactions": [...]
}
```

That matches the synthetic test fixture and keeps the file self-contained for re-ingest.

## Verification

```bash
uv run pytest tests/ingest/test_plaid.py -q
sqlite3 data/finances.db "
  SELECT a.institution, COUNT(*)
  FROM transactions t
  JOIN accounts a ON a.id = t.account_id
  WHERE a.source = 'plaid'
  GROUP BY 1
"
```

## Gotchas

- Plaid amount signs are inverted relative to this repo. Never insert raw `amount` as-is.
- If a transaction references an `account_id` absent from the same payload, ingest should fail loudly instead of creating a partial import.
- Keep raw exports out of git. `data/raw/` is already ignored; don't move files elsewhere without adding ignore rules first.
