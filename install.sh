#!/usr/bin/env bash
# f5e installer — idempotent. Sets up every dependency required to run the
# skills and the f5e Python package on macOS.
#
# Usage:  ./install.sh           # full setup
#         ./install.sh --check   # report missing deps without installing

set -euo pipefail

CHECK_ONLY=0
[[ "${1:-}" == "--check" ]] && CHECK_ONLY=1

# ── tiny output helpers ───────────────────────────────────────────────────────
b()   { printf "\033[1m%s\033[0m\n" "$*"; }
ok()  { printf "  \033[32m✓\033[0m %s\n" "$*"; }
miss(){ printf "  \033[33m·\033[0m %s\n" "$*"; }
err() { printf "  \033[31m✗\033[0m %s\n" "$*" >&2; }

if [[ "$OSTYPE" != darwin* ]]; then
  err "f5e installer currently supports macOS only (detected: $OSTYPE)."
  exit 1
fi

# ── 0. Homebrew is the prerequisite for everything else ──────────────────────
if ! command -v brew >/dev/null 2>&1; then
  err "Homebrew is required. Install from https://brew.sh first."
  exit 1
fi

# ── helper: install if missing ───────────────────────────────────────────────
MISSING=0
need() {
  local label="$1" cmd="$2" install="$3"
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "$label ($(command -v "$cmd"))"
    return 0
  fi
  miss "$label not found"
  MISSING=$((MISSING + 1))
  if (( CHECK_ONLY )); then return 0; fi
  b "    installing: $install"
  eval "$install"
  ok "$label installed"
}

# ── 1. CLI tools via brew ────────────────────────────────────────────────────
b "Checking CLI dependencies"
need "uv (Python package manager)" "uv"   "brew install uv"
need "1Password CLI"                "op"   "brew install 1password-cli"
need "Plaid CLI"                    "plaid" "brew install plaid/plaid-cli/plaid"
need "jq (JSON wrangler)"           "jq"   "brew install jq"
need "gh (GitHub CLI, optional)"    "gh"   "brew install gh"
need "sqlite3 (SQLite REPL)"        "sqlite3" "brew install sqlite"

# ── 2. Playwright MCP (registered with Claude Code at user scope) ────────────
b "Checking Playwright MCP registration"
if (( CHECK_ONLY )); then
  miss "Playwright MCP check skipped in --check mode"
elif command -v claude >/dev/null 2>&1; then
  if claude mcp list 2>/dev/null | grep -qi playwright; then
    ok "playwright MCP already registered"
  else
    miss "playwright MCP not registered"
    claude mcp add playwright -s user -- npx -y @playwright/mcp@latest
    ok "playwright MCP registered"
  fi
else
  miss "claude CLI not found — skipping Playwright MCP registration"
fi

# ── 3. Python deps via uv ────────────────────────────────────────────────────
b "Syncing Python dependencies (uv)"
if (( CHECK_ONLY )); then
  uv sync --dry-run 2>&1 | tail -3 || miss "uv sync would change state"
else
  uv sync
  ok "uv sync complete"
fi

# ── 4. SQLite DB scaffold ────────────────────────────────────────────────────
b "Initialising SQLite DB"
if (( CHECK_ONLY == 0 )); then
  uv run python -c "from f5e import db; con=db.connect(); db.apply_schema(con); con.commit(); print('  schema applied at', db.DB_PATH)"
else
  miss "skipped in --check mode"
fi

# ── 5. Verify ────────────────────────────────────────────────────────────────
b "Running test suite"
if (( CHECK_ONLY == 0 )); then
  uv run pytest -q
fi

# ── 6. Reminders that need a human ───────────────────────────────────────────
cat <<'EOF'

────────────────────────────────────────────────────────────────────────────────
Manual steps still required (these can't be scripted):

  1Password vault must contain entries:
    - "Kotak Bank"      — netbanking CRN + password
    - "Zerodha Console" — user_id + password + TOTP seed
    - "Plaid"           — client_id + secret + per-Item access_token(s)
    - "CoinMarketCap"   — API key for `python -m f5e.export.cmc`

  Plaid Trial Plan signup:
    https://dashboard.plaid.com/  →  Trial Plan  →  short form
    (~90% of personal-use applicants approved in <60s)

  After Trial Plan approval, run inside the repo:
    plaid login                           # one-time dashboard auth
    plaid item link --products transactions,investments
                                          # browser-based Link flow per institution
────────────────────────────────────────────────────────────────────────────────
EOF
