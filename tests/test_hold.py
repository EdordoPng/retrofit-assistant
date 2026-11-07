"""Restart hold boundaries, channel persistence and unchanged diagnostic payloads."""

import csv

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from retrofit_sim.baselines import CH

from retrofit_assistant import pipeline
from retrofit_assistant.confidence import assign_confidence
from retrofit_assistant.hold import hold_after_restart, sustained_channels
from retrofit_assistant.output import COLUMNS, write_predictions
from retrofit_assistant.params import B1_K, THERMAL_SETTLE_MIN
from retrofit_assistant.policy import apply_guarantees
from retrofit_assistant.recommendations import recommend

START = pd.Timestamp("2026-01-01T00:00:00Z")
RESTART = START + pd.Timedelta(minutes=1)
DUE = RESTART + pd.Timedelta(minutes=THERMAL_SETTLE_MIN)


def minutes(channels=("wt",), end=130):
    frame = pd.DataFrame({
        "asset_id": "A",
        "window_start_utc": pd.date_range(START, periods=end, freq="min"),
        "operating_mode": ["STOPPED"] + ["RUNNING"] * (end - 1),
    })
    for key in CH:
        frame["z_" + key] = 0.0
    for key in channels:
        frame.loc[1:, "z_" + key] = B1_K + 1
    return frame


