from pathlib import Path
import json

import pytest

from f5e.ingest import assets as ai

FIXTURE = Path(__file__).parent.parent / "fixtures" / "asset_snapshots_sample.json"


def test_ingest_creates_assets_and_snapshots(con):
    added, updated = ai.ingest(con, FIXTURE)
    assert added == 3
    assert updated == 0

    assets = con.execute(
        """
        SELECT source, asset_class, name, currency, notes
        FROM assets
        ORDER BY asset_class, name
        """
    ).fetchall()
    assert len(assets) == 3
    assert [row["asset_class"] for row in assets] == ["crypto", "private_equity", "vehicle"]

    snapshots = con.execute(
        """
        SELECT a.asset_class, s.as_of_date, s.quantity, s.unit_price, s.market_value, s.currency
        FROM asset_snapshots s
        JOIN assets a ON a.id = s.asset_id
        ORDER BY a.asset_class, a.name
        """
    ).fetchall()
    assert len(snapshots) == 3
    assert [row["market_value"] for row in snapshots] == [24000.0, 18000.0, 32000.0]
    assert snapshots[0]["quantity"] == 0.25
    assert snapshots[1]["quantity"] is None
    assert snapshots[2]["unit_price"] is None


def test_ingest_is_idempotent(con):
    a1, _ = ai.ingest(con, FIXTURE)
    a2, u2 = ai.ingest(con, FIXTURE)
    assert a1 == 3
    assert a2 == 0
    assert u2 == 3

    assets = con.execute("SELECT COUNT(*) AS n FROM assets").fetchone()["n"]
    snapshots = con.execute("SELECT COUNT(*) AS n FROM asset_snapshots").fetchone()["n"]
    assert assets == 3
    assert snapshots == 3


def test_ingest_crypto_requires_quantity(con, tmp_path):
    payload = json.loads(FIXTURE.read_text())
    payload["assets"][2].pop("quantity")
    path = tmp_path / "crypto-missing-quantity.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="quantity"):
        ai.ingest(con, path)


def test_ingest_writes_log_row(con):
    ai.ingest(con, FIXTURE)
    rows = con.execute("SELECT source, rows_added, rows_updated FROM ingestion_log").fetchall()
    assert len(rows) == 1
    assert rows[0]["source"] == "assets"
    assert rows[0]["rows_added"] == 3
