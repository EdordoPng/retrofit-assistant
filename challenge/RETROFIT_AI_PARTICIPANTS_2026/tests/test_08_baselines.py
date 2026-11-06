"""Gate 8: baselines run on starter and validation data, produce valid predictions and measured metrics."""
import os
import subprocess
import sys

import pandas as pd

from retrofit_sim.scoring import load_predictions

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(data, out):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "baselines", "run_baselines.py"), "--data", data, "--out", out, "--quick"],
                       capture_output=True, text=True, timeout=1800)
    assert r.returncode == 0, r.stderr[-3000:]
    m = pd.read_csv(os.path.join(out, "baseline_metrics.csv"))
    assert {"B0_scada_alarms", "B1_mode_aware_z", "B2_cusum", "B3_isolation_forest"} <= set(m.baseline)
    assert m.composite_score.between(0, 100).all()
    p = load_predictions(os.path.join(out, "predictions_B1_mode_aware_z_validation.csv"))
    assert len(p) > 0
    return m


def test_baselines_starter(starter_dir, tmp_path):
    _run(starter_dir, str(tmp_path / "starter"))


def test_baselines_full_validation(full_dir, tmp_path):
    m = _run(full_dir, str(tmp_path / "full"))
    v = m[m.split == "validation"].set_index("baseline")
    assert v.loc["B1_mode_aware_z", "composite_score"] > v.loc["B0_scada_alarms", "composite_score"]
