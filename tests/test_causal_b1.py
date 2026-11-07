"""Hand-calculated causal estimates and agreement with published B1 after day one."""

import hashlib
from importlib import metadata
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from retrofit_sim.baselines import CH, b1_threshold, regime_frame, zscores

from retrofit_assistant import baseline
from retrofit_assistant.baseline import causal_zscores
from retrofit_assistant.data import AVAILABILITY, InputContract, load_assets, load_features
from retrofit_assistant.detectors import causal_b1
from retrofit_assistant.params import MIN_POOL_SAMPLES, Z_FLOORS


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "challenge" / "RETROFIT_AI_PARTICIPANTS_2026" / "data" / "full"
# Scores: train 58.451, validation 78.013; commit 1fc6da3 (src/ unchanged
# since fc3ce49). These values apply with requirements-lock.txt.
FROZEN_SHA256 = {
    "train": "c89da333816f1700d4bde4f6ad9e194772bfa6e8b54bb4ac206296793b00a079",
    "validation": "26810c051cd4b2661072918aaee4cbc67b097fbebf77b0d4395e1bd897c23fe6",
}
# requirements-lock.txt does not specify the Python version.
LOCK_PYTHON = (3, 14)
MEAN = "vibration_rms_mm_s__mean"
STD = "vibration_rms_mm_s__std"
COUNT = "vibration_rms_mm_s__count"
PREDICTION_COLUMNS = [
    "asset_id", "alert_time_utc", "event_class", "fault_type", "confidence",
    "evidence", "recommended_action",
]


def _lock_mismatch():
    if sys.version_info[:2] != LOCK_PYTHON:
        return f"Python {sys.version_info[:2]} does not match locked {LOCK_PYTHON}"
    packages = {"pandas", "numpy", "pyarrow"}
    locked = {}
    for line in (ROOT / "requirements-lock.txt").read_text(encoding="utf-8").splitlines():
        name, separator, version = line.partition("==")
        if separator and name in packages:
            locked[name] = version.strip()
    for name in sorted(packages):
        if name not in locked:
            return f"{name} is missing from requirements-lock.txt"
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            return f"{name} is not installed; lock requires {locked[name]}"
        if installed != locked[name]:
            return f"{name} {installed} does not match locked {locked[name]}"
    return None


def _assert_frozen(split, digest):
    expected = FROZEN_SHA256[split]
    if digest != expected:
        pytest.fail(
            f"causal_b1 is frozen: its output is the reference and may change only "
            f"with an explicit decision by the user. Outside requirements-lock.txt, "
            f"version differences may explain a mismatch. Split: {split}; "
            f"obtained sha256: {digest}; expected: {expected}",
            pytrace=False,
        )


@pytest.mark.parametrize("split", ["train", "validation"])
def test_causal_b1_cli_output_is_frozen(tmp_path, split):
    mismatch = _lock_mismatch()
    if mismatch:
        pytest.skip(mismatch)
    output = tmp_path / "predictions.csv"
    result = subprocess.run(
        [sys.executable, "-m", "retrofit_assistant", "predict", "--data", str(DATA),
         "--split", split, "--detector", "causal_b1", "--out", str(output)],
        cwd=ROOT, env={**os.environ, "PYTHONHASHSEED": "1"},
        capture_output=True, text=True, timeout=180,
    )
    if result.returncode != 0:
        pytest.fail(f"causal_b1 CLI failed for {split} (exit {result.returncode}): {result.stderr}", pytrace=False)
    _assert_frozen(split, hashlib.sha256(output.read_bytes()).hexdigest())


@pytest.mark.parametrize("split", ["train", "validation"])
def test_frozen_check_rejects_altered_digest(split):
    digest = FROZEN_SHA256[split]
    _assert_frozen(split, digest)
    altered = digest[:-1] + ("0" if digest[-1] != "0" else "1")
    with pytest.raises(pytest.fail.Exception, match="frozen.*decision by the user"):
        _assert_frozen(split, altered)


def test_frozen_environment_matches_lock():
    if sys.version_info[:2] != LOCK_PYTHON:
        pytest.skip("Python version differs from the lock environment")
    mismatch = _lock_mismatch()
    if mismatch:
        pytest.fail(mismatch, pytrace=False)


@pytest.mark.parametrize("component", ["package", "python"])
def test_lock_mismatch_reports_difference(monkeypatch, component):
    if component == "python":
        monkeypatch.setattr(sys.modules[__name__], "LOCK_PYTHON", (0, 0))
        assert "Python" in _lock_mismatch()
    else:
        monkeypatch.setattr(sys.modules[__name__], "LOCK_PYTHON", sys.version_info[:2])
        original_version = metadata.version
        monkeypatch.setattr(metadata, "version", lambda name: "different" if name == "numpy" else original_version(name))
        assert "numpy" in _lock_mismatch()


