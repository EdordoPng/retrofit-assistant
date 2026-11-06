#!/usr/bin/env python3
"""30-minute quick start: load the starter tier, look at one asset, run the mode-aware baseline, score validation.

  python examples/quickstart.py            (uses data/starter; ~1 minute)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import pandas as pd  # noqa: E402

from retrofit_sim import baselines as B  # noqa: E402
from retrofit_sim.dataset import features_1min  # noqa: E402
from retrofit_sim.scoring import format_report, score  # noqa: E402

D = os.path.join(ROOT, "data", "starter")
assets = pd.read_csv(os.path.join(D, "assets.csv"))
print(assets[["asset_id", "split", "profile", "control", "instrumentation_tier", "channels_available"]].to_string(index=False))

tele = pd.read_csv(os.path.join(D, "telemetry.csv.gz"))
tele["timestamp_utc"] = pd.to_datetime(tele["timestamp_utc"], utc=True)
print(f"\ntelemetry rows: {len(tele):,} (10-s starter resolution)")
print(tele[tele.asset_id == "PUMP-06"].describe().T[["count", "mean", "min", "max"]].round(2).to_string())

ev = pd.read_csv(os.path.join(D, "events_train.csv"))
print("\ntraining events:\n" + ev[["event_id", "fault_type", "onset_utc", "end_utc", "severity", "observable"]].to_string(index=False))

# 1-min features -> regime-normalised z-scores -> mode-aware threshold baseline
feat = features_1min(tele)
feat["rows"] = (feat["rows"] * 10).astype("int16")
z = B.zscores(B.regime_frame(feat, assets))
val_ids = set(assets[assets.split == "validation"].asset_id)
# use the parameters tuned on the training split by baselines/run_baselines.py (fallback if not run yet)
import json  # noqa: E402
rp = os.path.join(ROOT, "baselines", "results", "baseline_report.json")
par = json.load(open(rp))["chosen_parameters"]["B1_mode_aware_z"] if os.path.exists(rp) else {"k": 6, "persist_min": 15}
pred = B.b1_threshold(z[z.asset_id.isin(val_ids)], k=par["k"], persist=par["persist_min"])
os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
out = os.path.join(ROOT, "build", "quickstart_predictions_validation.csv")
pred.to_csv(out, index=False)
print(f"\n{len(pred)} alerts written to {out}")

r = score(pred, pd.read_csv(os.path.join(D, "events_validation.csv")), assets,
          pd.read_csv(os.path.join(D, "benign_windows_train_validation.csv")), "validation")
print("\n" + format_report(r))
print("\nNote: starter tier (10-s data, 1 validation pump). Not comparable with the full-tier results in baselines/results.")
