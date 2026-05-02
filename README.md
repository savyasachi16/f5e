# f5e

Personal finance scratchpad — early days. Configured for [Claude Code](https://claude.com/claude-code) and [OpenCode](https://opencode.ai).

## Stack

<a href="https://www.python.org"><img src="https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white" alt="Python" /></a>
<a href="https://www.sqlite.org"><img src="https://img.shields.io/badge/SQLite-003B57?style=flat&logo=sqlite&logoColor=white" alt="SQLite" /></a>
<a href="https://github.com/jsvine/pdfplumber"><img src="https://img.shields.io/badge/pdfplumber-4B5563?style=flat" alt="pdfplumber" /></a>
<a href="https://docs.astral.sh/uv/"><img src="https://img.shields.io/badge/uv-DE5FE9?style=flat&logo=uv&logoColor=white" alt="uv" /></a>
<a href="https://docs.pytest.org/"><img src="https://img.shields.io/badge/pytest-0A9EDC?style=flat&logo=pytest&logoColor=white" alt="pytest" /></a>
<a href="https://playwright.dev"><img src="https://img.shields.io/badge/Playwright-2EAD33?style=flat&logo=playwright&logoColor=white" alt="Playwright" /></a>
<a href="https://plaid.com/docs/resources/cli/"><img src="https://img.shields.io/badge/Plaid_CLI-111111?style=flat&logo=plaid&logoColor=white" alt="Plaid CLI" /></a>

## What's here

Three skills so far, plus a Kite MCP wiring, a SQLite-backed ingestion pipeline, and manual non-brokerage asset snapshots.

| | |
|---|---|
| [`kotak-export`](.claude/skills/kotak-export/SKILL.md) | Download Kotak Mahindra Bank statements via Playwright + 1Password creds, then ingest PDFs into SQLite with `python -m f5e.ingest.kotak`. |
| [`zerodha-export`](.claude/skills/zerodha-export/SKILL.md) | Pull historical Zerodha trades from Console's internal JSON API + a FIFO P&L analyzer (STCG/LTCG). |
| [`plaid-export`](.claude/skills/plaid-export/SKILL.md) | Pull US cash transactions, investment transactions, and holdings through Plaid CLI into `data/raw/plaid/`, with `python -m f5e.export.plaid` handling pagination when needed. Per-institution recipes for Chase, Discover, Capital One, E*TRADE, Schwab, Robinhood; canonical slug→name fallback when a payload omits institution metadata. |
| [`kite` MCP](.mcp.json) | Hosted Zerodha Kite Connect MCP (read-only tools allowlisted in `.claude/settings.json`). |

Manual asset snapshots also land in SQLite through `python -m f5e.ingest.assets <path>`, using JSON under `data/raw/assets/`. Crypto holdings can be enriched first with `python -m f5e.export.cmc <input> <output>`.

## Setup

```bash
git clone https://github.com/savyasachi16/f5e.git
cd f5e

# One-time, if you don't already have these:
brew install 1password-cli
claude mcp add playwright -s user -- npx -y @playwright/mcp@latest
./install.sh --check
```

Open in Claude Code or OpenCode — both pick up [`CLAUDE.md`](CLAUDE.md) automatically.

## Layout

```
.claude/        # Claude Code config + skills
.opencode/      # OpenCode config (skills symlinked from .claude)
db/             # SQLite schema
data/           # gitignored finances.db + raw exports/assets
f5e/            # Python package: db helpers, ingesters, analyzers
tests/          # pytest suite with synthetic fixtures
.mcp.json       # MCP servers
CLAUDE.md       # project context
opencode.json   # OpenCode config
```

## Privacy

Repo is public, data isn't. `.gitignore` blocks PDFs, PNGs, trade JSON, and browser session caches. Don't commit those.
