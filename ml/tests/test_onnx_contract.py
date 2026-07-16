from pathlib import Path

import numpy as np
import onnxruntime as ort
import pandas as pd

from probora_ml.config import FEATURE_NAMES
from probora_ml.training.pipeline import _classifier, _export


def test_direction_export_uses_dense_probability_tensor(tmp_path: Path) -> None:
    random = np.random.default_rng(17)
    features = pd.DataFrame(
        random.normal(size=(90, len(FEATURE_NAMES))).astype("float32"),
        columns=FEATURE_NAMES,
    )
    labels = np.tile(np.array([0, 1, 2]), 30)
    model = _classifier(17).set_params(n_estimators=5).fit(features, labels)
    model_path = tmp_path / "direction.onnx"

    _export(model, model_path, len(FEATURE_NAMES))

    session = ort.InferenceSession(model_path.as_posix(), providers=["CPUExecutionProvider"])
    outputs = {output.name: output for output in session.get_outputs()}
    assert outputs["probabilities"].type == "tensor(float)"
    assert outputs["probabilities"].shape == [None, 3]
