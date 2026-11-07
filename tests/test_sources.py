"""Synthetic source and merged-policy contracts; no challenge telemetry."""

import io

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
import pytest
from retrofit_sim.baselines import CH
from retrofit_sim.scoring import bursts, load_predictions

from retrofit_assistant.data import AVAILABILITY
from retrofit_assistant.output import COLUMNS, write_predictions
from retrofit_assistant.params import ALERT_SPACING_MIN, STUCK_MIN_UPDATES
from retrofit_assistant.policy import apply_guarantees
from retrofit_assistant.sources import (
    INTERNAL_COLUMNS, cavitation_candidates, merge_candidates, npsh_available_m,
    stuck_candidates, vapour_pressure_kpa,
)

START = pd.Timestamp("2026-01-01T00:00:00Z")


def fixture(values, key="pd", wireless=False):
    values = np.asarray(values, dtype=float)
    channel = CH[key]
    minutes = pd.DataFrame({
        "asset_id": "A", "window_start_utc": pd.date_range(START, periods=len(values), freq="min"),
        "steady": True, "operating_mode": "RUNNING", "quality_any": 0.0,
        channel + "__mean": values, channel + "__count": np.where(np.isfinite(values), 1 if wireless else 60, 0),
    })
    assets = pd.DataFrame({"asset_id": ["A"], "channels_available": [channel],
                           "wireless_update_s": [300 if wireless else np.nan],
                           "window_end_utc": [START + pd.Timedelta(days=7)]})
    return minutes, assets


def existing(offsets=(), source="official", fault="UNKNOWN"):
    return pd.DataFrame([
        ["A", (START + pd.Timedelta(minutes=offset)).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "SENSOR" if fault == "SENSOR_STUCK" else "MACHINE", fault, 0.8, f"e{offset}", "verify", source]
        for offset in offsets
    ], columns=INTERNAL_COLUMNS)


def detect(minutes, assets, prior=None, until=None):
    return stuck_candidates(minutes, assets, existing() if prior is None else prior, until=until)


def test_dense_stuck_counts_real_updates_and_exact_duration():
    minutes, assets = fixture([100] * (STUCK_MIN_UPDATES + 5))
    result = detect(minutes, assets)
    assert len(result) == 1
    alert = result.iloc[0]
    assert pd.Timestamp(alert.alert_time_utc) == START + pd.Timedelta(minutes=STUCK_MIN_UPDATES)
    assert (alert.event_class, alert.fault_type, alert.decided_by) == ("SENSOR", "SENSOR_STUCK", "source_stuck")
    assert "discharge_pressure_kpa=100" in alert.evidence
    assert f"{STUCK_MIN_UPDATES} real updates" in alert.evidence
    assert f"{STUCK_MIN_UPDATES - 1:.1f} min" in alert.evidence
    assert detect(minutes.iloc[:STUCK_MIN_UPDATES - 1], assets).empty


def test_wireless_300s_pauses_preserve_episode_without_counting_minutes():
    values = np.full(5 * (STUCK_MIN_UPDATES - 1) + 1, np.nan)
    values[::5] = 42.5
    minutes, assets = fixture(values, key="bt", wireless=True)
    assert detect(minutes.iloc[:-1], assets).empty
    result = detect(minutes, assets)
    assert len(result) == 1
    assert pd.Timestamp(result.iloc[0].alert_time_utc) == START + pd.Timedelta(minutes=len(values))
    assert f"{STUCK_MIN_UPDATES} real updates" in result.iloc[0].evidence
    assert f"{5 * (STUCK_MIN_UPDATES - 1):.1f} min" in result.iloc[0].evidence


def test_normal_half_degree_quantization_is_not_stuck():
    # Independent thermal staircase: a stable plateau shorter than persistence.
    values = np.repeat([42.0, 42.5, 43.0, 42.5, 42.0], 8)
    sparse = np.full(len(values) * 5, np.nan)
    sparse[::5] = values
    minutes, assets = fixture(sparse, key="bt", wireless=True)
    assert detect(minutes, assets).empty


