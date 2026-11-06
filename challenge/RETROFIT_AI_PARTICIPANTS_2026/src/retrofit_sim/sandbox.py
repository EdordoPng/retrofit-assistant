"""Sealed what-if sandbox (simulation only).

Evaluates a proposed action for one asset at one point in time against the reduced-order pump model:
  none | speed_setpoint (VFD assets) | valve_position (valve-equipped loops) | clean_strainer | realign |
  replace_bearing | inspect
The asset model is rebuilt from the PUBLIC asset sheet (assets.csv) and profile defaults; the operating context
(duty, inlet temperature) comes from operating_context.csv at the requested time; the machine condition is a
user-supplied HYPOTHESIS (e.g. clog=2.0), never the simulator's hidden state. Nothing is written anywhere and no
device, network or file is touched: the function returns a dict.

This is not a controller and not engineering advice. Results carry model uncertainty (see caveats in the output).
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys

import numpy as np
import pandas as pd

from .context import Context
from .faults import LatentState
from .plant import simulate_truth

HYPOTHESIS_KEYS = {"clog": (0.0, 8.0), "restriction": (1.0, 4.0), "bearing_wear": (0.0, 0.95), "misalignment": (0.0, 1.0),
                   "unbalance": (0.0, 2.0), "impeller_wear": (0.0, 0.15), "air_entrainment": (0.0, 0.05)}
HEALTHY = {"clog": 0.05, "restriction": 1.0, "bearing_wear": 0.05, "misalignment": 0.02, "unbalance": 0.0,
           "impeller_wear": 0.0, "air_entrainment": 0.0}
# Intervention assumptions (illustrative; edit in your own analysis): stop duration [h], labor [h], parts [EUR]
INTERVENTIONS = {"none": (0.0, 0.0, 0.0), "speed_setpoint": (0.0, 0.0, 0.0), "valve_position": (0.0, 0.0, 0.0),
                 "inspect": (1.0, 2.0, 0.0), "clean_strainer": (1.5, 3.0, 50.0), "realign": (3.0, 6.0, 150.0),
                 "replace_bearing": (6.0, 12.0, 900.0)}
COST_ASSUMPTIONS = {"energy_eur_per_kwh": 0.12, "labour_eur_per_h": 75.0,
                    "stop_cost_eur_per_h": {"SHIP_SW_COOLING": 0.0, "SHIP_LT_FRESHWATER": 0.0, "INDUSTRIAL_CW": 400.0,
                                            "PROCESS_TRANSFER": 600.0}}
LIMITS = {"max_speed_step": 0.20, "max_motor_load": 1.00, "min_npsh_ratio": 1.30, "min_duty_satisfaction": 0.95,
          "max_bearing_temp_c": 85.0, "min_q_rel": 0.30, "max_q_rel": 1.30}


def _profiles(root):
    import yaml
    with open(os.path.join(root, "configs", "fleet_public.yaml"), encoding="utf-8") as fh:
        return yaml.safe_load(fh)["profiles"]


def asset_model(row: pd.Series, profiles: dict) -> dict:
    """Rebuild simulator parameters from the public asset sheet + profile defaults."""
    a = copy.deepcopy(profiles[row["profile"]])
    a.update({
        "asset_id": row["asset_id"], "profile": row["profile"], "control": row["control"],
        "q_bep_m3h": float(row["pump_rated_flow_m3_h"]), "h_bep_m": float(row["pump_rated_head_m"]),
        "h0_shutoff_ratio": float(row["pump_shutoff_head_m"]) / float(row["pump_rated_head_m"]),
        "eta_bep": float(row["pump_bep_efficiency"]), "npshr_bep_m": float(row["npsh3_at_bep_m"]),
        "q_design_m3h": float(row["design_flow_m3_h"]), "h_design_m": float(row["design_head_m"]),
        "system_static_m": float(row["static_head_m"]), "motor_kw": float(row["motor_rated_kw"]),
        "rated_rpm": float(row["motor_rated_rpm"]), "voltage_v": float(row["supply_voltage_v"]),
    })
    a.setdefault("motor_eff", 0.94)
    a.setdefault("motor_pf", 0.86)
    a.setdefault("design_supply_temp_c", 25.0)
    if pd.notna(row.get("min_speed_ratio")):
        a["r_min"] = float(row["min_speed_ratio"])
    return a


def _ctx(n, demand, t_in, ambient, suction_static):
    return Context(np.arange(n), np.ones(n, dtype=bool), np.full(n, "STEADY", dtype=object), np.full(n, demand),
                   np.full(n, t_in), np.full(n, ambient), np.full(n, suction_static), np.zeros(n), np.ones(n), [])


def _lat(n, h):
    return LatentState(*(np.full(n, float(h[k])) for k in ("bearing_wear", "clog", "restriction", "misalignment", "unbalance",
                                                           "impeller_wear", "air_entrainment")))


def _steady(a, ctx_args, hyp, horizon_s=3 * 3600):
    tr = simulate_truth(a, _ctx(horizon_s, *ctx_args), _lat(horizon_s, hyp), np.random.default_rng(0))
    keys = ["speed_ratio", "flow_m3h", "flow_required_m3h", "head_m", "suction_kpa_g", "discharge_kpa_g", "npsh_margin",
            "shaft_kw", "input_kw", "current_a", "motor_load", "bearing_temp_c", "vib_rms_mm_s", "vib_accel_rms_g",
            "valve_position_pct"]
    return {k: (None if np.isnan(tr[k][-1]) else float(np.round(tr[k][-1], 4))) for k in keys}


def what_if(data_dir: str, asset_id: str, time_utc: str, action: str = "none", value: float | None = None,
            hypothesis: dict | None = None, root: str | None = None) -> dict:
    root = root or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if action not in INTERVENTIONS:
        return {"accepted": False, "rejection_reasons": [f"unknown action '{action}'"], "allowed_actions": sorted(INTERVENTIONS)}
    assets = pd.read_csv(os.path.join(data_dir, "assets.csv"))
    if asset_id not in set(assets.asset_id):
        return {"accepted": False, "rejection_reasons": [f"unknown asset '{asset_id}'"]}
    row = assets[assets.asset_id == asset_id].iloc[0]
    a = asset_model(row, _profiles(root))
    hyp = dict(HEALTHY)
    reasons = []
    for k, v in (hypothesis or {}).items():
        if k not in HYPOTHESIS_KEYS:
            reasons.append(f"unknown hypothesis key '{k}' (allowed: {sorted(HYPOTHESIS_KEYS)})")
            continue
        lo, hi = HYPOTHESIS_KEYS[k]
        if not lo <= float(v) <= hi:
            reasons.append(f"hypothesis {k}={v} outside plausible range [{lo}, {hi}]")
        hyp[k] = float(np.clip(float(v), lo, hi))
    ctx = pd.read_csv(os.path.join(data_dir, "operating_context.csv"))
    ctx = ctx[ctx.asset_id == asset_id]
    t = pd.Timestamp(time_utc)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    ts = pd.to_datetime(ctx["timestamp_utc"], utc=True)
    if t < ts.min() or t > ts.max():
        return {"accepted": False, "rejection_reasons": [f"time {t.isoformat()} outside the asset's data window"]}
    c = ctx.iloc[int(np.argmin(np.abs((ts - t).dt.total_seconds().values)))]
    demand = float(c["duty_demand_pct"]) / 100.0
    if demand <= 0.01:
        return {"accepted": False, "rejection_reasons": ["pump is not scheduled to run at this time (duty demand 0)"]}
    susc = float(c["suction_static_head_m"]) if pd.notna(c.get("suction_static_head_m")) else float(
        a.get("context", {}).get("suction_static_m", a.get("context", {}).get("sea_chest_submergence_m", 3.0)))
    ctx_args = (demand, float(c["supply_water_temp_c"]), float(c["ambient_temp_c"]), susc)
    base = _steady(a, ctx_args, hyp)
    healthy_ref = _steady(a, ctx_args, HEALTHY)
    prop_a, prop_h = copy.deepcopy(a), dict(hyp)
    stop_h, labour_h, parts = INTERVENTIONS[action]
    if action == "speed_setpoint":
        if not a["control"].startswith("VFD"):
            reasons.append("speed set-point change requires a variable-speed drive; this asset is direct-on-line")
        elif value is None:
            reasons.append("speed_setpoint needs --value (speed ratio 0-1 or rpm)")
        else:
            r = float(value) / a["rated_rpm"] if float(value) > 2 else float(value)
            if not a.get("r_min", 0.5) <= r <= a.get("r_max", 1.0):
                reasons.append(f"speed ratio {r:.2f} outside drive limits [{a.get('r_min', 0.5):.2f}, {a.get('r_max', 1.0):.2f}]")
            if abs(r - (base["speed_ratio"] or 0)) > LIMITS["max_speed_step"]:
                reasons.append(f"speed step {r - (base['speed_ratio'] or 0):+.2f} exceeds the sandbox limit of +/-{LIMITS['max_speed_step']:.2f} per action")
            prop_a["speed_override"] = r
    elif action == "valve_position":
        if a["control"] not in ("FLOW_VALVE", "VFD_PRESSURE"):
            reasons.append("this asset has no controllable valve with position feedback")
        elif value is None or not 5 <= float(value) <= 100:
            reasons.append("valve_position needs --value in 5..100 %")
        else:
            prop_a["valve_override"] = float(value) / 100.0
    elif action == "clean_strainer":
        prop_h["clog"] = HEALTHY["clog"]
    elif action == "realign":
        prop_h["misalignment"] = HEALTHY["misalignment"]
    elif action == "replace_bearing":
        prop_h["bearing_wear"] = 0.03
        prop_h["misalignment"] = max(prop_h["misalignment"], 0.15)     # re-installation: some residual misalignment is common
    prop = _steady(prop_a, ctx_args, prop_h)
    # constraints on the proposed state
    req = prop["flow_required_m3h"] or healthy_ref["flow_m3h"]
    sat = prop["flow_m3h"] / max(req, 1e-6)
    warnings = []
    if sat < LIMITS["min_duty_satisfaction"]:
        msg = (f"cooling-duty satisfaction {sat:.2f} below the minimum {LIMITS['min_duty_satisfaction']:.2f} "
               f"(flow {prop['flow_m3h']:.0f} vs required {req:.0f} m3/h)")
        (warnings if action == "none" else reasons).append(msg)
    if prop["motor_load"] > LIMITS["max_motor_load"]:
        reasons.append(f"motor load {prop['motor_load']:.2f} exceeds {LIMITS['max_motor_load']:.2f} x rated")
    if prop["npsh_margin"] < LIMITS["min_npsh_ratio"]:
        reasons.append(f"NPSH margin ratio {prop['npsh_margin']:.2f} below {LIMITS['min_npsh_ratio']:.2f}")
    if prop["vib_rms_mm_s"] is not None and prop["vib_rms_mm_s"] >= float(row["vibration_trip_mm_s"]):
        reasons.append(f"predicted vibration {prop['vib_rms_mm_s']:.1f} mm/s at or above the trip limit {row['vibration_trip_mm_s']} mm/s")
    elif prop["vib_rms_mm_s"] is not None and prop["vib_rms_mm_s"] >= float(row["vibration_alarm_mm_s"]):
        warnings.append(f"predicted vibration {prop['vib_rms_mm_s']:.1f} mm/s above the alarm limit {row['vibration_alarm_mm_s']} mm/s")
    if prop["bearing_temp_c"] is not None and prop["bearing_temp_c"] > LIMITS["max_bearing_temp_c"]:
        reasons.append(f"predicted bearing temperature {prop['bearing_temp_c']:.0f} degC above {LIMITS['max_bearing_temp_c']:.0f} degC")
    q_rel = prop["flow_m3h"] / max((prop["speed_ratio"] or 1e-6) * a["q_bep_m3h"], 1e-6)
    if action in ("speed_setpoint", "valve_position") and not LIMITS["min_q_rel"] <= q_rel <= LIMITS["max_q_rel"]:
        reasons.append(f"operating point at {q_rel:.0%} of BEP flow is outside the allowable range "
                       f"{LIMITS['min_q_rel']:.0%}-{LIMITS['max_q_rel']:.0%}")
    alarm = float(row["vibration_alarm_mm_s"])

    def risk(s):
        v = min(1.0, (s["vib_rms_mm_s"] or 0) / alarm)
        npsh = min(1.0, max(0.0, (1.6 - (s["npsh_margin"] or 9)) / 0.6))
        load = min(1.0, max(0.0, ((s["motor_load"] or 0) - 0.9) / 0.2))
        return round(float(max(v, npsh, load)), 3)

    stop_cost = COST_ASSUMPTIONS["stop_cost_eur_per_h"].get(a["profile"], 0.0) * stop_h
    cost = stop_cost + COST_ASSUMPTIONS["labour_eur_per_h"] * labour_h + parts
    e_day = lambda s: (s["input_kw"] or 0) * 24 * COST_ASSUMPTIONS["energy_eur_per_kwh"]
    out = {
        "accepted": len(reasons) == 0, "rejection_reasons": reasons, "warnings": warnings, "asset_id": asset_id, "time_utc": t.isoformat(),
        "action": action, "value": value, "hypothesis": hyp,
        "context": {"duty_demand": demand, "inlet_temp_c": ctx_args[1], "ambient_c": ctx_args[2], "suction_static_m": susc},
        "baseline": {**base, "duty_satisfaction": round(base["flow_m3h"] / max(base["flow_required_m3h"] or healthy_ref["flow_m3h"], 1e-6), 3),
                     "risk_proxy": risk(base), "energy_eur_per_day": round(e_day(base), 2)},
        "proposed": {**prop, "duty_satisfaction": round(sat, 3), "risk_proxy": risk(prop), "energy_eur_per_day": round(e_day(prop), 2)},
        "intervention": {"stop_h": stop_h, "labour_h": labour_h, "parts_eur": parts, "estimated_cost_eur": round(cost, 0),
                         "cost_assumptions": COST_ASSUMPTIONS},
        "caveats": [
            "Reduced-order steady-state model (affinity laws, quadratic system curve); not a validated digital twin.",
            "Machine condition is the user's hypothesis, not a measured or hidden state.",
            "Built from public nameplate data and profile defaults; per-asset vibration and thermal baselines are not public, "
            "so vibration and temperature predictions are indicative only.",
            "Costs are illustrative assumptions; replace with site data.",
            "Sandbox output only: not a set-point, not a work order, not connected to any controller.",
        ],
    }
    return out


def _parse_hyp(items):
    h = {}
    for it in items or []:
        k, _, v = it.partition("=")
        h[k.strip()] = float(v)
    return h


def what_if_main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m retrofit_sim what_if", description="Simulation-only what-if sandbox.")
    p.add_argument("--data", default="data/full", help="Folder with assets.csv and operating_context.csv")
    p.add_argument("--asset", required=True)
    p.add_argument("--time", required=True, help="UTC time, e.g. 2025-08-13T10:00:00Z")
    p.add_argument("--action", default="none", choices=sorted(INTERVENTIONS))
    p.add_argument("--value", type=float, default=None)
    p.add_argument("--hypothesis", nargs="*", default=None, help="Assumed condition, e.g. clog=2.0 bearing_wear=0.5")
    a = p.parse_args(argv)
    r = what_if(a.data, a.asset, a.time, a.action, a.value, _parse_hyp(a.hypothesis))
    print(json.dumps(r, indent=2))
    return 0 if r.get("accepted") else 3


if __name__ == "__main__":
    sys.exit(what_if_main())
