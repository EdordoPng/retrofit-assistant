"""Gate 9: the what-if sandbox rejects infeasible actions and does not corrupt state."""
import hashlib
import os

from retrofit_sim.sandbox import what_if


def _digest(d):
    h = hashlib.sha256()
    for f in sorted(os.listdir(d)):
        p = os.path.join(d, f)
        if os.path.isfile(p):
            h.update(open(p, "rb").read())
    return h.hexdigest()


def test_rejections(full_dir):
    assert not what_if(full_dir, "PUMP-03", "2026-03-04T10:00:00Z", "speed_setpoint", 0.8)["accepted"]      # DOL pump
    r = what_if(full_dir, "PUMP-01", "2025-08-12T15:00:00Z", "speed_setpoint", 0.5)                      # too little flow
    assert not r["accepted"] and any("duty" in x or "step" in x for x in r["rejection_reasons"])
    assert not what_if(full_dir, "PUMP-01", "2025-08-12T15:00:00Z", "speed_setpoint", 1.3)["accepted"]     # beyond drive limit
    assert not what_if(full_dir, "PUMP-01", "2030-01-01T00:00:00Z", "none")["accepted"]                    # outside window
    assert not what_if(full_dir, "PUMP-01", "2025-08-12T15:00:00Z", "launch_rocket")["accepted"]
    assert not what_if(full_dir, "PUMP-01", "2025-08-12T15:00:00Z", "none", hypothesis={"clog": 99})["accepted"]


def test_feasible_action_and_no_side_effects(full_dir):
    before = _digest(full_dir)
    r1 = what_if(full_dir, "PUMP-01", "2025-08-12T15:00:00Z", "speed_setpoint", 0.72, {"clog": 2.0})
    r2 = what_if(full_dir, "PUMP-01", "2025-08-12T15:00:00Z", "speed_setpoint", 0.72, {"clog": 2.0})
    assert r1["accepted"] and r1 == r2
    assert r1["proposed"]["input_kw"] > r1["baseline"]["input_kw"]          # faster -> more power
    c = what_if(full_dir, "PUMP-06", "2025-10-09T21:50:00Z", "clean_strainer", hypothesis={"clog": 5.5})
    assert c["accepted"] and c["proposed"]["npsh_margin"] > c["baseline"]["npsh_margin"]
    assert _digest(full_dir) == before
