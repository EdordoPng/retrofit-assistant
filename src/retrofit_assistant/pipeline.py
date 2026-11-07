"""Load available minutes and run the requested advisory detector."""

import pandas as pd
from retrofit_sim.baselines import b1_threshold

from .confidence import assign_confidence
from .data import load_assets, load_features, load_snapshots
from .detectors import causal_b1, score_features
from .diagnosis import rediagnose
from .params import B1_K, B1_PERSIST
from .policy import apply_guarantees
from .recommendations import recommend
from .sources import cavitation_candidates, merge_candidates, stuck_candidates


def candidate_stream(features, assets, snapshots=None) -> pd.DataFrame:
    """Merged, diagnosed and guided candidates with explicit provenance, before guarantees."""
    scored = score_features(features, assets)
    candidates = b1_threshold(scored, k=B1_K, persist=B1_PERSIST)
    diagnosed = rediagnose(candidates, scored, assets, snapshots)
    merged = merge_candidates(diagnosed, stuck_candidates(scored, assets, diagnosed),
                              cavitation_candidates(scored, assets, diagnosed))
    return assign_confidence(recommend(merged))


def run_detector(data, split, detector="full", until=None, mask_tier=None) -> pd.DataFrame:
    """Run causally, optionally removing T2 instruments for development ablations."""
    if detector not in ("full", "causal_b1"):
        raise ValueError("Unknown detector")
    if mask_tier not in (None, "T1", "T0"):
        raise ValueError("Invalid mask tier")
    if mask_tier is not None and split == "test":
        raise ValueError("Tier ablation is limited to train and validation")
    assets = load_assets(data, split)
    features = load_features(data, assets, until=until)
    snapshot_assets = assets
    if mask_tier is not None:
        assets = assets.copy(deep=True)
        features = features.copy(deep=True)
        masked = assets.instrumentation_tier.eq("T2_FULL")
        # TECHNICAL_MODEL §10: T0 has drive speed/power only with a VFD;
        # T1 adds suction, vibration and bearing temperature. Cadence stays dense.
        removed = {"flow_m3_h", "motor_winding_temp_c", "valve_position_pct"}
        if mask_tier == "T0":
            removed |= {"suction_pressure_kpa", "vibration_rms_mm_s",
                        "vibration_accel_rms_g", "vibration_crest_factor", "bearing_temp_c"}
        for index in assets.index[masked]:
            channels = removed.copy()
            if not str(assets.at[index, "control"]).startswith("VFD"):
                channels |= {"motor_power_kw", "motor_speed_rpm"}
            installed = str(assets.at[index, "channels_available"]).split("|")
            assets.at[index, "channels_available"] = "|".join(c for c in installed if c not in channels)
            assets.at[index, "instrumentation_tier"] = {"T1": "T1_RETROFIT", "T0": "T0_LEGACY"}[mask_tier]
            columns = [c for c in features if c.split("__", 1)[0] in channels]
            # Shared columns belong to other assets too: erase every statistic
            # only on this asset, retaining the shared feature schema.
            features.loc[features.asset_id.eq(assets.at[index, "asset_id"]), columns] = float("nan")
        snapshot_assets = assets.loc[~masked] if mask_tier == "T0" else assets
    if detector == "causal_b1":
        return causal_b1(features, assets)
    snapshots = (load_snapshots(data, snapshot_assets, until=until)
                 if mask_tier != "T0" or not snapshot_assets.empty else None)
    return apply_guarantees(candidate_stream(features, assets, snapshots), features, assets)
