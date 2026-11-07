"""Causal, ordered channel checks and sensor shapes in physical units."""

import numpy as np
import pandas as pd
from retrofit_sim.baselines import CH, COUPLED

from .data import AVAILABILITY
from .params import (
    ACTUATOR_CHANNELS, B1_K, COUPLED_STILL_FRACTION, MAD_SCALE, NOISE_MIN_DENSE_COUNT,
    NOISE_RECENT_MIN, RAMP_MIN_HOURS, RAMP_MIN_R2,
    SHAPE_BLOCK_MIN, SHAPE_FIT_FRACTION,
    SHAPE_MIN_CHANGE_FLOORS, SHAPE_MIN_OBSERVATIONS, STEP_STABILITY_FRACTION,
    THERMAL_SETTLE_MIN, WIRELESS_CHANNELS, Z_FLOORS,
)


def observations(history, key):
    """Return real, good observations; never forward-fill missing samples."""
    channel = CH[key]
    mean, count = channel + "__mean", channel + "__count"
    if mean not in history or count not in history:
        return history.iloc[:0]
    valid = history[mean].notna() & history[count].gt(0)
    if "quality_any" in history:
        # DATA_DICTIONARY: COMM_LOSS=1, STALE=4, BAD_SENSOR_STATUS=8.
        valid &= (history.quality_any.fillna(0).astype("int64") & 13).eq(0)
    return history.loc[valid]


def update_interval(metadata, key):
    """Static sensor cadence; expected wireless pauses are not observations."""
    cadence = metadata.get("wireless_update_s", np.nan) if key in WIRELESS_CHANNELS else 60
    return pd.Timedelta(seconds=max(60, float(cadence)) if pd.notna(cadence) else 60)


def channel_snapshot(history, metadata, time):
    """Latest real reading within its installed instrument's update interval."""
    installed = str(metadata.get("channels_available", "")).split("|")
    latency = AVAILABILITY["features_1min.parquet"].latency
    snapshot = {}
    for key, channel in CH.items():
        if channel not in installed:
            continue
        obs = observations(history, key)
        if obs.empty:
            continue
        latest = obs.iloc[-1]
        age = time - (latest.window_start_utc + latency)
        if age < update_interval(metadata, key):
            snapshot[key] = latest
    return snapshot


def steady_minutes(history):
    """Consecutive completed steady minutes since the last non-steady row."""
    if history.empty or "steady" not in history:
        return 0
    steady = history.steady.fillna(False).to_numpy(dtype=bool)
    breaks = np.flatnonzero(~steady)
    return len(steady) - (int(breaks[-1]) + 1 if len(breaks) else 0)


def coupled_channels(key, installed):
    """Independent witnesses; an actuator's own deviation uses normal coupling."""
    return tuple(c for c in COUPLED.get(key, ()) if CH[c] in installed
                 and (key in ACTUATOR_CHANNELS or c not in ACTUATOR_CHANNELS))


def noise_channel(history, snapshot, installed, metadata):
    """Isolated variance from recent real-observation medians, not the last row."""
    if history.empty:
        return None
    recent = history.loc[history.window_start_utc > history.window_start_utc.iloc[-1]
                         - pd.Timedelta(minutes=NOISE_RECENT_MIN)]
    statistics = {}
    for key in CH:
        if key not in snapshot:
            continue
        obs = observations(recent, key)
        z, zs = "z_" + key, "zs_" + key
        if z not in obs or zs not in obs:
            continue
        valid = obs.loc[np.isfinite(obs[z]) & np.isfinite(obs[zs])]
        if len(valid) >= SHAPE_MIN_OBSERVATIONS:
            statistics[key] = (valid[z].abs().median(), valid[zs].median(), valid[zs].abs().median())
    # Stable ordering keeps CH as tie-breaker for equal recent variance evidence.
    for key in sorted(statistics, key=lambda c: -statistics[c][1]):
        if update_interval(metadata, key) > pd.Timedelta(minutes=1):
            continue
        obs = observations(recent, key)
        dense = obs.loc[obs[CH[key] + "__count"].ge(NOISE_MIN_DENSE_COUNT)]
        z, zs = "z_" + key, "zs_" + key
        dense = dense.loc[np.isfinite(dense[z]) & np.isfinite(dense[zs])]
        if len(dense) < SHAPE_MIN_OBSERVATIONS:
            continue
        if not (dense[zs].median() > B1_K and dense[z].abs().median() < B1_K * COUPLED_STILL_FRACTION):
            continue
        coupled = coupled_channels(key, installed)
        if not coupled or any(c not in statistics or statistics[c][2] >= B1_K * COUPLED_STILL_FRACTION
                              for c in coupled):
            continue
        return key
    return None


