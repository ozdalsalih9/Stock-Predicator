from probora_ml.config import ASSETS, US_EQUITY_PILOT


def test_us_equity_pilot_is_disjoint_and_fixed() -> None:
    crypto = {asset.symbol for asset in ASSETS}
    equities = {asset.symbol for asset in US_EQUITY_PILOT}

    assert len(crypto) == 8
    assert len(equities) == 20
    assert crypto.isdisjoint(equities)
    assert all(asset.asset_class == "us_equity" for asset in US_EQUITY_PILOT)
