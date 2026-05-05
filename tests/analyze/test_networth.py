import pytest

from f5e import db as f5e_db
from f5e.analyze import networth


def _account(con, *, account_type: str, external_id: str = "acct", currency: str = "USD") -> int:
    return f5e_db.upsert_account(
        con,
        source="test",
        institution="Test Bank",
        external_id=external_id,
        account_type=account_type,
        currency=currency,
        nickname=external_id,
    )


def test_balance_only_account_bucketed_correctly(con):
    checking = _account(con, account_type="checking", external_id="checking")
    card = _account(con, account_type="credit card", external_id="card")
    f5e_db.upsert_balance(con, account_id=checking, as_of_date="2026-05-01", current=1200, currency="USD")
    f5e_db.upsert_balance(con, account_id=card, as_of_date="2026-05-01", current=300, currency="USD")

    report = networth.collect(con)

    assert report["by_bucket"]["cash"] == pytest.approx(1200)
    assert report["by_bucket"]["liabilities"] == pytest.approx(-300)
    assert report["total"] == pytest.approx(900)


def test_holding_skipped_when_balance_present(con):
    account = _account(con, account_type="brokerage", external_id="brokerage")
    f5e_db.upsert_balance(con, account_id=account, as_of_date="2026-05-01", current=5000, currency="USD")
    f5e_db.upsert_holding(
        con,
        account_id=account,
        as_of_date="2026-05-01",
        symbol="AAPL",
        quantity=10,
        market_value=2000,
        currency="USD",
    )

    report = networth.collect(con)

    assert report["by_bucket"]["brokerage"] == pytest.approx(5000)
    assert [r["source"] for r in report["rows"]] == ["balance"]


def test_holding_used_when_no_balance(con):
    account = _account(con, account_type="brokerage", external_id="brokerage")
    f5e_db.upsert_holding(
        con,
        account_id=account,
        as_of_date="2026-05-01",
        symbol="AAPL",
        quantity=10,
        market_value=2000,
        currency="USD",
    )

    report = networth.collect(con)

    assert report["by_bucket"]["brokerage"] == pytest.approx(2000)
    assert report["rows"][0]["source"] == "holding"


def test_asset_snapshot_buckets(con):
    for asset_class in networth._ASSET_CLASS_BUCKETS:
        asset_id = f5e_db.upsert_asset(
            con,
            source="manual",
            asset_class=asset_class,
            name=asset_class,
            external_id=asset_class,
            currency="USD",
        )
        f5e_db.upsert_asset_snapshot(
            con,
            asset_id=asset_id,
            as_of_date="2026-05-01",
            market_value=100,
            currency="USD",
        )

    report = networth.collect(con)

    for bucket in networth._ASSET_CLASS_BUCKETS.values():
        assert report["by_bucket"][bucket] == pytest.approx(100)


def test_fx_conversion_inr_to_usd(con):
    account = _account(con, account_type="savings", external_id="savings", currency="INR")
    f5e_db.upsert_balance(con, account_id=account, as_of_date="2026-05-01", current=8300, currency="INR")

    report = networth.collect(con, rates={"INR": 1 / 83.0}, display_currency="USD")

    assert report["by_bucket"]["cash"] == pytest.approx(100)
    assert report["total"] == pytest.approx(100)


def test_missing_fx_rate_raises(con):
    account = _account(con, account_type="savings", external_id="savings", currency="INR")
    f5e_db.upsert_balance(con, account_id=account, as_of_date="2026-05-01", current=8300, currency="INR")

    with pytest.raises(ValueError, match="missing FX rate for INR -> USD"):
        networth.collect(con)


def test_render_omits_empty_buckets_and_shows_total(con):
    account = _account(con, account_type="checking", external_id="checking")
    f5e_db.upsert_balance(con, account_id=account, as_of_date="2026-05-01", current=1200, currency="USD")
    report = networth.collect(con)

    output = networth.render(report)

    assert "NET WORTH" in output
    assert "[CASH]" in output
    assert "[BROKERAGE]" not in output


def test_cli_uses_inr_rate(con, monkeypatch, capsys):
    account = _account(con, account_type="savings", external_id="savings", currency="INR")
    f5e_db.upsert_balance(con, account_id=account, as_of_date="2026-05-01", current=8300, currency="INR")
    monkeypatch.setattr(f5e_db, "connect", lambda: con)

    assert networth._cli(["networth", "--inr-per-usd", "83"]) == 0

    output = capsys.readouterr().out
    assert "NET WORTH" in output
    assert "100.00 USD" in output
