"""FIFO-matched realized P&L on equity trades, classified STCG vs LTCG.

Reads from the SQLite `trades` table (any source) instead of a single JSON file.
Indian capital-gains rule: hold > 365 days = LTCG, else STCG.
"""
import sys
from collections import defaultdict, deque
from datetime import datetime
from typing import Any

from f5e import db as f5e_db


def compute_realized(con, *, account_id: int | None = None) -> list[dict[str, Any]]:
    """Returns one row per sell-leg match (or UNMATCHED row when no buy)."""
    sql = "SELECT symbol, side, quantity, price, executed_at FROM trades"
    args: tuple = ()
    if account_id is not None:
        sql += " WHERE account_id = ?"
        args = (account_id,)
    sql += " ORDER BY executed_at, id"
    rows = con.execute(sql, args).fetchall()

    queues: dict[str, deque] = defaultdict(deque)
    realized: list[dict[str, Any]] = []

    for r in rows:
        sym = r["symbol"]
        qty = float(r["quantity"])
        px = float(r["price"])
        dt = datetime.fromisoformat(r["executed_at"]).date()

        if r["side"] == "buy":
            queues[sym].append([qty, px, dt])
            continue

        # sell
        remaining = qty
        while remaining > 0:
            if not queues[sym]:
                realized.append({
                    "sell_date": dt, "symbol": sym, "qty": remaining,
                    "buy_px": None, "sell_px": px, "buy_date": None,
                    "hold_days": None, "pnl": None, "type": "UNMATCHED",
                })
                break
            lot_qty, lot_px, lot_dt = queues[sym][0]
            take = min(lot_qty, remaining)
            hold = (dt - lot_dt).days
            realized.append({
                "sell_date": dt, "symbol": sym, "qty": take,
                "buy_px": lot_px, "sell_px": px, "buy_date": lot_dt,
                "hold_days": hold, "pnl": take * (px - lot_px),
                "type": "LTCG" if hold > 365 else "STCG",
            })
            queues[sym][0][0] -= take
            remaining -= take
            if queues[sym][0][0] == 0:
                queues[sym].popleft()

    return realized


def open_lots(con, *, account_id: int | None = None) -> dict[str, list]:
    """Returns symbol → list of [qty, avg_buy, buy_date] still-open lots."""
    sql = "SELECT symbol, side, quantity, price, executed_at FROM trades"
    args: tuple = ()
    if account_id is not None:
        sql += " WHERE account_id = ?"
        args = (account_id,)
    sql += " ORDER BY executed_at, id"
    rows = con.execute(sql, args).fetchall()
    queues: dict[str, deque] = defaultdict(deque)
    for r in rows:
        sym = r["symbol"]; qty = float(r["quantity"]); px = float(r["price"])
        dt = datetime.fromisoformat(r["executed_at"]).date()
        if r["side"] == "buy":
            queues[sym].append([qty, px, dt])
        else:
            remaining = qty
            while remaining > 0 and queues[sym]:
                take = min(queues[sym][0][0], remaining)
                queues[sym][0][0] -= take
                remaining -= take
                if queues[sym][0][0] == 0:
                    queues[sym].popleft()
    return {sym: list(q) for sym, q in queues.items() if q}


def _fy(d) -> str:
    yr = d.year - (1 if d.month < 4 else 0)
    return f"FY{yr:04d}-{(yr + 1) % 100:02d}"


def _print_summary(realized: list[dict]) -> None:
    print(f"\n{'='*78}\nREALIZED P&L SUMMARY\n{'='*78}\n")
    totals: dict[str, list] = defaultdict(lambda: [0, 0.0, 0.0])
    for r in realized:
        if r["pnl"] is None:
            totals["UNMATCHED"][0] += 1
            continue
        totals[r["type"]][0] += 1
        totals[r["type"]][1] += r["pnl"]
        totals[r["type"]][2] += r["qty"]
    print(f"{'Type':<10} {'Legs':>5} {'Qty':>10} {'Realized P&L':>18}")
    print("-" * 46)
    for typ in ("STCG", "LTCG", "UNMATCHED"):
        if typ in totals:
            legs, pnl, qty = totals[typ]
            print(f"{typ:<10} {legs:>5} {qty:>10.0f} ₹{pnl:>16,.2f}")

    print(f"\n{'='*78}\nP&L BY FINANCIAL YEAR (Indian FY: Apr–Mar)\n{'='*78}\n")
    fy_pnl: dict[str, dict] = defaultdict(lambda: {"STCG": 0.0, "LTCG": 0.0, "legs": 0})
    for r in realized:
        if r["pnl"] is None:
            continue
        fy = _fy(r["sell_date"])
        fy_pnl[fy][r["type"]] += r["pnl"]
        fy_pnl[fy]["legs"] += 1
    print(f"{'FY':<10} {'Legs':>5} {'STCG':>16} {'LTCG':>16} {'Total':>16}")
    print("-" * 65)
    for fy in sorted(fy_pnl):
        d = fy_pnl[fy]
        print(f"{fy:<10} {d['legs']:>5} ₹{d['STCG']:>14,.2f} ₹{d['LTCG']:>14,.2f} ₹{(d['STCG']+d['LTCG']):>14,.2f}")


def _cli(argv: list[str]) -> int:
    con = f5e_db.connect()
    realized = compute_realized(con)
    _print_summary(realized)
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
