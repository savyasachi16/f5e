from pathlib import Path
import json

import pytest

from f5e.export import cmc

FIXTURE = Path(__file__).parent.parent / "fixtures" / "crypto_holdings_sample.json"


def test_enrich_holdings_writes_enriched_snapshot(tmp_path):
    out = tmp_path / "crypto-priced.json"

    def fake_fetch(symbols, *, api_key, convert):
        assert symbols == ["BTC", "ETH"]
        assert api_key == "secret"
        assert convert == "USD"
        return {
            "BTC": {"symbol": "BTC", "quote": {"USD": {"price": 96000.0}}},
            "ETH": {"symbol": "ETH", "quote": {"USD": {"price": 2500.0}}},
        }

    result = cmc.enrich_holdings(
        input_path=FIXTURE,
        output_path=out,
        api_key="secret",
        fetcher=fake_fetch,
    )

    assert result == {"assets": 2, "symbols": 2}
    payload = json.loads(out.read_text())
    assert len(payload["assets"]) == 2
    assert payload["assets"][0]["source"] == "cmc"
    assert payload["assets"][0]["market_value"] == 24000.0
    assert payload["assets"][1]["market_value"] == 5000.0


def test_enrich_holdings_requires_api_key(tmp_path):
    out = tmp_path / "crypto-priced.json"

    with pytest.raises(ValueError, match="CMC_API_KEY"):
        cmc.enrich_holdings(input_path=FIXTURE, output_path=out, api_key=None)


def test_enrich_holdings_rejects_unknown_symbol(tmp_path):
    out = tmp_path / "crypto-priced.json"

    def fake_fetch(symbols, *, api_key, convert):
        return {"BTC": {"symbol": "BTC", "quote": {"USD": {"price": 96000.0}}}}

    with pytest.raises(ValueError, match="ETH"):
        cmc.enrich_holdings(
            input_path=FIXTURE,
            output_path=out,
            api_key="secret",
            fetcher=fake_fetch,
        )
