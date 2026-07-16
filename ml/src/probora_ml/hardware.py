from __future__ import annotations

from functools import lru_cache

import lightgbm as lgb
import numpy as np


@lru_cache(maxsize=1)
def gpu_training_available() -> bool:
    """Return whether this LightGBM build can train on an available OpenCL GPU."""
    features = np.array(
        [[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [1.0, 1.0]] * 4,
        dtype=np.float32,
    )
    labels = np.array([0, 0, 1, 1] * 4, dtype=np.int32)
    try:
        lgb.LGBMClassifier(
            n_estimators=1,
            num_leaves=2,
            min_child_samples=1,
            device_type="gpu",
            max_bin=63,
            verbosity=-1,
        ).fit(features, labels)
    except lgb.basic.LightGBMError:
        return False
    return True


def resolve_training_device(requested: str) -> str:
    normalized = requested.strip().lower()
    if normalized not in {"auto", "cpu", "gpu"}:
        raise ValueError("Training device must be one of: auto, cpu, gpu.")
    if normalized == "cpu":
        return "cpu"
    available = gpu_training_available()
    if normalized == "gpu" and not available:
        raise RuntimeError("GPU training was requested, but LightGBM could not use an OpenCL GPU.")
    return "gpu" if available else "cpu"
