"""Synthetic snapshot decisions, availability, and diagnosis boundaries (C13)."""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from retrofit_assistant.data import load_snapshots
from retrofit_assistant.diagnosis import rediagnose
from retrofit_assistant.output import COLUMNS
from retrofit_assistant.params import DECIDED_BY
from retrofit_assistant.recommendations import recommend
from retrofit_assistant.spectra import snapshot_lines, spectral_type


START = pd.Timestamp("2026-01-01T00:00:00Z")
META = pd.Series({"bearing_bpfo_order": 4.0, "bearing_bpfi_order": 6.0})


def waveform(bearing=False, a2=1.0, order=4.0):
    t = np.arange(10240) / 10240
    carrier = np.sin(2 * np.pi * 2800 * t)
    if bearing:
        carrier *= 1 + 0.8 * np.cos(2 * np.pi * order * 25 * t)
    noise = np.random.default_rng(23).normal(0, 0.1, len(t))
    return carrier + noise + a2 * np.sin(2 * np.pi * 50 * t)


def capture(time=START + pd.Timedelta(hours=1), **kwargs):
    row = {"asset_id": "A", "timestamp_utc": time, "rpm_at_capture": 1500.0,
           "sample_rate_hz": 10240, "samples": waveform()}
    row.update(kwargs)
    return row


def history(lockout=True):
    frame = pd.DataFrame({"window_start_utc": pd.date_range(START, periods=120, freq="min"),
                          "operating_mode": "RUNNING", "steady": True})
    if lockout:
        frame.loc[50:59, "operating_mode"] = "LOCKED_OUT"
        frame.loc[50:59, "steady"] = False
    return frame


@pytest.mark.parametrize("order,line", [(4.0, "BPFO"), (6.0, "BPFI")])
def test_bearing_envelope_known_order(order, line):
    row = capture(samples=waveform(bearing=True, order=order))
    lines = snapshot_lines(SimpleNamespace(**row), META)
    assert lines[line.lower()] >= 6
    result = spectral_type(pd.DataFrame([row]), history(), META, START + pd.Timedelta(hours=2))
    assert result[0] == "BEARING_WEAR"
    assert line in result[1] and "vibration_accel_rms_g" in result[1]


def test_carrier_without_bearing_modulation_does_not_diagnose():
    snapshots = pd.DataFrame([capture()])
    assert spectral_type(snapshots, history(False), META, START + pd.Timedelta(hours=2)) is None


def test_hann_two_x_amplitude_doubles():
    t = np.arange(10240) / 10240
    samples = np.sin(2 * np.pi * 50 * t)
    one = snapshot_lines(SimpleNamespace(**capture(samples=samples)), META)
    two = snapshot_lines(SimpleNamespace(**capture(samples=2 * samples)), META)
    assert two["a2"] == pytest.approx(2 * one["a2"])


@pytest.mark.parametrize("lockout,expected", [(True, "MISALIGNMENT"), (False, None)])
def test_two_x_doubled_after_lockout(lockout, expected):
    samples = waveform()
    snapshots = pd.DataFrame([
        capture(START + pd.Timedelta(minutes=30), samples=samples),
        capture(START + pd.Timedelta(minutes=90), samples=2 * samples),
    ])
    result = spectral_type(snapshots, history(lockout), META, START + pd.Timedelta(hours=2))
    assert (result[0] if result else None) == expected
    if result:
        assert "2x" in result[1] and "2 x before" in result[1]


def test_bearing_takes_precedence_over_post_lockout_two_x():
    snapshots = pd.DataFrame([
        capture(START + pd.Timedelta(minutes=30)),
        capture(START + pd.Timedelta(minutes=90), samples=waveform(bearing=True, a2=4)),
    ])
    assert spectral_type(snapshots, history(), META, START + pd.Timedelta(hours=2))[0] == "BEARING_WEAR"


@pytest.mark.parametrize("rpm", [None, np.nan, 0, -1500, np.inf])
def test_invalid_rpm_has_no_decision(rpm):
    snapshots = pd.DataFrame([capture(samples=waveform(bearing=True), rpm_at_capture=rpm)])
    assert spectral_type(snapshots, history(), META, START + pd.Timedelta(hours=2)) is None


def test_missing_rpm_column_has_no_decision():
    snapshots = pd.DataFrame([capture(samples=waveform(bearing=True))]).drop(columns="rpm_at_capture")
    assert spectral_type(snapshots, history(), META, START + pd.Timedelta(hours=2)) is None


def test_latest_capture_without_rpm_does_not_fall_back_to_older_bearing():
    snapshots = pd.DataFrame([
        capture(samples=waveform(bearing=True)),
        capture(START + pd.Timedelta(minutes=90), rpm_at_capture=np.nan),
    ])
    assert spectral_type(snapshots, history(), META, START + pd.Timedelta(hours=2)) is None


def test_capture_available_only_at_end_of_one_second():
    time = START + pd.Timedelta(hours=2)
    snapshots = pd.DataFrame([capture(time, samples=waveform(bearing=True))])
    assert spectral_type(snapshots, history(), META, time) is None
    assert spectral_type(snapshots, history(), META, time + pd.Timedelta(seconds=1))[0] == "BEARING_WEAR"


def test_future_capture_does_not_replace_available_healthy_capture():
    time = START + pd.Timedelta(hours=2)
    snapshots = pd.DataFrame([capture(), capture(time, samples=waveform(bearing=True))])
    assert spectral_type(snapshots, history(False), META, time) is None


