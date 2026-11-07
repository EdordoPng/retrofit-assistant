"""Dedicated causal alert sources; no event labels or fitted score thresholds."""

from dataclasses import dataclass
import math

import pandas as pd
from retrofit_sim.baselines import CH

from .consistency import update_interval
from .data import AVAILABILITY
from .output import COLUMNS
from .params import STUCK_BOUNDS, STUCK_MIN_MIN, STUCK_MIN_UPDATES

INTERNAL_COLUMNS = [*COLUMNS, "decided_by"]


def _candidate_frame(rows):
    # Empty and populated prefixes must expose the same candidate schema.
    return pd.DataFrame(rows, columns=INTERNAL_COLUMNS).astype({
        column: "float64" if column == "confidence" else "str" for column in INTERNAL_COLUMNS
    })


@dataclass
class _StuckState:
    value: float | None = None
    count: int = 0
    first: pd.Timestamp | None = None
    episode_start: pd.Timestamp | None = None
    latched: bool = False


def _bounds(key, metadata):
    """Transmitter clamps from sensors.py channel_specs, using public nameplates."""
    if key in STUCK_BOUNDS:
        return STUCK_BOUNDS[key]
    if key == "pd":
        head = metadata.get("pump_rated_head_m", math.nan)
        return -100, 1000 if head * 1.3 * 10 < 900 else 1600
    rating, factor = {
        "i": ("motor_rated_current_a", 2), "pw": ("motor_rated_kw", 1.6),
        "n": ("motor_rated_rpm", 1.2), "q": ("pump_rated_flow_m3_h", 1.5),
    }[key]
    upper = metadata.get(rating, math.inf) * factor
    return 0, upper if pd.notna(upper) else math.inf


def stuck_candidates(minutes, assets, existing, until=None):
    """Count equal real updates; missing wireless minutes never become updates.

    Stops/quality faults interrupt persistence without rearming an emitted
    episode. Only a different valid running update rearms it. Suppression uses
    alerts already decided by t, never a later alert in the supplied full frame.
    """
    rows = []
    latency = AVAILABILITY["features_1min.parquet"].latency
    for metadata in assets.to_dict("records"):
        asset = metadata["asset_id"]
        group = minutes.loc[minutes.asset_id == asset].sort_values("window_start_utc", kind="stable")
        if until is not None:
            group = group.loc[group.window_start_utc + latency <= pd.Timestamp(until)]
        installed = str(metadata.get("channels_available", "")).split("|")
        keys = tuple(key for key, channel in CH.items() if channel in installed
                     and channel + "__mean" in group and channel + "__count" in group)
        if not keys or group.empty:
            continue
        states = {key: _StuckState() for key in keys}
        values = {key: group[CH[key] + "__mean"].to_numpy(dtype=float) for key in keys}
        counts = {key: group[CH[key] + "__count"].to_numpy(dtype=float) for key in keys}
        bounds = {key: _bounds(key, metadata) for key in keys}
        durations = {key: max(pd.Timedelta(minutes=STUCK_MIN_MIN),
                              (STUCK_MIN_UPDATES - 1) * update_interval(metadata, key)) for key in keys}
        # quality_any is a floating column after missing-minute anchoring.
        quality = group.quality_any.fillna(0).astype("int64").to_numpy()
        eligible = (group.operating_mode.eq("RUNNING") & group.steady.fillna(False)).to_numpy(dtype=bool)
        prior = existing.loc[(existing.asset_id == asset) & existing.fault_type.eq("SENSOR_STUCK")]
        prior_times = pd.DatetimeIndex(pd.to_datetime(prior.alert_time_utc, utc=True)).sort_values()
        emitted = []
        for position, row_time in enumerate(group.window_start_utc):
            time = pd.Timestamp(row_time) + latency
            for key in keys:
                state = states[key]
                value, count = values[key][position], counts[key][position]
                lower, upper = bounds[key]
                if not eligible[position] or quality[position] & 15:
                    state.count, state.first = 0, None
                    continue
                if not math.isfinite(value) or not count > 0:
                    continue
                if not lower < value < upper:
                    state.count, state.first = 0, None
                    continue
                if value != state.value:
                    state.value, state.count = value, 0
                    state.first, state.episode_start, state.latched = None, time, False
                if state.count == 0:
                    state.first = time
                state.count += 1
                duration = time - state.first
                if state.latched or state.count < STUCK_MIN_UPDATES or duration < durations[key]:
                    continue
                state.latched = True
                left = prior_times.searchsorted(state.episode_start, side="left")
                right = prior_times.searchsorted(time, side="right")
                if left < right or any(state.episode_start <= previous <= time for previous in emitted):
                    continue
                rows.append({
                    "asset_id": asset, "alert_time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "event_class": "SENSOR", "fault_type": "SENSOR_STUCK", "confidence": 0.8,
                    "evidence": (f"{CH[key]}={value:.9g}; unchanged across {state.count} real updates "
                                 f"over {duration.total_seconds() / 60:.1f} min; running and steady"),
                    "recommended_action": f"Verify transmitter {CH[key]} against an independent reference.",
                    "decided_by": "source_stuck",
                })
                emitted.append(time)
    return _candidate_frame(rows)


def merge_candidates(official, *sources):
    """Stable asset/time union: official, stuck, cavitation, then input order."""
    frames = [frame for frame in (official, *sources) if not frame.empty]
    if not frames:
        return _candidate_frame([])
    result = pd.concat(frames, ignore_index=True)
    result["_priority"] = result.decided_by.map({"source_stuck": 1, "source_cavitation": 2}).fillna(0)
    result["_time"] = pd.to_datetime(result.alert_time_utc, utc=True)
    return result.sort_values(["asset_id", "_time", "_priority"], kind="stable")[INTERNAL_COLUMNS].reset_index(drop=True)
