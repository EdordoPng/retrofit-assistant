"""Prediction bytes, strict submission checks and content-safe CLI behavior."""

import csv
from dataclasses import FrozenInstanceError
import io
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from retrofit_sim.scoring import load_predictions

from retrofit_assistant import cli, pipeline
from retrofit_assistant.data import AVAILABILITY, InputContract, load_assets
from retrofit_assistant.output import COLUMNS, Check, validate_file, write_predictions
from retrofit_assistant.params import EVENT_CLASSES, FAULT_TYPES
from retrofit_assistant.pipeline import run_detector


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "challenge" / "RETROFIT_AI_PARTICIPANTS_2026" / "data" / "full"
HEADER = "asset_id,alert_time_utc,event_class,fault_type,confidence,evidence,recommended_action\n"
VALID = ["A", "2026-01-01T00:01:00Z", "MACHINE", "BEARING_WEAR", "0.700000", "SEGRETO", "Inspect"]


@pytest.fixture
def synthetic(tmp_path):
    metadata = pd.DataFrame({
        "asset_id": ["A", "B", "C"], "split": ["validation", "test", "train"],
        "window_start_utc": ["2026-01-01T00:00:00Z"] * 3,
        "window_end_utc": ["2026-01-02T00:00:00Z"] * 3,
        "motor_rated_rpm": [1500] * 3,
    })
    metadata.to_csv(tmp_path / "assets.csv", index=False)
    return tmp_path, metadata


def csv_file(tmp_path, rows=None, header=None):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS if header is None else header)
    writer.writerows([VALID] if rows is None else rows)
    path = tmp_path / "predictions.csv"
    path.write_text(buffer.getvalue(), encoding="utf-8", newline="")
    return path


def test_writer_explicit_text_and_dtype_independent_bytes(tmp_path):
    frame = pd.DataFrame([
        ["B", "2026-01-01T00:02:00Z", "SENSOR", "UNKNOWN", 0.123456789, None, float("nan")],
        ["A", "2026-01-01T00:02:00Z", "MACHINE", "BEARING_WEAR", 1.0, pd.NA, "Inspect"],
        ["A", "2026-01-01T00:01:00Z", "MACHINE", "BEARING_WEAR", 0.7, 'a, "quote"', "Review"],
    ], columns=COLUMNS)
    texts = [column for column in COLUMNS if column != "confidence"]
    obj = frame.astype({column: object for column in texts})
    string = frame.astype({column: "str" for column in texts})
    original = obj.copy(deep=True)
    first, second = tmp_path / "nested" / "object.csv", tmp_path / "string.csv"
    write_predictions(obj, first)
    write_predictions(string, second)
    expected = (
        HEADER
        + 'A,2026-01-01T00:01:00Z,MACHINE,BEARING_WEAR,0.700000,"a, ""quote""",Review\n'
        + 'A,2026-01-01T00:02:00Z,MACHINE,BEARING_WEAR,1.000000,,Inspect\n'
        + 'B,2026-01-01T00:02:00Z,SENSOR,UNKNOWN,0.123457,,\n'
    ).encode("utf-8")
    assert first.read_bytes() == second.read_bytes() == expected
    assert_frame_equal(obj, original)
    assert len(load_predictions(first)) == 3


def test_writer_stable_ties_and_empty_frame(tmp_path):
    frame = pd.DataFrame([VALID, VALID], columns=COLUMNS)
    frame["evidence"] = ["first", "second"]
    path = tmp_path / "ties.csv"
    write_predictions(frame, path)
    assert list(csv.reader(io.StringIO(path.read_text())))[1:] == [
        ["A", "2026-01-01T00:01:00Z", "MACHINE", "BEARING_WEAR", "0.700000", "first", "Inspect"],
        ["A", "2026-01-01T00:01:00Z", "MACHINE", "BEARING_WEAR", "0.700000", "second", "Inspect"],
    ]
    write_predictions(frame.iloc[:0], path)
    assert path.read_bytes() == HEADER.encode()


@pytest.mark.parametrize("column", COLUMNS)
def test_writer_missing_columns_raise(tmp_path, column):
    frame = pd.DataFrame([VALID], columns=COLUMNS).drop(columns=column)
    with pytest.raises(ValueError):
        write_predictions(frame, tmp_path / "invalid.csv")