def test_only_latest_capture_supplies_bearing_evidence():
    snapshots = pd.DataFrame([
        capture(samples=waveform(bearing=True)),
        capture(START + pd.Timedelta(minutes=90)),
    ])
    assert spectral_type(snapshots, history(False), META, START + pd.Timedelta(hours=2)) is None


def test_eight_hour_age_boundary():
    row = capture(samples=waveform(bearing=True))
    snapshots = pd.DataFrame([row])
    time = row["timestamp_utc"] + pd.Timedelta(hours=8)
    assert spectral_type(snapshots, history(), META, time)[0] == "BEARING_WEAR"
    assert spectral_type(snapshots, history(), META, time + pd.Timedelta(seconds=1)) is None


def diagnosis_inputs(cls="MACHINE", fault="UNKNOWN"):
    frame = history(False).assign(asset_id="A", regime=1, quality_any=0.0,
                                  vibration_accel_rms_g__mean=1.0,
                                  vibration_accel_rms_g__count=60.0,
                                  vibration_accel_rms_g__std=0.1, z_a=0.0, zs_a=0.0)
    assets = pd.DataFrame([dict(META, asset_id="A", channels_available="vibration_accel_rms_g")])
    alerts = pd.DataFrame([["A", (START + pd.Timedelta(hours=2)).isoformat(), cls, fault,
                            0.8, "official evidence", "verify"]], columns=COLUMNS)
    return alerts, frame, assets


def test_rediagnosis_changes_only_type_evidence_and_provenance():
    alerts, frame, assets = diagnosis_inputs()
    original = alerts.copy(deep=True)
    snapshots = pd.DataFrame([capture(samples=waveform(bearing=True))])
    result = rediagnose(alerts, frame, assets, snapshots)
    assert result.fault_type.tolist() == ["BEARING_WEAR"]
    assert result.decided_by.tolist() == ["rediagnose_spectrum"]
    assert "rediagnose_spectrum" in DECIDED_BY
    unchanged = ["asset_id", "alert_time_utc", "event_class", "confidence", "recommended_action"]
    assert_frame_equal(result[unchanged], original[unchanged], check_exact=True)
    assert_frame_equal(alerts, original, check_exact=True)
    assert "vibration_accel_rms_g" in recommend(result).recommended_action.iloc[0]


def test_other_assets_capture_is_ignored():
    alerts, frame, assets = diagnosis_inputs()
    snapshots = pd.DataFrame([capture(asset_id="B", samples=waveform(bearing=True))])
    assert_frame_equal(rediagnose(alerts, frame, assets, snapshots), rediagnose(alerts, frame, assets))


@pytest.mark.parametrize("cls,fault", [
    ("SENSOR", "SENSOR_DRIFT"), ("MACHINE", "SENSOR_STUCK"),
    ("SENSOR", "COMMUNICATION_LOSS"),
])
def test_sensor_or_protected_alert_is_untouched(cls, fault):
    alerts, frame, assets = diagnosis_inputs(cls, fault)
    snapshots = pd.DataFrame([capture(samples=waveform(bearing=True))])
    assert_frame_equal(rediagnose(alerts, frame, assets, snapshots), rediagnose(alerts, frame, assets))


def test_current_rediagnosis_to_sensor_precedes_spectra():
    alerts, frame, assets = diagnosis_inputs()
    frame["discharge_pressure_kpa__mean"] = 100.0
    frame["discharge_pressure_kpa__count"] = 60.0
    frame["discharge_pressure_kpa__std"] = 0.1
    frame["z_pd"], frame["zs_pd"] = 0.0, 0.0
    frame.loc[90:, "z_pd"] = 10.0
    assets.loc[0, "channels_available"] += "|discharge_pressure_kpa"
    # Two independent fresh witnesses confirm an isolated pressure fault.
    for channel in ("motor_current_a", "motor_power_kw"):
        assets.loc[0, "channels_available"] += "|" + channel
        frame[channel + "__mean"] = 100.0
        frame[channel + "__count"] = 60.0
        frame[channel + "__std"] = 0.1
    frame["z_i"], frame["zs_i"], frame["z_pw"], frame["zs_pw"] = 0.0, 0.0, 0.0, 0.0
    snapshots = pd.DataFrame([capture(samples=waveform(bearing=True))])
    result = rediagnose(alerts, frame, assets, snapshots)
    assert result.event_class.tolist() == ["SENSOR"]
    assert result.decided_by.tolist() == ["rediagnose_confirmed"]


def test_snapshot_loader_asset_filter_and_exact_until(tmp_path):
    rows = [capture(), capture(asset_id="B"), capture(START + pd.Timedelta(hours=2))]
    pd.DataFrame(rows).to_parquet(tmp_path / "vibration_snapshots.parquet", index=False)
    assets = pd.DataFrame({"asset_id": ["A"]})
    time = START + pd.Timedelta(hours=1)
    assert load_snapshots(tmp_path, assets, until=time).empty
    loaded = load_snapshots(tmp_path, assets, until=time + pd.Timedelta(seconds=1))
    assert loaded.asset_id.tolist() == ["A"]
    assert loaded.timestamp_utc.tolist() == [time]
    assert len(load_snapshots(tmp_path, assets)) == 2
    assert load_snapshots(tmp_path, assets.iloc[:0]).empty
    with pytest.raises(ValueError, match="timezone-aware"):
        load_snapshots(tmp_path, assets, until="2026-01-01")
