"""Hourly causal robust scores with a pool frozen after the first day."""

import numpy as np
import pandas as pd
from retrofit_sim.baselines import CH

from .data import AVAILABILITY
from .params import (
    BASELINE_HOURS, FLAT_MIN_COUNT, GAP_MIN_ROWS, MAD_SCALE,
    MIN_POOL_SAMPLES, MIN_REGIME_SAMPLES, Z_FLOORS, ZS_FLOOR_ABS, ZS_FLOOR_REL,
)


def causal_zscores(frame) -> pd.DataFrame:
    """Apply each hourly pool only to subsequent minutes; never revise old scores."""
    latency = AVAILABILITY["features_1min.parquet"].latency
    output = []
    for _, group in frame.groupby("asset_id", sort=False):
        group = group.copy().reset_index(drop=True)
        t0 = group["window_start_utc"].min()
        segments = ((group["window_start_utc"] - t0) // pd.Timedelta(hours=1)).clip(upper=BASELINE_HOURS)
        scores = {}
        for key, channel in CH.items():
            scores["z_" + key] = np.full(len(group), np.nan)
            std = channel + "__std"
            if std in group:
                scores["zs_" + key] = np.full(len(group), np.nan)
                scores["flat_" + key] = (group[std] == 0) & group[channel + "__count"].ge(FLAT_MIN_COUNT)
        scores["gap"] = group["rows"] < GAP_MIN_ROWS
        group = pd.concat([group, pd.DataFrame(scores)], axis=1)
        for segment in sorted(segments.unique()):
            if segment == 0:
                continue
            refresh = t0 + pd.Timedelta(hours=int(segment))
            pool = group.loc[group["steady"] & (group["window_start_utc"] + latency <= refresh)]
            if len(pool) < MIN_POOL_SAMPLES:
                continue
            target = segments == segment
            regime_sizes = pool.groupby("regime").size()
            sufficient = regime_sizes >= MIN_REGIME_SAMPLES
            for key, channel in CH.items():
                mean = channel + "__mean"
                if mean in group:
                    by_regime = pool.groupby("regime")[mean]
                    med = by_regime.median().where(sufficient)
                    mad = by_regime.apply(lambda s: (s - s.median()).abs().median()).where(sufficient)
                    pooled_med = pool[mean].median()
                    pooled_mad = (pool[mean] - pooled_med).abs().median()
                    mu = group.loc[target, "regime"].map(med).fillna(pooled_med)
                    sd = MAD_SCALE * group.loc[target, "regime"].map(mad).fillna(pooled_mad)
                    group.loc[target, "z_" + key] = (group.loc[target, mean] - mu) / np.maximum(sd, Z_FLOORS[key])
                std = channel + "__std"
                if std in group:
                    sb = pool[std].median()
                    mad_s = (pool[std] - sb).abs().median()
                    denominator = max(MAD_SCALE * mad_s, ZS_FLOOR_ABS + ZS_FLOOR_REL * abs(sb))
                    group.loc[target, "zs_" + key] = (group.loc[target, std] - sb) / denominator
        output.append(group)
    if not output:
        # Keep the same generated schema even when no asset has completed a minute.
        empty = frame.copy()
        for key, channel in CH.items():
            empty["z_" + key] = pd.Series(index=empty.index, dtype="float64")
            if channel + "__std" in empty:
                empty["zs_" + key] = pd.Series(index=empty.index, dtype="float64")
                empty["flat_" + key] = pd.Series(index=empty.index, dtype="bool")
        empty["gap"] = pd.Series(index=empty.index, dtype="bool")
        return empty.reset_index(drop=True)
    return pd.concat(output, ignore_index=True)
