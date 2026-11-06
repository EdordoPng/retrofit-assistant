"""Gate 6: missing data, dropouts, corrupt readings and drift parse and are handled."""
import os

import numpy as np
import pandas as pd

from retrofit_sim import baselines as B


def test_nullable_channels_and_quality_flags(full_dir):
    a = pd.read_csv(os.path.join(full_dir, "assets.csv"))
    legacy = a[a.instrumentation_tier == "T0_LEGACY"].asset_id.iloc[0]
    t = pd.read_parquet(os.path.join(full_dir, "telemetry", f"asset_id={legacy}"))
    assert t.vibration_rms_mm_s.isna().all() and t.flow_m3_h.isna().all()
    allq = pd.concat([pd.read_parquet(os.path.join(full_dir, "telemetry", f"asset_id={x}"), columns=["quality_flags"]) for x in a.asset_id])
    assert (allq.quality_flags & 16).any()                  # start-up inhibit present
    assert ((allq.quality_flags >= 0) & (allq.quality_flags < 32)).all()


def test_gateway_outage_rows_absent_and_detected(full_dir):
    t = pd.read_parquet(os.path.join(full_dir, "telemetry", "asset_id=PUMP-01"), columns=["timestamp_utc"])
    gaps = pd.to_datetime(t.timestamp_utc, utc=True).diff().dt.total_seconds()
    assert gaps.max() > 1800                                 # a multi-hour gateway outage
    feat = pd.read_parquet(os.path.join(full_dir, "features_1min.parquet"))
    f = B.regime_frame(feat[feat.asset_id == "PUMP-01"], pd.read_csv(os.path.join(full_dir, "assets.csv")))
    assert (f["rows"] == 0).sum() > 60                       # gap minutes reconstructed on the 1-min grid


def test_sparse_wireless_channels(full_dir):
    t = pd.read_parquet(os.path.join(full_dir, "telemetry", "asset_id=PUMP-01"), columns=["vibration_rms_mm_s", "motor_current_a"])
    share = t.vibration_rms_mm_s.notna().mean()
    assert 0.001 < share < 0.01                              # one value per 300 s
    assert t.motor_current_a.notna().mean() > 0.99


def test_starter_csv_parses(starter_dir):
    t = pd.read_csv(os.path.join(starter_dir, "telemetry.csv.gz"))
    assert len(t) > 100000 and t.timestamp_utc.str.endswith("Z").all()
    pd.to_datetime(t.timestamp_utc, utc=True)
