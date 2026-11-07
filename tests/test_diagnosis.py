"""Physical synthetic minutes, independent of challenge event labels."""

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from retrofit_sim.baselines import CH

from retrofit_assistant.diagnosis import rediagnose
from retrofit_assistant.output import COLUMNS
from retrofit_assistant.consistency import channel_snapshot, consistency_state, deviation_start
from retrofit_assistant import params


def fixture(shape="ramp", key="pd", references=("i",), cls="SENSOR", fault="SENSOR_CALIBRATION_SHIFT", wireless=False):
    times = pd.date_range("2026-01-01", periods=360, freq="min", tz="UTC")
    frame = pd.DataFrame({"asset_id": "A", "window_start_utc": times, "steady": True, "regime": 1,
                          "quality_any": 0.0})
    installed = tuple(c for c in CH if c == key or c in references)
    for c in installed:
        frame[CH[c] + "__mean"] = 100.0
        frame[CH[c] + "__count"] = 60.0
        frame[CH[c] + "__std"] = 0.1
        frame["z_" + c] = 0.0
        frame["zs_" + c] = 0.0
    mean = CH[key] + "__mean"
    if shape == "ramp":
        frame.loc[30:, mean] += np.arange(330) / 10
    elif shape == "step":
        frame.loc[240:, mean] += 30
    elif shape == "noise":
        frame.loc[350:, CH[key] + "__std"] = 10
        frame.loc[350:, "zs_" + key] = 30
    frame["z_" + key] = 0.0
    if shape == "ramp":
        frame.loc[30:, "z_" + key] = 3 + np.arange(330) / 30
    elif shape == "step":
        frame.loc[240:, "z_" + key] = 9.0
    elif shape == "ambiguous":
        frame.loc[240:, "z_" + key] = 9.0
    if wireless:
        for c in installed:
            if c not in ("v", "a", "c", "bt"):
                continue
            frame.loc[frame.index % 5 != 0, [CH[c] + "__mean", CH[c] + "__std", "z_" + c]] = np.nan
            frame.loc[frame.index % 5 != 0, CH[c] + "__count"] = 0
            frame.loc[frame.index % 5 == 0, CH[c] + "__count"] = 1
    assets = pd.DataFrame({"asset_id": ["A"], "channels_available": ["|".join(CH[c] for c in installed)],
                           "wireless_update_s": [300 if wireless else np.nan], "instrumentation_tier": ["T1_RETROFIT" if wireless else "T0_LEGACY"]})
    candidates = pd.DataFrame([["A", (times[-1] + pd.Timedelta(minutes=1)).isoformat(), cls, fault,
                                0.8, "official", "verify"]], columns=COLUMNS)
    return candidates, frame, assets


@pytest.mark.parametrize("shape,fault", [("step", "SENSOR_CALIBRATION_SHIFT"), ("ramp", "SENSOR_DRIFT"),
                                         ("noise", "SENSOR_NOISE_SPIKES"), ("ambiguous", "UNKNOWN")])
def test_confirmed_physical_shapes(shape, fault):
    candidates, frame, assets = fixture(shape, cls="MACHINE", fault="UNKNOWN")
    result = rediagnose(candidates, frame, assets)
    assert result.iloc[0].event_class == "SENSOR"
    assert result.iloc[0].fault_type == fault
    assert result.attrs["diagnosis_states"][0]["state"] == ("noise" if shape == "noise" else "confirmed")
    assert CH["pd"] in result.iloc[0].evidence


def test_single_process_transmitter_drift_stays_sensor():
    args = fixture()
    result = rediagnose(*args)
    assert tuple(result.iloc[0][["event_class", "fault_type"]]) == ("SENSOR", "SENSOR_DRIFT")


def test_ambiguous_confirmed_shape_preserves_official_sensor_type():
    candidates, frame, assets = fixture("ambiguous")
    original = candidates.copy(deep=True)
    result = rediagnose(candidates, frame, assets)
    assert_frame_equal(result[COLUMNS], original, check_exact=True)
    assert result.decided_by.tolist() == ["rediagnose_confirmed"]
    assert_frame_equal(candidates, original, check_exact=True)