@pytest.mark.parametrize("index,value,rule", [
    (0, "OTHER", "asset_id"), (2, "OTHER", "event_class"), (3, "OTHER", "fault_type"),
    (4, "nan", "confidence"), (4, "inf", "confidence"), (4, "-0.1", "confidence"),
    (4, "1.1", "confidence"), (4, "abc", "confidence"),
    (1, "2026-01-01T00:01:00", "utc_timestamp"),
    (1, "2026-01-01T00:01:00+00:00", "utc_timestamp"),
    (1, "2026-02-30T00:01:00Z", "utc_timestamp"),
    (1, "2026-1-01T00:01:00Z", "utc_timestamp"),
    (1, "2026-01-01T00:01:00.000Z", "utc_timestamp"),
    (1, "2026-01-01T00:00:59Z", "window_start"),
    (1, "2026-01-02T00:00:00Z", "window_end"),
])
def test_validator_each_row_rule(synthetic, index, value, rule):
    directory, metadata = synthetic
    row = VALID.copy()
    row[index] = value
    path = csv_file(directory, [row])
    assert validate_file(path, metadata) == Check(False, 1, rule)


@pytest.mark.parametrize("timestamp", ["2026-01-01T00:01:00Z", "2026-01-01T23:59:59Z"])
@pytest.mark.parametrize("confidence", ["0", "1"])
def test_validator_inclusive_start_exclusive_end_and_confidence_bounds(synthetic, timestamp, confidence):
    directory, metadata = synthetic
    row = VALID.copy()
    row[1], row[4] = timestamp, confidence
    assert validate_file(csv_file(directory, [row]), metadata) == Check(True, 1, "")


def test_validator_uses_contract_latency(synthetic, monkeypatch):
    directory, metadata = synthetic
    monkeypatch.setitem(AVAILABILITY, "features_1min.parquet", InputContract("window_start_utc", pd.Timedelta(minutes=2)))
    assert validate_file(csv_file(directory), metadata) == Check(False, 1, "window_start")


@pytest.mark.parametrize("header", [[], COLUMNS[::-1], COLUMNS[:-1], COLUMNS + ["extra"]])
def test_validator_exact_header(synthetic, header):
    directory, metadata = synthetic
    assert validate_file(csv_file(directory, header=header), metadata) == Check(False, 1, "columns")


@pytest.mark.parametrize("row", [VALID[:-1], VALID + ["extra"]])
def test_validator_row_shape_and_total_count(synthetic, row):
    directory, metadata = synthetic
    assert validate_file(csv_file(directory, [VALID, row, VALID]), metadata) == Check(False, 3, "row_shape")


def test_validator_rule_priority_is_global(synthetic):
    directory, metadata = synthetic
    confidence = VALID.copy()
    confidence[4] = "abc"
    asset = VALID.copy()
    asset[0] = "OTHER"
    assert validate_file(csv_file(directory, [confidence, asset]), metadata) == Check(False, 2, "asset_id")


@pytest.mark.parametrize("contents,expected", [
    (b"", Check(False, 0, "columns")),
    (HEADER.encode(), Check(False, 0, "0 alerts – likely pipeline error")),
    (b"\xff", Check(False, 0, "file_unreadable")),
    ((HEADER + '"unterminated').encode(), Check(False, 0, "file_unreadable")),
])
def test_validator_empty_header_only_and_unreadable(synthetic, contents, expected):
    directory, metadata = synthetic
    path = directory / "bad.csv"
    path.write_bytes(contents)
    assert validate_file(path, metadata) == expected


def test_validator_missing_file_and_frozen_result(synthetic):
    directory, metadata = synthetic
    result = validate_file(directory / "missing.csv", metadata)
    assert result == Check(False, 0, "file_unreadable")
    with pytest.raises(FrozenInstanceError):
        result.rule = "changed"


@pytest.mark.parametrize("split,asset", [("validation", "A"), ("test", "B"), ("train", "C")])
@pytest.mark.parametrize("passed", [True, False])
def test_check_cli_exact_output_without_row_content(synthetic, capsys, split, asset, passed):
    directory, _ = synthetic
    row = VALID.copy()
    row[0] = asset
    if not passed:
        row[4] = "abc"
    path = csv_file(directory, [row])
    result = cli.main(["check-submission", "--predictions", str(path), "--data", str(directory), "--split", split])
    captured = capsys.readouterr()
    assert result == (0 if passed else 1)
    assert captured.out == ("PASS rows=1\n" if passed else "FAIL rows=1 rule=confidence\n")
    assert captured.err == ""
    assert "SEGRETO" not in captured.out


@pytest.mark.parametrize("case,expected", [
    ("header", "FAIL rows=0 rule=0 alerts – likely pipeline error\n"),
    ("missing", "FAIL rows=0 rule=file_unreadable\n"),
    ("columns", "FAIL rows=1 rule=columns\n"),
])
def test_check_cli_other_failure_branches(synthetic, capsys, case, expected):
    directory, _ = synthetic
    path = directory / "missing.csv" if case == "missing" else csv_file(directory, rows=[] if case == "header" else [VALID], header=[] if case == "columns" else None)
    assert cli.main(["check-submission", "--predictions", str(path), "--data", str(directory), "--split", "validation"]) == 1
    captured = capsys.readouterr()
    assert captured.out == expected and captured.err == ""


