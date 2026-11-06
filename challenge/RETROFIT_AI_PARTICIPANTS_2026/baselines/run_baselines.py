#!/usr/bin/env python3
"""Run the reference baselines: tune on TRAIN labels only, evaluate on VALIDATION, write prediction CSVs + report.

  python baselines/run_baselines.py --data data/full --out baselines/results
  python baselines/run_baselines.py --data data/starter --out baselines/results_starter     (10-s CSV starter tier)
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import pandas as pd  # noqa: E402

from retrofit_sim import baselines as B  # noqa: E402
from retrofit_sim.dataset import features_1min  # noqa: E402
from retrofit_sim.scoring import format_report, score  # noqa: E402

METRICS = ["composite_score", "event_f1", "event_recall", "alert_precision", "false_alerts_per_asset_day", "timeliness",
           "fault_type_recall", "class_recall", "median_lead_time_h"]


def load(data):
    assets = pd.read_csv(os.path.join(data, "assets.csv"))
    fp = os.path.join(data, "features_1min.parquet")
    if os.path.exists(fp):
        feat = pd.read_parquet(fp)
    else:   # starter tier: build 1-min features from the 10-s CSV
        t = pd.read_csv(os.path.join(data, "telemetry.csv.gz"))
        t["timestamp_utc"] = pd.to_datetime(t["timestamp_utc"], utc=True)
        feat = features_1min(t)
        feat["rows"] = (feat["rows"] * 10).astype("int16")      # 10-s rows -> equivalent 1-s row count for gap rules
    ev_tr = pd.read_csv(os.path.join(data, "events_train.csv"))
    ev_va = pd.read_csv(os.path.join(data, "events_validation.csv"))
    bn_path = os.path.join(data, "benign_windows_train_validation.csv")
    bn = pd.read_csv(bn_path) if os.path.exists(bn_path) else None
    al = pd.read_csv(os.path.join(data, "alarms.csv"))
    return assets, feat, ev_tr, ev_va, bn, al


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--data", default=os.path.join(ROOT, "data", "full"))
    p.add_argument("--out", default=os.path.join(ROOT, "baselines", "results"))
    p.add_argument("--quick", action="store_true", help="Smaller tuning grid.")
    a = p.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    assets, feat, ev_tr, ev_va, bn, al = load(a.data)
    present = set(feat["asset_id"])
    assets_p = assets[assets.asset_id.isin(present)]
    train_ids = set(assets_p[assets_p.split == "train"].asset_id)
    val_ids = set(assets_p[assets_p.split == "validation"].asset_id)
    test_ids = set(assets_p[assets_p.split == "test"].asset_id)
    print(f"assets: train={sorted(train_ids)} validation={sorted(val_ids)} test={sorted(test_ids)}")
    zf = B.zscores(B.regime_frame(feat, assets))
    ztr, zva, zte = (zf[zf.asset_id.isin(s)] for s in (train_ids, val_ids, test_ids))

    def sc(pred, ev, split):
        return score(pred, ev, assets_p, bn, split)

    results, chosen = {}, {}
    # B0: SCADA alarms as they are
    for split, ids, ev in (("train", train_ids, ev_tr), ("validation", val_ids, ev_va)):
        results[("B0_scada_alarms", split)] = sc(B.b0_scada(al, ids), ev, split)
    # B1: tune k / persistence on train
    grid = [(k, m) for k in ([5, 8] if a.quick else [4, 6, 8, 12]) for m in ([10] if a.quick else [5, 15, 30])]
    best = max(grid, key=lambda km: sc(B.b1_threshold(ztr, *km), ev_tr, "train")["composite_score"])
    chosen["B1_mode_aware_z"] = {"k": best[0], "persist_min": best[1]}
    b1 = {s: B.b1_threshold(z, *best) for s, z in (("train", ztr), ("validation", zva), ("test", zte))}
    # B2: CUSUM h on train
    hs = [40, 120] if a.quick else [30, 60, 120, 240]
    hb = max(hs, key=lambda h: sc(B.b2_cusum(ztr, 2.0, h), ev_tr, "train")["composite_score"])
    chosen["B2_cusum"] = {"kappa": 2.0, "h": hb}
    b2 = {s: B.b2_cusum(z, 2.0, hb) for s, z in (("train", ztr), ("validation", zva), ("test", zte))}
    # B3: Isolation Forest trained on train minutes outside labelled event windows; quantile tuned on train
    qs = [0.995] if a.quick else [0.99, 0.995, 0.999]
    best_q, best_s, b3 = None, -1, {}
    for q in qs:
        pr, model, thr = B.b3_iforest(ztr, ev_tr, ztr, q=q)
        s = sc(pr, ev_tr, "train")["composite_score"]
        if s > best_s:
            best_q, best_s = q, s
    chosen["B3_isolation_forest"] = {"train_quantile": best_q, "persist_min": 10}
    for s, z in (("train", ztr), ("validation", zva), ("test", zte)):
        b3[s] = B.b3_iforest(ztr, ev_tr, z, q=best_q)[0]
    for name, preds in (("B1_mode_aware_z", b1), ("B2_cusum", b2), ("B3_isolation_forest", b3)):
        for split, ev in (("train", ev_tr), ("validation", ev_va)):
            results[(name, split)] = sc(preds[split], ev, split)
        for split in ("validation", "test"):
            if len(preds[split]) or split == "validation":
                preds[split].to_csv(os.path.join(a.out, f"predictions_{name}_{split}.csv"), index=False)
    # report
    rows = []
    for (name, split), r in results.items():
        rows.append({"baseline": name, "split": split, **{m: r[m] for m in METRICS},
                     "events_scored": r["events_scored"], "alerts": r["alerts_scored"]})
    tab = pd.DataFrame(rows)
    tab.to_csv(os.path.join(a.out, "baseline_metrics.csv"), index=False)
    with open(os.path.join(a.out, "baseline_report.json"), "w", encoding="utf-8") as fh:
        json.dump({"data": os.path.relpath(a.data, ROOT), "tuned_on": "train", "chosen_parameters": chosen,
                   "runtime_s": round(time.time() - t0, 1),
                   "results": {f"{k[0]}|{k[1]}": {m: v for m, v in r.items() if m != "per_event"} for k, r in results.items()},
                   "per_event_validation": {k[0]: r["per_event"] for k, r in results.items() if k[1] == "validation"}},
                  fh, indent=2, default=str)
    md = ["| Baseline | Split | Composite | Event F1 | Recall | Precision | False + excess alerts / asset-day | Timeliness | Fault-type recall | Class recall | Median lead to deadline (h) |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in tab.iterrows():
        f = lambda x, d=2: "-" if pd.isna(x) else f"{x:.{d}f}"
        md.append(f"| {r.baseline} | {r.split} | {f(r.composite_score, 1)} | {f(r.event_f1)} | {f(r.event_recall)} | {f(r.alert_precision)} | "
                  f"{f(r.false_alerts_per_asset_day)} | {f(r.timeliness)} | {f(r.fault_type_recall)} | {f(r.class_recall)} | {f(r.median_lead_time_h, 1)} |")
    with open(os.path.join(a.out, "baseline_metrics.md"), "w", encoding="utf-8") as fh:
        fh.write("Measured by baselines/run_baselines.py (parameters tuned on the training split only).\n\n")
        fh.write("Chosen parameters: " + json.dumps(chosen) + "\n\n" + "\n".join(md) + "\n")
    print("\n".join(md))
    for name in ("B1_mode_aware_z", "B2_cusum", "B3_isolation_forest"):
        print(f"\n[{name} | validation]\n" + format_report(results[(name, "validation")]))
    print(f"\nruntime {time.time() - t0:.0f} s; outputs in {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