@pytest.mark.parametrize("missing", ["nan", "zero_count"])
def test_missing_values_are_not_repetitions(missing):
    minutes, assets = fixture([100] * (STUCK_MIN_UPDATES * 2))
    if missing == "nan":
        minutes.loc[minutes.index % 2 == 1, "discharge_pressure_kpa__mean"] = np.nan
    else:
        minutes.loc[minutes.index % 2 == 1, "discharge_pressure_kpa__count"] = 0
    assert detect(minutes.iloc[:2 * (STUCK_MIN_UPDATES - 1)], assets).empty
    result = detect(minutes, assets)
    assert len(result) == 1
    assert pd.Timestamp(result.iloc[0].alert_time_utc) == START + pd.Timedelta(minutes=2 * STUCK_MIN_UPDATES - 1)


def test_stop_interrupts_persistence_and_restart_requires_new_updates():
    minutes, assets = fixture([100] * (2 * STUCK_MIN_UPDATES + 5))
    stop = STUCK_MIN_UPDATES - 2
    minutes.loc[stop:stop + 4, ["operating_mode", "steady"]] = ["STOPPED", False]
    result = detect(minutes, assets)
    assert len(result) == 1
    assert pd.Timestamp(result.iloc[0].alert_time_utc) == START + pd.Timedelta(minutes=stop + 5 + STUCK_MIN_UPDATES)


def test_stop_does_not_rearm_already_emitted_episode():
    minutes, assets = fixture([100] * (3 * STUCK_MIN_UPDATES))
    minutes.loc[STUCK_MIN_UPDATES:STUCK_MIN_UPDATES + 3, ["operating_mode", "steady"]] = ["STOPPED", False]
    assert len(detect(minutes, assets)) == 1


def test_only_a_different_valid_update_rearms_episode():
    minutes, assets = fixture([100] * STUCK_MIN_UPDATES + [101] * (STUCK_MIN_UPDATES + 30))
    result = detect(minutes, assets)
    assert len(result) == 2
    assert pd.to_datetime(result.alert_time_utc, utc=True).tolist() == [
        START + pd.Timedelta(minutes=n * STUCK_MIN_UPDATES) for n in (1, 2)
    ]


@pytest.mark.parametrize("flag", [1.0, 2.0, 4.0, 8.0])
def test_communication_saturation_or_bad_status_cannot_be_stuck(flag):
    minutes, assets = fixture([100] * (STUCK_MIN_UPDATES + 10))
    minutes["quality_any"] = flag
    assert detect(minutes, assets).empty


@pytest.mark.parametrize("value", [-20, 150])
def test_clamp_value_without_flag_is_not_stuck(value):
    minutes, assets = fixture([value] * (STUCK_MIN_UPDATES + 10), key="bt")
    assert detect(minutes, assets).empty


def test_only_running_and_steady_can_qualify():
    minutes, assets = fixture([100] * (STUCK_MIN_UPDATES + 10))
    minutes["steady"] = False
    assert detect(minutes, assets).empty
    minutes["steady"] = True
    minutes["operating_mode"] = "STARTING"
    assert detect(minutes, assets).empty


def test_absent_channel_disables_check():
    minutes, assets = fixture([100] * (STUCK_MIN_UPDATES + 10))
    assets["channels_available"] = "suction_pressure_kpa"
    assert detect(minutes, assets).empty


def test_prior_same_type_suppresses_source_within_episode():
    minutes, assets = fixture([100] * (STUCK_MIN_UPDATES + 10))
    assert detect(minutes, assets, existing((10,), fault="SENSOR_STUCK")).empty
    assert len(detect(minutes, assets, existing((10,), fault="SUCTION_STRAINER_CLOGGING"))) == 1
    # A later same-type decision must not affect an earlier source decision.
    assert len(detect(minutes, assets, existing((STUCK_MIN_UPDATES + 1,), fault="SENSOR_STUCK"))) == 1


def test_old_episode_does_not_suppress_new_one():
    minutes, assets = fixture([100] * STUCK_MIN_UPDATES + [101] * STUCK_MIN_UPDATES)
    result = detect(minutes, assets, existing((10,), fault="SENSOR_STUCK"))
    assert len(result) == 1
    assert pd.Timestamp(result.iloc[0].alert_time_utc) == START + pd.Timedelta(minutes=2 * STUCK_MIN_UPDATES)


