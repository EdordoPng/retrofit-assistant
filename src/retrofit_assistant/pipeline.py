"""Load available minutes and run the requested advisory detector."""

import pandas as pd
from retrofit_sim.baselines import b1_threshold

from .data import load_assets, load_features
from .detectors import causal_b1, score_features
from .diagnosis import rediagnose
from .params import B1_K, B1_PERSIST
from .policy import apply_guarantees


def run_detector(data, split, detector="full", until=None) -> pd.DataFrame:
    if detector not in ("full", "causal_b1"):
        raise ValueError("Unknown detector")
    assets = load_assets(data, split)
    features = load_features(data, assets, until=until)
    if detector == "causal_b1":
        return causal_b1(features, assets)
    scored = score_features(features, assets)
    candidates = b1_threshold(scored, k=B1_K, persist=B1_PERSIST)
    return apply_guarantees(rediagnose(candidates, scored, assets), features, assets)
