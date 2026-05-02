# f5e — Personal Finance Analysis & Advice

Tooling for analyzing personal finances across Indian (Kotak, Zerodha) **and US (Plaid)** providers — owner is an NRI with accounts on both sides. Used for tax planning, P&L analysis, and investment decisions. All ingested data lands in a single SQLite DB at `data/finances.db` (gitignored).

## Data sources

| Source | Access | Surface |
|---|---|---|
| Kotak Mahindra Bank netbanking | Playwright + 1Password | Statement PDFs -> `python -m f5e.ingest.kotak` -> SQLite transactions |
| Zerodha Console (`console.zerodha.com`) | Playwright + internal JSON API | Historical trades, tax P&L, ledger |
| Zerodha Kite Connect | Kite MCP (hosted) | Live data: holdings, positions, LTP, quotes, OHLC, historical, GTTs |
| Plaid (US accounts) | Plaid official CLI + Trial Plan | Cash transactions, investment transactions, and holdings via `plaid-export` |
| Manual assets | Local JSON files | Vehicle/private-equity/crypto snapshots via `python -m f5e.ingest.assets` |

## Skills

| Skill | Trigger | Purpose |
|---|---|---|
| `kotak-export` | "download Kotak statements" | Playwright-driven statement export, then `python -m f5e.ingest.kotak <pdf>` into SQLite |
| `zerodha-export` | "pull Zerodha tradebook / tax P&L" | Console internal-API export → `data/raw/zerodha/` → `python -m f5e.ingest.zerodha` → SQLite |
| `plaid-export` | "pull plaid / sync US accounts" | `python -m f5e.export.plaid ...` or raw Plaid CLI JSON/NDJSON → `data/raw/plaid/` → `python -m f5e.ingest.plaid` → SQLite (`transactions`, `trades`, `holdings`) |

All skills live in `.claude/skills/` (also symlinked into `.opencode/skills/`).

## MCPs

- **`kite`** (project scope, hosted, `https://mcp.kite.trade/mcp`) — Zerodha live data. **Read-only tools allowlisted** in `.claude/settings.json` (16 of 22). Write tools (`place_order`, `modify_*`, `cancel_*`, `*_gtt_*`) require explicit user confirmation each time.
- **`playwright`** (user scope) — browser automation; needed by both skills above.

## PII — non-negotiable

This repo is **PUBLIC on GitHub**. The `.gitignore` blocks PII-bearing files; never push:

- `data/finances.db` + `data/raw/` — everything ingested, including raw exports kept for re-ingest
- `*.pdf`, `*.png`, `*.jpg` — screenshots and statements show account numbers, balances, real names
- `.playwright-mcp/` — cached browser session, console logs

Add new PII-producing filename patterns to `.gitignore` *before* generating them.

## Credentials

All in 1Password — never inline. CLI:

```bash
op item get "<entry>" --vault Private --fields <field> --reveal   # password/secret
op item get "<entry>" --vault Private --otp                       # current TOTP
op item list --vault Private --format json | jq '.[] | select(.title | test("X"; "i")) | .title'   # find entry
```

Relevant entries (titles only — values stay in vault):
- `Kotak Bank` — netbanking (CRN + password; OTP via SMS, no seed)
- `Zerodha Console` — broker login (user ID + password + TOTP seed → fully automatable login)
- `Plaid` — client ID + production/sandbox secrets if bypassing dashboard auth
- `CoinMarketCap` — API key for crypto quote enrichment
- `MarketCheck` — API key for US vehicle price enrichment (`api_key` field)

## Working conventions

- **Long analyses → disk, not chat.** Write JSON to a `.gitignore`d path, run a `.py` analyzer, summarize the result. Don't dump tradebook arrays into the conversation.
- **Browser downloads land in `.playwright-mcp/`.** Move to a stable named path with the period in the filename (`<acct>/<period>.pdf`).
- **For tax filings, use Zerodha's official Tax P&L report** (charges-adjusted) — not my FIFO calc which excludes brokerage/STT/GST.
- **Capital-loss math (Indian equity, post-23-Jul-2024 rates):**
  - STCL → offsets STCG (20%) **and** LTCG (12.5%)
  - LTCL → offsets only LTCG
  - Carry forward 8 AYs; **must file ITR by due date** to claim
- **No wash-sale rule in India** — sell-and-rebuy to harvest losses is legal, but spread across days to avoid scrutiny on obvious round-tripping.

## Repo layout

```
f5e/
├── .claude/
│   ├── settings.json          # Kite read-only allowlist
│   └── skills/{kotak,zerodha,plaid}-export/SKILL.md
├── .opencode/
│   ├── skills/                # symlink → ../.claude/skills
│   └── commands/              # slash-command shims
├── data/                      # gitignored — finances.db + raw/{zerodha,kotak,plaid,assets}/
├── db/schema.sql              # idempotent SQLite schema
├── f5e/                       # Python package (`pdfplumber` runtime for Kotak PDF parsing)
│   ├── db.py                  # connect(), apply_schema(), upsert_*()
│   ├── export/plaid.py        # paginated Plaid CLI export helper
│   ├── ingest/{zerodha,plaid,kotak,assets}.py
│   └── analyze/fifo_pnl.py    # FIFO STCG/LTCG over the trades table
├── tests/                     # pytest, in-memory SQLite fixtures, synthetic data only
├── pyproject.toml             # uv-managed (`uv sync`, `uv run pytest`)
├── .mcp.json                  # Kite MCP (Claude Code reads this)
├── opencode.json              # OpenCode equivalent
├── CLAUDE.md                  # this file (symlink to AI.md, also referenced from opencode.json)
└── .gitignore
```

## Data flow

1. **Pull** — a `*-export` skill writes raw JSON/PDF to `data/raw/<source>/<period>.{json,pdf}`.
   - manual assets use JSON under `data/raw/assets/`
   - crypto holdings can be enriched with `python -m f5e.export.cmc <input> <output>`
   - US vehicles can be priced with `python -m f5e.export.vehicle <input> <output>` (MarketCheck VIN-based predict)
2. **Ingest** — `python -m f5e.ingest.<source> <path>` upserts into `data/finances.db`. Idempotent on `(account_id, source_uid)` — re-running is safe.
   - Kotak currently targets the extracted text shape covered by `tests/fixtures/kotak_statement_sample.txt` and will need refinement against live statement variants.
   - assets use separate `assets` / `asset_snapshots` tables and are snapshot-only in v1
3. **Analyze** — `python -m f5e.analyze.fifo_pnl` (or ad-hoc SQL via `sqlite3 data/finances.db`).

## Testing

- `uv sync` once, then `uv run pytest` for the suite.
- Tests use **in-memory SQLite** (`:memory:` fixture in `tests/conftest.py`) and **synthetic** sample data under `tests/fixtures/` — never copy real exports there.
- New ingestion modules: write a failing test against a synthetic fixture before implementing.

## Tone & style

This repo follows the global `~/.claude/CLAUDE.md` rules: direct, technical, max info density, no openers/closers/praise. Confidence score at the end of substantive answers.