def minute_frame(values):
    size = len(values)
    return pd.DataFrame({
        "asset_id": ["SYNTHETIC"] * size,
        "window_start_utc": pd.date_range("2026-01-01", periods=size, freq="min", tz="UTC"),
        "steady": [True] * size, "regime": [19] * size, "rows": [60.0] * size,
        MEAN: values, STD: [0.1] * size, COUNT: [60] * size,
    })


def fixture_a():
    frame = minute_frame([1.0, 3.0] * 15 + [5.0, 9.0] * 15 + [3.4826, 9.9652, 6.9652])
    frame.loc[30:59, "regime"] = 20
    frame.loc[61, "regime"] = 20
    frame.loc[62, "regime"] = 21
    return frame


def test_hand_regime_and_pooled_fallback():
    frame = fixture_a()
    original = frame.copy(deep=True)
    result = causal_zscores(frame)
    assert result.loc[:59, "z_v"].isna().all()
    assert result.loc[:59, "zs_v"].isna().all()
    assert result.loc[60:62, "z_v"].tolist() == pytest.approx([1.0, 1.0, 1.0])
    assert_frame_equal(frame, original)


def test_hand_regime_minimum_uses_pooled_values(monkeypatch):
    frame = fixture_a()
    frame.loc[60, MEAN] = 6.9652
    monkeypatch.setattr(baseline, "MIN_REGIME_SAMPLES", 31)
    assert causal_zscores(frame).loc[60, "z_v"] == pytest.approx(1.0)


def test_hand_mean_and_std_floors():
    frame = minute_frame([2.0] * 60 + [2.1])
    frame.loc[60, STD] = 0.112
    result = causal_zscores(frame)
    assert result.loc[60, "z_v"] == pytest.approx(2.0)
    assert result.loc[60, "zs_v"] == pytest.approx(2.0)


def test_hand_std_mad_is_pooled_across_regimes():
    frame = fixture_a()
    frame[STD] = [1.0, 3.0] * 15 + [5.0, 9.0] * 15 + [6.9652] * 3
    assert causal_zscores(frame).loc[60:62, "zs_v"].tolist() == pytest.approx([1.0, 1.0, 1.0])


@pytest.mark.parametrize("samples,finite", [(MIN_POOL_SAMPLES - 1, False), (MIN_POOL_SAMPLES, True)])
def test_minimum_pool_samples_per_asset(samples, finite):
    frame = minute_frame([2.0] * 120)
    frame.loc[samples:59, "steady"] = False
    # One valid mean is enough when the steady-row pool is large enough: the
    # minimum is counted across rows, rather than non-null values in a channel.
    frame.loc[1:59, MEAN] = np.nan
    result = causal_zscores(frame)
    assert result.loc[60:, "z_v"].notna().all() == finite
    assert result.loc[60:, "zs_v"].notna().all() == finite
    if finite:
        assert result.loc[60:, "z_v"].tolist() == pytest.approx([0.0] * 60)


def test_hand_refresh_does_not_use_current_hour():
    frame = minute_frame([2.0] * 121)
    frame.loc[61, MEAN] = 1000.0
    frame.loc[[61, 120], "regime"] = 21
    frame.loc[[62, 119], MEAN] = 2.1
    frame.loc[120, MEAN] = 1000.05
    result = causal_zscores(frame)
    assert result.loc[62, "z_v"] == pytest.approx(2.0)
    assert result.loc[119, "z_v"] == pytest.approx(2.0)
    assert result.loc[120, "z_v"] == pytest.approx(1.0)
    changed = frame.copy()
    changed.loc[61, MEAN] = 2000.0
    changed_result = causal_zscores(changed)
    assert changed_result.loc[62, "z_v"] == pytest.approx(2.0)
    assert changed_result.loc[119, "z_v"] == pytest.approx(2.0)
    assert changed_result.loc[120, "z_v"] == pytest.approx(-19999.0)


def test_hand_pool_includes_minute_59_and_uses_contract_latency(monkeypatch):
    frame = minute_frame([2.0] * 29 + [4.0] * 30 + [2.0, 4.4826])
    assert causal_zscores(frame).loc[60, "z_v"] == pytest.approx(1.0)
    monkeypatch.setitem(AVAILABILITY, "features_1min.parquet", InputContract("window_start_utc", pd.Timedelta(minutes=2)))
    # With a two-minute delay, minute 59 is unavailable and the median is 4.
    assert causal_zscores(frame).loc[60, "z_v"] == pytest.approx(9.652)