@pytest.mark.parametrize("destination", [
    "build/predictions/test.csv", "build/submission/predictions_test.csv",
    "build/submission/predictions_test_20261107T120000Z_abcdef.csv",
    "build/submission/predictions_test_20261307T120000Z_abcdef0.csv",
    "build/submission/predictions_test_20261107T120000Z_xyzxyzx.csv",
    "elsewhere/predictions_test_20261107T120000Z_abcdef0.csv",
])
def test_predict_test_bad_destination_precedes_data_access(tmp_path, monkeypatch, capsys, destination):
    monkeypatch.chdir(tmp_path)

    def fail_load(*args, **kwargs):
        pytest.fail("Data accessed before validating test output path")

    monkeypatch.setattr(cli, "run_detector", fail_load)
    assert cli.main(["predict", "--data", "does-not-exist", "--split", "test", "--out", destination]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "Invalid test output path\n"


def test_predict_test_synthetic_only(synthetic, monkeypatch, capsys):
    directory, _ = synthetic
    monkeypatch.chdir(directory)
    # Only a synthetic test asset, with a gateway outage long enough to alert.
    features = pd.DataFrame({
        "asset_id": ["B"] * 30,
        "window_start_utc": pd.date_range("2026-01-01T00:00:00Z", periods=30, freq="min"),
        "rows": [0] * 30, "operating_mode": ["RUNNING"] * 30,
        "running_fraction": [1.0] * 30,
    })
    features.to_parquet(directory / "features_1min.parquet", index=False)
    pd.DataFrame({"asset_id": pd.Series(dtype="str"),
                  "timestamp_utc": pd.Series(dtype="datetime64[ns, UTC]")}).to_parquet(
        directory / "vibration_snapshots.parquet", index=False,
    )
    destination = "build/submission/predictions_test_20261107T120000Z_abcdef0.csv"
    assert cli.main(["predict", "--data", str(directory), "--split", "test", "--out", destination]) == 0
    captured = capsys.readouterr()
    assert captured.out == destination + "\n" and captured.err == ""
    check = validate_file(destination, load_assets(directory, "test"))
    assert check.passed and check.rows > 0


def test_cli_no_arguments_prints_help(capsys):
    assert cli.main([]) == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out and "check-submission" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("split", ["train", "validation"])
def test_cli_prediction_bytes_identical_across_hash_seeds(tmp_path, split):
    paths = []
    for seed in ("1", "3"):
        destination = tmp_path / f"{split}_{seed}.csv"
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        result = subprocess.run(
            [sys.executable, "-m", "retrofit_assistant", "predict",
             "--data", str(DATA), "--split", split, "--out", str(destination)],
            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0
        assert result.stdout == str(destination) + "\n"
        assert result.stderr == ""
        paths.append(destination)
    assert paths[0].read_bytes() == paths[1].read_bytes()


def test_run_detector_validation_pump08_and_until(monkeypatch):
    loader = pipeline.load_assets

    def pump08(data, split):
        metadata = loader(data, split)
        return metadata.loc[metadata.asset_id == "PUMP-08"]

    monkeypatch.setattr(pipeline, "load_assets", pump08)
    reference = run_detector(DATA, "validation", "causal_b1")
    full = run_detector(DATA, "validation")
    assert not reference.empty
    identity = ["asset_id", "alert_time_utc"]
    assert full.confidence.between(0, 1).all()
    assert len(full) == len(reference)
    assert_frame_equal(full[identity], reference[identity], check_exact=True)
    assert full.event_class.isin(EVENT_CLASSES).all() and full.fault_type.isin(FAULT_TYPES).all()
    cutoff = pump08(DATA, "validation").window_start_utc.iloc[0]
    assert run_detector(DATA, "validation", until=cutoff).empty
    with pytest.raises(ValueError):
        run_detector("missing-data", "validation", detector="invalid")


TEMPLATE = ROOT / "challenge" / "RETROFIT_AI_PARTICIPANTS_2026" / "submission_template" / "predictions_template.csv"


def test_csv_columns_equal_template_and_drop_decided_by(tmp_path):
    template = TEMPLATE.read_text(encoding="utf-8").splitlines()[0].split(",")
    assert COLUMNS == template
    frame = pd.DataFrame([VALID], columns=COLUMNS).assign(decided_by="official")
    path = tmp_path / "with_provenance.csv"
    write_predictions(frame, path)
    assert path.read_text(encoding="utf-8").splitlines()[0].split(",") == template
    assert list(run_detector(DATA, "validation").columns) == template


def test_decided_by_vocabulary_matches_guidance():
    from retrofit_assistant import params, recommendations
    assert recommendations.DECIDED_BY == params.DECIDED_BY