def test_two_simultaneous_channels_emit_one_stuck_per_episode():
    minutes, assets = fixture([100] * STUCK_MIN_UPDATES)
    minutes["suction_pressure_kpa__mean"] = 50.0
    minutes["suction_pressure_kpa__count"] = 60.0
    assets["channels_available"] += "|suction_pressure_kpa"
    assert len(detect(minutes, assets)) == 1


def test_future_rows_and_future_official_alerts_do_not_change_prefix():
    minutes, assets = fixture([100] * (STUCK_MIN_UPDATES * 3))
    cut = START + pd.Timedelta(minutes=STUCK_MIN_UPDATES)
    complete = detect(minutes, assets)
    changed = minutes.copy()
    changed.loc[changed.window_start_utc + AVAILABILITY["features_1min.parquet"].latency > cut,
                ["discharge_pressure_kpa__mean", "operating_mode", "quality_any"]] = [-100, "STOPPED", 1.0]
    expected = complete.loc[pd.to_datetime(complete.alert_time_utc, utc=True) <= cut]
    assert_frame_equal(detect(changed, assets, until=cut), expected, check_exact=True)
    assert_frame_equal(detect(minutes, assets, existing((STUCK_MIN_UPDATES + 1,), fault="SENSOR_STUCK"), until=cut),
                       expected, check_exact=True)
    assert_frame_equal(detect(minutes, assets, until=cut - pd.Timedelta(seconds=1)), expected.iloc[:0], check_exact=True)


def test_merge_ties_are_official_stuck_cavitation_and_preserve_input():
    official = existing((10, 10)).assign(evidence=["first", "second"])
    original = official.copy(deep=True)
    stuck = existing((10,), source="source_stuck", fault="SENSOR_STUCK")
    cavitation = existing((10,), source="source_cavitation", fault="CAVITATION")
    result = merge_candidates(official, cavitation, stuck)
    assert result.decided_by.tolist() == ["official", "official", "source_stuck", "source_cavitation"]
    assert result.evidence.tolist()[:2] == ["first", "second"]
    assert_frame_equal(official, original, check_exact=True)
    assert list(merge_candidates(official.iloc[:0], stuck.iloc[:0]).columns) == INTERNAL_COLUMNS


def test_guarantees_apply_spacing_on_union_and_avoid_mixed_burst():
    official = existing((1,))
    stuck = existing((4,), source="source_stuck", fault="SENSOR_STUCK")
    minutes, assets = fixture([100] * 20)
    result = apply_guarantees(merge_candidates(official, stuck), minutes, assets)
    assert pd.to_datetime(result.alert_time_utc, utc=True).diff().iloc[1] == pd.Timedelta(minutes=ALERT_SPACING_MIN)
    collapsed = bursts(load_predictions(result))
    assert len(collapsed) == 2
    assert "AMBIGUOUS" not in collapsed.fault_type.tolist()


def test_new_source_alert_on_stopped_minute_is_dropped():
    minutes, assets = fixture([100] * 20)
    minutes.loc[3, "operating_mode"] = "STOPPED"
    candidates = existing((4,), source="source_stuck", fault="SENSOR_STUCK")
    assert apply_guarantees(candidates, minutes, assets).empty


def test_provenance_removed_by_guarantees_and_csv_writer(tmp_path):
    minutes, assets = fixture([100] * STUCK_MIN_UPDATES)
    result = apply_guarantees(detect(minutes, assets), minutes, assets)
    assert list(result.columns) == COLUMNS
    path = tmp_path / "predictions.csv"
    write_predictions(result, path)
    assert pd.read_csv(io.StringIO(path.read_text())).columns.tolist() == COLUMNS
    assert "decided_by" not in path.read_text()


def cavitation_fixture(pressure):
    minutes, assets = fixture(pressure, key="ps")
    minutes["fluid_temp_c__mean"] = 20.0
    minutes["fluid_temp_c__count"] = 60.0
    assets["channels_available"] += "|fluid_temp_c"
    assets["instrumentation_tier"] = "T1_RETROFIT"
    assets["npsh3_at_bep_m"] = 4.0
    assets["motor_rated_rpm"] = 1800.0
    assets["pump_rated_flow_m3_h"] = 100.0
    return minutes, assets


