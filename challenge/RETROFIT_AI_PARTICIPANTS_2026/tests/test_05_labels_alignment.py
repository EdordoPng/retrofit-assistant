"""Gate 5: anomaly / maintenance distribution and labels aligned with the time series."""
import os

import numpy as np
import pandas as pd


def _load(full_dir):
    a = pd.read_csv(os.path.join(full_dir, "assets.csv"))
    ev = pd.concat([pd.read_csv(os.path.join(full_dir, f)) for f in ("events_train.csv", "events_validation.csv")])
    for c in ("onset_utc", "detectable_utc", "action_deadline_utc", "end_utc"):
        ev[c] = pd.to_datetime(ev[c], utc=True, format="ISO8601")
    return a, ev


def test_event_times_ordered_and_inside_windows(full_dir):
    a, ev = _load(full_dir)
    ws = dict(zip(a.asset_id, pd.to_datetime(a.window_start_utc, utc=True)))
    we = dict(zip(a.asset_id, pd.to_datetime(a.window_end_utc, utc=True)))
    for _, e in ev.iterrows():
        assert ws[e.asset_id] <= e.onset_utc < we[e.asset_id]
        if pd.notna(e.detectable_utc):
            assert e.detectable_utc >= e.onset_utc
        if pd.notna(e.end_utc):
            assert e.end_utc > e.onset_utc and e.end_utc <= we[e.asset_id]
        if pd.notna(e.action_deadline_utc):
            assert e.action_deadline_utc >= e.onset_utc


def test_fault_coverage_in_training_split(full_dir):
    a, ev = _load(full_dir)
    tr = ev[ev.asset_id.isin(a[a.split == "train"].asset_id)]
    need_machine = {"BEARING_WEAR", "SUCTION_STRAINER_CLOGGING", "CAVITATION", "DISCHARGE_RESTRICTION", "MISALIGNMENT", "IMBALANCE"}
    need_sensor = {"SENSOR_DRIFT", "SENSOR_STUCK", "SENSOR_CALIBRATION_SHIFT", "COMMUNICATION_LOSS"}
    assert need_machine <= set(tr.fault_type) and need_sensor <= set(tr.fault_type)
    assert (tr.observable == False).any(), "at least one fault invisible to legacy instrumentation"  # noqa: E712
    assert tr.root_cause_event_id.notna().any(), "compound incidents present"


def test_repairs_have_maintenance_records(full_dir):
    a, ev = _load(full_dir)
    mt = pd.read_csv(os.path.join(full_dir, "maintenance.csv"))
    mt["start_utc"] = pd.to_datetime(mt.start_utc, utc=True, format="ISO8601")
    rep = ev[ev.end_utc.notna() & (ev.event_class == "MACHINE") & (ev.fault_type != "CAVITATION") & (ev.fault_type != "AIR_ENTRAINMENT")]
    for _, e in rep.iterrows():
        m = mt[(mt.asset_id == e.asset_id) & mt.in_window & ((mt.start_utc - e.end_utc).abs() < pd.Timedelta(minutes=5))]
        assert len(m) >= 1, e.event_id


def test_signal_changes_inside_event(full_dir):
    """Suction pressure falls during the PUMP-06 strainer clogging event (observable label really is visible)."""
    a, ev = _load(full_dir)
    e = ev[(ev.asset_id == "PUMP-06") & (ev.fault_type == "SUCTION_STRAINER_CLOGGING")].iloc[0]
    t = pd.read_parquet(os.path.join(full_dir, "telemetry", "asset_id=PUMP-06"))
    t["timestamp_utc"] = pd.to_datetime(t.timestamp_utc, utc=True)
    run = t.operating_mode.astype(str) == "RUNNING"
    pre = t[run & (t.timestamp_utc < e.onset_utc) & (t.timestamp_utc > e.onset_utc - pd.Timedelta(hours=12))]
    late = t[run & (t.timestamp_utc < e.end_utc) & (t.timestamp_utc > e.end_utc - pd.Timedelta(hours=6))]
    assert late.suction_pressure_kpa.median() < pre.suction_pressure_kpa.median() - 10


def test_alarms_are_not_labels(full_dir):
    al = pd.read_csv(os.path.join(full_dir, "alarms.csv"))
    assert not {"fault_type", "event_id"} & set(al.columns)
