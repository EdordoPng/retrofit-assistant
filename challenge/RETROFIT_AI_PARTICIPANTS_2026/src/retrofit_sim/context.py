"""Operating context generators: duty schedules, demand, seawater / supply temperatures, ambient, sea state.

Each generator returns per-second numpy arrays for one asset window. Schedules are produced as
piecewise segments first (minute resolution), then expanded to 1 Hz so that start-ups, load changes and
shutdowns are explicit, timestamped transitions that can be checked.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Monthly mean sea-surface temperature, Archipelago Sea / northern Baltic Proper [deg C].
# Blend of Utö station climatology (Laakso et al. 2018, Ocean Science) and HELCOM SST reports; see docs/PROVENANCE.md.
SST_FALLBACK = [1.5, 0.5, 0.5, 2.5, 7.0, 13.0, 17.5, 18.0, 14.0, 10.0, 6.0, 3.0]


@dataclass
class Segment:
    start: int          # seconds from window start
    end: int
    mode: str           # OFF | STARTUP | STEADY | LOAD_CHANGE | SHUTDOWN | MAINTENANCE | STANDBY
    demand: float       # 0..1 heat-load / duty demand at the end of the segment
    note: str = ""


@dataclass
class Context:
    t: np.ndarray                    # seconds
    running: np.ndarray              # bool: motor energised
    mode: np.ndarray                 # str codes
    demand: np.ndarray               # 0..1
    supply_temp_c: np.ndarray        # coolant / seawater temperature at pump inlet
    ambient_c: np.ndarray            # machinery-space ambient
    suction_static_m: np.ndarray     # static head on suction side (submergence / tank level / loop pressure)
    sea_state: np.ndarray            # significant wave height proxy [m] (ships only, else 0)
    supply_voltage_pu: np.ndarray    # supply voltage in per-unit (sags are benign disturbances)
    segments: list = field(default_factory=list)
    benign_events: list = field(default_factory=list)


def _smooth_noise(rng, n, sigma, tau_s, dt=1.0):
    """Ornstein-Uhlenbeck noise via exact AR(1), sampled at 60 s then interpolated to 1 Hz."""
    step = 60
    m = n // step + 2
    a = np.exp(-step / tau_s)
    e = rng.normal(0, sigma * np.sqrt(1 - a * a), m)
    x = np.empty(m)
    x[0] = rng.normal(0, sigma)
    for i in range(1, m):
        x[i] = a * x[i - 1] + e[i]
    return np.interp(np.arange(n), np.arange(m) * step, x)


def _expand(segments, n, startup_s, shutdown_s):
    mode = np.empty(n, dtype=object)
    demand = np.zeros(n)
    running = np.zeros(n, dtype=bool)
    prev_d = 0.0
    for s in segments:
        a, b = max(0, s.start), min(n, s.end)
        if b <= a:
            continue
        mode[a:b] = s.mode
        if s.mode in ("OFF", "STANDBY", "MAINTENANCE"):
            demand[a:b] = 0.0
            running[a:b] = False
            prev_d = 0.0
            continue
        running[a:b] = True
        if s.mode in ("LOAD_CHANGE", "STARTUP"):
            ramp = np.linspace(prev_d, s.demand, b - a)
            demand[a:b] = ramp
        elif s.mode == "SHUTDOWN":
            # stop command: the motor contactor / drive output opens at the start of STOPPING and the pump coasts down
            demand[a:b] = 0.0
            running[a:b] = False
        else:
            demand[a:b] = s.demand
        prev_d = s.demand
    return mode, demand, running


def ship_ropax(rng, n, start_month, cfg: dict, stops=()) -> Context:
    """Night/day RoPax-style liner schedule: sea passage, manoeuvring, port stays; duty/standby changeover."""
    segs = []
    t = 0
    leg_sea = int(cfg.get("sea_leg_h", 10.0) * 3600)
    leg_man = int(cfg.get("manoeuvre_h", 0.6) * 3600)
    port = int(cfg.get("port_h", 1.3) * 3600)
    d_sea, d_man, d_port = cfg.get("demand_sea", 0.88), cfg.get("demand_manoeuvre", 0.6), cfg.get("demand_port", 0.35)
    phase = int(rng.integers(0, leg_sea + port))
    t = -phase
    state = []
    while t < n:
        for (dur, d, md, note) in ((leg_man, d_man, "LOAD_CHANGE", "departure manoeuvring"),
                                   (int(leg_sea * rng.uniform(0.93, 1.07)), d_sea * rng.uniform(0.95, 1.04), "STEADY", "sea passage"),
                                   (leg_man, d_man, "LOAD_CHANGE", "arrival manoeuvring"),
                                   (int(port * rng.uniform(0.8, 1.3)), d_port, "STEADY", "port")):
            state.append((t, t + dur, md, d, note))
            t += dur
    # standby period (duty/standby changeover) — pump stopped for hours, restarted later
    standby = None
    if rng.random() < cfg.get("standby_prob", 0.6):
        s0 = int(rng.uniform(0.15, 0.7) * n)
        standby = (s0, s0 + int(rng.uniform(6, 30) * 3600))
    for (a, b, md, d, note) in state:
        segs.append(Segment(a, b, md, d, note))
    segs = _insert_stop(segs, standby, "STANDBY", n, cfg) if standby else segs
    for (a, b, md) in stops:
        segs = _insert_stop(segs, (a, b), md, n, cfg)
    segs = _with_transients(segs, n, cfg)
    mode, demand, running = _expand(segs, n, cfg.get("startup_s", 8), cfg.get("shutdown_s", 15))
    month = start_month
    sst = np.array(cfg.get("sst_monthly", SST_FALLBACK))
    day = np.arange(n) / 86400.0
    base_sst = np.interp(month - 1 + day / 30.4, np.arange(13), np.r_[sst, sst[0]])
    # spatial variation along the route (archipelago vs open sea), slow
    sst_route = base_sst + _smooth_noise(rng, n, cfg.get("sst_route_sd", 0.8), 6 * 3600)
    sea = np.clip(_smooth_noise(rng, n, 0.7, 10 * 3600) + cfg.get("hs_mean", 1.0), 0.1, None)
    storm_draw = rng.random()
    s0_draw = rng.uniform(0.1, 0.8)
    if cfg.get("storm_at_h") is not None or storm_draw < cfg.get("storm_prob", 0.5):            # one storm passage
        s0 = int(cfg["storm_at_h"] * 3600) if cfg.get("storm_at_h") is not None else int(s0_draw * n)
        L = int(rng.uniform(8, 20) * 3600)
        bump = np.zeros(n)
        idx = np.arange(s0, min(n, s0 + L))
        bump[idx] = np.sin(np.pi * (idx - s0) / L) * rng.uniform(1.5, 3.0)
        sea = sea + bump
    at_sea = np.isin(mode, ["STEADY"]) & (demand > 0.7)
    sea = np.where(at_sea, sea, 0.15)
    amb = cfg.get("engine_room_c", 34.0) + 4.0 * (demand - 0.6) + _smooth_noise(rng, n, 0.8, 3600)
    draft = cfg.get("sea_chest_submergence_m", 4.5) + _smooth_noise(rng, n, 0.15, 12 * 3600)
    volt = 1.0 + _smooth_noise(rng, n, 0.006, 1800)
    return Context(np.arange(n), running, mode, demand, sst_route, amb, draft, sea, volt, segs)


def industrial_shift(rng, n, start_month, start_weekday, cfg: dict, stops=()) -> Context:
    """Two-shift factory cooling circulation with weekend reduction and an occasional production stop."""
    segs = []
    day_s = 86400
    t = 0
    hours = cfg.get("shift_hours", [6, 22])
    while t < n:
        dow = (start_weekday + t // day_s) % 7
        d0 = t
        workday = dow < 5
        hi = cfg.get("demand_shift", 0.9) * rng.uniform(0.92, 1.05)
        lo = cfg.get("demand_night", 0.5) if workday else cfg.get("demand_weekend", 0.4)
        a = d0 + hours[0] * 3600
        b = d0 + hours[1] * 3600
        if workday:
            segs += [Segment(d0, a, "STEADY", lo, "night"), Segment(a, a + 900, "LOAD_CHANGE", hi, "shift start"),
                     Segment(a + 900, b, "STEADY", hi, "production"), Segment(b, b + 900, "LOAD_CHANGE", lo, "shift end"),
                     Segment(b + 900, d0 + day_s, "STEADY", lo, "night")]
        else:
            segs.append(Segment(d0, d0 + day_s, "STEADY", lo, "weekend"))
        t += day_s
    stop = None
    if rng.random() < cfg.get("stop_prob", 0.5):
        s0 = int(rng.uniform(0.2, 0.8) * n)
        stop = (s0, s0 + int(rng.uniform(2, 14) * 3600))
    segs = _insert_stop(segs, stop, "OFF", n, cfg) if stop else segs
    for (a, b, md) in stops:
        segs = _insert_stop(segs, (a, b), md, n, cfg)
    segs = _with_transients(segs, n, cfg)
    mode, demand, running = _expand(segs, n, cfg.get("startup_s", 6), cfg.get("shutdown_s", 10))
    day = np.arange(n) / 86400.0
    wet_bulb_m = np.array(cfg.get("supply_monthly", [8, 8, 10, 13, 17, 21, 24, 23, 19, 15, 11, 9]))
    base = np.interp(start_month - 1 + day / 30.4, np.arange(13), np.r_[wet_bulb_m, wet_bulb_m[0]])
    diurnal = cfg.get("diurnal_amp", 2.0) * np.sin(2 * np.pi * (day - 0.375))
    supply = base + diurnal + _smooth_noise(rng, n, 0.6, 4 * 3600) + 2.5 * demand
    amb = cfg.get("hall_c", 22.0) + 0.6 * diurnal + 3.0 * demand + _smooth_noise(rng, n, 0.7, 3600)
    static = np.full(n, cfg.get("suction_static_m", 3.0)) + _smooth_noise(rng, n, 0.2, 8 * 3600)
    volt = 1.0 + _smooth_noise(rng, n, 0.005, 1800)
    return Context(np.arange(n), running, mode, demand, supply, amb, static, np.zeros(n), volt, segs)


def process_batch(rng, n, start_month, cfg: dict, stops=()) -> Context:
    """Smaller process pump: batch cycles with frequent starts/stops and flow set-point changes."""
    segs = []
    t = 0
    while t < n:
        run = int(rng.uniform(*cfg.get("run_h", [1.0, 4.0])) * 3600)
        idle = int(rng.uniform(*cfg.get("idle_h", [0.2, 1.5])) * 3600)
        d = rng.choice(cfg.get("setpoints", [0.6, 0.8, 1.0]))
        segs.append(Segment(t, t + run, "STEADY", float(d), "batch"))
        if rng.random() < 0.35:
            mid = t + run // 2
            d2 = float(rng.choice(cfg.get("setpoints", [0.6, 0.8, 1.0])))
            segs[-1] = Segment(t, mid, "STEADY", float(d), "batch")
            segs.append(Segment(mid, mid + 120, "LOAD_CHANGE", d2, "set-point change"))
            segs.append(Segment(mid + 120, t + run, "STEADY", d2, "batch"))
        segs.append(Segment(t + run, t + run + idle, "OFF", 0.0, "between batches"))
        t += run + idle
    for (a, b, md) in stops:
        segs = _insert_stop(segs, (a, b), md, n, cfg)
    segs = _with_transients(segs, n, cfg)
    mode, demand, running = _expand(segs, n, cfg.get("startup_s", 4), cfg.get("shutdown_s", 6))
    supply = cfg.get("process_temp_c", 55.0) + 5.0 * (demand - 0.7) + _smooth_noise(rng, n, 1.2, 2 * 3600)
    amb = cfg.get("hall_c", 24.0) + _smooth_noise(rng, n, 1.0, 3600)
    static = np.full(n, cfg.get("suction_static_m", 2.0)) + _smooth_noise(rng, n, 0.3, 2 * 3600)  # tank level
    volt = 1.0 + _smooth_noise(rng, n, 0.006, 1800)
    return Context(np.arange(n), running, mode, demand, supply, amb, static, np.zeros(n), volt, segs)


def _insert_stop(segs, window, mode, n, cfg):
    a, b = window
    out = []
    for s in segs:
        if s.end <= a or s.start >= b:
            out.append(s)
            continue
        if s.start < a:
            out.append(Segment(s.start, a, s.mode, s.demand, s.note))
        if s.end > b:
            out.append(Segment(b, s.end, s.mode, s.demand, s.note))
    note = {"STANDBY": "duty/standby changeover", "MAINTENANCE": "maintenance (locked out)"}.get(mode, "planned stop")
    out.append(Segment(a, b, mode, 0.0, note))
    return sorted(out, key=lambda s: s.start)


def _with_transients(segs, n, cfg):
    """Insert explicit STARTUP / SHUTDOWN segments around every stopped interval."""
    su, sd = int(cfg.get("startup_s", 8)), int(cfg.get("shutdown_s", 15))
    out = []
    prev_run = False
    for i, s in enumerate(sorted(segs, key=lambda s: s.start)):
        run = s.mode not in ("OFF", "STANDBY", "MAINTENANCE")
        if run and not prev_run and s.start > 0 and s.end - s.start > su + 1:
            out.append(Segment(s.start, s.start + su, "STARTUP", s.demand, "start-up"))
            s = Segment(s.start + su, s.end, s.mode, s.demand, s.note)
        if not run and prev_run and out and out[-1].end - out[-1].start > sd + 1:
            last = out[-1]
            out[-1] = Segment(last.start, last.end - sd, last.mode, last.demand, last.note)
            out.append(Segment(last.end - sd, last.end, "SHUTDOWN", 0.0, "shutdown"))
        out.append(s)
        prev_run = run
    return out
