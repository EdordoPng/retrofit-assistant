"""Causal snapshot evidence for bearing wear and post-lockout misalignment."""

import numpy as np
import pandas as pd
from scipy.signal import hilbert

from .data import AVAILABILITY
from .params import (
    SNAPSHOT_MAX_AGE, SPECTRUM_BEARING_RATIO, SPECTRUM_ENVELOPE_BAND_HZ,
    SPECTRUM_LINE_TOLERANCE, SPECTRUM_MISALIGNMENT_RATIO, SPECTRUM_NOISE_BAND_FACTORS,
)


def _line_mask(frequencies, frequency):
    return ((frequencies >= frequency * (1 - SPECTRUM_LINE_TOLERANCE))
            & (frequencies <= frequency * (1 + SPECTRUM_LINE_TOLERANCE)))


def _line(frequencies, amplitudes, frequency):
    mask = _line_mask(frequencies, frequency)
    return amplitudes[mask].max() if mask.any() else np.nan


def _ratio(peak, noise):
    if not np.isfinite(peak) or not np.isfinite(noise):
        return np.nan
    return peak / noise if noise > 0 else (np.inf if peak > 0 else 0.0)


def snapshot_lines(row, meta):
    """Hann line amplitudes and bearing envelope peak/background ratios."""
    rpm = getattr(row, "rpm_at_capture", np.nan)
    if pd.isna(rpm) or not np.isfinite(rpm) or rpm <= 0:
        return None
    samples = np.asarray(row.samples, dtype=float)
    if samples.ndim != 1 or len(samples) < 2 or not np.isfinite(samples).all():
        return None
    sample_rate = row.sample_rate_hz
    if not np.isfinite(sample_rate) or sample_rate <= 0:
        return None
    samples = samples - samples.mean()
    size = len(samples)
    window = np.hanning(size)
    frequencies = np.fft.rfftfreq(size, 1 / sample_rate)
    amplitudes = np.abs(np.fft.rfft(samples * window))
    running = rpm / 60
    band = np.fft.rfft(samples)
    low, high = SPECTRUM_ENVELOPE_BAND_HZ
    band[(frequencies < low) | (frequencies > high)] = 0
    envelope = np.abs(hilbert(np.fft.irfft(band, size)))
    envelope = envelope - envelope.mean()
    envelope_amplitudes = np.abs(np.fft.rfft(envelope * window))

    def bearing_ratio(order):
        if pd.isna(order) or not np.isfinite(order) or order <= 0:
            return np.nan
        frequency = order * running
        lower, upper = SPECTRUM_NOISE_BAND_FACTORS
        background = ((frequencies >= lower * frequency)
                      & (frequencies <= upper * frequency)
                      & ~_line_mask(frequencies, frequency))
        if not background.any():
            return np.nan
        return _ratio(_line(frequencies, envelope_amplitudes, frequency),
                      np.median(envelope_amplitudes[background]))

    return {"a2": _line(frequencies, amplitudes, 2 * running),
            "bpfo": bearing_ratio(meta.get("bearing_bpfo_order", np.nan)),
            "bpfi": bearing_ratio(meta.get("bearing_bpfi_order", np.nan))}


def spectral_type(snapshots, history, meta, time):
    """Use the latest completed capture; older steady captures anchor lockout ratios.

    The caller supplies only the alert's asset and completed feature minutes.
    Historical captures are used only for the before/after 2x comparison.
    """
    latency = AVAILABILITY["vibration_snapshots.parquet"].latency
    available = snapshots.loc[snapshots.timestamp_utc + latency <= time].sort_values("timestamp_utc")
    if available.empty or time - available.timestamp_utc.iloc[-1] > SNAPSHOT_MAX_AGE:
        return None
    current = snapshot_lines(next(available.tail(1).itertuples(index=False)), meta)
    if current is None:
        return None
    if any(current[line] >= SPECTRUM_BEARING_RATIO for line in ("bpfo", "bpfi")):
        return ("BEARING_WEAR", "vibration_accel_rms_g envelope peak "
                f"BPFO {current['bpfo']:.3g} BPFI {current['bpfi']:.3g} x band noise")
    lockout = history.loc[history.operating_mode == "LOCKED_OUT"]
    if lockout.empty:
        return None
    last = lockout.window_start_utc.max()
    prefix = history.loc[history.window_start_utc <= last].sort_values("window_start_utc")
    flags = (prefix.operating_mode == "LOCKED_OUT").to_numpy()
    index = len(flags) - 1
    while index > 0 and flags[index - 1]:
        index -= 1
    start = prefix.window_start_utc.iloc[index]
    steady = set(history.loc[history.steady.fillna(False).astype(bool), "window_start_utc"])
    before, after = [], []
    for row in available.itertuples(index=False):
        if row.timestamp_utc.floor("min") not in steady:
            continue
        target = before if row.timestamp_utc < start else after if row.timestamp_utc > last else None
        if target is not None:
            lines = snapshot_lines(row, meta)
            if lines is not None and np.isfinite(lines["a2"]):
                target.append(lines["a2"])
    if before and after:
        ratio = _ratio(np.median(after), np.median(before))
        if ratio >= SPECTRUM_MISALIGNMENT_RATIO:
            return "MISALIGNMENT", f"vibration_accel_rms_g 2x after lockout {ratio:.3g} x before"
    return None
