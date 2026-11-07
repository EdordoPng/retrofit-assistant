"""Development-only tier comparisons; labels enter only the official scorer."""

from pathlib import Path

import pandas as pd
from retrofit_sim.scoring import score

from .data import load_assets
from .output import write_predictions
from .pipeline import run_detector


T1_LABEL = "T1 simulato ottimistico (cadenza wireless non emulata)"
OBSERVABLE_NOTE = (
    "I flag `observable` degli eventi sono quelli della strumentazione reale (T2): "
    "i punteggi mascherati sono quindi pessimistici."
)


def markdown_table(rows):
    columns = ("tier", "split", "pompe", "composite", "eventi rilevati/totali",
               "tipi corretti", "median_lead_time_h", "early_warning_rate")
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for label, split, result in rows:
        optional = lambda value, digits: "-" if value is None or pd.isna(value) else f"{value:.{digits}f}"
        values = [label, split, ", ".join(result["assets"]), f"{result['composite_score']:.3f}",
                  f"{result['true_positive_events']}/{result['events_scored']}",
                  str(sum(e["type_correct"] for e in result["per_event"])),
                  optional(result["median_lead_time_h"], 2), optional(result["early_warning_rate"], 3)]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"


def ablate(data, out):
    """Score all train/validation T2 pumps; compare real T1/T0 train references."""
    data, destination = Path(data), Path(out)
    if not destination.resolve().is_relative_to(Path("build").resolve()):
        raise ValueError("Ablation output must be inside build/")
    rows, references = [], []
    benign = pd.read_csv(data / "benign_windows_train_validation.csv")
    for split in ("train", "validation"):
        assets = load_assets(data, split)
        events = pd.read_csv(data / f"events_{split}.csv")

        def measure(predictions, selected, name):
            path = Path("build/predictions/ablation") / f"{name}_{split}.csv"
            write_predictions(predictions.loc[predictions.asset_id.isin(selected.asset_id)], path)
            return score(path, events, selected, benign, split)

        t2 = assets.loc[assets.instrumentation_tier.eq("T2_FULL")]
        for mask, label in ((None, "T2 originale"), ("T1", T1_LABEL), ("T0", "T0 simulato")):
            predictions = run_detector(data, split, mask_tier=mask)
            rows.append((label, split, measure(predictions, t2, mask or "T2")))
            if mask is None and split == "train":
                for tier in ("T1_RETROFIT", "T0_LEGACY"):
                    selected = assets.loc[assets.instrumentation_tier.eq(tier)]
                    references.append((tier + " reale", split, measure(predictions, selected, tier)))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "# Ablazione della strumentazione\n\n" + markdown_table(rows)
        + "\n" + OBSERVABLE_NOTE + "\n\n"
        + "## Riferimento: strumentazione reale su train\n\n" + markdown_table(references),
        encoding="utf-8",
    )
    return destination