def test_shape_block_fits_b1_persistence():
    assert params.SHAPE_BLOCK_MIN == 10
    assert params.SHAPE_BLOCK_MIN <= params.B1_PERSIST


@pytest.mark.parametrize("cls,fault,expected", [("SENSOR", "SENSOR_DRIFT", ("MACHINE", "UNKNOWN")),
                                              ("MACHINE", "IMPELLER_WEAR", ("MACHINE", "IMPELLER_WEAR"))])
def test_following_references_refute_sensor(cls, fault, expected):
    candidates, frame, assets = fixture(cls=cls, fault=fault)
    frame["z_i"] = 5.0
    result = rediagnose(candidates, frame, assets)
    assert tuple(result.iloc[0][["event_class", "fault_type"]]) == expected
    assert result.attrs["diagnosis_states"][0]["state"] == "refuted"


@pytest.mark.parametrize("missing", ["absent", "nan", "stale"])
def test_unverifiable_process_transmitter_keeps_official(missing):
    candidates, frame, assets = fixture(references=() if missing == "absent" else ("i",))
    if missing == "nan":
        frame["z_i"] = np.nan
    elif missing == "stale":
        frame.loc[350:, CH["i"] + "__mean"] = np.nan
    original = candidates.copy(deep=True)
    result = rediagnose(candidates, frame, assets)
    assert_frame_equal(result[COLUMNS], original, check_exact=True)
    assert result.decided_by.tolist() == ["official"]
    assert_frame_equal(candidates, original, check_exact=True)
    assert result.attrs["diagnosis_states"][0]["state"] == "unverifiable"


@pytest.mark.parametrize("key", ["c", "a", "v"])
def test_unverifiable_accelerometer_is_machine(key):
    result = rediagnose(*fixture(key=key, references=()))
    assert tuple(result.iloc[0][["event_class", "fault_type"]]) == ("MACHINE", "UNKNOWN")
    assert result.attrs["diagnosis_states"][0]["accelerometer_exception"]


@pytest.mark.parametrize("fault", ["COMMUNICATION_LOSS", "SENSOR_STUCK"])
def test_protected_official_diagnoses(fault):
    candidates, frame, assets = fixture(fault=fault)
    original = candidates.copy(deep=True)
    result = rediagnose(candidates, frame, assets)
    assert_frame_equal(result[COLUMNS], original, check_exact=True)
    assert result.decided_by.tolist() == ["official_protected"]
    assert_frame_equal(candidates, original, check_exact=True)


def test_rows_order_times_and_confidence_unchanged():
    candidates, frame, assets = fixture()
    candidates = pd.concat([candidates, candidates.assign(confidence=0.42)], ignore_index=True)
    candidates.index = [9, 4]
    original = candidates.copy(deep=True)
    result = rediagnose(candidates, frame, assets)
    assert list(result.columns) == [*candidates.columns, "decided_by"]
    expected = original.copy(deep=True)
    expected["fault_type"] = "SENSOR_DRIFT"
    expected["evidence"] = ("discharge_pressure_kpa=132.9; fresh coupled channels remain still; "
                            "physical ramp +6/h over 5.33 h; concordant halves")
    expected["recommended_action"] = "Verify discharge_pressure_kpa against an independent reference; review instrument history."
    assert_frame_equal(result[COLUMNS], expected, check_exact=True)
    assert result.decided_by.tolist() == ["rediagnose_confirmed", "rediagnose_confirmed"]
    assert_frame_equal(candidates, original, check_exact=True)
    assert_frame_equal(result[["asset_id", "alert_time_utc", "confidence"]], candidates[["asset_id", "alert_time_utc", "confidence"]])
    empty = candidates.iloc[:0].copy(deep=True)
    empty_original = empty.copy(deep=True)
    empty_result = rediagnose(empty, frame, assets)
    assert_frame_equal(empty_result[COLUMNS], empty_original, check_exact=True)
    assert empty_result.decided_by.tolist() == []
    assert_frame_equal(empty, empty_original, check_exact=True)


