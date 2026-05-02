---
name: plaid-export
description: Pull US account data through Plaid's official CLI, persist raw JSON under data/raw/plaid, then ingest it into SQLite. Use when the user asks to sync Plaid, fetch US accounts, or import cash transactions, investment transactions, or holdings from a linked US institution.
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
- Plaid dashboard login completed:
  `plaid login`
- Plaid **Trial Plan** approved in the dashboard so real institutions are allowed
- 1Password entry titled `Plaid` with:
  - `client_id`
  - `secret`
  - one field per linked item access token, e.g. `chase_token`, `schwab_token`

## Link a new institution

1. Run `plaid item link --products transactions,investments`
2. Complete the browser-based Link flow
3. The CLI stores the linked Item in its local config. If you need raw credentials outside the CLI, save them to 1Password separately.

## Export transactions

Suggested layout:

```text
data/raw/plaid/<institution>/<YYYY-MM-DD>-transactions.json
```

Example:

```bash
mkdir -p data/raw/plaid/chase
plaid transactions list --item chase --json \
  > "data/raw/plaid/chase/$(date +%F)-transactions.json"
```

## Export holdings

Suggested layout:

```text
data/raw/plaid/<institution>/<YYYY-MM-DD>-holdings.json
```

Example:

```bash
mkdir -p data/raw/plaid/schwab
plaid investments holdings --item schwab --json \
  > "data/raw/plaid/schwab/$(date +%F)-holdings.json"
```

## Export investment transactions

Suggested layout:

```text
data/raw/plaid/<institution>/<YYYY-MM-DD>-investment-transactions.json
```

Example:

```bash
mkdir -p data/raw/plaid/robinhood
plaid investments transactions --item robinhood --json \
  > "data/raw/plaid/robinhood/$(date +%F)-investment-transactions.json"
```

## Ingest into SQLite

```bash
python -m f5e.ingest.plaid data/raw/plaid/chase/2026-05-01-transactions.json
```

Current ingester behavior:

- creates/updates `accounts` rows with `source='plaid'`
- ingests `transactions`
- ingests `investment_transactions`
  - `buy` / `sell` → `trades`
  - `cash` / `dividend` style entries → `transactions`
- ingests investment `holdings` when the payload includes `holdings` + `securities`
- flips Plaid amount signs to repo convention:
  - Plaid `+amount` = money out
  - repo `+amount` = money in
- preserves account/transaction currency at row level
- accepts the current Plaid CLI NDJSON output format (`diagnostic` line + payload)
- logs the run in `ingestion_log`

## Expected input shape

The ingester expects one JSON object containing:

```json
{
  "institution": {"name": "Chase"},
  "accounts": [...],
  "transactions": [...],
  "investment_transactions": [...],
  "holdings": [...],
  "securities": [...]
}
```

Only the fields relevant to the specific export need to be present. Transactions-only and holdings-only payloads are both supported. The live CLI currently writes NDJSON with a diagnostic line first; the ingester handles that directly.

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
sqlite3 data/finances.db "
  SELECT a.institution, h.symbol, h.quantity, h.market_value
  FROM holdings h
  JOIN accounts a ON a.id = h.account_id
  WHERE a.source = 'plaid'
  ORDER BY a.institution, h.symbol
"
```

## Gotchas

- Plaid amount signs are inverted relative to this repo. Never insert raw `amount` as-is.
- If a transaction references an `account_id` absent from the same payload, ingest should fail loudly instead of creating a partial import.
- Some live exports omit `institution.name` and only include `item.institution_id`; pass `institution="..."` to `plaid.ingest(...)` when you need a stable institution label.
- Keep raw exports out of git. `data/raw/` is already ignored; don't move files elsewhere without adding ignore rules first.
