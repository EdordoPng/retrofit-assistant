"""Reference detectors, before the full pipeline's alert policy."""

import pandas as pd
from retrofit_sim.baselines import b1_threshold, regime_frame

from .baseline import causal_zscores
from .params import B1_K, B1_PERSIST


def causal_b1(features, assets) -> pd.DataFrame:
    """Run published B1 thresholds on hourly causal scores, retaining reminders."""
    if features.empty:
        return b1_threshold(features)
    return b1_threshold(score_features(features, assets), k=B1_K, persist=B1_PERSIST)


def score_features(features, assets) -> pd.DataFrame:
    """Share the causal score frame without changing the reference thresholds."""
    if features.empty:
        return features.copy()
    return causal_zscores(regime_frame(features, assets))
