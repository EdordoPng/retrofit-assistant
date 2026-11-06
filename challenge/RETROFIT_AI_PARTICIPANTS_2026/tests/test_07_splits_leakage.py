"""Gate 7 (participant side): split disjointness and absence of hidden labels in the public data."""
import os

import pandas as pd

PRIVATE_NAMES = ("events_test", "benign_windows_test", "truth_1min", "maintenance_hidden_in_window", "fleet_test_private",
                 "generation_record")


def test_assets_and_windows_disjoint(full_dir):
    a = pd.read_csv(os.path.join(full_dir, "assets.csv"))
    assert a.asset_id.is_unique
    a["s"], a["e"] = pd.to_datetime(a.window_start_utc, utc=True), pd.to_datetime(a.window_end_utc, utc=True)
    for i, x in a.iterrows():
        for j, y in a.iterrows():
            if i < j and x.split != y.split:
                assert x.e <= y.s or y.e <= x.s, f"time overlap between {x.asset_id} ({x.split}) and {y.asset_id} ({y.split})"


def test_events_do_not_span_splits(full_dir):
    a = pd.read_csv(os.path.join(full_dir, "assets.csv"))
    tr = pd.read_csv(os.path.join(full_dir, "events_train.csv"))
    va = pd.read_csv(os.path.join(full_dir, "events_validation.csv"))
    assert set(tr.asset_id) <= set(a[a.split == "train"].asset_id)
    assert set(va.asset_id) <= set(a[a.split == "validation"].asset_id)
    assert not set(tr.event_id) & set(va.event_id)


def test_no_private_files_or_test_labels_in_public_tree(full_dir):
    root = os.path.dirname(os.path.dirname(full_dir))
    test_ids = set(pd.read_csv(os.path.join(full_dir, "assets.csv")).query("split == 'test'").asset_id)
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in ("organizer", "build", ".git")]   # organizer workspace only, never shipped
        for f in files:
            assert not any(p in f for p in PRIVATE_NAMES), os.path.join(d, f)
            if f.startswith("events_") and f.endswith(".csv"):
                ev = pd.read_csv(os.path.join(d, f))
                assert not set(ev.asset_id) & test_ids, f
    mt = pd.read_csv(os.path.join(full_dir, "maintenance.csv"))
    assert not mt[mt.asset_id.isin(test_ids)].in_window.any(), "test-asset in-window work orders would reveal labels"
