"""Operator-facing records derived from observed signals and the fault plan:
SCADA/PLC-style alarms, maintenance log (history + in-window interventions) and event labels.
"""
from __future__ import annotations

import numpy as np

# Alarm rules: (tag, kind, limit-key, delay_s, clear_deadband (fraction of limit), inhibit_after_start_s, priority)
ALARM_RULES = [
    ("vibration_rms_mm_s", "HI", "vib_alarm_mm_s", 30, 0.10, 90, 2),
    ("vibration_rms_mm_s", "HIHI", "vib_trip_mm_s", 10, 0.10, 90, 1),
    ("bearing_temp_c", "HI", "bearing_alarm_c", 60, 0.03, 0, 2),
    ("bearing_temp_c", "HIHI", "bearing_trip_c", 30, 0.03, 0, 1),
    ("motor_winding_temp_c", "HI", "winding_alarm_c", 60, 0.03, 0, 2),
    ("suction_pressure_kpa", "LO", "suction_lo_kpa", 20, 0.05, 60, 2),
    ("discharge_pressure_kpa", "LO", "discharge_lo_kpa", 20, 0.05, 60, 2),
    ("flow_m3_h", "LO", "flow_lo_m3h", 30, 0.05, 90, 2),
    ("motor_current_a", "HI", "current_hi_a", 15, 0.03, 20, 2),
    ("fluid_temp_c", "HI", "fluid_hi_c", 120, 0.02, 0, 3),
]


def _runs(mask):
    """Start/end indices of True runs."""
    m = np.concatenate([[False], mask, [False]]).astype(np.int8)
    d = np.diff(m)
    return list(zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]))


def alarms(asset_id: str, obs: dict, present: np.ndarray, running: np.ndarray, limits: dict, t0_ms: int, rng,
           comm_quality: np.ndarray, night: np.ndarray) -> list:
    rows = []
    n = len(running)
    start_idx = np.nonzero(np.diff(running.astype(int)) == 1)[0] + 1
    since_start = np.full(n, 10 ** 9)
    last = -10 ** 9
    j = 0
    starts = set(start_idx.tolist())
    for i in range(n):
        if i in starts:
            last = i
        since_start[i] = i - last
    for tag, kind, key, delay, db, inhibit, prio in ALARM_RULES:
        if tag not in obs or key not in limits or limits[key] is None:
            continue
        x = obs[tag].astype(float)
        # sparse sensors: hold last value for alarm evaluation (what a SCADA tag does)
        idx = np.where(~np.isnan(x), np.arange(n), 0)
        np.maximum.accumulate(idx, out=idx)
        xh = x[idx]
        xh[np.isnan(x[idx])] = np.nan
        lim = limits[key]
        if kind.startswith("HI"):
            bad = xh > lim
            ok = xh < lim * (1 - db)
        else:
            bad = xh < lim
            ok = xh > lim + max(abs(lim) * db, 2.0)
        if kind in ("LO",) or tag.startswith("vibration") or tag == "motor_current_a":
            bad &= running
        bad &= since_start >= inhibit
        bad &= present
        last_clear = -1
        for a, b in _runs(bad):
            if b - a < delay or a + delay <= last_clear:
                continue                      # still the same (uncleared) alarm: no new alarm instance
            raise_i = a + delay
            # clear when ok again for 30 s
            k = b
            while k < n and not (ok[k] if not np.isnan(xh[k]) else False):
                k += 1
                if k - b > 6 * 3600:
                    break
            clear_i = min(n - 1, k + 30)
            last_clear = clear_i
            ack_delay = rng.lognormal(np.log(240 if not night[raise_i] else 900), 0.9)
            ack_i = raise_i + int(ack_delay)
            rows.append({"asset_id": asset_id, "tag": tag, "alarm_type": kind, "priority": prio,
                         "raised_ms": t0_ms + raise_i * 1000, "cleared_ms": t0_ms + clear_i * 1000,
                         "acknowledged_ms": t0_ms + ack_i * 1000 if ack_i < clear_i + 3600 else None,
                         "value_at_raise": float(xh[raise_i]) if not np.isnan(xh[raise_i]) else None, "limit": float(lim)})
    # bad-quality / communication alarms (from quality bits), delay 30 s
    for a, b in _runs((comm_quality & 1) > 0):
        if b - a >= 30:
            rows.append({"asset_id": asset_id, "tag": "INSTRUMENT", "alarm_type": "BAD_QUALITY", "priority": 3,
                         "raised_ms": t0_ms + (a + 30) * 1000, "cleared_ms": t0_ms + b * 1000,
                         "acknowledged_ms": t0_ms + (a + 30 + int(rng.lognormal(np.log(600), 0.8))) * 1000, "value_at_raise": None, "limit": None})
    gaps = _runs(~present)
    for a, b in gaps:
        if b - a >= 60:
            rows.append({"asset_id": asset_id, "tag": "GATEWAY", "alarm_type": "COMM_LOSS", "priority": 3,
                         "raised_ms": t0_ms + (a + 60) * 1000, "cleared_ms": t0_ms + b * 1000,
                         "acknowledged_ms": None, "value_at_raise": None, "limit": None})
    return rows


