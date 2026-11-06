"""Stress tier: deterministic random fleet of unseen assets (ratings, seasons, instrumentation, fault plans)."""
from __future__ import annotations

import numpy as np

from .fleet import _deep_merge, default_limits

RANGES = {  # (q_bep m3/h, h_bep m, rated rpm options, eta range) - same pump family, documented in TECHNICAL_MODEL.md
    "SHIP_SW_COOLING": ((300, 750), (20, 30), (1780, 1785), (0.80, 0.85)),
    "SHIP_LT_FRESHWATER": ((250, 500), (28, 38), (1775, 1780), (0.79, 0.84)),
    "INDUSTRIAL_CW": ((150, 450), (25, 40), (1480, 2955), (0.76, 0.84)),
    "PROCESS_TRANSFER": ((30, 80), (35, 50), (2930, 2950), (0.65, 0.74)),
}
CONTROLS = {"SHIP_SW_COOLING": ["VFD_TEMPERATURE", "FIXED_SPEED"], "SHIP_LT_FRESHWATER": ["FIXED_SPEED"],
            "INDUSTRIAL_CW": ["VFD_PRESSURE", "FIXED_SPEED"], "PROCESS_TRANSFER": ["FLOW_VALVE"]}
MOTOR_STEPS = [5.5, 7.5, 11, 15, 18.5, 22, 30, 37, 45, 55, 75, 90]
FAULT_MENU = ["BEARING_WEAR", "SUCTION_STRAINER_CLOGGING", "DISCHARGE_RESTRICTION", "MISALIGNMENT", "IMBALANCE",
              "SENSOR_DRIFT", "SENSOR_STUCK", "SENSOR_CALIBRATION_SHIFT", "SENSOR_NOISE_SPIKES", "COMMUNICATION_LOSS"]
SENSOR_TAGS = ["discharge_pressure_kpa", "suction_pressure_kpa", "bearing_temp_c", "motor_current_a", "flow_m3_h"]


def _fault(rng, typ, days, tags=None):
    tags = tags or SENSOR_TAGS
    H = days * 24
    on = float(rng.uniform(0.1, 0.7) * H)
    end = float(min(H - 1, on + rng.uniform(8, 60))) if rng.random() < 0.6 else None
    e = {"type": typ, "onset_h": round(on, 1)}
    if end:
        e["end_h"] = round(end, 1)
    if typ == "BEARING_WEAR":
        e["params"] = {"rate_per_h": float(rng.uniform(0.008, 0.014)), "t_fail_h": float(rng.uniform(0.6, 2.0) * H)}
        if end:
            e["repair_h"] = 5.0
    elif typ == "SUCTION_STRAINER_CLOGGING":
        e["params"] = {"rate_per_h": float(rng.uniform(0.03, 0.12)), "c_max": float(rng.uniform(2.0, 6.0)), "shape": "linear"}
        if end:
            e["repair_h"] = 1.5
    elif typ == "DISCHARGE_RESTRICTION":
        e["params"] = {"rate_per_h": float(rng.choice([0.03, 0.1, 2.0])), "extra_max": float(rng.uniform(0.4, 1.5)), "shape": "exp"}
        if end:
            e["repair_h"] = 1.0
    elif typ == "MISALIGNMENT":
        e["params"] = {"level": float(rng.uniform(0.3, 0.7)), "growth_per_h": float(rng.uniform(0, 0.004))}
        if end:
            e["repair_h"] = 3.0
    elif typ == "IMBALANCE":
        e["params"] = {"rate_per_h": float(rng.uniform(0.005, 0.015)), "u_max": float(rng.uniform(0.6, 1.5)), "shape": "linear"}
    elif typ == "SENSOR_DRIFT":
        e["sensor_tag"] = str(rng.choice(tags))
        e["params"] = {"drift_per_h": float(rng.choice([-1, 1]) * rng.uniform(0.1, 0.6))}
    elif typ == "SENSOR_CALIBRATION_SHIFT":
        e["sensor_tag"] = str(rng.choice(tags))
        e["params"] = {"step": float(rng.choice([-1, 1]) * rng.uniform(5, 20))}
    elif typ == "SENSOR_STUCK":
        e["sensor_tag"] = str(rng.choice(tags))
        e["end_h"] = round(min(H - 1, on + rng.uniform(2, 20)), 1)
    elif typ == "SENSOR_NOISE_SPIKES":
        e["sensor_tag"] = str(rng.choice(tags))
        e["end_h"] = round(min(H - 1, on + rng.uniform(2, 12)), 1)
        e["params"] = {"noise_mult": float(rng.uniform(3, 6)), "spike_rate": float(rng.uniform(0.001, 0.005)), "spike_size": 25.0}
    elif typ == "COMMUNICATION_LOSS":
        e["sensor_tag"] = "GATEWAY"
        e["end_h"] = round(min(H - 1, on + rng.uniform(0.5, 4)), 1)
    return e


