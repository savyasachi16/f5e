from pathlib import Path
import json

import pytest

from f5e.export import vehicle
from f5e.ingest import assets as assets_ingest

FIXTURE = Path(__file__).parent.parent / "fixtures" / "vehicles_sample.json"


def _fake_fetch_factory(prices: dict[str, float]):
    def fake(asset, *, api_key):
        assert api_key == "secret"
        key = asset.get("vin") or asset["name"]
        return {"price": prices[key], "raw": {"echo": asset}}
    return fake


def test_enrich_vehicles_writes_snapshot_payload(tmp_path):
    out = tmp_path / "vehicles-priced.json"
    prices = {"5YJYGDEE7NF000001": 38500.0, "JYARM18E5MA000002": 6200.0}

    result = vehicle.enrich_vehicles(
        input_path=FIXTURE,
        output_path=out,
        api_key="secret",
        fetcher=_fake_fetch_factory(prices),
        as_of_date="2026-05-02",
    )

    assert result == {"assets": 2}
    payload = json.loads(out.read_text())
    assert len(payload["assets"]) == 2
    car, bike = payload["assets"]
    assert car["asset_class"] == "vehicle"
    assert car["source"] == "marketcheck"
    assert car["as_of_date"] == "2026-05-02"
    assert car["quantity"] == 1
    assert car["unit_price"] == 38500.0
    assert car["market_value"] == 38500.0
    assert car["currency"] == "USD"
    assert car["external_id"] == "5YJYGDEE7NF000001"
    assert bike["market_value"] == 6200.0


def test_enrich_vehicles_requires_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("MARKETCHECK_API_KEY", raising=False)
    out = tmp_path / "vehicles-priced.json"

    with pytest.raises(ValueError, match="MARKETCHECK_API_KEY"):
        vehicle.enrich_vehicles(input_path=FIXTURE, output_path=out, api_key=None)


def test_enrich_vehicles_rejects_missing_price(tmp_path):
    out = tmp_path / "vehicles-priced.json"

    def bad_fetch(asset, *, api_key):
        return {"raw": {}}  # no price

    with pytest.raises(ValueError, match="price"):
        vehicle.enrich_vehicles(
            input_path=FIXTURE,
            output_path=out,
            api_key="secret",
            fetcher=bad_fetch,
        )


def test_enriched_output_round_trips_through_assets_ingester(con, tmp_path):
    out = tmp_path / "vehicles-priced.json"
    prices = {"5YJYGDEE7NF000001": 38500.0, "JYARM18E5MA000002": 6200.0}

    vehicle.enrich_vehicles(
        input_path=FIXTURE,
        output_path=out,
        api_key="secret",
        fetcher=_fake_fetch_factory(prices),
        as_of_date="2026-05-02",
    )

    added, updated = assets_ingest.ingest(con, out)
    assert added == 2
    assert updated == 0

    rows = con.execute(
        """
        SELECT a.name, a.asset_class, a.external_id, s.market_value, s.unit_price, s.currency
        FROM assets a JOIN asset_snapshots s ON s.asset_id = a.id
        ORDER BY a.name
        """
    ).fetchall()
    assert [r["name"] for r in rows] == ["2021 Yamaha MT-07", "2022 Tesla Model Y"]
    assert all(r["asset_class"] == "vehicle" for r in rows)
    assert [r["external_id"] for r in rows] == ["JYARM18E5MA000002", "5YJYGDEE7NF000001"]
    assert [r["market_value"] for r in rows] == [6200.0, 38500.0]


def test_motorcycle_fallback_requires_year_make_model(tmp_path):
    out = tmp_path / "vehicles-priced.json"
    payload = {"assets": [{"name": "bike", "vehicle_type": "motorcycle"}]}
    src = tmp_path / "in.json"
    src.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="year"):
        vehicle.enrich_vehicles(input_path=src, output_path=out, api_key="secret")
