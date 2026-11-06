"""Gate 3: numerical stability and intuitive physical response of the reduced-order model."""
import numpy as np

from retrofit_sim import physics as ph

QB, HB, H0 = 500 / 3600, 26.0, 1.22


def test_more_resistance_never_more_flow():
    K = np.linspace(500, 20000, 50)
    Q = ph.solve_operating_point(np.ones(50), HB, QB, H0, 3.0, K, 1.0)
    assert np.all(np.diff(Q) < 0) and np.all(Q > 0)


def test_affinity_laws_pure_friction_system():
    # static head 0 -> operating point scales Q ~ n, H ~ n^2, P ~ n^3 (within the stated validity range)
    K = (HB * 0.98) / (QB * 0.95) ** 2
    r = np.array([0.6, 0.8, 1.0])
    Q = ph.solve_operating_point(r, HB, QB, H0, 0.0, K, 1.0)
    H = ph.pump_head(Q, r, HB, QB, H0, 1.0)
    P = ph.shaft_power(Q, H, r, QB, HB, 0.82, H0, 1000.0, 1.0)
    np.testing.assert_allclose(Q / Q[-1], r, rtol=1e-3)
    np.testing.assert_allclose(H / H[-1], r ** 2, rtol=1e-3)
    np.testing.assert_allclose(P / P[-1], r ** 3, rtol=0.04)


def test_energy_chain_plausible():
    r = np.linspace(0.5, 1.0, 20)
    Q = ph.solve_operating_point(r, HB, QB, H0, 3.0, 9000.0, 1.0)
    H = ph.pump_head(Q, r, HB, QB, H0, 1.0)
    P_hyd = 1000 * 9.81 * Q * H
    P_sh = ph.shaft_power(Q, H, r, QB, HB, 0.82, H0, 1000.0, 1.0)
    P_in, eta_m, pf, I, lam = ph.motor_electrical(P_sh, 55e3, 0.95, 0.86, 440.0)
    assert np.all(P_hyd < P_sh) and np.all(P_sh < P_in)
    eta_pump = P_hyd / P_sh
    assert eta_pump.max() <= 0.83 and eta_pump.min() > 0.4
    assert np.all((pf > 0) & (pf <= 0.95)) and np.all(I > 0)


def test_npsh_and_cavitation_monotone():
    sigma_hi = ph.cavitation_head_factor(np.array([12.0]), np.array([4.0]))[0][0]
    sigma_lo = ph.cavitation_head_factor(np.array([3.0]), np.array([4.0]))[0][0]
    assert sigma_hi == 1.0 or sigma_hi > 0.999
    assert sigma_lo < sigma_hi
    f1 = ph.cavitation_head_factor(np.array([4.0]), np.array([4.0]))[0][0]
    assert 0.95 < f1 < 0.99          # ~3 % head drop at NPSHa = NPSH3


def test_water_properties():
    assert 999 < ph.water_density(np.array([10.0]), 0.0)[0] < 1001
    assert 1003 < ph.water_density(np.array([10.0]), 6.0)[0] < 1006
    np.testing.assert_allclose(ph.vapour_pressure_pa(np.array([20.0, 60.0])), [2339, 19946], rtol=0.03)