def cavitation_detect(minutes, assets, prior=None, until=None):
    return cavitation_candidates(minutes, assets, existing() if prior is None else prior, until=until)


@pytest.mark.parametrize("temperature,pressure", [(20, 2.339), (40, 7.385), (60, 19.946), (80, 47.415)])
def test_vapour_pressure_against_water_saturation_table(temperature, pressure):
    # Standard saturated-water table values (kPa), independent of Antoine coefficients.
    # NIST Stull broad-range fit is an approximation; engineering tolerance 3%.
    assert vapour_pressure_kpa(temperature) == pytest.approx(pressure, rel=0.03)


@pytest.mark.parametrize("temperature", [-30, 120, np.nan])
def test_vapour_pressure_does_not_extrapolate(temperature):
    assert np.isnan(vapour_pressure_kpa(temperature))


def test_npsh_uses_gauge_plus_atmosphere_and_velocity_only_with_flow():
    static = npsh_available_m(-20.0, 20.0)
    assert static == pytest.approx((101.325 - 20 - 2.339) / 9.80665, abs=0.003)
    assert npsh_available_m(-20.0, 20.0, None, 100) == static
    assert npsh_available_m(-20.0, 20.0, 100, None) == static
    assert npsh_available_m(-20.0, 20.0, 100, 100) - static == pytest.approx(2.5 ** 2 / (2 * 9.80665))


def test_cavitation_triggers_at_five_completed_minutes_exactly():
    minutes, assets = cavitation_fixture([-75] * 20)
    assert cavitation_detect(minutes.iloc[:4], assets).empty
    result = cavitation_detect(minutes, assets)
    assert len(result) == 1
    row = result.iloc[0]
    assert pd.Timestamp(row.alert_time_utc) == START + pd.Timedelta(minutes=5)
    assert (row.event_class, row.fault_type, row.decided_by) == ("MACHINE", "CAVITATION", "source_cavitation")
    assert "low margin for 5.0 min" in row.evidence
    assert "speed unavailable" in row.evidence and "flow unavailable" in row.evidence
    assert "required-NPSH dependence on flow unknown" in row.evidence
    assert "one physical context, n = 1 pump" in row.evidence
    assert "this matches the simulator's model; on real equipment the margin needs site verification" in row.evidence


@pytest.mark.parametrize("missing", ["installed", "mean", "count"])
def test_cavitation_missing_suction_channel_disables_rule(missing):
    minutes, assets = cavitation_fixture([-75] * 10)
    if missing == "installed":
        assets["channels_available"] = "fluid_temp_c"
    else:
        minutes = minutes.drop(columns=["suction_pressure_kpa__" + missing])
    assert cavitation_detect(minutes, assets).empty


def test_cavitation_no_t0_alert_even_with_inconsistent_extra_columns():
    minutes, assets = cavitation_fixture([-75] * 10)
    assets["instrumentation_tier"] = "T0_LEGACY"
    assert cavitation_detect(minutes, assets).empty


def test_cavitation_recovers_and_rearms_for_distinct_episodes():
    minutes, assets = cavitation_fixture([-75] * 5 + [0] + [-75] * 10)
    result = cavitation_detect(minutes, assets)
    assert pd.to_datetime(result.alert_time_utc, utc=True).tolist() == [
        START + pd.Timedelta(minutes=5), START + pd.Timedelta(minutes=11),
    ]


def test_clogging_cannot_suppress_cavitation_but_prior_same_episode_can():
    minutes, assets = cavitation_fixture([-75] * 10)
    assert len(cavitation_detect(minutes, assets, existing((3,), fault="SUCTION_STRAINER_CLOGGING"))) == 1
    assert cavitation_detect(minutes, assets, existing((3,), fault="CAVITATION")).empty
    assert len(cavitation_detect(minutes, assets, existing((6,), fault="CAVITATION"))) == 1


