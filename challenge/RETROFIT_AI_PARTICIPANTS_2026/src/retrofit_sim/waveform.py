"""Short acceleration waveform snapshots, as captured periodically by retrofit vibration sensors.

The snapshot is synthesised from the same vibration components as the 1 Hz overall values (plant.py):
running-speed harmonics (unbalance 1x, misalignment 2x/3x), vane-pass, structural broadband, rolling-element
bearing outer-race impacts (BPFO impulse train exciting a housing resonance), and cavitation broadband noise.
Amplitudes agree with the 1 Hz overall values to within the sensor tolerance; this is a reduced-order signal
model, not a measured or rotordynamic simulation.
"""
from __future__ import annotations

import numpy as np

G = 9.80665


def _vel_to_acc_amp(v_rms_mm_s, f_hz):
    """Peak acceleration [g] of a sinusoid with velocity RMS v at frequency f."""
    return v_rms_mm_s * 1e-3 * np.sqrt(2.0) * 2 * np.pi * f_hz / G


def _bandnoise(rng, n, fs, f_lo, f_hi):
    x = rng.normal(0, 1, n)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / fs)
    X[(f < f_lo) | (f > f_hi)] = 0
    y = np.fft.irfft(X, n)
    return y / (np.std(y) + 1e-12)


def snapshot(truth: dict, i: int, asset: dict, rng, fs: int = 10240, dur_s: float = 1.0) -> np.ndarray:
    n = int(fs * dur_s)
    t = np.arange(n) / fs
    fr = max(float(truth["rpm"][i]) / 60.0, 0.0)
    x = np.zeros(n)
    if fr < 1.0:
        return (0.003 * rng.normal(0, 1, n)).astype(np.float32)          # stopped: sensor noise floor
    ph = lambda: rng.uniform(0, 2 * np.pi)
    v_imb, v_mis, v_hyd = truth["_v_imb"][i], truth["_v_mis"][i], truth["_v_hyd"][i]
    v_str, v_brg = truth["_v_struct"][i], truth["_v_brg"][i]
    a_base, a_brg, a_cav = truth["_a_base"][i], truth["_a_brg"][i], truth["_a_cav"][i]
    vanes = int(asset.get("impeller_vanes", 6))
    # running-speed harmonics
    x += _vel_to_acc_amp(np.hypot(v_imb, 0.6 * v_mis), fr) * np.sin(2 * np.pi * fr * t + ph())
    x += _vel_to_acc_amp(0.8 * v_mis + 0.15 * v_str, 2 * fr) * np.sin(2 * np.pi * 2 * fr * t + ph())
    x += _vel_to_acc_amp(0.25 * v_mis + 0.1 * v_str, 3 * fr) * np.sin(2 * np.pi * 3 * fr * t + ph())
    x += _vel_to_acc_amp(0.6 * v_hyd + 0.5 * v_str, vanes * fr) * np.sin(2 * np.pi * vanes * fr * t + ph())
    x += _vel_to_acc_amp(0.25 * v_str, 2 * vanes * fr) * np.sin(2 * np.pi * 2 * vanes * fr * t + ph())
    # bearing outer-race defect: impulse train at BPFO exciting a ~2.8 kHz housing resonance, plus the BPFO line
    if a_brg > 1e-4:
        bpfo = asset.get("bearing_bpfo_order", 3.05) * fr * (1 - 0.01 * rng.random())  # slip lowers real peaks slightly
        f_res = asset.get("housing_resonance_hz", 2800.0)
        imp = np.zeros(n)
        k = np.arange(0, dur_s, 1.0 / bpfo)
        idx = (k * fs + rng.normal(0, 0.002 * fs / bpfo, k.size)).astype(int)
        idx = idx[(idx >= 0) & (idx < n)]
        imp[idx] = 1.0 + 0.2 * rng.normal(0, 1, idx.size)
        tk = np.arange(int(0.004 * fs)) / fs
        kernel = np.exp(-tk / 0.0008) * np.sin(2 * np.pi * f_res * tk)
        burst = np.convolve(imp, kernel)[:n]
        burst /= (np.std(burst) + 1e-12)
        x += a_brg * burst
        x += _vel_to_acc_amp(0.5 * v_brg, bpfo) * np.sin(2 * np.pi * bpfo * t + ph())
    # cavitation / air: broadband 1-4.5 kHz with burst modulation
    if a_cav > 1e-4:
        env = 1.0 + 0.8 * np.clip(_bandnoise(rng, n, fs, 1, 30), -1.2, 3)
        x += a_cav * env * _bandnoise(rng, n, fs, 1000, 4500)
    # structural / flow broadband and sensor noise floor
    x += a_base * _bandnoise(rng, n, fs, 10, 4500)
    x += 0.002 * rng.normal(0, 1, n)
    return x.astype(np.float32)


def snapshot_schedule(n: int, running: np.ndarray, interval_s: int, rng) -> list:
    """Capture times: every interval_s, shifted to the next time the pump has been running for >= 120 s."""
    times = []
    first = int(rng.integers(0, interval_s))
    for t0 in range(first, n, interval_s):
        j = t0
        while j < n and not running[max(0, j - 120):j + 1].all():
            j += 60
            if j - t0 > interval_s // 2:
                break
        if j < n and running[max(0, j - 120):j + 1].all():
            times.append(j)
    return times
