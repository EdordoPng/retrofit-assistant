"""Instrumentation and observation model: truth -> what the historian actually stores.

Every channel has: source, range, accuracy (1-sigma noise), offset (unit calibration), resolution,
time constant, update interval and a dropout process. Instrument faults (drift, stuck, calibration step,
noise/spikes, communication loss) act here, on the reading, never on the physics.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

QUALITY_BITS = {"COMM_LOSS": 1, "OUT_OF_RANGE": 2, "STALE": 4, "BAD_SENSOR_STATUS": 8, "STARTUP_INHIBIT": 16}


@dataclass
class Channel:
    column: str
    truth_key: str
    source: str              # PLC | VFD | WIRELESS | IOLINK | POWER_METER | FLOW_METER
    lo: float
    hi: float
    sigma: float             # white noise, engineering units
    rel_sigma: float         # additional noise proportional to reading
    resolution: float
    tau_s: float             # sensor/transmitter lag
    update_s: int            # new value every update_s seconds (otherwise NaN in the 1 Hz table)
    offset_sd: float = 0.0   # unit-to-unit calibration offset (1-sigma)
    gain_sd: float = 0.0


# Instrumentation tiers. Columns absent from a tier are NULL for that asset.
TIERS = {
    # legacy: motor-control-centre current, discharge pressure transmitter, line temperature; VFD data if a drive exists
    "T0_LEGACY": ["motor_current_a", "discharge_pressure_kpa", "fluid_temp_c", "ambient_temp_c"],
    # low-cost retrofit: + battery wireless vibration/temperature sensor on the pump bearing housing, + suction pressure
    "T1_RETROFIT": ["motor_current_a", "discharge_pressure_kpa", "suction_pressure_kpa", "fluid_temp_c", "ambient_temp_c",
                    "vibration_rms_mm_s", "vibration_accel_rms_g", "vibration_crest_factor", "bearing_temp_c"],
    # well-instrumented: + flow meter, wired IO-Link vibration at 1 s, PT100 bearing and winding, power meter, valve feedback
    "T2_FULL": ["motor_current_a", "motor_power_kw", "discharge_pressure_kpa", "suction_pressure_kpa", "flow_m3_h",
                "fluid_temp_c", "ambient_temp_c", "bearing_temp_c", "motor_winding_temp_c", "vibration_rms_mm_s",
                "vibration_accel_rms_g", "vibration_crest_factor", "valve_position_pct"],
}
VFD_CHANNELS = ["motor_speed_rpm", "motor_power_kw"]       # drives report speed and power over fieldbus


def channel_specs(asset: dict) -> dict:
    """Channel definitions scaled to the asset's ratings (transmitter ranges follow sizing practice)."""
    tier = asset["instrumentation_tier"]
    wireless = tier == "T1_RETROFIT"
    i_rated = asset["motor_kw"] * 1000 / (asset["motor_eff"] * np.sqrt(3) * asset["voltage_v"] * asset["motor_pf"])
    p_range_d = 1000.0 if asset["h_bep_m"] * 1.3 * 10 < 900 else 1600.0      # kPa(g) 0-10 / 0-16 bar transmitters
    vib_upd = asset.get("wireless_update_s", 300) if wireless else 1
    ch = {
        "motor_current_a": Channel("motor_current_a", "current_a", "VFD" if asset["control"].startswith("VFD") else "PLC",
                                   0, 2.0 * i_rated, 0.004 * 2.0 * i_rated, 0.003, 0.1, 1.0, 1, 0.002 * i_rated, 0.005),
        "motor_power_kw": Channel("motor_power_kw", "input_kw", "VFD" if asset["control"].startswith("VFD") else "POWER_METER",
                                  0, 1.6 * asset["motor_kw"], 0.003 * asset["motor_kw"], 0.005, 0.1, 1.0, 1, 0.0, 0.005),
        "motor_speed_rpm": Channel("motor_speed_rpm", "rpm", "VFD", 0, 1.2 * asset["rated_rpm"], 1.0, 0.0, 1.0, 0.5, 1),
        "discharge_pressure_kpa": Channel("discharge_pressure_kpa", "discharge_kpa_g", "PLC", -100, p_range_d,
                                          0.0025 * p_range_d, 0.0, 0.1, 0.5, 1, 0.002 * p_range_d, 0.003),
        "suction_pressure_kpa": Channel("suction_pressure_kpa", "suction_kpa_g", "PLC", -100, 600, 0.0025 * 700, 0.0, 0.1, 0.5, 1,
                                        0.002 * 700, 0.003),
        "flow_m3_h": Channel("flow_m3_h", "flow_m3h", "FLOW_METER", 0, 1.5 * asset["q_bep_m3h"], 0.005 * asset["q_bep_m3h"], 0.01,
                             0.1, 3.0, 1, 0.0, 0.01),
        "fluid_temp_c": Channel("fluid_temp_c", "fluid_temp_c", "PLC", -20, 120, 0.08, 0.0, 0.1, 25.0, 1, 0.15, 0.0),
        "ambient_temp_c": Channel("ambient_temp_c", "ambient_c", "PLC", -30, 70, 0.15, 0.0, 0.1, 120.0, 10, 0.3, 0.0),
        "bearing_temp_c": Channel("bearing_temp_c", "bearing_temp_c", "WIRELESS" if wireless else "PLC", -20, 150,
                                  0.3 if wireless else 0.1, 0.0, 0.1 if not wireless else 0.5, 60.0 if wireless else 20.0, vib_upd,
                                  1.0 if wireless else 0.2, 0.0),
        "motor_winding_temp_c": Channel("motor_winding_temp_c", "winding_temp_c", "PLC", -20, 200, 0.2, 0.0, 0.1, 20.0, 1, 0.5, 0.0),
        "vibration_rms_mm_s": Channel("vibration_rms_mm_s", "vib_rms_mm_s", "WIRELESS" if wireless else "IOLINK", 0, 50,
                                      0.03, 0.06, 0.01, 1.0, vib_upd, 0.0, 0.05),
        "vibration_accel_rms_g": Channel("vibration_accel_rms_g", "vib_accel_rms_g", "WIRELESS" if wireless else "IOLINK", 0, 16,
                                         0.004, 0.08, 0.001, 1.0, vib_upd, 0.0, 0.05),
        "vibration_crest_factor": Channel("vibration_crest_factor", "vib_crest", "WIRELESS" if wireless else "IOLINK", 1, 20,
                                          0.08, 0.06, 0.01, 1.0, vib_upd, 0.0, 0.0),
        "valve_position_pct": Channel("valve_position_pct", "valve_position_pct", "PLC", 0, 100, 0.3, 0.0, 0.1, 2.0, 1, 0.5, 0.0),
    }
    cols = list(TIERS[tier])
    if asset["control"].startswith("VFD"):
        cols += [c for c in VFD_CHANNELS if c not in cols]
    if asset["control"] not in ("FLOW_VALVE", "VFD_PRESSURE") and "valve_position_pct" in cols:
        cols.remove("valve_position_pct")       # manual valves have no position feedback
    cols = [c for c in cols if c not in set(asset.get("missing_channels", []))]   # stress tier: failed / absent sensors
    return {c: ch[c] for c in cols}