def test_availability_future_and_permutations():
    candidates, frame, assets = fixture()
    cut = pd.Timestamp(candidates.iloc[0].alert_time_utc)
    future = frame.iloc[-20:].copy()
    future["window_start_utc"] = pd.date_range(cut, periods=len(future), freq="min")
    future[CH["pd"] + "__mean"] = -1e9
    future["z_i"] = 100
    extended = pd.concat([frame, future], ignore_index=True)
    expected = rediagnose(candidates, frame, assets)
    assert_frame_equal(rediagnose(candidates, extended, assets), expected)
    assert_frame_equal(rediagnose(candidates, extended.sample(frac=1, random_state=7).iloc[:, ::-1], assets), expected)


@pytest.mark.parametrize("shape,fault", [("step", "SENSOR_CALIBRATION_SHIFT"), ("ramp", "SENSOR_DRIFT")])
def test_wireless_real_updates(shape, fault):
    result = rediagnose(*fixture(shape, key="bt", references=("tf",), wireless=True))
    assert result.iloc[0].fault_type == fault
    assert result.attrs["diagnosis_states"][0]["state"] == "confirmed"


def test_wireless_missing_update_is_not_still_and_std_is_not_noise():
    candidates, frame, assets = fixture("noise", key="bt", references=("tf",), wireless=True)
    result = rediagnose(candidates, frame, assets)
    assert result.iloc[0].fault_type != "SENSOR_NOISE_SPIKES"
    frame.loc[350:, CH["tf"] + "__mean"] = np.nan
    assert rediagnose(candidates, frame, assets).attrs["diagnosis_states"][0]["state"] == "unverifiable"


def test_missing_one_installed_reference_does_not_establish_stillness():
    candidates, frame, assets = fixture(references=("i", "q"))
    frame["z_q"] = np.nan
    assert rediagnose(candidates, frame, assets).attrs["diagnosis_states"][0]["state"] == "unverifiable"


@pytest.mark.parametrize("wireless,key,onset", [(False, "pd", 30), (True, "bt", 30)])
def test_episode_onset_is_causal_and_ignores_expected_wireless_pauses(wireless, key, onset):
    candidates, frame, assets = fixture("ramp", key=key, references=("tf",), wireless=wireless)
    cut = frame.window_start_utc.iloc[200] + pd.Timedelta(minutes=1)
    metadata = assets.iloc[0]
    expected = frame.window_start_utc.iloc[onset]
    assert deviation_start(frame, key, metadata, cut) == expected
    changed = frame.copy()
    changed.loc[changed.window_start_utc + pd.Timedelta(minutes=1) > cut, "z_" + key] = 0
    assert deviation_start(changed, key, metadata, cut) == expected
    assert deviation_start(frame.iloc[:201], key, metadata, cut) == expected


def test_onset_is_current_episode_not_first_historical_deviation():
    candidates, frame, assets = fixture("step")
    frame.loc[50:70, "z_pd"] = 8
    cut = pd.Timestamp(candidates.iloc[0].alert_time_utc)
    assert deviation_start(frame, "pd", assets.iloc[0], cut) == frame.window_start_utc.iloc[240]


def test_step_remains_visible_beyond_six_hours():
    candidates, frame, assets = fixture("step", cls="MACHINE", fault="UNKNOWN")
    extra = pd.concat([frame.iloc[[-1]]] * 480, ignore_index=True)
    extra.window_start_utc = pd.date_range(frame.window_start_utc.iloc[-1] + pd.Timedelta(minutes=1), periods=480, freq="min")
    extended = pd.concat([frame, extra], ignore_index=True)
    candidates.alert_time_utc = (extended.window_start_utc.iloc[-1] + pd.Timedelta(minutes=1)).isoformat()
    assert rediagnose(candidates, extended, assets).iloc[0].fault_type == "SENSOR_CALIBRATION_SHIFT"


@pytest.mark.parametrize("interruption", ["stop", "missing"])
def test_no_physical_shape_across_interrupted_before_after(interruption):
    candidates, frame, assets = fixture("step", cls="MACHINE", fault="UNKNOWN")
    if interruption == "stop":
        frame.loc[235:238, "steady"] = False
    else:
        frame.loc[235:238, CH["pd"] + "__mean"] = np.nan
    result = rediagnose(candidates, frame, assets)
    assert tuple(result.iloc[0][["event_class", "fault_type"]]) == ("SENSOR", "UNKNOWN")