def candidate(offset=16, rule="official"):
    return pd.DataFrame([{
        "asset_id": "A", "alert_time_utc": (START + pd.Timedelta(minutes=offset)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event_class": "MACHINE", "fault_type": "BEARING_WEAR", "confidence": .42,
        # Deliberately misleading text: channel selection must use z-scores.
        "evidence": "discharge_pressure_kpa deviates", "recommended_action": "original inspection",
        "decided_by": rule,
    }])


@pytest.mark.parametrize("channels", [("wt",), ("bt",), ("c",), ("wt", "bt", "c")])
def test_sustained_held_channels_emit_at_settling_time(channels):
    alerts, scored = candidate(), minutes(channels)
    before_alerts, before_scored = alerts.copy(deep=True), scored.copy(deep=True)
    result = hold_after_restart(alerts, scored)
    assert len(result) == 1
    assert pd.Timestamp(result.iloc[0].alert_time_utc) == DUE
    assert result.iloc[0].held_from_utc == alerts.iloc[0].alert_time_utc
    payload = [column for column in alerts if column != "alert_time_utc"]
    assert_frame_equal(result[payload], alerts[payload], check_exact=True)
    assert_frame_equal(alerts, before_alerts, check_exact=True)
    assert_frame_equal(scored, before_scored, check_exact=True)


def test_thermal_and_pressure_sustained_is_not_held():
    alerts = candidate()
    result = hold_after_restart(alerts, minutes(("wt", "pd")))
    assert_frame_equal(result[alerts.columns], alerts, check_exact=True)
    assert result.held_from_utc.isna().all()


@pytest.mark.parametrize("mode", ["STOPPED", "LOCKED_OUT"])
@pytest.mark.parametrize("offset", [40, THERMAL_SETTLE_MIN])
def test_stop_during_wait_clears_held_candidate(mode, offset):
    scored = minutes()
    scored.loc[offset, "operating_mode"] = mode
    assert hold_after_restart(candidate(), scored).empty


@pytest.mark.parametrize("end", [16, THERMAL_SETTLE_MIN])
def test_truncated_before_due_cannot_emit(end):
    assert hold_after_restart(candidate(), minutes(end=end)).empty


def test_due_minute_must_exist_even_when_later_minutes_exist():
    scored = minutes().drop(index=THERMAL_SETTLE_MIN)
    assert hold_after_restart(candidate(), scored).empty


@pytest.mark.parametrize("value", [0.0, B1_K, -B1_K, float("nan")])
def test_failed_recheck_drops_candidate_even_if_unrelated_channel_deviates(value):
    scored = minutes()
    scored.loc[THERMAL_SETTLE_MIN, "z_wt"] = value
    scored.loc[THERMAL_SETTLE_MIN, "z_pd"] = B1_K + 2
    assert hold_after_restart(candidate(), scored).empty


def test_recheck_needs_only_one_of_the_original_sustained_channels():
    scored = minutes(("wt", "bt"))
    scored.loc[THERMAL_SETTLE_MIN, "z_wt"] = 0
    scored.loc[THERMAL_SETTLE_MIN, "z_bt"] = -B1_K - 1
    result = hold_after_restart(candidate(), scored)
    assert len(result) == 1
    assert pd.Timestamp(result.iloc[0].alert_time_utc) == DUE


def test_fewer_than_fifteen_available_minutes_is_not_held():
    alerts = candidate(offset=14)
    result = hold_after_restart(alerts, minutes())
    assert_frame_equal(result[alerts.columns], alerts, check_exact=True)
    assert result.held_from_utc.isna().all()


@pytest.mark.parametrize("rule", ["source_stuck", "source_cavitation"])
def test_dedicated_source_is_unchanged_even_on_truncated_run(rule):
    alerts = candidate(rule=rule)
    result = hold_after_restart(alerts, minutes(end=16))
    assert_frame_equal(result[alerts.columns], alerts, check_exact=True)
    assert result.held_from_utc.isna().all()


def test_new_restart_uses_new_settling_deadline_and_discards_old_candidate():
    scored = minutes(end=180)
    scored.loc[40, "operating_mode"] = "LOCKED_OUT"
    alerts = pd.concat([candidate(), candidate(offset=60)], ignore_index=True)
    result = hold_after_restart(alerts, scored)
    assert len(result) == 1
    assert result.iloc[0].held_from_utc == alerts.iloc[1].alert_time_utc
    assert pd.Timestamp(result.iloc[0].alert_time_utc) == START + pd.Timedelta(minutes=41 + THERMAL_SETTLE_MIN)


def test_missing_minute_neither_stops_wait_nor_restarts_running_pump():
    scored = minutes().drop(index=[8, 40])
    result = hold_after_restart(candidate(offset=20), scored)
    assert pd.Timestamp(result.iloc[0].alert_time_utc) == DUE
    alerts = candidate(offset=125)
    result = hold_after_restart(alerts, scored)
    assert_frame_equal(result[alerts.columns], alerts, check_exact=True)
    assert result.held_from_utc.isna().all()


@pytest.mark.parametrize("offset", [121, 122])
def test_candidate_at_or_after_deadline_is_not_held(offset):
    alerts = candidate(offset=offset)
    result = hold_after_restart(alerts, minutes())
    assert_frame_equal(result[alerts.columns], alerts, check_exact=True)
    assert result.held_from_utc.isna().all()


def test_without_explicit_stop_there_is_no_restart():
    scored = minutes()
    scored.loc[0, "operating_mode"] = "RUNNING"
    alerts = candidate()
    result = hold_after_restart(alerts, scored)
    assert_frame_equal(result[alerts.columns], alerts, check_exact=True)


def test_persistence_uses_only_completed_minutes_at_original_candidate():
    scored = minutes()
    scored.loc[16, "z_wt"] = 0  # Available one minute after the candidate.
    scored.loc[15, "z_pd"] = B1_K + 1  # One-minute spike is not sustained.
    result = hold_after_restart(candidate(), scored)
    assert pd.Timestamp(result.iloc[0].alert_time_utc) == DUE


def test_sustained_channels_follow_ch_order_and_require_every_minute():
    history = minutes(("wt", "bt", "c", "pd")).iloc[1:16].copy()
    history.loc[8, "z_pd"] = B1_K
    assert sustained_channels(history) == ("c", "bt", "wt")
    history.loc[8, "z_wt"] = float("nan")
    assert sustained_channels(history) == ("c", "bt")


def test_pipeline_holds_before_guidance_and_confidence(monkeypatch):
    alerts, scored = candidate(), minutes()
    monkeypatch.setattr(pipeline, "score_features", lambda features, assets: features)
    monkeypatch.setattr(pipeline, "b1_threshold", lambda *args, **kwargs: alerts.copy())
    monkeypatch.setattr(pipeline, "rediagnose", lambda frame, *args: frame)
    monkeypatch.setattr(pipeline, "stuck_candidates", lambda *args: alerts.iloc[:0])
    monkeypatch.setattr(pipeline, "cavitation_candidates", lambda *args: alerts.iloc[:0])
    result = pipeline.candidate_stream(scored, pd.DataFrame())
    expected = assign_confidence(recommend(alerts))
    assert pd.Timestamp(result.iloc[0].alert_time_utc) == DUE
    assert result.iloc[0].held_from_utc == alerts.iloc[0].alert_time_utc
    assert_frame_equal(result.drop(columns=["alert_time_utc", "held_from_utc"]),
                       expected.drop(columns="alert_time_utc"), check_exact=True)


def test_held_provenance_is_removed_before_csv(tmp_path):
    scored = minutes()
    held = hold_after_restart(candidate(), scored)
    assets = pd.DataFrame({"asset_id": ["A"], "window_end_utc": [START + pd.Timedelta(days=1)]})
    result = apply_guarantees(held, scored, assets)
    assert list(result.columns) == COLUMNS
    path = tmp_path / "held.csv"
    write_predictions(result, path)
    with path.open(newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows[0] == COLUMNS
    assert len(rows) == 2
    assert rows[1][1] == DUE.strftime("%Y-%m-%dT%H:%M:%SZ")
