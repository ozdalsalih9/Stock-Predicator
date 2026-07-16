import pandas as pd

from probora_ml.ingestion.fred_market import attach_fred_market_features


def test_fred_join_never_uses_observation_before_its_availability() -> None:
    samples = pd.DataFrame(
        {"snapshot_time": pd.to_datetime(["2025-01-02", "2025-01-03"], utc=True)}
    )
    macro = pd.DataFrame(
        {
            "observation_date": pd.to_datetime(["2025-01-01"], utc=True),
            "available_at": pd.to_datetime(["2025-01-03"], utc=True),
            "vix_level": [0.20],
        }
    )

    result = attach_fred_market_features(samples, macro)

    assert pd.isna(result.loc[0, "vix_level"])
    assert result.loc[1, "vix_level"] == 0.20
