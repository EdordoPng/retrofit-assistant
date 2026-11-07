"""Dedicated causal alert sources; no event labels or fitted score thresholds."""

from dataclasses import dataclass
from collections import deque
import math
from statistics import median

import pandas as pd
from retrofit_sim.baselines import CH

from .consistency import update_interval
from .data import AVAILABILITY
from .output import COLUMNS
from .params import (
    BASELINE_HOURS, CAVITATION_ACCEL_MIN_HISTORY, CAVITATION_ANTOINE,
    CAVITATION_ANTOINE_K_RANGE, CAVITATION_ATMOSPHERE_KPA,
    CAVITATION_GRAVITY_M_S2, CAVITATION_MIN_MIN, CAVITATION_NPSH_MARGIN,
    CAVITATION_SUCTION_VELOCITY_BEP_M_S, CAVITATION_WATER_DENSITY_KG_M3,
    STUCK_BOUNDS, STUCK_MIN_MIN, STUCK_MIN_UPDATES,
)

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


def vapour_pressure_kpa(temperature_c):
    """Water Antoine pressure, NIST/Stull; refuse extrapolation beyond its range."""
    kelvin = float(temperature_c) + 273.15
    if not CAVITATION_ANTOINE_K_RANGE[0] <= kelvin <= CAVITATION_ANTOINE_K_RANGE[1]:
        return math.nan
    a, b, c = CAVITATION_ANTOINE
    return 100 * 10 ** (a - b / (kelvin + c))


def npsh_available_m(suction_kpa, temperature_c, flow_m3_h=None, rated_flow_m3_h=None):
    """Static suction gauge head plus estimated kinetic head when flow exists.

    Standard stagnation-head formulation (KSB NPSH lexicon, link in params).
    No suction diameter is public: velocity uses the documented BEP sizing
    estimate, not a reconstructed simulator flow or an inferred T1 flow.
    """
    head = ((suction_kpa + CAVITATION_ATMOSPHERE_KPA - vapour_pressure_kpa(temperature_c)) * 1000
            / (CAVITATION_WATER_DENSITY_KG_M3 * CAVITATION_GRAVITY_M_S2))
    if (flow_m3_h is not None and rated_flow_m3_h is not None
            and math.isfinite(flow_m3_h) and flow_m3_h >= 0
            and math.isfinite(rated_flow_m3_h) and rated_flow_m3_h > 0):
        velocity = CAVITATION_SUCTION_VELOCITY_BEP_M_S * flow_m3_h / rated_flow_m3_h
        head += velocity ** 2 / (2 * CAVITATION_GRAVITY_M_S2)
    return head


def _acceleration_evidence(history, decision_time, episode_start, cadence):
    if not history or decision_time - history[-1][0] >= cadence:
        return "acceleration confirmation unavailable: no fresh update; emitted without waiting"
    past = [value for time, value in history if time < episode_start]
    if len(past) < CAVITATION_ACCEL_MIN_HISTORY:
        return "acceleration confirmation unavailable: insufficient causal history; emitted without waiting"
    background = median(past)
    current = history[-1][1]
    status = "increasing" if current > background else "not increasing"
    return f"fresh acceleration={current:.6g} g vs pre-episode causal median={background:.6g} g ({status})"


