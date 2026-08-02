from probora_ml.evaluation.linear_direction_ablation import (
    AUTOREGRESSIVE_FEATURE_NAMES,
    FEATURE_SETS,
)


def test_autoregressive_challenger_uses_only_asset_history_features() -> None:
    assert AUTOREGRESSIVE_FEATURE_NAMES
    assert "autoregressive" not in FEATURE_SETS
    assert not any(
        name.startswith(("benchmark_", "market_breadth", "momentum_rank", "volatility_rank"))
        for name in AUTOREGRESSIVE_FEATURE_NAMES
    )
