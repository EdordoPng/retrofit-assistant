"""Load available minutes and run the requested advisory detector."""

import pandas as pd

from .data import load_assets, load_features
from .detectors import causal_b1
from .policy import apply_guarantees


def run_detector(data, split, detector="full", until=None) -> pd.DataFrame:
    if detector not in ("full", "causal_b1"):
        raise ValueError("Unknown detector")
    assets = load_assets(data, split)
    features = load_features(data, assets, until=until)
    candidates = causal_b1(features, assets)
    if detector == "causal_b1":
        return candidates
    return apply_guarantees(candidates, features, assets)
