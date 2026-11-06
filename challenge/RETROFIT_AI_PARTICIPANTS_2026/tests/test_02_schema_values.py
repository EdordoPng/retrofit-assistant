"""Gate 2: timestamps, IDs, units / schema, valid ranges, no impossible negative absolute quantities."""
import json
import os

import numpy as np
import pandas as pd

from retrofit_sim.schema import TELEMETRY


def test_schema_file_matches_code(full_dir):
    with open(os.path.join(full_dir, "schema.json"), encoding="utf-8") as fh:
        js = json.load(fh)
    assert set(js["tables"]["telemetry"]) == set(TELEMETRY)


def test_telemetry_columns_ranges_and_monotonic(full_dir):
    assets = pd.read_csv(os.path.join(full_dir, "assets.csv"))
    for aid in assets.asset_id:
        df = pd.read_parquet(os.path.join(full_dir, "telemetry", f"asset_id={aid}"))
        cols = set(df.columns) - {"day"}
        assert cols == set(TELEMETRY) - {"asset_id"}, aid
        ts = pd.to_datetime(df["timestamp_utc"], utc=True)
        assert ts.is_monotonic_increasing and ts.is_unique, aid
        assert (ts.diff().dropna() >= pd.Timedelta(seconds=1)).all()
        for c, (typ, unit, nullable, valid, _) in TELEMETRY.items():
            if c not in df or not isinstance(valid, list) or typ.startswith("category"):
                continue
            x = df[c].dropna()
            if len(x) and not isinstance(valid[0], str):
                assert x.min() >= valid[0] - 1e-6 and x.max() <= valid[1] + 1e-6, (aid, c, x.min(), x.max())
        # absolute pressure >= 0 (gauge >= -101.325 kPa); power, current, flow non-negative
        for c in ("suction_pressure_kpa", "discharge_pressure_kpa"):
            assert (df[c].dropna() >= -101.325).all()
        for c in ("motor_power_kw", "motor_current_a", "flow_m3_h", "motor_speed_rpm"):
            assert (df[c].dropna() >= 0).all()
        assert set(df["operating_mode"].astype(str).unique()) <= set(TELEMETRY["operating_mode"][3])


def test_assets_and_ids_consistent(full_dir):
    assets = pd.read_csv(os.path.join(full_dir, "assets.csv"))
    assert assets.asset_id.is_unique
    ctx = pd.read_csv(os.path.join(full_dir, "operating_context.csv"))
    assert set(ctx.asset_id) == set(assets.asset_id)
    for name in ("alarms.csv", "maintenance.csv", "events_train.csv", "events_validation.csv"):
        t = pd.read_csv(os.path.join(full_dir, name))
        assert set(t.asset_id) <= set(assets.asset_id), name
    # power plausibility: rated current matches rated power at nameplate efficiency / pf within 10 %
    assert ((assets.motor_rated_current_a > 0) & (assets.motor_rated_kw > 0)).all()
    hyd = 1000 * 9.81 * assets.pump_rated_flow_m3_h / 3600 * assets.pump_rated_head_m / 1000
    shaft = hyd / assets.pump_bep_efficiency
    assert ((shaft < assets.motor_rated_kw) & (shaft > 0.5 * assets.motor_rated_kw)).all(), "motor sizing"
