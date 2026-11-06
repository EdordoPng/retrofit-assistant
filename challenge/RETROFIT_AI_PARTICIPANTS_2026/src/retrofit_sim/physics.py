"""Reduced-order physics for a motor-driven centrifugal pump in a cooling loop.

All internal quantities are SI (m3/s, m, Pa, W, K, rad/s). Functions are vectorised over numpy arrays.
This is a quasi-steady, lumped model chosen for transparency. It is NOT a validated high-fidelity digital twin.

Pump family (one coherent, dimensionless family; radial end-suction / split-case style impeller):
    head      h(q) = h0 - (h0 - 1) q^2,               q = Q / (r Q_bep), r = n / n_rated
    affinity  H(Q, r) = r^2 H_bep h(Q / (r Q_bep)) = H_bep (h0 r^2 - (h0 - 1) Q^2 / Q_bep^2)
    efficiency  eta(q, r) = eta_bep_r q (2 - q),   eta_bep_r = 1 - (1 - eta_bep) r^-0.1   (Moody-type step-up)
    shaft power P = rho g Q H / eta  ->  P / P_bep = r^3 h(q) / (2 - q) (finite at shut-off, ~h0/2 P_bep)
    NPSHr     NPSHr(q, r) = NPSHr_bep r^2 (a0 + (1 - a0) q^b)
System:  H_sys = H_static + K_total Q^2, with valve, strainer and heat-exchanger terms.
"""
from __future__ import annotations

import numpy as np

G = 9.80665
P_ATM = 101_325.0


def water_density(t_c, salinity_psu=0.0):
    """kg/m3. Pure-water polynomial (Kell-like fit, 0-60 C) + linear salinity term (~0.78 kg/m3 per psu)."""
    t = np.asarray(t_c, dtype=float)
    rho_w = 999.84 + 0.0679 * t - 0.009096 * t ** 2 + 1.0e-4 * t ** 3 - 1.0e-6 * t ** 4
    return rho_w + 0.78 * salinity_psu


def vapour_pressure_pa(t_c):
    """Saturation vapour pressure of water [Pa], Antoine equation (1-100 C)."""
    t = np.asarray(t_c, dtype=float)
    p_mmhg = 10 ** (8.07131 - 1730.63 / (233.426 + t))
    return p_mmhg * 133.322


def pump_head(Q, r, H_bep, Q_bep, h0, head_factor=1.0):
    """Pump head [m] at flow Q [m3/s] and speed ratio r. head_factor < 1 models impeller wear / cavitation loss."""
    H = H_bep * (h0 * r ** 2 - (h0 - 1.0) * (Q / Q_bep) ** 2)
    return np.maximum(H, 0.0) * head_factor


def pump_efficiency(Q, r, Q_bep, eta_bep):
    r_safe = np.maximum(r, 0.05)
    eta_r = 1.0 - (1.0 - eta_bep) * r_safe ** -0.1
    q = np.clip(Q / (r_safe * Q_bep), 0.0, 1.95)
    return np.maximum(eta_r * q * (2.0 - q), 1e-3)


def shaft_power(Q, H, r, Q_bep, H_bep, eta_bep, h0, rho, head_factor=1.0):
    """Shaft power [W]. Uses the closed form so that shut-off power is finite and physically plausible."""
    r_safe = np.maximum(r, 1e-6)
    q = np.clip(Q / (r_safe * Q_bep), 0.0, 1.95)
    eta_r = 1.0 - (1.0 - eta_bep) * np.maximum(r_safe, 0.05) ** -0.1
    P_bep_r = rho * G * Q_bep * H_bep / eta_r                 # BEP power at rated speed with speed-corrected efficiency
    h = (h0 - (h0 - 1.0) * q ** 2) * head_factor
    return P_bep_r * r_safe ** 3 * np.maximum(h, 0.0) / (2.0 - q) * (r > 0)


def npsh_required(Q, r, Q_bep, npshr_bep, a0=0.55, b=2.6):
    r_safe = np.maximum(r, 1e-6)
    q = np.clip(Q / (r_safe * Q_bep), 0.0, 2.0)
    return npshr_bep * r_safe ** 2 * (a0 + (1.0 - a0) * q ** b)