@pytest.mark.parametrize("settled", [False, True])
def test_thermal_deviation_only_counts_after_model_settling(settled):
    candidates, frame, assets = fixture("step", key="wt", references=("i",), fault="SENSOR_DRIFT")
    frame["steady"] = False
    frame.loc[frame.index[-(params.THERMAL_SETTLE_MIN if settled else 15):], "steady"] = True
    original = candidates.copy(deep=True)
    result = rediagnose(candidates, frame, assets)
    assert result.attrs["diagnosis_states"][0]["state"] == ("confirmed" if settled else "unverifiable")
    if not settled:
        assert_frame_equal(result[COLUMNS], original, check_exact=True)
        assert result.decided_by.tolist() == ["official"]
        assert_frame_equal(candidates, original, check_exact=True)


def test_recent_thermal_restart_leaves_crest_exception():
    candidates, frame, assets = fixture("step", key="wt", references=("c",))
    frame.loc[240:, "z_c"] = 8
    frame.loc[240:, "z_wt"] = -13
    frame["steady"] = False
    frame.loc[345:, "steady"] = True
    result = rediagnose(candidates, frame, assets)
    assert tuple(result.iloc[0][["event_class", "fault_type"]]) == ("MACHINE", "UNKNOWN")
    assert result.attrs["diagnosis_states"][0]["accelerometer_exception"]


def test_variance_on_coupled_channel_refutes_isolated_noise():
    candidates, frame, assets = fixture("noise")
    frame["zs_i"] = 9.0
    assert rediagnose(candidates, frame, assets).iloc[0].fault_type != "SENSOR_NOISE_SPIKES"


def test_single_minute_variance_spike_does_not_become_persistent_noise():
    candidates, frame, assets = fixture("noise")
    frame.loc[:358, "zs_pd"] = 0
    assert rediagnose(candidates, frame, assets).iloc[0].fault_type != "SENSOR_NOISE_SPIKES"


@pytest.mark.parametrize("fault", ["COMMUNICATION_LOSS", "SENSOR_STUCK"])
def test_protected_diagnoses_precede_noise_check(fault):
    candidates, frame, assets = fixture("noise", fault=fault)
    original = candidates.copy(deep=True)
    result = rediagnose(candidates, frame, assets)
    assert_frame_equal(result[COLUMNS], original, check_exact=True)
    assert result.decided_by.tolist() == ["official_protected"]
    assert_frame_equal(candidates, original, check_exact=True)


def test_float_quality_comm_loss_bit_is_not_a_valid_reference():
    candidates, frame, assets = fixture("step")
    frame["quality_any"] = 1.0
    original = candidates.copy(deep=True)
    result = rediagnose(candidates, frame, assets)
    assert_frame_equal(result[COLUMNS], original, check_exact=True)
    assert result.decided_by.tolist() == ["official"]
    assert_frame_equal(candidates, original, check_exact=True)
    assert result.attrs["diagnosis_states"][0]["state"] == "unverifiable"


@pytest.mark.parametrize("q_z,expected", [(12, "q"), (9, "pd")])
def test_channel_priority_uses_severity_with_ch_tie_breaker(q_z, expected):
    candidates, frame, assets = fixture("step", references=("q",))
    frame["z_q"] = q_z
    time = pd.Timestamp(candidates.iloc[0].alert_time_utc)
    snapshot = channel_snapshot(frame, assets.iloc[0], time)
    state, key, deviating = consistency_state(snapshot, assets.iloc[0].channels_available.split("|"), 360)
    assert state == "refuted"
    assert key == expected


def test_noise_recent_medians_survive_a_dirty_last_minute():
    candidates, frame, assets = fixture("noise")
    frame.loc[359, ["z_pd", "zs_pd", "zs_i"]] = [3, 0, 9]
    result = rediagnose(candidates, frame, assets)
    assert result.iloc[0].fault_type == "SENSOR_NOISE_SPIKES"
    assert result.attrs["diagnosis_states"][0]["state"] == "noise"


