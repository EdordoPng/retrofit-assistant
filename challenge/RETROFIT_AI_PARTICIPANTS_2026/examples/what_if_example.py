#!/usr/bin/env python3
"""Sandbox what-if examples (simulation only): three proposals, one accepted, two rejected with reasons."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from retrofit_sim.sandbox import what_if  # noqa: E402

D = os.path.join(ROOT, "data", "full")
cases = [
    ("Raise SW pump speed while a clogged strainer is suspected", "PUMP-01", "2025-08-12T15:00:00Z", "speed_setpoint", 0.72, {"clog": 2.0}),
    ("Slow the SW pump to save energy (too far)", "PUMP-01", "2025-08-12T15:00:00Z", "speed_setpoint", 0.50, {}),
    ("Clean the strainer of the cavitating process pump", "PUMP-06", "2025-10-09T21:50:00Z", "clean_strainer", None, {"clog": 5.5}),
    ("Speed change on a direct-on-line pump", "PUMP-03", "2026-03-04T10:00:00Z", "speed_setpoint", 0.8, {}),
]
for title, aid, t, act, val, hyp in cases:
    r = what_if(D, aid, t, act, val, hyp)
    print(f"\n== {title}\n   {aid} {t} action={act} value={val} hypothesis={hyp}")
    print(f"   accepted: {r['accepted']}  reasons: {r['rejection_reasons']}  warnings: {r.get('warnings')}")
    if "baseline" in r:
        for k in ("speed_ratio", "flow_m3h", "duty_satisfaction", "input_kw", "npsh_margin", "vib_rms_mm_s", "risk_proxy", "energy_eur_per_day"):
            print(f"   {k:20s} baseline={r['baseline'][k]!s:>10}  proposed={r['proposed'][k]!s:>10}")
        print(f"   intervention cost estimate: {r['intervention']['estimated_cost_eur']} EUR (assumptions in output JSON)")
print("\nFull JSON of the first case:\n" + json.dumps(what_if(D, *cases[0][1:]), indent=1)[:1500] + " ...")
