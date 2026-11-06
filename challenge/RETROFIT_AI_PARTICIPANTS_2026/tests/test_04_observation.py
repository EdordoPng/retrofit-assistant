"""Gate 4: the true (latent) state drives observed signals with realistic lag and noise."""
import numpy as np

from retrofit_sim import generate as G
from retrofit_sim.dataset import enrich_asset
from retrofit_sim.faults import FaultSpec, build_latent
from retrofit_sim.plant import simulate_truth
from retrofit_sim.sensors import channel_specs, observe


def _asset(fleet, aid):
    cfg, assets = fleet
    return cfg, enrich_asset(next(x for x in assets if x["asset_id"] == aid))


def test_clog_lowers_suction_pressure_with_lag(fleet):
    cfg, a = _asset(fleet, "PUMP-09")             # fixed-speed, fully instrumented
    a = dict(a, scenario=[])
    res = G.simulate_asset(a, 1, 0.25, want_detectability=False)
    n = res["n"]
    onset = 3 * 3600
    lat = build_latent(n, [FaultSpec("SUCTION_STRAINER_CLOGGING", onset, None, {"rate_per_h": 50.0, "c_max": 3.0, "shape": "linear"})], {})
    tr = simulate_truth(res["acfg"], res["ctx"], lat, np.random.default_rng(0))
    specs = channel_specs(res["acfg"])
    obs, _, _ = observe(tr, res["acfg"], specs, [], {}, np.random.default_rng(1))
    run = tr["speed_ratio"] > 0.9
    before = np.nanmean(obs["suction_pressure_kpa"][onset - 1800:onset][run[onset - 1800:onset]])
    after = np.nanmean(obs["suction_pressure_kpa"][onset + 3600:onset + 5400][run[onset + 3600:onset + 5400]])
    assert after < before - 5.0
    # transmitter lag: right at the step the reading has not yet reached the new value
    assert tr["flow_m3h"][onset + 3600] < tr["flow_m3h"][onset - 60]


def test_noise_level_matches_channel_spec(fleet):
    cfg, a = _asset(fleet, "PUMP-09")
    res = G.simulate_asset(dict(a, scenario=[]), 2, 0.1, want_detectability=False)
    spec = res["specs"]["discharge_pressure_kpa"]
    y = res["obs"]["discharge_pressure_kpa"].astype(float)
    x = res["truth"]["discharge_kpa_g"]
    resid = (y - x)[2000:]
    resid = resid[~np.isnan(resid)]
    resid = resid - np.median(resid)                 # remove unit calibration offset
    assert 0.5 * spec.sigma < np.std(resid) < 2.5 * spec.sigma


def test_bearing_temperature_lags_load(fleet):
    cfg, a = _asset(fleet, "PUMP-04")
    res = G.simulate_asset(dict(a, scenario=[]), 3, 1.0, want_detectability=False)
    bt = res["truth"]["bearing_temp_c"]
    assert np.max(np.abs(np.diff(bt))) < 0.05        # first-order thermal lag (tau ~ 25 min): no jumps


def test_sensor_fault_changes_reading_not_physics(fleet):
    cfg, a = _asset(fleet, "PUMP-03")
    res = G.simulate_asset(dict(a, scenario=[]), 4, 0.2, want_detectability=False)
    f = FaultSpec("SENSOR_CALIBRATION_SHIFT", 3600, None, {"step": 20.0}, sensor_tag="discharge_pressure_kpa")
    o1, _, _ = observe(res["truth"], res["acfg"], res["specs"], [], {}, np.random.default_rng(5))
    o2, _, _ = observe(res["truth"], res["acfg"], res["specs"], [f], {}, np.random.default_rng(5))
    d = o2["discharge_pressure_kpa"].astype(float) - o1["discharge_pressure_kpa"].astype(float)
    assert abs(np.nanmedian(d[:3600])) < 0.2 and abs(np.nanmedian(d[4000:]) - 20.0) < 0.5
    np.testing.assert_array_equal(o1["motor_current_a"], o2["motor_current_a"])