def test_noise_rejected_when_coupled_recent_median_is_high():
    candidates, frame, assets = fixture("noise")
    frame.loc[350:355, "zs_i"] = 9
    assert rediagnose(candidates, frame, assets).iloc[0].fault_type != "SENSOR_NOISE_SPIKES"


def test_noise_requires_three_real_recent_observations():
    candidates, frame, assets = fixture("noise")
    frame.loc[350:357, CH["pd"] + "__mean"] = np.nan
    frame.loc[350:357, CH["pd"] + "__count"] = 0
    assert rediagnose(candidates, frame, assets).iloc[0].fault_type != "SENSOR_NOISE_SPIKES"


def test_controlled_flow_drift_with_persistent_speed_compensation_is_sensor():
    candidates, frame, assets = fixture("ramp", key="q", references=("i", "n"))
    frame.loc[30:, "z_n"] = -9
    frame.loc[30:, CH["n"] + "__mean"] -= np.arange(330) / 20
    result = rediagnose(candidates, frame, assets)
    assert tuple(result.iloc[0][["event_class", "fault_type"]]) == ("SENSOR", "SENSOR_DRIFT")
    assert result.attrs["diagnosis_states"][0]["state"] == "confirmed"
    assert "motor_speed_rpm=" in result.iloc[0].evidence
    assert "context only" in result.iloc[0].evidence
    frame["z_n"] = 0
    still_actuator = rediagnose(candidates, frame, assets)
    assert still_actuator.attrs["diagnosis_states"] == result.attrs["diagnosis_states"]
    assert tuple(still_actuator.iloc[0][["event_class", "fault_type"]]) == ("SENSOR", "SENSOR_DRIFT")


@pytest.mark.parametrize("shape", ["step", "noise"])
def test_actuator_is_not_sufficient_as_an_independent_witness(shape):
    candidates, frame, assets = fixture(shape, key="q", references=("n", "vp"))
    frame["z_n"] = 5
    frame["z_vp"] = -5
    result = rediagnose(candidates, frame, assets)
    assert result.iloc[0].fault_type == candidates.iloc[0].fault_type
    assert result.attrs["diagnosis_states"][0]["state"] == "unverifiable"
    assert "motor_speed_rpm=" in result.iloc[0].evidence
    assert "valve_position_pct=" in result.iloc[0].evidence


def test_noise_ignores_actuator_variance_as_an_independent_witness():
    candidates, frame, assets = fixture("noise", key="q", references=("i", "n", "vp"))
    frame["zs_n"] = 10
    frame["zs_vp"] = 10
    result = rediagnose(candidates, frame, assets)
    assert result.iloc[0].fault_type == "SENSOR_NOISE_SPIKES"
    assert result.attrs["diagnosis_states"][0]["state"] == "noise"


@pytest.mark.parametrize("scenario,expected", [
    ("confirmed", "rediagnose_confirmed"), ("noise", "rediagnose_noise"),
    ("refuted", "rediagnose_refuted"), ("machine_refuted", "official"),
    ("accelerometer", "rediagnose_accelerometer"), ("unverifiable", "official"),
    ("protected", "official_protected"),
])
def test_decided_by_contract_without_input_mutation(scenario, expected):
    if scenario == "accelerometer":
        candidates, frame, assets = fixture(key="c", references=())
    elif scenario == "unverifiable":
        candidates, frame, assets = fixture(references=())
    else:
        candidates, frame, assets = fixture(
            "noise" if scenario == "noise" else "step",
            cls="MACHINE" if scenario == "machine_refuted" else "SENSOR",
            fault="SENSOR_STUCK" if scenario == "protected" else "SENSOR_DRIFT",
        )
        if scenario in ("refuted", "machine_refuted"):
            frame["z_i"] = 5.0
    original = candidates.copy(deep=True)
    result = rediagnose(candidates, frame, assets)
    assert list(result.columns) == [*COLUMNS, "decided_by"]
    assert result.decided_by.tolist() == [expected]
    assert expected in params.DECIDED_BY
    assert_frame_equal(candidates, original, check_exact=True)
    assert "decided_by" not in result.attrs
