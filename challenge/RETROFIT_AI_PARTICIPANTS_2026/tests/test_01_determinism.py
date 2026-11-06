"""Gate 1: deterministic regeneration (same seed -> identical content; published data reproducible)."""
import hashlib
import os

import numpy as np
import pandas as pd

from retrofit_sim import generate as G
from retrofit_sim.dataset import enrich_asset


def _hash(df):
    return hashlib.sha256(pd.util.hash_pandas_object(df.reset_index(drop=True), index=False).values.tobytes()).hexdigest()


def test_same_seed_same_content(fleet):
    cfg, assets = fleet
    a = enrich_asset(next(x for x in assets if x["asset_id"] == "PUMP-06"))
    r1 = G.simulate_asset(a, cfg["public_seed"], 1.0)
    r2 = G.simulate_asset(a, cfg["public_seed"], 1.0)
    assert _hash(G.telemetry_frame(r1)) == _hash(G.telemetry_frame(r2))
    assert pd.DataFrame(G.events_for(r1)).equals(pd.DataFrame(G.events_for(r2)))
    assert pd.DataFrame(G.alarms_for(r1)).equals(pd.DataFrame(G.alarms_for(r2)))


def test_different_seed_different_trajectory(fleet):
    cfg, assets = fleet
    a = enrich_asset(next(x for x in assets if x["asset_id"] == "PUMP-06"))
    t1 = G.telemetry_frame(G.simulate_asset(a, cfg["public_seed"], 0.5, want_detectability=False))
    t2 = G.telemetry_frame(G.simulate_asset(a, cfg["public_seed"] + 1, 0.5, want_detectability=False))
    assert _hash(t1) != _hash(t2)


def test_published_telemetry_is_reproducible(fleet, full_dir):
    """Regenerate one published asset (7 days) from the public config and compare with the shipped Parquet."""
    cfg, assets = fleet
    a = enrich_asset(next(x for x in assets if x["asset_id"] == "PUMP-03"))
    res = G.simulate_asset(a, cfg["public_seed"], 7.0, want_detectability=False)
    regen = G.telemetry_frame(res).drop(columns=["asset_id"])
    pub = pd.read_parquet(os.path.join(full_dir, "telemetry", "asset_id=PUMP-03"))
    pub = pub.drop(columns=[c for c in ("day", "asset_id") if c in pub.columns]).sort_values("timestamp_utc").reset_index(drop=True)
    assert len(pub) == len(regen)
    for c in regen.columns:
        if c == "timestamp_utc":
            assert (pd.to_datetime(pub[c], utc=True).values == pd.to_datetime(regen[c], utc=True).values).all()
        elif regen[c].dtype.kind == "f":
            np.testing.assert_array_equal(pub[c].to_numpy(dtype="float32"), regen[c].to_numpy(dtype="float32"))
        else:
            assert (pub[c].astype(str).values == regen[c].astype(str).values).all(), c
