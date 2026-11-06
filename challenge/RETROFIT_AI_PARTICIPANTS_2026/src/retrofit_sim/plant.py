"""Quasi-steady plant simulation at 1 Hz: control -> speed -> hydraulics -> power -> thermal -> vibration.

`simulate_truth` returns the TRUE physical state (private). Observations are produced by sensors.py.
"""
from __future__ import annotations

import numpy as np

from . import physics as ph
from .context import Context
from .faults import LatentState

CP_WATER = 4180.0


def _rate_limit_lag(x, tau_s, running=None):
    """First-order lag of a controller command, initialised at the first command value."""
    from scipy.signal import lfilter
    a = np.exp(-1.0 / tau_s)
    y, _ = lfilter([1 - a], [1, -a], x, zi=np.array([a * x[0]]))     # starts settled at the initial command
    return y


def simulate_truth(asset: dict, ctx: Context, lat: LatentState, rng: np.random.Generator) -> dict:
    n = len(ctx.t)
    A = asset
    Qb = A["q_bep_m3h"] / 3600.0
    Hb = A["h_bep_m"]
    h0 = A["h0_shutoff_ratio"]
    eta_b = A["eta_bep"]
    run = ctx.running.astype(float)

    # ---- fluid properties --------------------------------------------------------------------------------
    rho = ph.water_density(ctx.supply_temp_c, A.get("salinity_psu", 0.0))

    # ---- system resistance ---------------------------------------------------------------------------------
    H_static = np.full(n, A["system_static_m"])
    K_design = (A["h_design_m"] - A["system_static_m"]) / (A["q_design_m3h"] / 3600.0) ** 2
    valve_open_design = A.get("valve_design_position", 0.8)
    # valve K at design position equals valve_share * K_design
    rel_design = 50.0 ** (valve_open_design - 1.0)
    K_valve_full = K_design * A.get("valve_share_of_K", 0.25) * rel_design ** 2
    K_suction0 = A.get("suction_loss_m_at_design", 0.8) / (A["q_design_m3h"] / 3600.0) ** 2
    K_suction = K_suction0 * (1.0 + A.get("strainer_share", 0.6) * ((1.0 + lat.clog) ** 2 - 1.0))
    # discharge-side pipe/heat-exchanger resistance: design total minus valve and suction shares
    K_pipe = np.maximum(K_design * (1.0 - A.get("valve_share_of_K", 0.25)) - K_suction0, 0.1 * K_design) * lat.restriction

    # ---- control: speed and valve -----------------------------------------------------------------------------
    ctrl = A["control"]
    head_factor_wear = 1.0 - lat.impeller_wear
    dem = ctx.demand
    valve_pos = np.full(n, valve_open_design)
    q_req = np.full(n, np.nan)
    if ctrl == "VFD_TEMPERATURE":
        # heat removed ~ Q * dT; colder supply water -> less flow required. Q_req relative to design flow.
        t_set = A.get("controlled_temp_setpoint_c", 36.0)
        t_ref = A.get("design_supply_temp_c", 32.0)
        need = dem * (t_set - t_ref) / np.maximum(t_set - ctx.supply_temp_c, 3.0)
        q_req = np.clip(need, A.get("min_flow_frac", 0.4), 1.15) * A["q_design_m3h"] / 3600.0
        K_tot_nom = K_pipe + ph.valve_K(valve_pos, K_valve_full) + K_suction
        r_need = ph.speed_for_flow(q_req, Hb, Qb, h0, H_static, K_tot_nom, head_factor_wear)
        r_cmd = np.clip(r_need, A.get("r_min", 0.55), A.get("r_max", 1.0))
        r_target = _rate_limit_lag(r_cmd, A.get("speed_tau_s", 20.0), ctx.running)
    elif ctrl == "VFD_PRESSURE":
        # constant differential-pressure control with demand-dependent consumer valves (factory loops)
        consumer_open = np.clip(0.35 + 0.65 * dem, 0.2, 1.0)
        valve_pos = consumer_open if A.get("valve_override") is None else np.full(n, float(A["valve_override"]))
        dp_head = A.get("dp_setpoint_m", A["h_design_m"] * 0.9)
        K_tot_nom = K_pipe + ph.valve_K(valve_pos, K_valve_full) + K_suction
        # find r such that pump head at the operating point equals the set-point:  A r^2 - B Q^2 = dp,  Q^2 = (dp - Hst)/K
        Q2 = np.maximum(dp_head - H_static, 0.1) / K_tot_nom
        r_need = np.sqrt((dp_head + Hb * head_factor_wear * (h0 - 1) / Qb ** 2 * Q2) / (Hb * h0 * head_factor_wear))
        r_cmd = np.clip(r_need, A.get("r_min", 0.5), A.get("r_max", 1.0))
        r_target = _rate_limit_lag(r_cmd, A.get("speed_tau_s", 15.0), ctx.running)
    elif ctrl == "FLOW_VALVE":
        # fixed speed + PI-controlled throttling valve holding a flow set-point (process pumps)
        q_sp = np.clip(dem, 0.2, 1.1) * A["q_design_m3h"] / 3600.0
        q_req = q_sp
        r_target = np.ones(n)
        K_needed = (Hb * h0 * head_factor_wear - H_static) / np.maximum(q_sp, 1e-4) ** 2 - Hb * (h0 - 1) * head_factor_wear / Qb ** 2 - K_pipe - K_suction
        rel = np.sqrt(K_valve_full / np.maximum(K_needed, 1e-6))
        pos = 1.0 + np.log(np.clip(rel, 1e-3, 1.0)) / np.log(50.0)
        valve_pos = _rate_limit_lag(np.clip(pos, 0.05, 1.0), A.get("valve_tau_s", 8.0), ctx.running)
    else:  # FIXED_SPEED (DOL)
        r_target = np.ones(n)
    # sandbox overrides (what-if tool only): fixed speed ratio and / or fixed valve position
    if A.get("speed_override") is not None:
        r_target = np.full(n, float(A["speed_override"]))
    if A.get("valve_override") is not None:
        valve_pos = np.full(n, float(A["valve_override"]))

    # start-up ramps / coast-down
    r = np.zeros(n)
    su = A.get("startup_ramp_s", 5.0)
    state_r = 0.0
    # vectorised piecewise: ramp up with time constant su/3 when running, coast down with tau_cd when stopped
    tau_up = max(su / 3.0, 0.5)
    tau_cd = A.get("coastdown_tau_s", 6.0)
    a_up, a_cd = np.exp(-1.0 / tau_up), np.exp(-1.0 / tau_cd)
    tgt = r_target * run
    state_r = float(tgt[0])          # window starts in the scheduled state (no artificial start-up at t = 0)
    for i in range(n):            # 600k steps of trivial arithmetic; ~0.3 s
        a = a_up if tgt[i] > state_r else a_cd
        state_r = a * state_r + (1 - a) * tgt[i]
        r[i] = state_r
    r[r < 1e-3] = 0.0

    K_valve = ph.valve_K(valve_pos, K_valve_full)
    K_total = K_pipe + K_valve + K_suction          # suction-side losses (incl. strainer) are part of the system curve

    # ---- hydraulics with cavitation fixed point -------------------------------------------------------------------
    roll = np.zeros(n)
    if np.any(ctx.sea_state > 0.2):
        T_roll = A.get("roll_period_s", 11.0)
        roll = 0.25 * ctx.sea_state * np.sin(2 * np.pi * ctx.t / T_roll + rng.uniform(0, 6.28))   # suction head oscillation [m]
    p_loop = A.get("loop_pressurisation_kpa", 0.0) * 1000.0
    pv = ph.vapour_pressure_pa(ctx.supply_temp_c)
    hf_air = 1.0 - 2.5 * lat.air_entrainment
    hf = head_factor_wear * hf_air
    # suction line sized for ~2.5 m/s at BEP flow (common design guidance 1.5-3 m/s)
    A_suction = Qb / A.get("suction_velocity_bep_m_s", 2.5)

    def _npsh(Qx):
        # total (stagnation) head at the pump inlet: atmosphere / loop pressure + submergence - suction losses
        p_tot = ph.P_ATM + p_loop + rho * ph.G * (ctx.suction_static_m + roll - K_suction * Qx ** 2)
        npsha_x = (p_tot - pv) / (rho * ph.G)                 # NPSHa = total inlet head above vapour pressure
        p_static = p_tot - 0.5 * rho * (Qx / A_suction) ** 2   # what a wall-tapping gauge reads
        return p_static, npsha_x, ph.npsh_required(Qx, r, Qb, A["npshr_bep_m"])

    # Operating point with cavitation head loss: Q* = g(Q*), g(Q) = system/pump intersection with head factor cav(Q).
    # g is non-increasing in Q, so g(Q) - Q is strictly decreasing and bisection on [0, Q_no_cavitation] is robust.
    Q_hi = ph.solve_operating_point(r, Hb, Qb, h0, H_static, K_total, hf)
    lo, hi = np.zeros(n), Q_hi.copy()
    for _ in range(26):
        mid = 0.5 * (lo + hi)
        _, a_m, r_m = _npsh(mid)
        g = ph.solve_operating_point(r, Hb, Qb, h0, H_static, K_total, hf * ph.cavitation_head_factor(a_m, r_m)[0])
        up = g > mid
        lo = np.where(up, mid, lo)
        hi = np.where(up, hi, mid)
    Q = 0.5 * (lo + hi)
    p_suction_abs, npsha, npshr = _npsh(Q)
    cav, sigma = ph.cavitation_head_factor(npsha, npshr)
    H = ph.pump_head(Q, r, Hb, Qb, h0, hf * cav)
    p_suction_abs = np.maximum(p_suction_abs, pv + 50.0)            # liquid cannot sustain pressure below vapour pressure
    p_discharge_abs = p_suction_abs + rho * ph.G * H
    q_rel = np.where(r > 0, Q / (np.maximum(r, 1e-6) * Qb), 0.0)

    # ---- power -----------------------------------------------------------------------------------------------------
    P_shaft = ph.shaft_power(Q, H, r, Qb, Hb, eta_b, h0, rho, hf * cav)
    P_shaft *= 1.0 + 0.04 * lat.bearing_wear ** 2 + 0.02 * lat.misalignment     # friction losses
    P_rated = A["motor_kw"] * 1000.0
    vfd = A.get("vfd_efficiency") if ctrl.startswith("VFD") else None
    V = A["voltage_v"] * ctx.supply_voltage_pu
    P_in, eta_m, pf, I, lam = ph.motor_electrical(P_shaft, P_rated, A["motor_eff"], A["motor_pf"], V,
                                                   A.get("const_loss_share", 0.35), vfd)
    # DOL inrush: ~6-7x rated current for a few seconds during start (VFD soft start limits to ~1.1x)
    starting = (r < 0.9 * np.maximum(r_target, 1e-3)) & (run > 0) & (np.r_[0, np.diff(r)] > 0)
    I_rated = P_rated / (A["motor_eff"] * np.sqrt(3) * A["voltage_v"] * A["motor_pf"])
    inrush = A.get("inrush_multiple", 6.5) if not ctrl.startswith("VFD") else 1.1
    I = np.where(starting, np.maximum(I, inrush * I_rated * (1 - r) + I), I)
    energised = run > 0                      # contactor / drive output closed
    I = np.where(energised, I, 0.0)
    P_in = np.where(energised, P_in, 0.0)
    slip = A.get("rated_slip", 0.015) * np.clip(lam, 0, 1.5)
    n_sync = A["rated_rpm"] / (1 - A.get("rated_slip", 0.015))
    rpm = r * n_sync * (1 - slip) * (r > 0)

    # ---- thermal ------------------------------------------------------------------------------------------------------
    # fluid heating in the pump (losses into the liquid); matters at low flow / shut-off
    P_hyd = rho * ph.G * Q * H
    dT_fluid = np.where(Q > 1e-4, (P_shaft - P_hyd) * 0.9 / (rho * CP_WATER * np.maximum(Q, 1e-4)), 0.0)
    dT_fluid = np.minimum(dT_fluid, 25.0)
    fluid_temp = ctx.supply_temp_c + ph.first_order(dT_fluid, 1.0, 60.0)
    bw = lat.bearing_wear
    brg_rise = A.get("bearing_rise_k", 28.0) * (r ** 1.3) * (0.75 + 0.25 * np.clip(lam, 0, 1.2))
    brg_rise += 40.0 * np.clip(bw - 0.4, 0, None) ** 1.6 * (0.4 + 0.6 * r) + 6.0 * lat.misalignment * r
    brg_ss = np.where(run > 0, ctx.ambient_c * 0.6 + fluid_temp * 0.4 + brg_rise, ctx.ambient_c * 0.6 + fluid_temp * 0.4)
    bearing_temp = ph.first_order(brg_ss, 1.0, A.get("bearing_tau_s", 1500.0))
    w_rise = A.get("winding_rise_k", 75.0) * (0.25 + 0.75 * np.clip(lam, 0, 1.4) ** 2) / np.maximum(ctx.supply_voltage_pu, 0.8) ** 2
    winding_temp = ph.first_order(ctx.ambient_c + np.where(run > 0, w_rise, 0.0), 1.0, A.get("winding_tau_s", 2400.0))

    # ---- vibration (overall velocity RMS 10-1000 Hz, acceleration RMS, crest factor) --------------------------------------
    v_struct = A.get("vib_base_mm_s", 1.2) * (0.4 + 0.6 * r ** 1.5)
    v_imb = (A.get("unbalance_base_mm_s", 0.6) + 4.0 * lat.unbalance) * r ** 2
    v_mis = 4.5 * lat.misalignment * (0.5 + 0.5 * np.clip(lam, 0, 1.2)) * r
    v_hyd = A.get("hydraulic_vib_mm_s", 1.0) * r ** 2 * np.abs(q_rel - 1.0) ** 1.5 * (1.0 + 2.0 * (q_rel < 0.5))
    cav_int = np.clip((1.25 - sigma) / 0.45, 0, 1) * (r > 0.2)
    v_cav = A.get("cavitation_vib_mm_s", 3.0) * cav_int * r ** 2 + 3.0 * lat.air_entrainment * r
    v_brg = 14.0 * np.clip(bw - 0.4, 0, None) ** 1.5 * (0.3 + 0.7 * r)
    v2 = v_struct ** 2 + v_imb ** 2 + v_mis ** 2 + v_hyd ** 2 + v_cav ** 2 + v_brg ** 2
    # start-up: passing through structural resonance gives a short benign spike
    v2 = v2 + np.where(starting, (A.get("startup_vib_spike_mm_s", 4.0) * np.sin(np.pi * np.clip(r, 0, 1))) ** 2, 0.0)
    # process variability of broadband vibration (flow turbulence, structure), ~4 % (1 sigma), correlated over minutes
    from .context import _smooth_noise
    vib_v = np.sqrt(v2) * (r > 0.02) * np.exp(_smooth_noise(rng, n, 0.04, 180.0))
    a_base = A.get("accel_base_g", 0.15) * (0.3 + 0.7 * r ** 2)
    a_brg = 2.2 * np.clip(bw - 0.12, 0, None) ** 1.3 * r
    a_cav = 1.5 * cav_int * r ** 2 + 0.8 * lat.air_entrainment
    vib_a = np.sqrt(a_base ** 2 + a_brg ** 2 + a_cav ** 2 + (0.02 * vib_v) ** 2) * (r > 0.02) * np.exp(_smooth_noise(rng, n, 0.05, 120.0))
    # crest factor: rises with early localised damage (impacts, up to ~6) and falls back as damage spreads
    xb = np.clip(bw - 0.12, 0, None)
    crest = 3.2 + 50.0 * xb * np.exp(-6.0 * xb) + 1.0 * cav_int
    crest = np.where(r > 0.02, crest, np.nan)

    return {
        "speed_ratio": r, "rpm": rpm, "flow_m3h": Q * 3600.0, "head_m": H, "q_rel": q_rel,
        "suction_kpa_g": (p_suction_abs - ph.P_ATM) / 1000.0, "discharge_kpa_g": (p_discharge_abs - ph.P_ATM) / 1000.0,
        "suction_kpa_abs": p_suction_abs / 1000.0, "npsha_m": npsha, "npshr_m": npshr, "npsh_margin": sigma,
        "shaft_kw": P_shaft / 1000.0, "input_kw": P_in / 1000.0, "current_a": I, "motor_load": lam, "power_factor": pf,
        "motor_eff": eta_m, "fluid_temp_c": fluid_temp, "bearing_temp_c": bearing_temp, "winding_temp_c": winding_temp,
        "vib_rms_mm_s": vib_v, "vib_accel_rms_g": vib_a, "vib_crest": crest, "valve_position_pct": valve_pos * 100.0,
        "cavitation_intensity": cav_int, "ambient_c": ctx.ambient_c, "supply_temp_c": ctx.supply_temp_c,
        "K_total": K_total, "K_suction": K_suction, "hydraulic_kw": P_hyd / 1000.0,
        "flow_required_m3h": np.where(run > 0, q_req * 3600.0, np.nan),
        # vibration components (velocity mm/s RMS, acceleration g RMS) used by the waveform-snapshot synthesiser
        "_v_struct": v_struct * (r > 0.02), "_v_imb": v_imb, "_v_mis": v_mis, "_v_hyd": v_hyd, "_v_cav": v_cav, "_v_brg": v_brg,
        "_a_base": a_base * (r > 0.02), "_a_brg": a_brg, "_a_cav": a_cav,
    }
