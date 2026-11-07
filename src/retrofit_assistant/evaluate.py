"""Train and validation comparisons using the official scorer."""

from pathlib import Path

import pandas as pd
from retrofit_sim.scoring import WEIGHTS, score

from .output import write_predictions
from .pipeline import run_detector

SPLITS = ("train", "validation")
DETECTORS = ("full", "causal_b1")
DECLARED_B1 = {"train": 58.2, "validation": 78.0}


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


def gate(full_scores, reference_scores):
    return (all(full_scores[s] >= reference_scores[s] for s in SPLITS)
            and any(full_scores[s] > reference_scores[s] for s in SPLITS))


def markdown_table(results):
    columns = ("detector", "split", "composite", "event_f1", "event_recall", "alert_precision",
               "timeliness", "fault_type_recall", "class_recall", "alert_burden",
               "false_alerts_per_asset_day", "eventi rilevati/totali", "false_alert_episodes",
               "excess_repeat_episodes", "tipo corretto", "classe corretta")
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
                      str(sum(e["class_correct"] for e in r["per_event"]))]
            rows.append("| " + " | ".join(values) + " |")
    for split in SPLITS:
        rows.append("| " + " | ".join(["B1 dichiarato", split, f"{DECLARED_B1[split]:.1f}"]
                                        + ["-"] * (len(columns) - 3)) + " |")
    return "\n".join(rows) + "\n"


def compare(data, out, use_gate=False):
    results = {detector: {split: evaluate_split(data, split, detector) for split in SPLITS}
               for detector in DETECTORS}
    destination = Path(out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(markdown_table(results), encoding="utf-8")
    if not use_gate:
        return True
    return gate(*( {split: results[detector][split]["composite_score"] for split in SPLITS}
                   for detector in DETECTORS))
