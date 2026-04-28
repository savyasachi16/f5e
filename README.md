# f5e

Personal finance scratchpad — early days. Configured for [Claude Code](https://claude.com/claude-code) and [OpenCode](https://opencode.ai).

## What's here

Two skills so far, plus a Kite MCP wiring. More may follow as I figure out what I actually want this to do.

| | |
|---|---|
| [`kotak-export`](.claude/skills/kotak-export/SKILL.md) | Download Kotak Mahindra Bank statements via Playwright + 1Password creds. |
| [`zerodha-export`](.claude/skills/zerodha-export/SKILL.md) | Pull historical Zerodha trades from Console's internal JSON API + a FIFO P&L analyzer (STCG/LTCG). |
| [`kite` MCP](.mcp.json) | Hosted Zerodha Kite Connect MCP (read-only tools allowlisted in `.claude/settings.json`). |

## Setup

```bash
git clone https://github.com/savyasachi16/f5e.git
cd f5e

# One-time, if you don't already have these:
brew install 1password-cli
claude mcp add playwright -s user -- npx -y @playwright/mcp@latest
```

Open in Claude Code or OpenCode — both pick up [`CLAUDE.md`](CLAUDE.md) automatically.

## Layout

```
.claude/        # Claude Code config + skills
.opencode/      # OpenCode config (skills symlinked from .claude)
.mcp.json       # MCP servers
CLAUDE.md       # project context
opencode.json   # OpenCode config
```

## Privacy

Repo is public, data isn't. `.gitignore` blocks PDFs, PNGs, trade JSON, and browser session caches. Don't commit those.
