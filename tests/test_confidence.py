"""Evidence-level provenance, train consistency and scorer-window boundaries."""

from pathlib import Path
import json
import os
import subprocess
import sys

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from retrofit_assistant import evaluate, report
from retrofit_assistant.confidence import (
    EvidenceLevel, RULE_LEVELS, TRAIN_LEVELS, assign_confidence, evidence_level,
)
from retrofit_assistant.output import COLUMNS
from retrofit_assistant.params import DECIDED_BY

DATA = Path(__file__).resolve().parents[1] / "challenge/RETROFIT_AI_PARTICIPANTS_2026/data/full"


def test_all_rules_have_the_fixed_evidence_level():
    assert set(RULE_LEVELS) == set(DECIDED_BY)
    assert {rule for rule, level in RULE_LEVELS.items() if level == "high"} == {
        "official_protected", "rediagnose_noise", "rediagnose_spectrum",
        "source_cavitation", "source_stuck",
    }
    assert {rule for rule, level in RULE_LEVELS.items() if level == "medium"} == {
        "official", "rediagnose_confirmed",
    }
    assert {rule for rule, level in RULE_LEVELS.items() if level == "low"} == {
        "rediagnose_accelerometer", "rediagnose_refuted",
    }


def test_assign_changes_only_confidence_and_preserves_input():
    frame = pd.DataFrame({
        "decided_by": DECIDED_BY, "confidence": [0.12] * len(DECIDED_BY),
        "asset_id": ["A"] * len(DECIDED_BY), "evidence": list(DECIDED_BY),
        "extra": range(len(DECIDED_BY)),
    }, index=range(10, 10 + len(DECIDED_BY)))
    original = frame.copy(deep=True)
    result = assign_confidence(frame)
    assert_frame_equal(frame, original, check_exact=True)
    assert_frame_equal(result.drop(columns="confidence"), frame.drop(columns="confidence"),
                       check_exact=True)
    assert list(result.columns) == list(frame.columns)
    assert result.confidence.between(0, 1).all()
    for rule, value in zip(result.decided_by, result.confidence):
        assert value == TRAIN_LEVELS[RULE_LEVELS[rule]].type_reliability


@pytest.mark.parametrize("rule", ["unknown_rule", "", None])
def test_unknown_rule_raises(rule):
    with pytest.raises(ValueError, match="decided_by"):
        assign_confidence(pd.DataFrame({"decided_by": [rule], "confidence": [.5]}))


def test_empty_frame_is_copied_unchanged():
    frame = pd.DataFrame(columns=COLUMNS + ["decided_by"])
    result = assign_confidence(frame)
    assert result is not frame
    assert_frame_equal(result, frame, check_exact=True)


@pytest.mark.parametrize("name", TRAIN_LEVELS)
def test_report_shows_separate_train_reliabilities_and_csv_round_trip(name):
    level = TRAIN_LEVELS[name]
    value = float(f"{level.type_reliability:.6f}")
    assert evidence_level(value) == name
    assert report._confidence(value) == (
        f"confidence {name} · alert {level.alert_reliability:.2f} (n={level.n})"
        f" · type {level.type_reliability:.2f} (n={level.n})"
    )
    assert 0 <= level.alert_reliability <= 1
    assert 0 <= level.type_reliability <= 1


@pytest.mark.parametrize("value,label", [(.3, "low"), (.5, "medium"), (.77, "high")])
def test_unmatched_report_value_keeps_threshold_label(value, label):
    assert report._confidence(value) == f"{value:.2f} {label}"


def test_train_measurement_matches_fixed_table():
    code = f"""import json
from dataclasses import asdict
from retrofit_assistant.evaluate import evaluate_confidence
print(json.dumps({{name: asdict(level) for name, level in
                  evaluate_confidence({str(DATA)!r}, 'train').items()}}))
"""
    measured = subprocess.run(
        [sys.executable, "-c", code], env={**os.environ, "PYTHONHASHSEED": "0"},
        capture_output=True, text=True, check=True,
    )
    assert {name: EvidenceLevel(**level) for name, level in json.loads(measured.stdout).items()} == TRAIN_LEVELS
    assert TRAIN_LEVELS == {
        "high": EvidenceLevel(14, 14, 14),
        "medium": EvidenceLevel(32, 31, 20),
        "low": EvidenceLevel(3, 2, 0),
    }


