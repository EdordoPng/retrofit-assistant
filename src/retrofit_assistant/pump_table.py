"""Development-only per-pump table; labels enter only the official scorer.

The JSON is the single source for the README, slides and dashboard. The dashboard
must read it from a path passed as an argument and must not recalculate the numbers.

Test pumps contribute only their id, split and instrumentation tier from assets.csv.
"""

import argparse
import json
from pathlib import Path
import sys

import pandas as pd
from retrofit_sim.scoring import score

from .data import load_assets
from .pipeline import run_detector

SCORED_SPLITS = ("train", "validation")
COUNTS = ("scored_events", "detected", "type_correct", "class_correct",
          "false_alert_episodes", "excess_repeat_episodes")
TEST_STATUS = "labels held by organizers, not scored"
SPLIT_ROLES = {
    "train": "rules designed and thresholds chosen on these pumps (in-sample)",
    "validation": "used for selection",
    "test": "the only independent measure",
}
TIER_NAMES = {"T2_FULL": "T2", "T1_RETROFIT": "T1", "T0_LEGACY": "T0"}
ABLATION_TIERS = ((None, "T2 (real)"), ("T1", "T1 (simulated, optimistic)"), ("T0", "T0 (simulated)"))
NOTES = (
    "Per-pump counts come from the official scorer applied to one pump at a time; "
    "split totals are the official split scores.",
    "No composite score is given per pump or per tier: real pumps of different tiers "
    "carry different events. Tiers are compared only through the ablation, which "
    "re-runs the same T2 events with the missing channels masked.",
    "Ablation event flags are those of the real T2 instrumentation, so masked "
    "scores are pessimistic.",
)


def counts(result):
    events = result["per_event"]
    return {
        "scored_events": result["events_scored"],
        "detected": result["true_positive_events"],
        "type_correct": sum(e["type_correct"] for e in events),
        "class_correct": sum(e["class_correct"] for e in events),
        "false_alert_episodes": result["false_alert_episodes"],
        "excess_repeat_episodes": result["excess_repeat_episodes"],
    }


def check_totals(rows, totals):
    """Raise unless per-pump counts add up to the official split counts."""
    for split, total in totals.items():
        summed = {key: sum(r[key] for r in rows if r["split"] == split) for key in COUNTS}
        if summed != {key: total[key] for key in COUNTS}:
            raise ValueError(f"Per-pump counts do not add up on {split}: {summed} != {total}")


def held_out_rows(data):
    """Test pumps: id, split and tier only; nothing else is read for them."""
    assets = pd.read_csv(Path(data) / "assets.csv", usecols=["asset_id", "split", "instrumentation_tier"])
    selected = assets.loc[assets.split.eq("test")]
    return [{"asset_id": a, "split": "test", "instrumentation_tier": t, "tier": TIER_NAMES[t],
             "status": TEST_STATUS}
            for a, t in zip(selected.asset_id, selected.instrumentation_tier)]


def build_table(data, commit):
    data = Path(data)
    benign = pd.read_csv(data / "benign_windows_train_validation.csv")
    rows, totals, ablation = [], {}, []
    for split in SCORED_SPLITS:
        assets = load_assets(data, split)
        events = pd.read_csv(data / f"events_{split}.csv")
        predictions = run_detector(data, split)
        result = score(predictions, events, assets, benign, split)
        totals[split] = {"composite": round(result["composite_score"], 3), **counts(result)}
        for asset in assets.itertuples(index=False):
            one = assets.loc[assets.asset_id.eq(asset.asset_id)]
            rows.append({"asset_id": asset.asset_id, "split": split,
                         "instrumentation_tier": asset.instrumentation_tier,
                         "tier": TIER_NAMES[asset.instrumentation_tier],
                         **counts(score(predictions, events, one, benign, split))})
        t2 = assets.loc[assets.instrumentation_tier.eq("T2_FULL")]
        for mask, label in ABLATION_TIERS:
            masked = predictions if mask is None else run_detector(data, split, mask_tier=mask)
            result = score(masked, events, t2, benign, split)
            ablation.append({"tier": label, "split": split, "assets": list(t2.asset_id),
                             "composite": round(result["composite_score"], 3), **counts(result)})
    check_totals(rows, totals)
    return {"commit": commit, "split_roles": SPLIT_ROLES, "pumps": rows + held_out_rows(data),
            "split_totals": totals, "ablation": ablation, "notes": list(NOTES)}


def markdown(table):
    header = ("pump", "split", "tier", "scored events", "detected", "type correct",
              "class correct", "false-alert episodes", "excess repeats")
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * len(header)) + " |"]
    for r in table["pumps"]:
        if r["split"] == "test":
            values = [r["asset_id"], r["split"], r["tier"], r["status"]] + [""] * 5
        else:
            values = [r["asset_id"], r["split"], r["tier"], *(str(r[k]) for k in COUNTS)]
        lines.append("| " + " | ".join(values) + " |")
    for split, t in table["split_totals"].items():
        lines.append("| " + " | ".join([f"**{split} total**", split, "mixed",
                                        *(str(t[k]) for k in COUNTS)]) + " |")
    lines += ["", "Official composite: " + ", ".join(
        f"{split} {t['composite']:.3f}" for split, t in table["split_totals"].items()) + ".",
        "", "Split roles: " + "; ".join(f"{s}: {role}" for s, role in table["split_roles"].items()) + ".",
        "", "| ablation tier | split | pumps | composite | detected / scored | type correct |",
        "| --- | --- | --- | --- | --- | --- |"]
    for a in table["ablation"]:
        lines.append(f"| {a['tier']} | {a['split']} | {', '.join(a['assets'])} | {a['composite']:.3f}"
                     f" | {a['detected']} / {a['scored_events']} | {a['type_correct']} |")
    lines += [""] + [f"- {note}" for note in table["notes"]]
    lines.append(f"\nGenerated at commit {table['commit']}.")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m retrofit_assistant.pump_table")
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", default="build/scores/pump_table.json")
    parser.add_argument("--commit", required=True, help="git rev-parse --short HEAD")
    args = parser.parse_args(argv)
    destination = Path(args.out)
    if destination.suffix != ".json" or not destination.resolve().is_relative_to(Path("build").resolve()):
        raise SystemExit("Output must be a .json file inside build/")
    table = build_table(args.data, args.commit)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(table, indent=2) + "\n", encoding="utf-8")
    destination.with_suffix(".md").write_text(markdown(table), encoding="utf-8")
    print(destination)
    return 0


if __name__ == "__main__":
    sys.exit(main())