def cavitation_candidates(minutes, assets, existing, until=None):
    """Nameplate NPSH margin; one physical train context, n = 1 pump (PUMP-06).

    this matches the simulator's model; on real equipment the margin needs site verification
    Required-NPSH dependence on flow is unknown. Speed-squared scaling and a
    BEP velocity estimate do not replace site curves or suction geometry.
    """
    rows = []
    latency = AVAILABILITY["features_1min.parquet"].latency
    minute = pd.Timedelta(minutes=1)
    for metadata in assets.to_dict("records"):
        installed = str(metadata.get("channels_available", "")).split("|")
        if metadata.get("instrumentation_tier") == "T0_LEGACY" or any(CH[key] not in installed for key in ("ps", "tf")):
            continue
        required = metadata.get("npsh3_at_bep_m", math.nan)
        if not math.isfinite(required) or required <= 0:
            continue
        asset = metadata["asset_id"]
        group = minutes.loc[minutes.asset_id == asset].sort_values("window_start_utc", kind="stable")
        if until is not None:
            group = group.loc[group.window_start_utc + latency <= pd.Timestamp(until)]
        if group.empty or any(CH[key] + suffix not in group for key in ("ps", "tf") for suffix in ("__mean", "__count")):
            continue
        keys = tuple(key for key in ("ps", "tf", "q", "n", "a") if CH[key] in installed
                     and all(CH[key] + suffix in group for suffix in ("__mean", "__count")))
        values = {key: group[CH[key] + "__mean"].to_numpy(dtype=float) for key in keys}
        counts = {key: group[CH[key] + "__count"].to_numpy(dtype=float) for key in keys}
        quality = group.quality_any.fillna(0).astype("int64").to_numpy()
        eligible = (group.operating_mode.eq("RUNNING") & group.steady.fillna(False)).to_numpy(dtype=bool)
        prior = existing.loc[(existing.asset_id == asset) & existing.fault_type.eq("CAVITATION")]
        prior_times = pd.DatetimeIndex(pd.to_datetime(prior.alert_time_utc, utc=True)).sort_values()
        acceleration = deque()
        cadence = update_interval(metadata, "a")
        low_start, episode_start, previous_row, latched = None, None, None, False
        for position, row_time in enumerate(group.window_start_utc):
            decision_time = pd.Timestamp(row_time) + latency
            continuous = previous_row is None or row_time - previous_row == minute
            previous_row = row_time
            if not continuous:
                low_start = None
            while acceleration and acceleration[0][0] < decision_time - pd.Timedelta(hours=BASELINE_HOURS):
                acceleration.popleft()
            if not eligible[position] or quality[position] & 15:
                low_start = None
                continue
            observed = {key: values[key][position] for key in keys
                        if counts[key][position] > 0 and math.isfinite(values[key][position])}
            if "a" in observed:
                acceleration.append((decision_time, observed["a"]))
            if "ps" not in observed or "tf" not in observed:
                low_start = None
                continue
            flow = observed.get("q")
            rated_flow = metadata.get("pump_rated_flow_m3_h", math.nan)
            kinetic = flow is not None and flow >= 0 and math.isfinite(rated_flow) and rated_flow > 0
            available = npsh_available_m(observed["ps"], observed["tf"], flow, rated_flow)
            speed, rated_speed = observed.get("n"), metadata.get("motor_rated_rpm", math.nan)
            scaled = speed is not None and speed > 0 and math.isfinite(rated_speed) and rated_speed > 0
            npsh3 = required * (speed / rated_speed) ** 2 if scaled else required
            margin = available / npsh3
            if not math.isfinite(margin):
                low_start = None
                continue
            if margin >= CAVITATION_NPSH_MARGIN:
                low_start, episode_start, latched = None, None, False
                continue
            if episode_start is None:
                episode_start = decision_time
            if low_start is None:
                low_start = row_time
            duration = decision_time - low_start
            if latched or duration < pd.Timedelta(minutes=CAVITATION_MIN_MIN):
                continue
            latched = True
            left = prior_times.searchsorted(episode_start, side="left")
            right = prior_times.searchsorted(decision_time, side="right")
            if left < right:
                continue
            speed_note = f"speed={speed:.6g} rpm, speed-squared scaled" if scaled else "speed unavailable, nameplate NPSH3 used"
            flow_note = (f"flow={flow:.6g} m3/h, kinetic head estimated from BEP sizing" if kinetic
                         else "flow unavailable, kinetic head omitted")
            rows.append({
                "asset_id": asset, "alert_time_utc": decision_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "event_class": "MACHINE", "fault_type": "CAVITATION", "confidence": 0.8,
                "evidence": (
                    f"suction_pressure_kpa={observed['ps']:.6g} gauge; fluid_temp_c={observed['tf']:.6g}; "
                    f"NPSHa={available:.6g} m / NPSH3={npsh3:.6g} m = {margin:.6g} < {CAVITATION_NPSH_MARGIN}; "
                    f"low margin for {duration.total_seconds() / 60:.1f} min; {speed_note}; {flow_note}; "
                    f"required-NPSH dependence on flow unknown; rho={CAVITATION_WATER_DENSITY_KG_M3:g} kg/m3 "
                    f"and atmosphere={CAVITATION_ATMOSPHERE_KPA:g} kPa approximations; "
                    + _acceleration_evidence(acceleration, decision_time, episode_start, cadence)
                    + "; cavitation: one physical context, n = 1 pump in train; "
                    "this matches the simulator's model; on real equipment the margin needs site verification"
                ),
                "recommended_action": "Inspect suction conditions and verify inlet pressure and temperature independently.",
                "decided_by": "source_cavitation",
            })
    return _candidate_frame(rows)