@pytest.mark.parametrize("split", ["test", "invalid"])
def test_measurement_rejects_other_splits_before_loading(monkeypatch, split):
    def fail(*args, **kwargs):
        pytest.fail("input accessed")
    monkeypatch.setattr(evaluate, "load_assets", fail)
    monkeypatch.setattr(evaluate, "run_detector", fail)
    with pytest.raises(ValueError, match="Unsupported split"):
        evaluate.evaluate_confidence("missing", split)


def windows_fixture():
    assets = pd.DataFrame([dict(asset_id="A", window_start_utc="2026-01-01T00:00:00Z",
                                window_end_utc="2026-01-02T00:00:00Z")])
    events = pd.DataFrame([
        dict(asset_id="A", fault_type="BEARING_WEAR", event_class="MACHINE", observable=True,
             onset_utc="2026-01-01T01:00:00Z", detectable_utc="2026-01-01T09:00:00Z",
             end_utc="2026-01-01T12:00:00Z"),
        dict(asset_id="A", fault_type="SENSOR_DRIFT", event_class="SENSOR", observable="1",
             onset_utc="2026-01-01T16:00:00Z", detectable_utc=None,
             end_utc="2026-01-01T17:00:00Z"),
        dict(asset_id="A", fault_type="CAVITATION", event_class="MACHINE", observable="true",
             onset_utc="2026-01-01T19:00:00Z", detectable_utc=None,
             end_utc="2026-01-01T20:00:00Z"),
        dict(asset_id="A", fault_type="IMBALANCE", event_class="MACHINE", observable=True,
             onset_utc="2026-01-01T23:00:00Z", detectable_utc=None, end_utc=None),
        dict(asset_id="A", fault_type="IMPELLER_WEAR", event_class="MACHINE", observable=False,
             onset_utc="2026-01-01T00:00:00Z", detectable_utc=None, end_utc=None),
        dict(asset_id="B", fault_type="IMPELLER_WEAR", event_class="MACHINE", observable=True,
             onset_utc="2026-01-01T00:00:00Z", detectable_utc=None, end_utc=None),
    ])
    return assets, events


@pytest.mark.parametrize("time,fault_type,hits,type_hits,n", [
    ("02:59:59", "IMPELLER_WEAR", 0, 0, 1),
    ("03:00:00", "BEARING_WEAR", 1, 1, 1),
    ("12:00:00", "BEARING_WEAR", 1, 1, 1),
    ("12:00:01", "BEARING_WEAR", 0, 0, 1),
    ("16:00:00", "SENSOR_DRIFT", 1, 1, 1),
    ("17:30:00", "SENSOR_DRIFT", 1, 1, 1),
    ("17:30:01", "SENSOR_DRIFT", 0, 0, 1),
    ("19:00:00", "UNKNOWN", 1, 0, 1),
    ("20:30:00", "CAVITATION", 1, 1, 1),
    ("20:30:01", "CAVITATION", 0, 0, 1),
    ("23:59:59", "IMBALANCE", 1, 1, 1),
    ("24:00:00", "IMBALANCE", 0, 0, 0),
])
def test_measurement_uses_scorer_windows(time, fault_type, hits, type_hits, n):
    assets, events = windows_fixture()
    timestamp = pd.Timestamp("2026-01-01T00:00:00Z") + pd.Timedelta(time)
    alerts = pd.DataFrame([dict(asset_id="A", alert_time_utc=timestamp,
                                fault_type=fault_type, confidence=15 / 16)])
    measured = evaluate.measure_evidence_levels(alerts, events, assets)
    assert measured == {"high": EvidenceLevel(n, hits, type_hits),
                        "medium": EvidenceLevel(0, 0, 0), "low": EvidenceLevel(0, 0, 0)}


def test_empty_measurement_and_unmatched_value():
    assets, events = windows_fixture()
    measured = evaluate.measure_evidence_levels(pd.DataFrame(columns=COLUMNS), events, assets)
    assert all(level == EvidenceLevel(0, 0, 0) for level in measured.values())
    alerts = pd.DataFrame([dict(asset_id="A", alert_time_utc="2026-01-01T10:00:00Z",
                                fault_type="BEARING_WEAR", confidence=.77)])
    with pytest.raises(ValueError, match="evidence level"):
        evaluate.measure_evidence_levels(alerts, events, assets)