def sample_fleet(public_cfg: dict, seed: int, n_assets: int = 6, days: float = 3.0, missing_prob: float = 0.25) -> list:
    rng = np.random.default_rng([int(seed), 911])
    out = []
    profiles = list(RANGES)
    for k in range(n_assets):
        prof = profiles[int(rng.integers(0, len(profiles)))]
        (q0, q1), (h0, h1), rpms, (e0, e1) = RANGES[prof]
        q = float(np.round(rng.uniform(q0, q1), -1 if q1 > 100 else 0))
        h = float(np.round(rng.uniform(h0, h1), 1))
        rpm = float(rng.choice(rpms))
        eta = float(np.round(rng.uniform(e0, e1), 3))
        p_shaft = 1000 * 9.81 * q / 3600 * h / eta / 1000
        motor = next(m for m in MOTOR_STEPS if m >= 1.12 * p_shaft)
        ctrl = str(rng.choice(CONTROLS[prof]))
        tier = str(rng.choice(["T0_LEGACY", "T1_RETROFIT", "T2_FULL"], p=[0.35, 0.4, 0.25]))
        month = int(rng.integers(1, 13))
        a = _deep_merge(public_cfg["profiles"][prof], {
            "asset_id": f"STRESS-{k + 1:02d}", "split": "stress", "site": "Stress-test site (fictional)",
            "system": f"{prof.replace('_', ' ').title()} pump", "profile": prof, "control": ctrl,
            "start_utc": f"2025-{month:02d}-{int(rng.integers(1, 20)):02d}T00:00:00", "commissioned_year": int(rng.integers(1995, 2022)),
            "instrumentation_tier": tier, "q_bep_m3h": q, "h_bep_m": h, "eta_bep": eta,
            "npshr_bep_m": float(np.round(rng.uniform(2.6, 4.8), 1)), "q_design_m3h": round(0.95 * q, 0), "h_design_m": round(0.98 * h, 1),
            "motor_kw": motor, "motor_eff": 0.90 + 0.05 * min(1, motor / 75), "motor_pf": 0.85, "rated_rpm": rpm,
            "vib_base_mm_s": float(rng.uniform(0.9, 1.7)),
            "unbalance_base_mm_s": 0.6, "hydraulic_vib_mm_s": 1.0, "cavitation_vib_mm_s": 3.0, "accel_base_g": float(rng.uniform(0.13, 0.25)),
            "dp_setpoint_m": round(0.85 * h, 1),
        })
        from .sensors import TIERS
        have = [t for t in SENSOR_TAGS if t in TIERS[tier]]
        if rng.random() < missing_prob:
            # a failed or removed optional instrument (core legacy signals are always kept)
            optional = [c for c in TIERS[tier] if c not in TIERS["T0_LEGACY"]]
            if optional:
                a["missing_channels"] = [str(rng.choice(optional))]
        have = [t for t in have if t not in a.get("missing_channels", [])]
        n_f = int(rng.integers(2, 5))
        menu = [t for t in FAULT_MENU if not (t.startswith("SENSOR") and not have)]
        picks = list(rng.choice(menu, n_f, replace=False))
        if not any(not str(t).startswith(("SENSOR", "COMMUNICATION")) for t in picks):
            picks[0] = str(rng.choice(["BEARING_WEAR", "SUCTION_STRAINER_CLOGGING", "DISCHARGE_RESTRICTION"]))
        a["scenario"] = [_fault(rng, str(t), days, have) for t in picks]
        a.setdefault("design_supply_temp_c", 25.0)
        a["limits"] = default_limits(a)
        a["_limit_overrides"] = []
        out.append(a)
    return out
