---
name: zerodha-export
description: Fetch historical trades, P&L, and other data from Zerodha Console via its internal JSON API (auth piggybacks on a Playwright-driven login). Use when the user asks to pull Zerodha tradebook, tax P&L, ledger, contract notes, or any historical data the Kite Connect API doesn't expose.
allowed-tools:
  - Bash
  - Read
  - Write
---

# /zerodha-export — Zerodha Console Data Export

The Kite Connect API (and the official Kite MCP that wraps it) only exposes **today's** orders and trades. Historical trade history, tax P&L, ledger, and contract notes live exclusively in Zerodha **Console** (`console.zerodha.com`).

This skill drives Console via Playwright MCP, captures the session, and calls Console's *internal* JSON endpoints directly — much faster than scraping HTML/PDF reports and reusable for any Console page.

## When to use vs. when to skip

- **Use** for: historical trades (>1 day old), tax P&L, segment-wise P&L, ledger entries, contract notes, charges/brokerage breakdown, holdings history snapshots.
- **Skip** (use `mcp__kite__*` tools instead) for: today's orders/trades, current holdings, live LTP/quotes, placing orders, GTTs.

## Prerequisites

- **Playwright MCP** at user scope: `claude mcp add playwright -s user -- npx -y @playwright/mcp@latest`
- **1Password CLI** authed (`op vault list` works)
- **1Password entry** for Zerodha with these fields (the OTP field stores the TOTP seed so login is fully automatable — no human relay):
  - `username` (User ID, e.g. `XXX###`)
  - `password` (CONCEALED)
  - `one-time password` (OTP type — TOTP seed)

Find your entry: `op item list --vault Private --format json | jq '.[] | select(.title | test("zerodha|kite"; "i")) | .title'`

## Login flow (fully automated, no human in the loop)

1. Pull creds via `op`:
   ```bash
   op item get "<entry>" --vault Private --fields username --reveal
   op item get "<entry>" --vault Private --fields password --reveal
   op item get "<entry>" --vault Private --otp     # current 6-digit TOTP
   ```
2. `mcp__playwright__browser_navigate` → `https://kite.zerodha.com/`
3. Type username (`refref` from snapshot), password, click "Login"
4. Wait for TOTP screen → fill the 6-digit code → submit
5. Once on `/dashboard`, the session cookies (`public_token`, `enctoken`) are set for both `kite.zerodha.com` and `console.zerodha.com` (Console SSOs off the Kite session).
6. Navigate to `https://console.zerodha.com/` to confirm Console is reachable.

If the login fails with "invalid TOTP," the 30-second window may have just rolled over — re-fetch the OTP and retry.

## Auth piggyback: CSRF token

Console's API requires an `x-csrftoken` header. **The CSRF token is the value of the `public_token` cookie** — Console reads the cookie and echoes it as the header. Inside `browser_evaluate`:

```js
const csrf = document.cookie.split('; ').find(c => c.startsWith('public_token=')).split('=')[1];
const r = await fetch('/api/reports/tradebook?...', {
  credentials: 'include',
  headers: {'x-csrftoken': csrf, 'accept': 'application/json'}
});
```

`credentials: 'include'` makes the browser send the session cookies; the explicit `x-csrftoken` header satisfies CSRF verification.

## Discovered endpoints

### Tradebook (historical trades)

```
GET /api/reports/tradebook
  ?segment=EQ          # EQ | FO | CD | COM
  &from_date=YYYY-MM-DD
  &to_date=YYYY-MM-DD
  &page=N              # 1-based
  &sort_by=order_execution_time
  &sort_desc=false
```

Response shape:
```json
{ "status": "success",
  "data": { "state": "SUCCESS",
            "result": [ /* trade objects */ ],
            "pagination": { "page": N, "per_page": 20, "total_pages": M, "total": K } } }
```

Trade object fields: `trade_date`, `trade_type` (`buy`/`sell`), `quantity`, `price`, `tradingsymbol`, `isin`, `exchange`, `segment`, `order_execution_time`, `order_id`, `trade_id`, `series`, `instrument_id`, `expiry_date` (F&O), `strike` (F&O).

**Pagination is 20 trades/page** — fetch in a loop until `page >= total_pages`.

### Tradebook heatmap (calendar of trade activity)

```
GET /api/reports/tradebook/heatmap?segment=EQ&from_date=...&to_date=...
```

### Other endpoints (capture via network sniff — see below)

- Tax P&L: `/api/reports/pnl/...` (sniff to confirm)
- Ledger: `/api/funds/...`
- Holdings history snapshots
- Charges breakdown

## Discovering new endpoints

For any Console page you need:

1. Navigate to the page in Playwright
2. Trigger the report (click submit/filters)
3. `mcp__playwright__browser_network_requests` with `filter: "api/"` and `requestHeaders: true`
4. Copy the URL + headers; replicate via `fetch()` from page context

## Bulk-fetch idiom (paginated, retry on transient errors)

