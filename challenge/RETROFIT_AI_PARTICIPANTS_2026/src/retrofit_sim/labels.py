"""Event labels from simulator truth: onset, detectability (counterfactual), action deadline, severity."""
from __future__ import annotations

import numpy as np

# observable channels that can carry each fault's signature (column -> truth key)
OBS_KEYS = {"motor_current_a": "current_a", "motor_power_kw": "input_kw", "motor_speed_rpm": "rpm",
            "discharge_pressure_kpa": "discharge_kpa_g", "suction_pressure_kpa": "suction_kpa_g", "flow_m3_h": "flow_m3h",
            "fluid_temp_c": "fluid_temp_c", "bearing_temp_c": "bearing_temp_c", "motor_winding_temp_c": "winding_temp_c",
            "vibration_rms_mm_s": "vib_rms_mm_s", "vibration_accel_rms_g": "vib_accel_rms_g",
            "vibration_crest_factor": "vib_crest", "valve_position_pct": "valve_position_pct"}


def rolling_mean(x, w):
    x = np.nan_to_num(np.asarray(x, dtype=float))
    c = np.cumsum(np.r_[0.0, x])
    out = (c[w:] - c[:-w]) / w
    return np.r_[np.full(w - 1, out[0] if len(out) else 0.0), out]


def detectable_time(truth_f, truth_h, specs, active, window_s=600, k_sigma=3.0, unusable=None):
    """First time the fault's effect on ANY instrumented channel exceeds k sigma of that channel's noise
    (10-min mean; vibration and current additionally need a 2 % change to exceed unit-to-unit process variability),
    while the fault is active, the pump runs and the channel is not blinded by an instrument fault or data gap. None if never (unobservable with this
    instrumentation). Also returns the channels that carried the evidence."""
    best = None
    chans = []
    running = truth_f["speed_ratio"] > 0.05
    for col, c in specs.items():
        key = OBS_KEYS.get(col)
        if key is None:
            continue
        d = np.abs(np.nan_to_num(truth_f[key]) - np.nan_to_num(truth_h[key]))
        # noise of a 10-min mean (sparse sensors average fewer samples)
        n_eff = max(1, window_s // max(c.update_s, 1))
        sig = (c.sigma + c.rel_sigma * np.abs(np.nan_to_num(truth_h[key]))) / np.sqrt(n_eff)
        thr = k_sigma * np.maximum(sig, c.resolution) + 0.02 * np.abs(np.nan_to_num(truth_h[key])) * (col.startswith("vibration") or col == "motor_current_a")
        ok = (rolling_mean(d, window_s) > rolling_mean(thr, window_s)) & active & running
        if unusable is not None and col in unusable:
            ok &= ~unusable[col]          # channel blinded by an instrument fault or a data gap at that time
        idx = np.nonzero(ok)[0]
        if idx.size:
            chans.append((int(idx[0]), col))
            best = int(idx[0]) if best is None else min(best, int(idx[0]))
    chans = [c for i, c in sorted(chans)]
    return best, chans


def first_crossing(mask):
    idx = np.nonzero(mask)[0]
    return int(idx[0]) if idx.size else None


def cavitation_episodes(truth, min_dur_s=300, margin=1.15):
    """Emergent low-NPSH episodes (simplified criterion sigma = NPSHa/NPSHr < 1.15 while running)."""
    m = (truth["npsh_margin"] < margin) & (truth["speed_ratio"] > 0.3)
    from .records import _runs
    eps = []
    for a, b in _runs(m):
        if b - a >= min_dur_s:
            eps.append((int(a), int(b)))
    # merge episodes separated by < 30 min
    merged = []
    for a, b in eps:
        if merged and a - merged[-1][1] < 1800:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return merged


def severity_class(x, cuts):
    lo, hi = cuts
    return "minor" if x < lo else ("moderate" if x < hi else "severe")
