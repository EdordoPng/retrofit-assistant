"""Latent fault processes.

A fault changes *physical* state variables (wear, clogging, resistance, misalignment, unbalance,
impeller condition) or *instrument* state (drift, stuck, calibration step, dropout). Signals are generated
afterwards from these states, so every symptom has a physical or instrument cause.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

MACHINE_FAULTS = ("BEARING_WEAR", "SUCTION_STRAINER_CLOGGING", "CAVITATION", "DISCHARGE_RESTRICTION",
                  "MISALIGNMENT", "IMBALANCE", "IMPELLER_WEAR", "AIR_ENTRAINMENT")
SENSOR_FAULTS = ("SENSOR_DRIFT", "SENSOR_STUCK", "SENSOR_CALIBRATION_SHIFT", "SENSOR_NOISE_SPIKES", "COMMUNICATION_LOSS")
BENIGN = ("STARTUP", "SHUTDOWN", "LOAD_CHANGE", "STANDBY_CHANGEOVER", "HEAVY_WEATHER", "VOLTAGE_SAG",
          "PLANNED_STOP", "SETPOINT_CHANGE", "PLANNED_MAINTENANCE")


@dataclass
class FaultSpec:
    fault_type: str
    onset_s: int                      # physical onset (seconds from window start); may be < 0 (pre-existing)
    end_s: int | None                 # repair / resolution time; None = persists to end of window
    params: dict = field(default_factory=dict)
    event_id: str = ""
    root_cause: str | None = None     # event_id of the causing fault (compound incidents)
    sensor_tag: str | None = None     # for sensor faults


@dataclass
class LatentState:
    bearing_wear: np.ndarray          # 0 (new) .. 1 (failed); ~0.25 = ISO stage 2, ~0.6 stage 3
    clog: np.ndarray                  # suction strainer blockage factor, >= 0 (0 = clean)
    restriction: np.ndarray           # multiplier on discharge-side resistance, >= 1
    misalignment: np.ndarray          # 0..1 severity
    unbalance: np.ndarray             # extra unbalance severity, >= 0
    impeller_wear: np.ndarray         # fractional head loss, 0..0.15
    air_entrainment: np.ndarray       # gas volume fraction proxy at suction, 0..0.1


def _ramp(t, onset, end, shape="exp", rate=1.0, start=0.0, top=1.0):
    """Monotone growth from `start` at onset to `top`; resets to baseline after `end` (repair)."""
    x = np.zeros_like(t, dtype=float)
    active = t >= onset
    if end is not None:
        active &= t < end
    tau = np.maximum(t - onset, 0) / 3600.0  # hours since onset
    if shape == "exp":
        y = start + (top - start) * (1 - np.exp(-rate * tau))
    elif shape == "accel":                     # slow, then accelerating (bearing-type): y = start * exp(rate tau)
        y = np.minimum(top, start * np.exp(rate * tau))
    elif shape == "linear":
        y = np.minimum(top, start + rate * tau)
    else:
        raise ValueError(shape)
    x[active] = y[active]
    return x


def build_latent(n: int, faults: list, baseline: dict) -> LatentState:
    t = np.arange(n, dtype=float)
    bw = np.full(n, baseline.get("bearing_wear", 0.05))
    clog = np.full(n, baseline.get("clog", 0.05))
    restr = np.ones(n)
    mis = np.full(n, baseline.get("misalignment", 0.02))
    unb = np.full(n, baseline.get("unbalance", 0.0))
    iw = np.full(n, baseline.get("impeller_wear", 0.0))
    air = np.zeros(n)
    for f in faults:
        p = f.params
        if f.fault_type == "BEARING_WEAR":
            # accelerating damage growth from the healthy baseline: w = w_b + s (exp(k tau) - 1), capped at w_max.
            # s is set so that w reaches 0.95 (functional failure) t_fail_h hours after onset.
            b0 = baseline.get("bearing_wear", 0.05)
            k = p["rate_per_h"]
            s = (0.95 - b0) / np.expm1(k * p["t_fail_h"])
            tau = np.maximum(t - f.onset_s, 0) / 3600.0
            g = np.minimum(p.get("w_max", 0.95), b0 + s * np.expm1(k * tau))
            on = (t >= f.onset_s) & ((t < f.end_s) if f.end_s is not None else True)
            bw = np.where(on, np.maximum(bw, g), bw)
            if f.end_s is not None:
                bw[int(f.end_s):] = baseline.get("bearing_wear_after_repair", 0.03)
        elif f.fault_type == "SUCTION_STRAINER_CLOGGING":
            g = _ramp(t, f.onset_s, f.end_s, p.get("shape", "linear"), p["rate_per_h"], clog[min(max(int(f.onset_s), 0), n - 1)], p["c_max"])
            clog = np.where(g > 0, np.maximum(clog, g), clog)
            if f.end_s is not None:
                clog[int(f.end_s):] = baseline.get("clog", 0.05)
        elif f.fault_type == "DISCHARGE_RESTRICTION":
            g = _ramp(t, f.onset_s, f.end_s, p.get("shape", "exp"), p["rate_per_h"], 0.0, p["extra_max"])
            restr = restr * (1.0 + g)
        elif f.fault_type == "MISALIGNMENT":
            # step after re-installation, optionally growing as the coupling wears
            g = np.where((t >= f.onset_s) & ((t < f.end_s) if f.end_s is not None else True),
                         p["level"] + p.get("growth_per_h", 0.0) * np.maximum(t - f.onset_s, 0) / 3600.0, 0.0)
            mis = np.maximum(mis, np.minimum(g, 1.0))
        elif f.fault_type == "IMBALANCE":
            g = _ramp(t, f.onset_s, f.end_s, p.get("shape", "linear"), p["rate_per_h"], p.get("u0", 0.0), p["u_max"])
            unb = np.maximum(unb, g)
        elif f.fault_type == "IMPELLER_WEAR":
            g = _ramp(t, f.onset_s, f.end_s, "linear", p["rate_per_h"], p.get("iw0", 0.0), p["iw_max"])
            iw = np.maximum(iw, g)
        elif f.fault_type == "AIR_ENTRAINMENT":
            g = _ramp(t, f.onset_s, f.end_s, "exp", 2.0, 0.0, p["alpha_max"])
            air = np.maximum(air, g)
    return LatentState(bw, clog, restr, mis, unb, iw, air)
