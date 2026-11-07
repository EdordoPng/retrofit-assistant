"""Comparison, official score integration, and CLI boundaries."""

import math
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest
from retrofit_sim.scoring import score

from retrofit_assistant import evaluate

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "challenge" / "RETROFIT_AI_PARTICIPANTS_2026" / "data" / "full"


@pytest.mark.parametrize("full,reference,expected", [
    ((1, 1), (1, 1), False), ((2, 1), (1, 1), True),
    ((2, 2), (1, 1), True), ((2, 0), (1, 1), False),
    ((0, 2), (1, 1), False), ((0, 0), (1, 1), False),
])
def test_gate(full, reference, expected):
    assert evaluate.gate(dict(zip(evaluate.SPLITS, full)), dict(zip(evaluate.SPLITS, reference))) is expected


def synthetic_score():
    assets = pd.DataFrame([{"asset_id": "A", "split": "train", "window_start_utc": "2026-01-01T00:00:00Z",
                            "window_end_utc": "2026-01-02T00:00:00Z"}])
    events = pd.DataFrame([{"event_id": "E", "asset_id": "A", "event_class": "MACHINE",
                            "fault_type": "BEARING_WEAR", "onset_utc": "2026-01-01T12:00:00Z",
                            "detectable_utc": "2026-01-01T12:00:00Z", "action_deadline_utc": None,
                            "end_utc": None, "observable": True}])
    predictions = pd.DataFrame([{"asset_id": "A", "alert_time_utc": "2026-01-01T01:00:00Z",
                                 "event_class": "MACHINE", "fault_type": "BEARING_WEAR", "confidence": 1.0},
                                {"asset_id": "A", "alert_time_utc": "2026-01-01T12:00:00Z",
                                 "event_class": "MACHINE", "fault_type": "BEARING_WEAR", "confidence": 1.0}])
    return score(predictions, events, assets, split="train")


def test_burden_from_official_score():
    result = synthetic_score()
    assert math.isclose(evaluate.alert_burden(result), max(0, 1 - result["false_alerts_per_asset_day"] / 2), abs_tol=1e-9)


def test_markdown_table_counts_and_columns():
    result = synthetic_score()
    results = {detector: {split: result for split in evaluate.SPLITS} for detector in evaluate.DETECTORS}
    table = evaluate.markdown_table(results)
    for name in ("composite", "event_f1", "event_recall", "alert_precision", "timeliness",
                 "fault_type_recall", "class_recall", "alert_burden", "false_alerts_per_asset_day",
                 "eventi rilevati/totali", "false_alert_episodes", "excess_repeat_episodes", "tipo corretto", "classe corretta"):
        assert name in table
    assert "| B1 dichiarato | train | 58.2 |" in table
    assert "| B1 dichiarato | validation | 78.0 |" in table
    assert "| 1/1 | 1 | 0 | 1 | 1 |" in table


def test_rejects_test_split_before_detector_or_writes(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(evaluate, "run_detector", lambda *a, **kw: pytest.fail("detector called"))
    with pytest.raises(ValueError):
        evaluate.evaluate_split(tmp_path, "test", "full")
    assert not list(tmp_path.iterdir())


def run_cli(tmp_path, *args):
    return subprocess.run([sys.executable, "-m", "retrofit_assistant", *map(str, args)], cwd=tmp_path,
                          env={**os.environ, "PYTHONHASHSEED": "1"}, capture_output=True, text=True, timeout=180)


def test_cli_import_isolation(tmp_path):
    result = subprocess.run([sys.executable, "-c", "import retrofit_assistant.cli, sys; "
                             "assert 'retrofit_assistant.evaluate' not in sys.modules; "
                             "assert 'retrofit_sim.scoring' not in sys.modules"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_compare_error(tmp_path):
    result = run_cli(tmp_path, "compare", "--data", tmp_path / "missing", "--out", tmp_path / "report.md")
    assert result.returncode == 2
    assert "Compare failed: FileNotFoundError:" in result.stderr


def test_compare_rejects_split(tmp_path):
    result = run_cli(tmp_path, "compare", "--data", DATA, "--out", tmp_path / "report.md", "--split", "test")
    assert result.returncode != 0
    assert not list(tmp_path.iterdir())


def test_compare_end_to_end(tmp_path):
    report = tmp_path / "compare.md"
    result = run_cli(tmp_path, "compare", "--data", DATA, "--out", report, "--gate")
    assert result.returncode == 1, result.stderr
    assert "GATE FAIL" in result.stdout
    table = report.read_text(encoding="utf-8")
    assert "| causal_b1 | train | 58.451 |" in table
    assert "| causal_b1 | validation | 78.013 |" in table
    assert {p.name for p in (tmp_path / "build" / "predictions").iterdir()} == {
        f"{detector}_{split}.csv" for detector in evaluate.DETECTORS for split in evaluate.SPLITS}