OBS_TEXT = {
    "BEARING_WEAR": ["Noise from pump bearing housing, rumbling at speed.", "Bearing housing feels hot, grease discoloured.",
                     "Increased vibration reported by watchkeeper; suspect bearing.", "Rough running, possible cavitation?"],
    "SUCTION_STRAINER_CLOGGING": ["Strainer opened: mussels and debris found.", "Low suction pressure noted; strainer cleaned.",
                                  "Flow felt low, cooler outlet warm. Strainer partly blocked.", "Crackling noise from pump, suspected cavitation."],
    "DISCHARGE_RESTRICTION": ["Discharge valve found partly closed after previous work.", "Heat exchanger fouled, cleaned.",
                              "High discharge pressure, low flow; checked valves.", "Pump seems weak; impeller suspected."],
    "MISALIGNMENT": ["Coupling alignment checked with laser tool, corrected.", "Axial vibration high after overhaul.",
                     "Coupling rubber elements worn; realigned.", "Vibration high after bearing change; suspect looseness."],
    "IMBALANCE": ["Impeller fouled with marine growth, cleaned and balanced.", "1x vibration high; impeller inspected.",
                  "Vibration increases with speed; deposits on impeller."],
    "IMPELLER_WEAR": ["Wear ring clearance excessive; renewed.", "Pump head below curve at test; impeller worn.",
                      "Erosion on impeller vanes found."],
    "CAVITATION": ["Gravel-like noise at pump inlet.", "Cavitation noise at high flow; suction checked.", "Strange noise, bearing suspected."],
    "SENSOR_DRIFT": ["{tag} compared with a portable reference: instrument drifting, recalibrated.", "{tag} does not match the local gauge; recalibrated."],
    "SENSOR_STUCK": ["{tag} value frozen in SCADA; sensor replaced.", "{tag} constant for hours; cable / transmitter fault repaired."],
    "SENSOR_CALIBRATION_SHIFT": ["{tag}: offset found after recent work; corrected.", "{tag}: calibration error after maintenance, corrected."],
    "SENSOR_NOISE_SPIKES": ["{tag} noisy; loose connector tightened.", "Spikes on {tag}; cable screen re-terminated."],
    "COMMUNICATION_LOSS": ["Gateway rebooted.", "Wireless sensor battery replaced.", "Network switch power cycled."],
}
ACTION = {"BEARING_WEAR": "BEARING_REPLACEMENT", "SUCTION_STRAINER_CLOGGING": "STRAINER_CLEANING",
          "DISCHARGE_RESTRICTION": "VALVE_OR_COOLER_SERVICE", "MISALIGNMENT": "REALIGNMENT", "IMBALANCE": "IMPELLER_CLEAN_BALANCE",
          "IMPELLER_WEAR": "WEAR_RING_IMPELLER_RENEWAL", "CAVITATION": "SUCTION_INSPECTION", "SENSOR_DRIFT": "SENSOR_RECALIBRATION",
          "SENSOR_STUCK": "SENSOR_REPLACEMENT", "SENSOR_CALIBRATION_SHIFT": "SENSOR_RECALIBRATION",
          "SENSOR_NOISE_SPIKES": "WIRING_REPAIR", "COMMUNICATION_LOSS": "NETWORK_RESET"}


TAG_NAME = {"discharge_pressure_kpa": "Discharge pressure transmitter", "suction_pressure_kpa": "Suction pressure transmitter",
            "flow_m3_h": "Flow meter", "bearing_temp_c": "Bearing temperature sensor", "motor_current_a": "Motor current transducer",
            "fluid_temp_c": "Water temperature sensor", "vibration_rms_mm_s": "Vibration sensor", "motor_power_kw": "Power meter",
            "motor_winding_temp_c": "Winding temperature sensor", "valve_position_pct": "Valve position feedback"}
SENSOR_TYPES = {"SENSOR_DRIFT", "SENSOR_STUCK", "SENSOR_CALIBRATION_SHIFT", "SENSOR_NOISE_SPIKES"}


def operator_text(fault_type: str, rng, correct_prob=0.75, tag=None):
    """Recorded observation. Machine faults: usually consistent with the cause, sometimes a plausible misdiagnosis (the
    last template). Instrument faults name the affected instrument."""
    opts = OBS_TEXT.get(fault_type, ["Inspection, no finding."])
    if fault_type in SENSOR_TYPES:
        txt = opts[int(rng.integers(0, len(opts)))].format(tag=TAG_NAME.get(tag, "Instrument"))
        return txt[0].upper() + txt[1:], "CONFIRMED" if rng.random() < 0.8 else "PROBABLE"
    if rng.random() < correct_prob:
        return opts[int(rng.integers(0, max(1, len(opts) - 1)))], "CONFIRMED" if rng.random() < 0.7 else "PROBABLE"
    return opts[-1], "UNCERTAIN"