def test_hand_pool_stops_growing_at_24_hours():
    frame = minute_frame([2.0] * 1800 + [2.1])
    original = causal_zscores(frame)
    changed = frame.copy()
    changed.loc[1440:1799, MEAN] = 1e9
    changed.loc[1440:1799, STD] = 1e6
    altered = causal_zscores(changed)
    assert original.loc[1800, "z_v"] == pytest.approx(2.0)
    assert altered.loc[1800, "z_v"] == pytest.approx(2.0)
    assert original.loc[1800, "zs_v"] == altered.loc[1800, "zs_v"] == 0.0


def test_gap_and_flat_exist_during_segment_zero():
    frame = minute_frame([2.0] * 61)
    frame.loc[0, "rows"] = 29
    frame.loc[0:1, STD] = 0.0
    frame.loc[1, COUNT] = 29
    result = causal_zscores(frame)
    assert result.loc[0, "gap"]
    assert not result.loc[1, "gap"]
    assert result.loc[0, "flat_v"]
    assert not result.loc[1, "flat_v"]
    assert result.loc[0, ["z_v", "zs_v"]].isna().all()


def test_channel_schema_does_not_depend_on_future_non_null_values():
    frame = minute_frame([np.nan] * 120 + [2.0])
    frame[STD] = np.nan
    prefix = causal_zscores(frame.iloc[:120])
    complete = causal_zscores(frame)
    assert prefix.columns.equals(complete.columns)
    assert_frame_equal(prefix, complete.iloc[:120].reset_index(drop=True))
    assert complete.z_v.isna().all()
    assert complete.zs_v.isna().all()
    assert not complete.flat_v.any()
    for key in CH:
        assert "z_" + key in complete
    assert "zs_a" not in complete and "flat_a" not in complete


def test_independent_asset_pools():
    first = minute_frame([2.0] * 60 + [2.1])
    second = minute_frame([20.0] * 60 + [20.1])
    second["asset_id"] = "SECOND"
    result = causal_zscores(pd.concat([first, second], ignore_index=True))
    assert result.loc[[60, 121], "z_v"].tolist() == pytest.approx([2.0, 2.0])


def test_floor_keys_match_published_channels():
    assert set(Z_FLOORS) == set(CH)


@pytest.fixture(scope="module")
def real_frames():
    result = {}
    for split in ["train", "validation"]:
        assets = load_assets(DATA, split)
        for asset_id in assets.asset_id:
            selected = assets.loc[assets.asset_id == asset_id]
            features = load_features(DATA, selected)
            frame = regime_frame(features, selected)
            result[asset_id] = (features, selected, frame, causal_zscores(frame))
    return result


@pytest.mark.parametrize("asset_id", [f"PUMP-{i:02d}" for i in range(1, 10)])
def test_real_scores_exactly_match_published_b1_after_24_hours(real_frames, asset_id):
    _, _, frame, actual = real_frames[asset_id]
    published = zscores(frame)
    after_day = frame.window_start_utc >= frame.window_start_utc.min() + pd.Timedelta(hours=24)
    columns = [column for column in published if column.startswith(("z_", "zs_")) or column == "gap"]
    assert_frame_equal(actual.loc[after_day, columns], published.loc[after_day, columns], check_exact=True, check_dtype=False)
    flat = [column for column in published if column.startswith("flat_")]
    assert_frame_equal(actual.loc[after_day, flat].fillna(False), published.loc[after_day, flat].fillna(False), check_exact=True)


@pytest.mark.parametrize("asset_id", [f"PUMP-{i:02d}" for i in range(1, 10)])
def test_real_steady_pool_counts(real_frames, asset_id):
    _, _, frame, _ = real_frames[asset_id]
    t0 = frame.window_start_utc.min()
    available = frame.window_start_utc + AVAILABILITY["features_1min.parquet"].latency
    assert (frame.steady & (available <= t0 + pd.Timedelta(hours=1))).sum() == 51
    assert (frame.steady & (available <= t0 + pd.Timedelta(hours=24))).sum() >= 808


def test_causal_b1_matches_reference_composition_and_empty_schema(real_frames):
    features, assets, _, scored = real_frames["PUMP-08"]
    actual = causal_b1(features, assets)
    expected = b1_threshold(scored, 6.0, 15)
    assert_frame_equal(actual, expected, check_exact=True)
    assert actual.columns.tolist() == PREDICTION_COLUMNS
    assert not actual.empty
    empty = causal_b1(features.iloc[:0], assets)
    assert empty.empty
    assert empty.columns.tolist() == PREDICTION_COLUMNS
