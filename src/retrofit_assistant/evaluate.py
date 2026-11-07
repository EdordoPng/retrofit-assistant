"""Train and validation comparisons using the official scorer."""

from pathlib import Path

import pandas as pd
from retrofit_sim.scoring import POST_TOL, PRE_TOL, SOFT_END, WEIGHTS, score

from .confidence import EvidenceLevel, TRAIN_LEVELS, evidence_level
from .data import load_assets
from .output import write_predictions
from .pipeline import run_detector

SPLITS = ("train", "validation")
DETECTORS = ("full", "causal_b1")
DECLARED_B1 = {"train": 58.2, "validation": 78.0}
# Median lead to deadline (h), baselines/results/baseline_metrics.md, B1_mode_aware_z.
DECLARED_B1_LEAD = {"train": 55.8, "validation": 8.3}


def measure_evidence_levels(alerts, events, assets):
    """Count emitted alerts in observable event windows, separately from type hits.

    These are per-alert shares, not the scorer's first-detection or repeat metrics.
    Any observable window is an alert hit; a type hit additionally needs a window
    of the same fault type. The scorer's inclusive bounds and tolerances apply.
    The policy removes decided_by, leaving the level encoded in confidence.
    """
    starts = dict(zip(assets.asset_id, pd.to_datetime(assets.window_start_utc, utc=True)))
    ends = dict(zip(assets.asset_id, pd.to_datetime(assets.window_end_utc, utc=True)))
    events = events.loc[events.asset_id.isin(starts)
                        & events.observable.astype(str).str.lower().isin(["true", "1"])].copy()
    for column in ("onset_utc", "detectable_utc", "end_utc"):
        events[column] = pd.to_datetime(events[column], utc=True)
    windows = []
    for event in events.itertuples(index=False):
        start = max(event.onset_utc, starts[event.asset_id])
        if pd.notna(event.detectable_utc):
            start = max(start, event.detectable_utc - PRE_TOL)
        end = ends[event.asset_id]
        if pd.notna(event.end_utc):
            soft = event.fault_type in SOFT_END or event.event_class == "SENSOR"
            end = min(end, event.end_utc + (POST_TOL if soft else pd.Timedelta(0)))
        windows.append((event.asset_id, start, end, event.fault_type))
    counts = {name: [0, 0, 0] for name in TRAIN_LEVELS}
    for alert in alerts.itertuples(index=False):
        time = pd.Timestamp(alert.alert_time_utc)
        if alert.asset_id not in starts or not starts[alert.asset_id] <= time < ends[alert.asset_id]:
            continue
        name = evidence_level(alert.confidence)
        if name is None:
            raise ValueError("Alert has no evidence level")
        matching = [fault_type for asset, start, end, fault_type in windows
                    if asset == alert.asset_id and start <= time <= end]
        counts[name][0] += 1
        counts[name][1] += bool(matching)
        counts[name][2] += alert.fault_type in matching
    return {name: EvidenceLevel(*values) for name, values in counts.items()}


def evaluate_confidence(data, split, alerts=None):
    """Measure train or validation evidence levels without updating the train table."""
    if split not in SPLITS:
        raise ValueError(f"Unsupported split: {split}")
    assets = load_assets(data, split)
    events = pd.read_csv(Path(data) / f"events_{split}.csv")
    if alerts is None:
        alerts = run_detector(data, split)
    return measure_evidence_levels(alerts, events, assets)


def evidence_markdown_table(measurements):
    rows = ["Evidence levels: train fit; validation check only. Reliability uses (hits + 1) / (n + 2).",
            "", "| split | evidence level | alert hits/n | alert hit rate | alert reliability | type hits/n | type hit rate | type reliability |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for split in SPLITS:
        for name, level in measurements[split].items():
            alert_rate = level.alert_hits / level.n if level.n else None
            type_rate = level.type_hits / level.n if level.n else None
            rows.append(f"| {split} | {name} | {level.alert_hits}/{level.n} | {_optional(alert_rate, 3)}"
                        f" | {level.alert_reliability:.3f} | {level.type_hits}/{level.n}"
                        f" | {_optional(type_rate, 3)} | {level.type_reliability:.3f} |")
    return "\n".join(rows) + "\n"


def evaluate_split(data, split, detector):
    if split not in SPLITS:
        raise ValueError(f"Unsupported split: {split}")
    data = Path(data)
    events = pd.read_csv(data / f"events_{split}.csv")
    assets = pd.read_csv(data / "assets.csv")
    benign = pd.read_csv(data / "benign_windows_train_validation.csv")
    path = Path("build") / "predictions" / f"{detector}_{split}.csv"
    write_predictions(run_detector(data, split, detector=detector), path)
    return score(path, events, assets, benign, split)


def alert_burden(result):
    # Recover the unexposed component from the scorer's weighted composite.
    other = sum(WEIGHTS[key] * result["event_f1" if key == "f1" else key]
                for key in WEIGHTS if key != "alert_burden")
    return (result["composite_score"] / 100 - other) / WEIGHTS["alert_burden"]


def _optional(value, digits):
    return "-" if value is None or pd.isna(value) else f"{value:.{digits}f}"


def gate(full_scores, reference_scores):
    return (all(full_scores[s] >= reference_scores[s] for s in SPLITS)
            and any(full_scores[s] > reference_scores[s] for s in SPLITS))


def markdown_table(results):
    columns = ("detector", "split", "composite", "event_f1", "event_recall", "alert_precision",
               "timeliness", "fault_type_recall", "class_recall", "alert_burden",
               "false_alerts_per_asset_day", "eventi rilevati/totali", "false_alert_episodes",
               "excess_repeat_episodes", "tipo corretto", "classe corretta",
               "median_lead_time_h", "early_warning_rate")
    rows = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for detector in DETECTORS:
        for split in SPLITS:
            r = results[detector][split]
            metrics = [r[k] for k in ("event_f1", "event_recall", "alert_precision", "timeliness",
                                       "fault_type_recall", "class_recall")]
            values = [detector, split, f"{r['composite_score']:.3f}",
                      *(f"{value:.3f}" for value in metrics), f"{alert_burden(r):.3f}",
                      f"{r['false_alerts_per_asset_day']:.3f}",
                      f"{r['true_positive_events']}/{r['events_scored']}",
                      str(r["false_alert_episodes"]), str(r["excess_repeat_episodes"]),
                      str(sum(e["type_correct"] for e in r["per_event"])),
                      str(sum(e["class_correct"] for e in r["per_event"])),
                      _optional(r["median_lead_time_h"], 2), _optional(r["early_warning_rate"], 3)]
            rows.append("| " + " | ".join(values) + " |")
    for split in SPLITS:
        rows.append("| " + " | ".join(["B1 dichiarato", split, f"{DECLARED_B1[split]:.1f}"]
                                        + ["-"] * (len(columns) - 5)
                                        + [f"{DECLARED_B1_LEAD[split]:.1f}", "-"]) + " |")
    return "\n".join(rows) + "\n"


def compare(data, out, use_gate=False):
    results = {detector: {split: evaluate_split(data, split, detector) for split in SPLITS}
               for detector in DETECTORS}
    destination = Path(out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    measurements = {
        split: evaluate_confidence(data, split, pd.read_csv(
            Path("build") / "predictions" / f"full_{split}.csv"))
        for split in SPLITS
    }
    destination.write_text(markdown_table(results) + "\n" + evidence_markdown_table(measurements),
                           encoding="utf-8")
    if not use_gate:
        return True
    return gate(*( {split: results[detector][split]["composite_score"] for split in SPLITS}
                   for detector in DETECTORS))