@pytest.mark.parametrize("interruption", ["stop", "quality", "missing", "gap"])
def test_cavitation_requires_continuous_valid_running_minutes(interruption):
    minutes, assets = cavitation_fixture([-75] * 12)
    if interruption == "stop":
        minutes.loc[3, ["operating_mode", "steady"]] = ["STOPPED", False]
    elif interruption == "quality":
        minutes.loc[3, "quality_any"] = 1.0
    elif interruption == "missing":
        minutes.loc[3, "fluid_temp_c__mean"] = np.nan
    else:
        minutes = minutes.drop(index=3)
    result = cavitation_detect(minutes, assets)
    assert len(result) == 1
    assert pd.Timestamp(result.iloc[0].alert_time_utc) == START + pd.Timedelta(minutes=9)


def test_cavitation_gap_or_stop_does_not_rearm_without_margin_recovery():
    minutes, assets = cavitation_fixture([-75] * 20)
    minutes.loc[7, ["operating_mode", "steady"]] = ["STOPPED", False]
    minutes.loc[12, "fluid_temp_c__mean"] = np.nan
    assert len(cavitation_detect(minutes, assets)) == 1


def test_cavitation_speed_squared_scaling_uses_measured_speed():
    minutes, assets = cavitation_fixture([-45] * 5)
    assert cavitation_detect(minutes, assets).empty
    minutes["motor_speed_rpm__mean"] = 2400.0
    minutes["motor_speed_rpm__count"] = 60.0
    assets["channels_available"] += "|motor_speed_rpm"
    result = cavitation_detect(minutes, assets)
    assert len(result) == 1
    assert "speed=2400 rpm, speed-squared scaled" in result.iloc[0].evidence


@pytest.mark.parametrize("fresh", [True, False])
def test_cavitation_acceleration_is_optional_fresh_causal_confirmation(fresh):
    minutes, assets = cavitation_fixture([0] * 15 + [-75] * 5)
    assets["channels_available"] += "|vibration_accel_rms_g"
    assets["wireless_update_s"] = 300
    minutes["vibration_accel_rms_g__mean"] = np.nan
    minutes["vibration_accel_rms_g__count"] = 0.0
    minutes.loc[[4, 9, 14], ["vibration_accel_rms_g__mean", "vibration_accel_rms_g__count"]] = [0.1, 1.0]
    if fresh:
        minutes.loc[19, ["vibration_accel_rms_g__mean", "vibration_accel_rms_g__count"]] = [0.3, 1.0]
    result = cavitation_detect(minutes, assets)
    assert len(result) == 1
    assert pd.Timestamp(result.iloc[0].alert_time_utc) == START + pd.Timedelta(minutes=20)
    assert ("(increasing)" if fresh else "no fresh update; emitted without waiting") in result.iloc[0].evidence


def test_cavitation_future_rows_and_future_official_decisions_cannot_change_prefix():
    minutes, assets = cavitation_fixture([-75] * 15)
    cut = START + pd.Timedelta(minutes=5)
    complete = cavitation_detect(minutes, assets)
    changed = minutes.copy()
    changed.loc[changed.window_start_utc + AVAILABILITY["features_1min.parquet"].latency > cut,
                ["suction_pressure_kpa__mean", "fluid_temp_c__mean", "quality_any"]] = [500, 120, 2.0]
    changed_full = cavitation_detect(changed, assets)
    assert_frame_equal(changed_full.loc[pd.to_datetime(changed_full.alert_time_utc, utc=True) <= cut],
                       complete, check_exact=True)
    assert_frame_equal(cavitation_detect(changed, assets, until=cut), complete, check_exact=True)
    assert_frame_equal(cavitation_detect(minutes, assets, existing((6,), fault="CAVITATION"), until=cut),
                       complete, check_exact=True)
    assert_frame_equal(cavitation_detect(minutes, assets, until=cut - pd.Timedelta(seconds=1)),
                       complete.iloc[:0], check_exact=True)


def test_cavitation_provenance_is_dropped_before_csv(tmp_path):
    minutes, assets = cavitation_fixture([-75] * 5)
    result = apply_guarantees(cavitation_detect(minutes, assets), minutes, assets)
    assert list(result.columns) == COLUMNS
    destination = tmp_path / "cavitation.csv"
    write_predictions(result, destination)
    assert pd.read_csv(destination).columns.tolist() == COLUMNS
    assert "decided_by" not in destination.read_text()