Run this inside `browser_evaluate` with the `filename` parameter to dump straight to disk:

```js
async () => {
  const csrf = document.cookie.split('; ').find(c => c.startsWith('public_token=')).split('=')[1];
  const all = [];
  for (let page = 1; page <= 100; page++) {
    let attempt = 0;
    while (attempt < 3) {
      try {
        const r = await fetch(`/api/reports/tradebook?segment=EQ&from_date=2018-01-01&to_date=${new Date().toISOString().slice(0,10)}&page=${page}&sort_by=order_execution_time&sort_desc=false`, {
          credentials: 'include',
          headers: {'x-csrftoken': csrf, 'accept': 'application/json'}
        });
        if (!(r.headers.get('content-type') || '').includes('json')) {
          await new Promise(r => setTimeout(r, 800)); attempt++; continue;
        }
        const j = await r.json();
        if (j.status !== 'success') { await new Promise(r => setTimeout(r, 800)); attempt++; continue; }
        if (!j.data?.result?.length) return all;
        all.push(...j.data.result);
        if (j.data.pagination && page >= j.data.pagination.total_pages) return all;
        break;
      } catch (e) { attempt++; await new Promise(r => setTimeout(r, 800)); }
    }
    if (attempt >= 3) { all.push({_error: {page}}); return all; }
    await new Promise(r => setTimeout(r, 200));   // gentle pacing
  }
  return all;
}
```

## Session caveats

- **Browser session can drop to `about:blank`** between Claude tool calls. Recovery is cheap because TOTP is in `op` — just `browser_navigate`, fill creds, fetch fresh OTP, fill, submit.
- The Kite session cookie persists across Console navigation; logging into Kite once is enough. Logging out of Kite invalidates Console.
- **Don't put long loops with many fetches in a single `browser_evaluate` call** if the data is huge — return values get truncated at ~200KB. Prefer either (a) the `filename` parameter to dump to disk (no truncation), or (b) chunked fetches that return summaries.
- Empty `from_date` window can return `total: 0` silently — verify with a probe call before assuming the user has no data.

## Reusable analysis: FIFO realized P&L (STCG/LTCG)

After fetching the tradebook JSON, the canonical analysis is per-symbol FIFO matching of sells against earlier buys, classified by holding period. **Indian equity tax (post-23-Jul-2024 rates):**

- **STCG** (≤ 365 days): 20% on net gains; can offset against STCG and LTCG.
- **LTCG** (> 365 days): 12.5% on net gains above ₹1.25L per FY exemption; can offset only against LTCG.
- **Losses carry forward 8 years** if ITR is filed by the due date.

Skeleton (Python):

```python
import json
from collections import defaultdict, deque
from datetime import datetime

trades = json.load(open("zerodha-trades-eq.json"))
trades.sort(key=lambda t: t["order_execution_time"])

queues: dict[str, deque] = defaultdict(deque)   # FIFO buy lots per symbol
realized = []

for t in trades:
    sym, qty, px = t["tradingsymbol"], int(t["quantity"]), float(t["price"])
    dt = datetime.fromisoformat(t["order_execution_time"]).date()
    if t["trade_type"] == "buy":
        queues[sym].append([qty, px, dt])
    else:  # sell
        remaining = qty
        while remaining > 0 and queues[sym]:
            lot_qty, lot_px, lot_dt = queues[sym][0]
            take = min(lot_qty, remaining)
            hold_days = (dt - lot_dt).days
            realized.append({
                "sell_date": dt, "symbol": sym, "qty": take,
                "buy_px": lot_px, "sell_px": px, "hold_days": hold_days,
                "pnl": take * (px - lot_px),
                "type": "LTCG" if hold_days > 365 else "STCG",
            })
            queues[sym][0][0] -= take
            remaining -= take
            if queues[sym][0][0] == 0:
                queues[sym].popleft()
        # if remaining > 0 here, it means a sell with no matched buy
        # → either the fetch window started too late, OR a corporate action
        # (split/bonus/demerger) added shares not represented as a trade.
```

**Common gotcha**: if you set `from_date` too recent, sells of older holdings will be unmatched. Probe the earliest trade with a wide window first (e.g. `from_date=2018-01-01`) to find the actual account opening date, then narrow.

**Charges caveat**: tradebook prices are clean; brokerage, STT, exchange fees, GST, stamp duty are NOT subtracted. Real realized P&L is ~0.1-0.3% worse per trade. Console's *Tax P&L* report (different endpoint) accounts for these — pull it for tax filings.

## Output convention

Suggested layout under the working directory:

```
zerodha-trades-eq.json     # raw EQ trades
zerodha-trades-fo.json     # raw F&O trades (if needed)
zerodha-pnl-summary.txt    # analyzer output
analyze_trades.py          # the FIFO analyzer
```

Don't commit these — they contain account-specific PII. Add to `.gitignore` if working in a tracked repo.
