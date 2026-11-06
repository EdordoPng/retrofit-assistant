#!/usr/bin/env python3
"""Illustrative business-logic example for one retrofitted pump (NOT a realized saving; every input is an assumption).

Links the benchmark metrics (event recall, false alerts per asset-day, lead time) to money, so teams can argue
business usefulness with their own measured numbers. Writes examples/business_case_output.md.

  python examples/business_case.py [--recall 0.75] [--fa-per-day 0.07]
"""
import argparse
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BASE = {  # name: (value, unit, basis)
    "events_per_year": (0.6, "1/yr", "assumption: developing faults that would otherwise end in an unplanned stop (bearing, clogging/cavitation, restriction) for one duty pump"),
    "recall": (0.75, "-", "measured: B1 baseline validation event recall (replace with your own)"),
    "fa_per_day": (0.07, "1/asset-day", "measured: B1 baseline validation false + excess-repeat alerts per asset-day"),
    "unplanned_stop_h": (10.0, "h", "assumption: detection by failure, diagnosis, parts, repair"),
    "planned_stop_h": (3.0, "h", "assumption: same work prepared and done in a planned window"),
    "downtime_cost_eur_h": (1500.0, "EUR/h", "assumption: production loss of a mid-size process line with no redundant pump"),
    "repair_unplanned_eur": (9000.0, "EUR", "assumption within a typical EUR 3-15 k small/medium pump overhaul range (itself an estimate)"),
    "repair_planned_eur": (4000.0, "EUR", "assumption: damage limited when caught early (e.g. bearing only, no shaft/seal damage)"),
    "false_alert_cost_eur": (120.0, "EUR", "assumption: ~1.5 h of technician/operator time to check a false alert"),
    "capex_eur": (4500.0, "EUR", "BOM option B ~EUR 2.1-2.4 k (built from list prices, RETROFIT_FEASIBILITY.md section 2) + cabling, enclosure, installation ~EUR 2 k (assumption)"),
    "opex_eur_yr": (700.0, "EUR/yr", "assumption: connectivity, software maintenance, battery/sensor replacements"),
}


LABEL = {"events_per_year": "Developing faults per year", "recall": "Share caught early (recall)", "fa_per_day": "False + excess alerts per pump-day",
         "unplanned_stop_h": "Unplanned stop duration", "planned_stop_h": "Planned stop duration", "downtime_cost_eur_h": "Downtime cost",
         "repair_unplanned_eur": "Repair cost, unplanned", "repair_planned_eur": "Repair cost, planned", "false_alert_cost_eur": "Cost of checking one false alert",
         "capex_eur": "Installed cost (hardware + installation)", "opex_eur_yr": "Operating cost"}

def evaluate(p):
    caught = p["events_per_year"] * p["recall"]
    benefit = caught * ((p["unplanned_stop_h"] - p["planned_stop_h"]) * p["downtime_cost_eur_h"]
                        + p["repair_unplanned_eur"] - p["repair_planned_eur"])
    nuisance = p["fa_per_day"] * 365 * p["false_alert_cost_eur"]
    net = benefit - nuisance - p["opex_eur_yr"]
    payback = p["capex_eur"] / net if net > 0 else float("inf")
    return {"caught_per_yr": caught, "benefit": benefit, "nuisance": nuisance, "net": net, "payback_yr": payback}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recall", type=float, default=None)
    ap.add_argument("--fa-per-day", type=float, default=None)
    ap.add_argument("--out", default=os.path.join(ROOT, "examples", "business_case_output.md"))
    a = ap.parse_args()
    p = {k: v[0] for k, v in BASE.items()}
    if a.recall is not None:
        p["recall"] = a.recall
    if a.fa_per_day is not None:
        p["fa_per_day"] = a.fa_per_day
    r = evaluate(p)
    L = ["# Illustrative business case: one retrofitted duty pump (synthetic scenario)", "",
         "All inputs are assumptions or benchmark measurements on synthetic data. This is a worked example of the business "
         "logic, not a realized or expected saving for any real site.", "", "## Inputs", "",
         "| Input | Value | Unit | Basis |", "|---|---|---|---|"]
    L += [f"| {LABEL[k]} | {p[k]:g} | {BASE[k][1]} | {BASE[k][2]} |" for k in BASE]
    L += ["", "## Result (base case)", "",
          f"- Faults caught early per year: {r['caught_per_yr']:.2f}",
          f"- Avoided downtime and repair cost: EUR {r['benefit']:,.0f} per year",
          f"- False-alert handling cost: EUR {r['nuisance']:,.0f} per year",
          f"- Net annual effect after operating cost: EUR {r['net']:,.0f}",
          f"- Simple payback on EUR {p['capex_eur']:,.0f} installed cost: "
          + (f"{r['payback_yr']:.1f} years" if r['payback_yr'] != float('inf') else "never (net effect not positive)"), "",
          "## Sensitivity (one input changed at a time)", "", "| Input | Low | High | Net EUR/yr at low | Net EUR/yr at high | Payback at low | Payback at high |",
          "|---|---|---|---|---|---|---|"]
    fmt = lambda x: "never" if x == float("inf") else f"{x:.1f} yr"
    for k, (lo, hi) in {"events_per_year": (0.2, 1.2), "recall": (0.4, 0.95), "fa_per_day": (0.0, 0.5),
                        "downtime_cost_eur_h": (0.0, 5000.0), "repair_unplanned_eur": (5000.0, 15000.0), "capex_eur": (2500.0, 12000.0)}.items():
        rl, rh = evaluate(dict(p, **{k: lo})), evaluate(dict(p, **{k: hi})),
        L.append(f"| {LABEL[k]} | {lo:g} | {hi:g} | {rl['net']:,.0f} | {rh['net']:,.0f} | {fmt(rl['payback_yr'])} | {fmt(rh['payback_yr'])} |")
    # break-even downtime cost
    lo, hi = 0.0, 50000.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if evaluate(dict(p, downtime_cost_eur_h=mid))["net"] > p["capex_eur"] / 5:
            hi = mid
        else:
            lo = mid
    ship = evaluate(dict(p, downtime_cost_eur_h=0.0, events_per_year=0.3))
    L += ["", "## Break-even and redundancy", "",
          f"- Break-even: with these assumptions, a 5-year payback needs a downtime cost of about EUR {hi:,.0f} per hour.",
          f"- Redundant duty/standby pump (e.g. a ship seawater pump with a healthy standby, downtime cost about 0) and "
          f"0.3 events per year: net effect EUR {ship['net']:,.0f} per year, so payback "
          f"{fmt(ship['payback_yr'])}. Here the case rests on repair-cost avoidance, energy (drive retrofits are a separate, "
          "documented lever) and crew time, not on downtime.",
          "- Each false alert per asset-day costs about EUR " + f"{365 * p['false_alert_cost_eur']:,.0f}" + " per year in "
          "checks alone and erodes operator trust; the benchmark weights alert burden for this reason.",
          ""]
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
