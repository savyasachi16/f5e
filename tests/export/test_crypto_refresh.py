from pathlib import Path
import json

import pytest

from f5e import db as f5e_db
from f5e.export import crypto_refresh
from f5e.ingest import assets as assets_ingest


def _seed_crypto(con, *, symbol, name, quantity, price, as_of_date="2026-05-01"):
    asset_id = f5e_db.upsert_asset(
        con, source="cmc", asset_class="crypto",
        name=name, external_id=symbol, currency="USD",
    )
    f5e_db.upsert_asset_snapshot(
        con, asset_id=asset_id, as_of_date=as_of_date,
        market_value=quantity * price, currency="USD",
        quantity=quantity, unit_price=price,
    )


def test_refresh_writes_snapshot_per_asset(con, tmp_path):
    _seed_crypto(con, symbol="BTC", name="CMC BTC", quantity=1.0, price=70000.0)
    _seed_crypto(con, symbol="ETH", name="CMC ETH", quantity=2.0, price=2000.0)
    out = tmp_path / "crypto-priced.json"

    def fake_fetch(symbols):
        assert sorted(symbols) == ["BTC", "ETH"]
        return {"BTC": 80000.0, "ETH": 2500.0}

    result = crypto_refresh.refresh(
        con, output_path=out, fetcher=fake_fetch, as_of_date="2026-05-03",
    )
    assert result == {"assets": 2}

    payload = json.loads(out.read_text())
    by_sym = {a["external_id"]: a for a in payload["assets"]}
    assert by_sym["BTC"]["market_value"] == 80000.0
    assert by_sym["BTC"]["quantity"] == 1.0
    assert by_sym["ETH"]["market_value"] == 5000.0
    assert by_sym["ETH"]["quantity"] == 2.0
    assert all(a["asset_class"] == "crypto" for a in payload["assets"])
    # source is preserved from the existing asset row so the refresh updates
    # the same record rather than creating a parallel asset
    assert all(a["source"] == "cmc" for a in payload["assets"])
    assert all(a["as_of_date"] == "2026-05-03" for a in payload["assets"])


def test_refresh_uses_latest_snapshot_quantity(con, tmp_path):
    _seed_crypto(con, symbol="BTC", name="CMC BTC", quantity=1.0, price=70000.0, as_of_date="2026-05-01")
    _seed_crypto(con, symbol="BTC", name="CMC BTC", quantity=1.5, price=72000.0, as_of_date="2026-05-02")
    out = tmp_path / "crypto-priced.json"

    def fake_fetch(symbols):
        return {"BTC": 80000.0}

    crypto_refresh.refresh(con, output_path=out, fetcher=fake_fetch, as_of_date="2026-05-03")
    payload = json.loads(out.read_text())
    assert payload["assets"][0]["quantity"] == 1.5
    assert payload["assets"][0]["market_value"] == 1.5 * 80000.0


def test_refresh_then_ingest_round_trip(con, tmp_path):
    _seed_crypto(con, symbol="BTC", name="CMC BTC", quantity=1.0, price=70000.0)
    out = tmp_path / "crypto-priced.json"
    crypto_refresh.refresh(
        con, output_path=out,
        fetcher=lambda syms: {"BTC": 90000.0},
        as_of_date="2026-05-03",
    )
    added, updated = assets_ingest.ingest(con, out)
    assert added == 1  # new snapshot row for 2026-05-03
    assert updated == 0

    rows = con.execute(
        """
        SELECT s.as_of_date, s.market_value
        FROM asset_snapshots s
        JOIN assets a ON a.id = s.asset_id
        WHERE a.external_id = 'BTC'
        ORDER BY s.as_of_date
        """
    ).fetchall()
    assert [r["as_of_date"] for r in rows] == ["2026-05-01", "2026-05-03"]
    assert rows[1]["market_value"] == 90000.0


def test_refresh_rejects_missing_quote(con, tmp_path):
    _seed_crypto(con, symbol="BTC", name="CMC BTC", quantity=1.0, price=70000.0)
    out = tmp_path / "crypto-priced.json"

    with pytest.raises(ValueError, match="BTC"):
        crypto_refresh.refresh(con, output_path=out, fetcher=lambda syms: {})


def test_refresh_skips_when_no_crypto_assets(con, tmp_path):
    out = tmp_path / "crypto-priced.json"
    result = crypto_refresh.refresh(con, output_path=out, fetcher=lambda syms: {})
    assert result == {"assets": 0}
    assert json.loads(out.read_text()) == {"assets": []}