def observe(truth: dict, asset: dict, specs: dict, sensor_faults: list, comm: dict, rng: np.random.Generator):
    """Return (observed columns dict, per-row quality bitmask, rows_present mask, applied fault info)."""
    from .physics import first_order
    n = len(truth["rpm"])
    out = {}
    qual = np.zeros(n, dtype=np.int32)
    t = np.arange(n)
    running = truth["speed_ratio"] > 0.02
    for col, c in specs.items():
        x = np.asarray(truth[c.truth_key], dtype=float).copy()
        undefined = np.isnan(x)                     # e.g. crest factor while stopped
        if c.tau_s > 0.6:
            x = first_order(np.where(undefined, np.nanmedian(x) if (~undefined).any() else 0.0, x), 1.0, c.tau_s)
            x[undefined] = np.nan
        off = rng.normal(0, c.offset_sd) if c.offset_sd else 0.0
        gain = 1.0 + (rng.normal(0, c.gain_sd) if c.gain_sd else 0.0)
        y = x * gain + off + rng.normal(0, 1, n) * (c.sigma + c.rel_sigma * np.abs(x))
        # instrument faults on this channel
        for f in sensor_faults:
            if f.sensor_tag != col:
                continue
            a = max(0, int(f.onset_s))
            b = n if f.end_s is None else min(n, int(f.end_s))
            if b <= a:
                continue
            p = f.params
            if f.fault_type == "SENSOR_DRIFT":
                y[a:b] += p["drift_per_h"] * (t[a:b] - a) / 3600.0
                if f.end_s is None or b == n:
                    pass
            elif f.fault_type == "SENSOR_CALIBRATION_SHIFT":
                y[a:b] += p["step"]
            elif f.fault_type == "SENSOR_STUCK":
                y[a:b] = y[a]
            elif f.fault_type == "SENSOR_NOISE_SPIKES":
                y[a:b] += rng.normal(0, p["noise_mult"] * (c.sigma + c.rel_sigma * np.abs(x[a:b]) + 1e-9))
                k = rng.random(b - a) < p["spike_rate"]
                y[a:b][k] += rng.choice([-1, 1], k.sum()) * p["spike_size"]
            elif f.fault_type == "COMMUNICATION_LOSS":
                y[a:b] = np.nan
                qual[a:b] |= QUALITY_BITS["COMM_LOSS"]
        # sample-and-hold transmitters update every update_s; table carries NaN between updates (sparse wireless)
        if c.update_s > 1:
            phase = int(rng.integers(0, c.update_s))
            keep = ((t - phase) % c.update_s) == 0
            y = np.where(keep, y, np.nan)
        # resolution and range clamp (out-of-range readings saturate and are flagged)
        y = np.round(y / c.resolution) * c.resolution
        # saturation outside the transmitter range is flagged; clipping of noise just below zero is not
        oor = (y < c.lo - 3.0 * (c.sigma + c.resolution)) | (y > c.hi)
        qual[oor] |= QUALITY_BITS["OUT_OF_RANGE"]
        y = np.clip(y, c.lo, c.hi)
        # physical meaning while stopped: speed/current/power read ~0; vibration sensors report low background
        if col in ("motor_speed_rpm", "motor_current_a", "motor_power_kw"):
            y = np.where(running | np.isnan(y), y, np.clip(rng.normal(0, c.sigma, n), 0, None).round(1))
        out[col] = y.astype(np.float32)
    # random single-sample drops and channel-level glitches
    for col in out:
        k = rng.random(n) < asset.get("sample_drop_prob", 0.0015)
        out[col][k] = np.nan
    # gateway outages: rows missing entirely
    present = np.ones(n, dtype=bool)
    for (a, b) in comm.get("gateway_outages", []):
        present[a:b] = False
    return out, qual, present
