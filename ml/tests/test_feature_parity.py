import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from probora_ml.config import FEATURE_NAMES
from probora_ml.features.daily import build_feature_row


def test_python_features_match_shared_csharp_golden_fixture() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    frame = pd.DataFrame(
        [
            {
                "open_time": start + timedelta(days=index),
                "open": 100 + index,
                "high": 102 + index,
                "low": 99 + index,
                "close": 101 + index,
                "volume": 1_000 + index,
                "trade_count": 100_000 + index,
                "taker_buy_base_volume": 500 + index / 2,
            }
            for index in range(400)
        ]
    )
    fixture = Path(__file__).parents[2] / "tests" / "fixtures" / "feature-parity-v2.json"
    expected = json.loads(fixture.read_text(encoding="utf-8"))
    all_features = build_feature_row(frame, frame, 0.75)
    actual = {name: all_features[name] for name in FEATURE_NAMES}

    assert actual.keys() == expected.keys()
    for name, expected_value in expected.items():
        assert actual[name] == pytest.approx(expected_value, abs=1e-10)