def consistency_state(snapshot, installed, settled_minutes):
    """Return one state, selected channel, and ordered deviating channels.

    A positively isolated channel takes priority. Otherwise a following reference
    refutes isolation. Missing/NaN references never establish stillness.
    """
    # Python's stable sort retains CH as the explicit tie-breaker.
    deviating = tuple(sorted((key for key in CH if key in snapshot
        and (key not in ("wt", "bt") or settled_minutes >= THERMAL_SETTLE_MIN)
        and abs(snapshot[key].get("z_" + key, np.nan)) > B1_K),
        key=lambda c: -abs(snapshot[c]["z_" + c])))
    following = None
    for key in deviating:
        # Only installed coupled instruments can participate; the snapshot omits
        # absent/stale instruments. At least one real reference is necessary.
        coupled = coupled_channels(key, installed)
        values = [snapshot[c].get("z_" + c, np.nan) for c in coupled if c in snapshot]
        finite = [value for value in values if np.isfinite(value)]
        threshold = B1_K * COUPLED_STILL_FRACTION
        if finite and any(abs(value) >= threshold for value in finite):
            if following is None:
                following = key
        elif finite and len(finite) == len(coupled):
            return "confirmed", key, deviating
    if following is not None:
        return "refuted", following, deviating
    return "unverifiable", deviating[0] if deviating else None, deviating


def deviation_start(history, key, metadata, time):
    """First real minute above k/3 in the current causal observation episode."""
    latency = AVAILABILITY["features_1min.parquet"].latency
    prefix = history.loc[history.window_start_utc + latency <= time].sort_values("window_start_utc")
    obs = observations(prefix, key)
    if obs.empty or "z_" + key not in obs:
        return None
    z = obs["z_" + key].to_numpy(dtype=float)
    times = obs.window_start_utc.tolist()
    start = None
    cadence = update_interval(metadata, key)
    for i in range(len(obs) - 1, -1, -1):
        if not np.isfinite(z[i]) or abs(z[i]) <= B1_K * COUPLED_STILL_FRACTION:
            break
        if i < len(obs) - 1 and times[i + 1] - times[i] > cadence:
            break
        start = times[i]
    return start


def sensor_shape(history, key, metadata, time):
    """Physical before/after blocks anchored at the causal episode onset."""
    start = deviation_start(history, key, metadata, time)
    if start is None:
        return "UNKNOWN", "no continuous deviation episode"
    mean = CH[key] + "__mean"
    cadence = update_interval(metadata, key)
    # Three real wireless updates need 15 min; dense blocks remain 10 min.
    duration = max(pd.Timedelta(minutes=SHAPE_BLOCK_MIN), SHAPE_MIN_OBSERVATIONS * cadence)
    frame = history.loc[history.window_start_utc >= start - duration]
    if "steady" in frame and not frame.steady.fillna(False).all():
        return "UNKNOWN", "stop or settling interrupts before/after continuity"
    obs = observations(frame, key)
    before, after = obs.loc[obs.window_start_utc < start], obs.loc[obs.window_start_utc >= start]
    if min(len(before), len(after)) < SHAPE_MIN_OBSERVATIONS:
        return "UNKNOWN", "insufficient real before/after observations"
    if obs.window_start_utc.diff().gt(cadence).any() or before.window_start_utc.iloc[0] > start - duration:
        return "UNKNOWN", "missing continuity across the change"
    # A physical regime change is not an instrument step. No z refresh is used
    # in the fit: only physical means at the current, comparable operating regime.
    if "regime" in frame and not frame.regime.eq(frame.regime.iloc[-1]).all():
        return "UNKNOWN", "operating regime changed across the physical comparison"
    level = before[mean].median()
    shifted = after[mean].median()
    delta = abs(shifted - level)
    spread = MAD_SCALE * np.median(abs(after[mean] - shifted))
    floor = Z_FLOORS[key]
    elapsed = time - (start + AVAILABILITY["features_1min.parquet"].latency)
    if (elapsed + cadence >= duration and delta >= SHAPE_MIN_CHANGE_FLOORS * floor
            and spread <= STEP_STABILITY_FRACTION * delta):
        return "SENSOR_CALIBRATION_SHIFT", f"persistent physical step {delta:.3g}; episode since {start.isoformat()}"
    # Fit a ramp to physical block medians of the episode, with no implicit
    # observations in the normal pauses of battery wireless instruments.
    blocks = after.groupby((after.window_start_utc - start) // duration)[mean].agg(["median", "count"])
    blocks = blocks.loc[blocks["count"] >= SHAPE_MIN_OBSERVATIONS]
    if len(blocks) < 6:
        return "UNKNOWN", "too few populated physical blocks"
    y = blocks["median"].to_numpy(dtype=float)
    x = blocks.index.to_numpy(dtype=float) * duration.total_seconds() / 3600
    total = np.sum((y - np.median(y)) ** 2)
    if total <= 0:
        return "UNKNOWN", "no separable physical change"
    slope, intercept = np.polyfit(x, y, 1)
    linear_error = np.sum((y - (slope * x + intercept)) ** 2)
    if x[-1] >= RAMP_MIN_HOURS and len(y) >= 6:
        middle = len(y) // 2
        slopes = [np.polyfit(x[a:b], y[a:b], 1)[0] for a, b in ((0, middle), (middle, len(y)))]
        change = abs(slope * x[-1])
        # Reject a single dominant jump: ramp evidence is distributed over time.
        dominant_jump = np.max(abs(np.diff(y)))
        if (change >= SHAPE_MIN_CHANGE_FLOORS * floor and linear_error <= (1 - RAMP_MIN_R2) * total
                and dominant_jump <= SHAPE_FIT_FRACTION * change and all(s * slope > 0 for s in slopes)):
            return "SENSOR_DRIFT", f"physical ramp {slope:+.3g}/h over {x[-1]:.2f} h; concordant halves"
    return "UNKNOWN", "step, ramp and variance not separable"