def solve_operating_point(r, H_bep, Q_bep, h0, H_static, K_total, head_factor=1.0):
    """Intersection of pump curve and system curve. Closed form for the quadratic family.
    Returns Q [m3/s] >= 0 (0 when the pump cannot overcome static head)."""
    A = H_bep * h0 * head_factor
    B = H_bep * (h0 - 1.0) / Q_bep ** 2 * head_factor
    num = A * r ** 2 - H_static
    Q = np.sqrt(np.maximum(num, 0.0) / (B + K_total))
    return Q


def speed_for_flow(Q_target, H_bep, Q_bep, h0, H_static, K_total, head_factor=1.0):
    """Speed ratio needed to deliver Q_target through the system (inverse of solve_operating_point)."""
    A = H_bep * h0 * head_factor
    B = H_bep * (h0 - 1.0) / Q_bep ** 2 * head_factor
    return np.sqrt(np.maximum((H_static + (B + K_total) * Q_target ** 2) / A, 0.0))


def cavitation_head_factor(npsha, npshr, sharpness=6.0):
    """Head-drop factor from the NPSH margin sigma = NPSHa / NPSHr (simplified, not CFD).
    By definition NPSHr is the NPSH at which head drops 3 %, so factor(sigma=1) = 0.97;
    the drop grows quickly below 1 (breakdown) and is negligible above ~1.3."""
    sigma = npsha / np.maximum(npshr, 1e-3)
    drop = 0.03 * np.exp(-sharpness * (sigma - 1.0))
    return np.clip(1.0 - drop, 0.55, 1.0), sigma


def equal_percentage_cv(position_frac, cv_max, rangeability=50.0):
    p = np.clip(position_frac, 0.02, 1.0)
    return cv_max * rangeability ** (p - 1.0)


def valve_K(position_frac, K_full_open, rangeability=50.0):
    """Valve resistance coefficient (head = K Q^2) for an equal-percentage valve; K ~ 1/Cv^2."""
    rel = equal_percentage_cv(position_frac, 1.0, rangeability)
    return K_full_open / rel ** 2


def motor_electrical(P_shaft, P_rated, eta_rated, pf_rated, V_line, const_loss_share=0.35, vfd_eff=None):
    """Motor input power [W], efficiency, power factor and line current [A] from shaft power.
    Loss model: L = L_c + L_v (P/P_rated)^2 with L_c a fixed share of rated losses (iron + friction)."""
    lam = np.clip(P_shaft / P_rated, 0.0, 2.0)
    L_rated = P_rated * (1.0 / eta_rated - 1.0)
    P_in = P_shaft + (const_loss_share * L_rated + (1 - const_loss_share) * L_rated * lam ** 2) * (P_shaft > 0)
    eta = np.where(P_in > 0, P_shaft / np.maximum(P_in, 1.0), 0.0)
    # power-factor droop at part load (cf. IE3 catalogue data: ~0.86 at full load, ~0.75 at half load)
    pf = pf_rated * (1.0 - np.exp(-lam / 0.3)) / (1.0 - np.exp(-1.0 / 0.3))
    pf = np.clip(pf, 0.05, 0.95)
    I = np.where(P_in > 0, P_in / (np.sqrt(3.0) * V_line * pf), 0.0)
    if vfd_eff is not None:
        # drive efficiency falls at part load (US DOE motor tip sheet, PWM drives 25-100 hp), scaled to the rated value
        eff = np.interp(lam, [0.0, 0.125, 0.25, 0.5, 0.75, 1.0], [0.80, 0.88, 0.93, 0.96, 0.965, 0.97]) * (vfd_eff / 0.97)
        P_in = P_in / eff
    return P_in, eta, pf, I, lam


def first_order(x, dt, tau, x0=None):
    """Exact discretisation of a first-order lag, vectorised via an IIR recursion (loop in numpy blocks)."""
    from scipy.signal import lfilter
    a = np.exp(-dt / np.asarray(tau, dtype=float))
    x = np.asarray(x, dtype=float)
    if np.ndim(a) == 0:
        zi = np.array([(x0 if x0 is not None else x[0]) * a])
        y, _ = lfilter([1 - a], [1, -a], x, zi=zi)
        return y
    # time-varying tau: explicit loop in compiled-friendly chunks
    y = np.empty_like(x)
    prev = x0 if x0 is not None else x[0]
    for i in range(len(x)):
        prev = a[i] * prev + (1 - a[i]) * x[i]
        y[i] = prev
    return y
