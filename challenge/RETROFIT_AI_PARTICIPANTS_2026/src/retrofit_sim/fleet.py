"""Fleet configuration loading: profile defaults + per-asset overrides + alarm limits."""
from __future__ import annotations

import copy

import numpy as np
import yaml

# ISO 10816-7 (rotodynamic pumps) recommended alarm / trip on non-rotating parts, mm/s RMS, as quoted in the
# Europump vibration guideline (2013). Category I = critical duty, Category II = general duty.
VIB_LIMITS = {("I", False): (5.0, 8.3), ("I", True): (6.3, 9.5), ("II", False): (6.4, 10.6), ("II", True): (7.6, 11.9)}
CATEGORY = {"SHIP_SW_COOLING": "I", "SHIP_LT_FRESHWATER": "I", "INDUSTRIAL_CW": "II", "PROCESS_TRANSFER": "II"}


def _deep_merge(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def rated_current_a(a: dict) -> float:
    return a["motor_kw"] * 1000 / (a["motor_eff"] * np.sqrt(3) * a["voltage_v"] * a["motor_pf"])


def default_limits(a: dict) -> dict:
    cat = CATEGORY.get(a["profile"], "II")
    alarm, trip = VIB_LIMITS[(cat, a["motor_kw"] > 200)]
    i_r = rated_current_a(a)
    q_min = a.get("flow_min_frac", 0.35) * a["q_design_m3h"]
    return {
        "vib_alarm_mm_s": alarm, "vib_trip_mm_s": trip,
        "bearing_alarm_c": 85.0, "bearing_trip_c": 95.0,
        "winding_alarm_c": 140.0,
        "suction_lo_kpa": a.get("suction_lo_kpa", -35.0 if a["profile"] != "SHIP_LT_FRESHWATER" else 60.0),
        "discharge_lo_kpa": a.get("discharge_lo_kpa", round(0.45 * a["h_design_m"] * 9.81, 0)),
        "flow_lo_m3h": round(q_min, 0), "flow_min_m3h": round(q_min, 0),
        "current_hi_a": round(1.05 * i_r, 1),
        "fluid_hi_c": a.get("fluid_hi_c", 45.0 if a["profile"].startswith("SHIP") else 75.0 if a["profile"] == "PROCESS_TRANSFER" else 38.0),
    }


def load_fleet(path: str, overrides: dict | None = None) -> tuple[dict, list]:
    with open(path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    profiles = cfg["profiles"]
    assets = []
    for raw in cfg["assets"]:
        prof = raw["profile"]
        base = profiles[prof] if prof in profiles else {}
        a = _deep_merge(base, raw)
        a.setdefault("design_supply_temp_c", 32.0)
        a["limits"] = _deep_merge(default_limits(a), raw.get("limits", {}))
        a["_limit_overrides"] = sorted(raw.get("limits", {}).keys())
        assets.append(a)
    if overrides:
        for a in assets:
            a.update(overrides.get(a["asset_id"], {}))
    return cfg, assets


def merge_profiles(public_cfg: dict, private_cfg: dict) -> list:
    """Private (test) asset entries reuse the public profile defaults."""
    out = []
    for raw in private_cfg["assets"]:
        prof = raw["profile"]
        base = private_cfg.get("profiles", {}).get(prof, public_cfg["profiles"][prof])
        a = _deep_merge(base, raw)
        a.setdefault("design_supply_temp_c", 32.0)
        a["limits"] = _deep_merge(default_limits(a), raw.get("limits", {}))
        a["_limit_overrides"] = sorted(raw.get("limits", {}).keys())
        out.append(a)
    return out


def commissioning_limits(a: dict, truth_h: dict, steady: np.ndarray) -> dict:
    """Process alarm limits as a commissioning engineer would set them: from the healthy operating envelope of
    the installed system (pressures, flow), rounded. Explicit config limits are kept."""
    lim = dict(a["limits"])
    keep = set(a.get("_limit_overrides", []))
    if steady.sum() < 600:
        return lim
    p1 = lambda k: float(np.nanpercentile(truth_h[k][steady], 1))
    if "discharge_lo_kpa" not in keep:
        lim["discharge_lo_kpa"] = float(np.floor(0.75 * p1("discharge_kpa_g") / 5.0) * 5.0)
    if "suction_lo_kpa" not in keep:
        lim["suction_lo_kpa"] = float(np.floor((p1("suction_kpa_g") - max(25.0, 0.25 * abs(p1("suction_kpa_g")))) / 5.0) * 5.0)
    if "flow_lo_m3h" not in keep:
        lim["flow_lo_m3h"] = float(np.floor(0.8 * p1("flow_m3h") / 5.0) * 5.0)
    if "flow_min_m3h" not in keep:
        lim["flow_min_m3h"] = float(np.floor(0.85 * p1("flow_m3h") / 5.0) * 5.0)
    if "fluid_hi_c" not in keep:
        lim["fluid_hi_c"] = float(np.ceil((np.nanpercentile(truth_h["fluid_temp_c"][steady], 99.5) + 6.0)))
    return lim
