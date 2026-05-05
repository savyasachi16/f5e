# f5e - Working State

> Living handoff doc. Last updated: 2026-05-05.

## Current status

The repo is on `main` with cross-agent parity in place, SQLite-backed ingestion for Kotak/Zerodha/Plaid/manual assets, and analyzers for FIFO P&L plus net worth. Durable capability docs live in `AI.md` and `README.md`; this file tracks recent deltas and open work only.

## Recent commits

- `61c9b92` `test(analyze): cover networth CLI path`
- `ee563a4` `test(analyze): expand fifo_pnl coverage to open_lots and CLI`
- `eef6bd1` `test(analyze): cover networth analyzer paths`
- `ac28657` `chore(lint): add ruff config and clean baseline issues`
- `b9c1e20` `style: replace em/en dashes with hyphens or colons throughout`
- `75e3e9e` `feat(agents): add Codex and Gemini CLI cross-agent parity`
- `50e4fbd` `feat(assets): support brokerage, ulip, cash, real_estate classes`
- `ff536fe` `fix(export): preserve asset source on crypto refresh`

## Verified

- `uv run ruff check f5e tests` -> passed
- `uv run pytest -q` -> 71 passed
- Coverage now clears the local target:
  - total: 80%
  - `f5e/analyze/networth.py`: 97%
  - `f5e/analyze/fifo_pnl.py`: 94%

## Recent changes

- Added `ruff` as a dev dependency with conservative lint rules: `E`, `F`, `I`, `UP`, `B`, `SIM`, with `E501` ignored for now.
- Cleaned the initial lint baseline without enabling formatter enforcement.
- Added focused net-worth tests for balances, liabilities, holdings fallback/dedup, asset buckets, FX conversion, missing FX rates, rendering, and CLI rates.
- Expanded FIFO P&L tests for open lots, account filtering, Indian FY boundaries, summary output, and CLI smoke behavior.
- Documented lint usage in `AI.md` and README development commands.

## Open / next

- Consider adding CI for `uv run ruff check f5e tests` and `uv run pytest`.
- Decide separately whether to enable `ruff format`; not part of the current lint baseline.
- Continue filling lower-priority coverage gaps in exporters and ingesters when those modules change.
- Extend Kotak parsing only if a new statement variant actually breaks.
- Link Charles Schwab brokerage once Plaid dashboard OAuth registration is complete.

## Gotchas

- The repo is public; never commit `data/finances.db`, raw exports, PDFs, screenshots, or `.playwright-mcp/`.
- Zerodha `trade_id` alone is not unique; use `order_id:trade_id`.
- Plaid amount signs are inverted relative to repo convention: Plaid positive means outflow, repo positive means inflow.
- Plaid investment transactions page at 100 by default; exactly 100 rows means keep paging.
