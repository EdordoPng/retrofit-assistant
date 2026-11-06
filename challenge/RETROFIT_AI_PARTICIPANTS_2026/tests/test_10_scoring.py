"""Scorer rules: bursts, anchored episodes, repair-bounded windows, anti-gaming."""
import os

import pandas as pd
import pytest

from retrofit_sim.scoring import FAULT_TYPES, score


def _setup():
    assets = pd.DataFrame({"asset_id": ["A"], "split": ["validation"], "window_start_utc": ["2026-01-01T00:00:00Z"],
                           "window_end_utc": ["2026-01-08T00:00:00Z"]})
    ev = pd.DataFrame([{"event_id": "A-E01", "asset_id": "A", "event_class": "MACHINE", "fault_type": "BEARING_WEAR",
                        "onset_utc": "2026-01-02T00:00:00Z", "detectable_utc": "2026-01-02T06:00:00Z",
                        "action_deadline_utc": "2026-01-03T00:00:00Z", "end_utc": "2026-01-04T00:00:00Z", "observable": True}])
    return assets, ev


def _p(rows):
    return pd.DataFrame(rows, columns=["asset_id", "alert_time_utc", "event_class", "fault_type", "confidence"])


def test_perfect_single_alert():
    assets, ev = _setup()
    r = score(_p([("A", "2026-01-02T08:00:00Z", "MACHINE", "BEARING_WEAR", 0.9)]), ev, assets)
    assert r["event_recall"] == 1 and r["alert_precision"] == 1 and r["fault_type_recall"] == 1
    assert r["composite_score"] > 99


def test_shotgun_burst_gets_no_type_credit():
    assets, ev = _setup()
    rows = [("A", "2026-01-02T08:00:00Z", "MACHINE" if "SENSOR" not in t and t != "COMMUNICATION_LOSS" else "SENSOR", t, 0.5)
            for t in sorted(FAULT_TYPES)]
    r = score(_p(rows), ev, assets)
    assert r["alert_bursts"] == 1 and r["fault_type_recall"] == 0 and r["class_recall"] == 0


def test_alert_stream_is_not_chained_into_one_episode():
    assets, ev = _setup()
    times = pd.date_range("2026-01-05T00:00Z", "2026-01-06T00:00Z", freq="29min")
    r = score(_p([("A", t.isoformat(), "MACHINE", "IMBALANCE", 0.5) for t in times]), ev, assets)
    assert r["false_alert_episodes"] >= 24


def test_alert_after_repair_lockout_is_not_a_detection():
    assets, ev = _setup()
    r = score(_p([("A", "2026-01-04T00:10:00Z", "MACHINE", "BEARING_WEAR", 0.9)]), ev, assets)
    assert r["true_positive_events"] == 0 and r["false_alert_episodes"] == 1


def test_too_early_alert_cannot_match():
    assets, ev = _setup()
    ev.loc[0, "detectable_utc"] = "2026-01-02T12:00:00Z"
    r = score(_p([("A", "2026-01-02T03:00:00Z", "MACHINE", "BEARING_WEAR", 0.9)]), ev, assets)   # before detectable - 6 h
    assert r["true_positive_events"] == 0


def test_invalid_class_rejected():
    assets, ev = _setup()
    with pytest.raises(ValueError):
        score(_p([("A", "2026-01-02T08:00:00Z", "MACHINE_OR_SENSOR", "BEARING_WEAR", 0.9)]), ev, assets)


def test_spam_strategy_scores_below_baseline(full_dir):
    """Uninformed alerting every 29 min with all types must not beat the simple baseline on validation."""
    assets = pd.read_csv(os.path.join(full_dir, "assets.csv"))
    ev = pd.read_csv(os.path.join(full_dir, "events_validation.csv"))
    rows = []
    for _, a in assets[assets.split == "validation"].iterrows():
        for t in pd.date_range(a.window_start_utc, a.window_end_utc, freq="29min", inclusive="left"):
            for ft in sorted(FAULT_TYPES - {"UNKNOWN"}):
                cls = "SENSOR" if ft.startswith("SENSOR") or ft == "COMMUNICATION_LOSS" else "MACHINE"
                rows.append((a.asset_id, t.isoformat(), cls, ft, 0.5))
    r = score(_p(rows), ev, assets, None, "validation")
    assert r["composite_score"] < 35, r["composite_score"]
