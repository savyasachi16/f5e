# f5e — Personal Finance Analysis & Advice

Tooling for analyzing personal finances across Indian banking + brokerage providers (Kotak, Zerodha). Used for tax planning, P&L analysis, and investment decisions.

## Data sources

| Source | Access | Surface |
|---|---|---|
| Kotak Mahindra Bank netbanking | Playwright + 1Password | Statement PDFs |
| Zerodha Console (`console.zerodha.com`) | Playwright + internal JSON API | Historical trades, tax P&L, ledger |
| Zerodha Kite Connect | Kite MCP (hosted) | Live data: holdings, positions, LTP, quotes, OHLC, historical, GTTs |

## Skills

| Skill | Trigger | Purpose |
|---|---|---|
| `kotak-export` | "download Kotak statements" | Playwright-driven statement export, handles ngbDatepicker traps |
| `zerodha-export` | "pull Zerodha tradebook / tax P&L" | Console internal-API export + FIFO P&L analyzer (STCG/LTCG) |

Both skills live in `.claude/skills/` (also symlinked into `.opencode/skills/`).

## MCPs

- **`kite`** (project scope, hosted, `https://mcp.kite.trade/mcp`) — Zerodha live data. **Read-only tools allowlisted** in `.claude/settings.json` (16 of 22). Write tools (`place_order`, `modify_*`, `cancel_*`, `*_gtt_*`) require explicit user confirmation each time.
- **`playwright`** (user scope) — browser automation; needed by both skills above.

## PII — non-negotiable

This repo is **PUBLIC on GitHub**. The `.gitignore` blocks PII-bearing files; never push:

- `zerodha-trades-*.json` — full trade history
- `*.pdf`, `*.png`, `*.jpg` — screenshots and statements show account numbers, balances, real names
- `.playwright-mcp/` — cached browser session, console logs
- `analyze_trades.py` — local-only working analyzer (uncomment its gitignore line to share)

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
│   └── skills/{kotak,zerodha}-export/SKILL.md
├── .opencode/
│   ├── skills/                # symlink → ../.claude/skills
│   └── commands/              # slash-command shims
├── .mcp.json                  # Kite MCP (Claude Code reads this)
├── opencode.json              # OpenCode equivalent (mcp + permissions + instructions ref)
├── CLAUDE.md                  # this file (also referenced from opencode.json)
└── .gitignore
```

## Tone & style

This repo follows the global `~/.claude/CLAUDE.md` rules: direct, technical, max info density, no openers/closers/praise. Confidence score at the end of substantive answers.
