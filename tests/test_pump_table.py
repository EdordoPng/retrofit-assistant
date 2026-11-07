"""Per-pump table contracts: official counts, totals and held-out test pumps."""

import json

import pandas as pd
import pytest

from retrofit_assistant import pump_table

SECRET = "must-not-leak"


@pytest.fixture
def data(tmp_path):
    rows = [("A", "train", "T2_FULL"), ("B", "train", "T1_RETROFIT"),
            ("V", "validation", "T2_FULL"), ("X", "test", "T0_LEGACY")]
    pd.DataFrame([{"asset_id": a, "split": s, "instrumentation_tier": t,
                   "window_start_utc": "2026-01-01T00:00:00Z",
                   "window_end_utc": "2026-01-02T00:00:00Z", "channels_available": SECRET}
                  for a, s, t in rows]).to_csv(tmp_path / "assets.csv", index=False)
    for name in ("events_train.csv", "events_validation.csv", "benign_windows_train_validation.csv"):
        pd.DataFrame({"asset_id": []}).to_csv(tmp_path / name, index=False)
    return tmp_path


def result(scored, detected, false_alerts=0, excess=0):
    return {"composite_score": 50.0, "events_scored": scored, "true_positive_events": detected,
            "false_alert_episodes": false_alerts, "excess_repeat_episodes": excess,
            "per_event": [{"type_correct": True, "class_correct": True}] * detected}


@pytest.fixture
def fake(monkeypatch):
    calls = []

    def run_detector(data, split, mask_tier=None):
        calls.append((split, mask_tier))
        return pd.DataFrame({"asset_id": []})

    def score(predictions, events, assets, benign, split):
        per_pump = {"A": result(2, 1, 1), "B": result(1, 1, 0, 1), "V": result(3, 3)}
        if len(assets) == 1:
            return per_pump[assets.asset_id.iloc[0]]
        ids = list(assets.asset_id)
        return result(sum(per_pump[a]["events_scored"] for a in ids),
                      sum(per_pump[a]["true_positive_events"] for a in ids),
                      sum(per_pump[a]["false_alert_episodes"] for a in ids),
                      sum(per_pump[a]["excess_repeat_episodes"] for a in ids))

    monkeypatch.setattr(pump_table, "run_detector", run_detector)
    monkeypatch.setattr(pump_table, "score", score)
    return calls


def test_detector_never_runs_on_test_split(data, fake):
    pump_table.build_table(data, "abc")
    assert {split for split, _ in fake} == {"train", "validation"}
    assert {mask for _, mask in fake} == {None, "T1", "T0"}


def test_test_pumps_carry_only_tier_and_status(data, fake):
    table = pump_table.build_table(data, "abc")
    test = [r for r in table["pumps"] if r["split"] == "test"]
    assert test == [{"asset_id": "X", "split": "test", "instrumentation_tier": "T0_LEGACY", "tier": "T0",
                     "status": "labels held by organizers, not scored"}]
    assert SECRET not in json.dumps(table) and SECRET not in pump_table.markdown(table)


def test_per_pump_counts_add_up_to_split_totals(data, fake):
    table = pump_table.build_table(data, "abc")
    train = [r for r in table["pumps"] if r["split"] == "train"]
    assert [r["asset_id"] for r in train] == ["A", "B"]
    assert table["split_totals"]["train"]["detected"] == sum(r["detected"] for r in train) == 2
    assert all("composite" not in r for r in table["pumps"])
    assert [r["instrumentation_tier"] for r in table["pumps"]] == [
        "T2_FULL", "T1_RETROFIT", "T2_FULL", "T0_LEGACY"]


def test_mismatched_totals_raise():
    rows = [{"split": "train", **dict.fromkeys(pump_table.COUNTS, 1)}]
    with pytest.raises(ValueError, match="do not add up"):
        pump_table.check_totals(rows, {"train": dict.fromkeys(pump_table.COUNTS, 2)})


@pytest.mark.parametrize("out", ["elsewhere/table.json", "build/scores/table.csv"])
def test_output_must_be_json_inside_build(data, out):
    with pytest.raises(SystemExit):
        pump_table.main(["--data", str(data), "--out", out, "--commit", "abc"])
