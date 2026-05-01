from datetime import date
from pathlib import Path

import pytest

from f5e import db as f5e_db
from f5e.analyze import fifo_pnl
from f5e.ingest import zerodha as zi

FIXTURE = Path(__file__).parent.parent / "fixtures" / "zerodha_trades_sample.json"


def _seed_one(con, *, side: str, symbol: str = "TESTCO", quantity: int, price: float, executed_at: str, source_uid: str):
    aid = f5e_db.upsert_account(
        con, source="zerodha", institution="Zerodha", external_id="ZX1234", currency="INR",
    )
    f5e_db.upsert_trade(
        con, account_id=aid, source_uid=source_uid, symbol=symbol,
        side=side, quantity=quantity, price=price, currency="INR",
        executed_at=executed_at,
    )


def test_stcg_classification(con):
    _seed_one(con, side="buy",  quantity=10, price=100, executed_at="2024-01-15T09:30:00", source_uid="b1")
    _seed_one(con, side="sell", quantity=10, price=150, executed_at="2024-06-15T09:30:00", source_uid="s1")
    realized = fifo_pnl.compute_realized(con)
    assert len(realized) == 1
    r = realized[0]
    assert r["type"] == "STCG"
    assert r["pnl"] == pytest.approx(500.0)
    assert r["hold_days"] < 365


def test_ltcg_classification(con):
    _seed_one(con, side="buy",  quantity=10, price=100, executed_at="2023-01-15T09:30:00", source_uid="b1")
    _seed_one(con, side="sell", quantity=10, price=200, executed_at="2024-06-15T09:30:00", source_uid="s1")
    realized = fifo_pnl.compute_realized(con)
    assert len(realized) == 1
    r = realized[0]
    assert r["type"] == "LTCG"
    assert r["pnl"] == pytest.approx(1000.0)
    assert r["hold_days"] > 365


def test_unmatched_sell_flagged(con):
    _seed_one(con, side="sell", quantity=5, price=150, executed_at="2024-06-15T09:30:00", source_uid="s1")
    realized = fifo_pnl.compute_realized(con)
    assert len(realized) == 1
    assert realized[0]["type"] == "UNMATCHED"
    assert realized[0]["pnl"] is None


def test_fifo_splits_across_lots(con):
    """End-to-end on the sample fixture — verifies the multi-lot split math."""
    aid = f5e_db.upsert_account(
        con, source="zerodha", institution="Zerodha", external_id="ZX1234", currency="INR",
    )
    zi.ingest(con, FIXTURE, external_id="ZX1234")

    realized = fifo_pnl.compute_realized(con)
    # Sell 1: 8 @ 150 against buy1 (8 of 10 @ 100), STCG, pnl = 400
    # Sell 2: 7 @ 200 splits — 2 @ 100 (LTCG, pnl=200) + 5 @ 120 (STCG, pnl=400)
    by_type = {"STCG": 0.0, "LTCG": 0.0}
    for r in realized:
        if r["pnl"] is not None:
            by_type[r["type"]] += r["pnl"]
    assert by_type["STCG"] == pytest.approx(800.0)
    assert by_type["LTCG"] == pytest.approx(200.0)


LEGACY = Path(__file__).resolve().parents[2] / "zerodha-trades-eq.json"
LEGACY_RELOCATED = Path(__file__).resolve().parents[2] / "data" / "raw" / "zerodha" / "zerodha-trades-eq.json"


@pytest.mark.skipif(
    not LEGACY.exists() and not LEGACY_RELOCATED.exists(),
    reason="real Zerodha trades file not present (gitignored)",
)
def test_parity_with_legacy_script(con):
    """Golden: new analyzer over real data must match legacy script totals to ₹0.01."""
    src = LEGACY if LEGACY.exists() else LEGACY_RELOCATED
    zi.ingest(con, src, external_id="ZX1234")
    realized = fifo_pnl.compute_realized(con)
    new_totals = {"STCG": 0.0, "LTCG": 0.0}
    for r in realized:
        if r["pnl"] is not None:
            new_totals[r["type"]] += r["pnl"]

    # Run legacy script in-process for comparison
    import json
    from collections import defaultdict, deque
    from datetime import datetime as _dt
    trades = json.load(open(src))
    # Mirror the ingest-side dedup: composite (order_id, trade_id) is the real PK.
    seen: set[tuple] = set()
    deduped = []
    for t in trades:
        k = (t["order_id"], t["trade_id"])
        if k in seen:
            continue
        seen.add(k)
        deduped.append(t)
    trades = deduped
    trades.sort(key=lambda t: t["order_execution_time"])
    queues: dict[str, deque] = defaultdict(deque)
    legacy_totals = {"STCG": 0.0, "LTCG": 0.0}
    for t in trades:
        sym = t["tradingsymbol"]
        qty = int(t["quantity"]); px = float(t["price"])
        dt = _dt.fromisoformat(t["order_execution_time"]).date()
        if t["trade_type"] == "buy":
            queues[sym].append([qty, px, dt])
        else:
            remaining = qty
            while remaining > 0 and queues[sym]:
                lot_qty, lot_px, lot_dt = queues[sym][0]
                take = min(lot_qty, remaining)
                hold = (dt - lot_dt).days
                pnl = take * (px - lot_px)
                legacy_totals["LTCG" if hold > 365 else "STCG"] += pnl
                queues[sym][0][0] -= take
                remaining -= take
                if queues[sym][0][0] == 0:
                    queues[sym].popleft()

    assert new_totals["STCG"] == pytest.approx(legacy_totals["STCG"], abs=0.01)
    assert new_totals["LTCG"] == pytest.approx(legacy_totals["LTCG"], abs=0.01)
