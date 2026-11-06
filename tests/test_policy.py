"""Emission guarantees, causal prefixes and official-scorer boundary fixtures."""

from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from retrofit_sim.scoring import CLASSES, FAULT_TYPES as OFFICIAL_FAULT_TYPES, score

from retrofit_assistant.data import AVAILABILITY, InputContract, load_assets, load_features
from retrofit_assistant.detectors import causal_b1
from retrofit_assistant.params import EVENT_CLASSES, FAULT_TYPES
from retrofit_assistant.policy import apply_guarantees


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "challenge" / "RETROFIT_AI_PARTICIPANTS_2026" / "data" / "full"
BASE = pd.Timestamp("2026-01-01T01:00:00Z")
COLUMNS = ["asset_id", "alert_time_utc", "event_class", "fault_type", "confidence", "evidence", "recommended_action"]


def candidates(offsets, asset_ids=None):
    return pd.DataFrame({
        "asset_id": asset_ids if asset_ids is not None else ["A"] * len(offsets),
        "alert_time_utc": [(BASE + pd.Timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ") for m in offsets],
        "event_class": ["MACHINE"] * len(offsets),
        "fault_type": ["BEARING_WEAR"] * len(offsets),
        "confidence": [0.7] * len(offsets),
        "evidence": [f"evidence {i}" for i in range(len(offsets))],
        "recommended_action": ["Inspect bearing"] * len(offsets),
    }, columns=COLUMNS)


def assets():
    return pd.DataFrame({
        "asset_id": ["A", "B"], "split": ["validation", "validation"],
        "window_start_utc": [pd.Timestamp("2026-01-01T00:00:00Z")] * 2,
        "window_end_utc": [pd.Timestamp("2026-01-08T00:00:00Z")] * 2,
    })


def minutes(modes=None):
    modes = modes or {}
    return pd.DataFrame({
        "asset_id": ["A"] * 32,
        "window_start_utc": pd.date_range("2026-01-01T00:58:00Z", periods=32, freq="min"),
        "operating_mode": [modes.get(i - 1, "RUNNING") for i in range(32)],
    })


def test_direct_pass_through_and_inputs_unchanged():
    proposed, telemetry, metadata = candidates([0, 10, 20]), minutes(), assets()
    copies = [frame.copy(deep=True) for frame in (proposed, telemetry, metadata)]
    actual = apply_guarantees(proposed, telemetry, metadata)
    assert_frame_equal(actual, proposed, check_exact=True)
    for original, copy in zip((proposed, telemetry, metadata), copies):
        assert_frame_equal(original, copy, check_exact=True)


@pytest.mark.parametrize("offsets,expected", [
    ([0, 3], ["2026-01-01T01:00:00Z", "2026-01-01T01:06:00Z"]),
    ([0, 6], ["2026-01-01T01:00:00Z", "2026-01-01T01:06:00Z"]),
    ([0, 1, 2], ["2026-01-01T01:00:00Z", "2026-01-01T01:06:00Z", "2026-01-01T01:12:00Z"]),
])
def test_spacing_changes_only_emission_time(offsets, expected):
    proposed = candidates(offsets)
    result = apply_guarantees(proposed, minutes(), assets())
    assert result.alert_time_utc.tolist() == expected
    assert_frame_equal(result.drop(columns="alert_time_utc"), proposed.drop(columns="alert_time_utc"))


def test_time_order_is_stable_and_reminders_are_retained():
    proposed = candidates([3, 0, 0])
    result = apply_guarantees(proposed, minutes(), assets())
    assert result.evidence.tolist() == ["evidence 1", "evidence 2", "evidence 0"]
    assert result.alert_time_utc.tolist() == ["2026-01-01T01:00:00Z", "2026-01-01T01:06:00Z", "2026-01-01T01:12:00Z"]
    reminder = candidates([0, 720])
    assert_frame_equal(apply_guarantees(reminder, minutes(), assets()), reminder)


def test_pumps_have_independent_spacing():
    proposed = candidates([0, 0], ["A", "B"])
    assert_frame_equal(apply_guarantees(proposed, minutes(), assets()), proposed)


@pytest.mark.parametrize("mode,dropped", [
    ("STOPPED", True), ("LOCKED_OUT", True), ("STARTING", False),
    ("STOPPING", False), ("RUNNING", False), (None, False),
])
def test_current_minute_mode(mode, dropped):
    result = apply_guarantees(candidates([0]), minutes({0: mode}), assets())
    assert result.empty == dropped
    if not dropped:
        assert_frame_equal(result, candidates([0]))


def test_gap_does_not_carry_forward_previous_stopped_state():
    proposed = candidates([0])
    proposed["fault_type"] = "COMMUNICATION_LOSS"
    proposed["event_class"] = "SENSOR"
    telemetry = minutes({-1: "STOPPED"})
    telemetry = telemetry.loc[telemetry.window_start_utc != pd.Timestamp("2026-01-01T00:59:00Z")]
    assert_frame_equal(apply_guarantees(proposed, telemetry, assets()), proposed)


@pytest.mark.parametrize("stop_offset,dropped", [(3, True), (5, True), (6, True), (2, False), (7, False)])
def test_stop_interval_is_inclusive_and_limited_to_delay(stop_offset, dropped):
    result = apply_guarantees(candidates([0, 3]), minutes({stop_offset: "STOPPED"}), assets())
    expected = ["2026-01-01T01:00:00Z"] if dropped else ["2026-01-01T01:00:00Z", "2026-01-01T01:06:00Z"]
    assert result.alert_time_utc.tolist() == expected


def test_dropped_candidate_does_not_update_spacing():
    result = apply_guarantees(candidates([0, 3, 7]), minutes({5: "LOCKED_OUT"}), assets())
    assert result.alert_time_utc.tolist() == ["2026-01-01T01:00:00Z", "2026-01-01T01:07:00Z"]
    assert result.evidence.tolist() == ["evidence 0", "evidence 2"]


def test_delay_at_exclusive_window_end_is_dropped():
    metadata = assets()
    metadata["window_end_utc"] = pd.Timestamp("2026-01-01T01:06:00Z")
    result = apply_guarantees(candidates([0, 3, 6]), minutes(), metadata)
    assert result.alert_time_utc.tolist() == ["2026-01-01T01:00:00Z"]


def test_stop_minute_end_uses_availability_contract(monkeypatch):
    monkeypatch.setitem(AVAILABILITY, "features_1min.parquet", InputContract("window_start_utc", pd.Timedelta(minutes=2)))
    # The stopped row starts at 00:59; under this contract it becomes available at 01:01.
    result = apply_guarantees(candidates([0]), minutes({0: "STOPPED"}), assets())
    assert_frame_equal(result, candidates([0]))


def test_mixed_stream_prefixes_never_revise_emitted_alerts():
    proposed = candidates([0, 1, 2, 3, 7, 8, 13, 14, 20], ["A", "B", "A", "A", "A", "B", "A", "A", "B"])
    proposed.loc[2, "fault_type"] = "UNKNOWN"
    proposed.loc[5, ["event_class", "fault_type"]] = ["SENSOR", "COMMUNICATION_LOSS"]
    telemetry = minutes({5: "STOPPED", 12: "LOCKED_OUT", 14: None})
    metadata = assets()
    complete = apply_guarantees(proposed, telemetry, metadata)
    for seconds in range(0, 1501, 30):
        cut = BASE + pd.Timedelta(seconds=seconds)
        prefix_candidates = proposed.loc[pd.to_datetime(proposed.alert_time_utc, utc=True) <= cut]
        prefix_minutes = telemetry.loc[telemetry.window_start_utc + pd.Timedelta(minutes=1) <= cut]
        prefix = apply_guarantees(prefix_candidates, prefix_minutes, metadata)
        prefix = prefix.loc[pd.to_datetime(prefix.alert_time_utc, utc=True) <= cut].reset_index(drop=True)
        expected = complete.loc[pd.to_datetime(complete.alert_time_utc, utc=True) <= cut].reset_index(drop=True)
        assert_frame_equal(prefix, expected, check_exact=True)


@pytest.mark.parametrize("column", COLUMNS)
def test_missing_prediction_column_raises(column):
    with pytest.raises(ValueError, match="missing columns"):
        apply_guarantees(candidates([0]).drop(columns=column), minutes(), assets())


@pytest.mark.parametrize("frame_name,column", [
    ("minutes", "asset_id"), ("minutes", "window_start_utc"), ("minutes", "operating_mode"),
    ("assets", "asset_id"), ("assets", "window_end_utc"),
])
def test_missing_context_column_raises(frame_name, column):
    telemetry, metadata = minutes(), assets()
    if frame_name == "minutes":
        telemetry = telemetry.drop(columns=column)
    else:
        metadata = metadata.drop(columns=column)
    with pytest.raises(ValueError, match="missing columns"):
        apply_guarantees(candidates([0]), telemetry, metadata)


@pytest.mark.parametrize("column", ["event_class", "fault_type"])
@pytest.mark.parametrize("value", ["INVALID", "MACHINE,SENSOR", "", None, float("nan"), pd.NA, ["MACHINE", "SENSOR"]])
def test_invalid_or_multiple_labels_raise(column, value):
    proposed = candidates([0])
    proposed[column] = pd.Series([value], dtype=object)
    with pytest.raises(ValueError, match="Invalid"):
        apply_guarantees(proposed, minutes(), assets())


def test_empty_candidates_keep_prediction_columns():
    proposed = candidates([])
    assert_frame_equal(apply_guarantees(proposed, minutes(), assets()), proposed)


def test_vocabularies_match_official_scorer():
    assert isinstance(FAULT_TYPES, tuple) and len(FAULT_TYPES) == 14
    assert set(FAULT_TYPES) == OFFICIAL_FAULT_TYPES
    assert set(EVENT_CLASSES) == CLASSES


@pytest.mark.parametrize("split", ["train", "validation"])
def test_real_filter_matches_causal_b1_row_for_row(split):
    metadata = load_assets(DATA, split)
    telemetry = load_features(DATA, metadata)
    proposed = causal_b1(telemetry, metadata)
    assert not proposed.empty
    assert_frame_equal(apply_guarantees(proposed, telemetry, metadata), proposed, check_exact=True)


@pytest.fixture
def scoring_event():
    return pd.DataFrame([{
        "event_id": "SYNTHETIC-EVENT", "asset_id": "A", "event_class": "MACHINE",
        "fault_type": "BEARING_WEAR", "onset_utc": "2026-01-01T00:00:00Z",
        "detectable_utc": "2026-01-01T00:00:00Z", "action_deadline_utc": None,
        "end_utc": None, "observable": True,
    }])


def score_synthetic(proposed, event):
    return score(proposed, event, assets().iloc[:1], split="validation")


def test_scorer_mixed_types_lose_type_credit(scoring_event):
    proposed = candidates([0, 3])
    proposed.loc[1, "fault_type"] = "CAVITATION"
    result = score_synthetic(proposed, scoring_event)
    assert result["alert_bursts"] == 1
    assert result["fault_type_recall"] == 0.0
    assert result["class_recall"] == 1.0


def test_scorer_mixed_classes_lose_class_credit(scoring_event):
    proposed = candidates([0, 3])
    proposed.loc[1, "event_class"] = "SENSOR"
    result = score_synthetic(proposed, scoring_event)
    assert result["alert_bursts"] == 1
    assert result["class_recall"] == 0.0
    assert result["fault_type_recall"] == 1.0


@pytest.mark.parametrize("second,expected_bursts", [("2026-01-01T01:05:00Z", 1), ("2026-01-01T01:05:01Z", 2)])
def test_scorer_five_minute_boundary(scoring_event, second, expected_bursts):
    # BENCHMARK_RULES §4 says "less than 5 min", but scoring.py:75 includes
    # exactly 5:00 in a burst. This is why our mandatory spacing is 6 minutes.
    proposed = candidates([0, 5])
    proposed.loc[1, "alert_time_utc"] = second
    assert score_synthetic(proposed, scoring_event)["alert_bursts"] == expected_bursts


def test_scorer_unknown_then_diagnosis_does_not_revise_first_detection(scoring_event):
    proposed = candidates([0, 6])
    proposed.loc[0, "fault_type"] = "UNKNOWN"
    result = score_synthetic(proposed, scoring_event)
    assert result["alert_bursts"] == 2
    assert result["fault_type_recall"] == 0.0
    assert result["repeat_alerts"] == 1


def test_filter_preserves_type_credit_by_separating_bursts(scoring_event):
    proposed = candidates([0, 3])
    proposed.loc[1, "fault_type"] = "CAVITATION"
    filtered = apply_guarantees(proposed, minutes(), assets())
    result = score_synthetic(filtered, scoring_event)
    assert result["alert_bursts"] == 2
    assert result["fault_type_recall"] == 1.0
