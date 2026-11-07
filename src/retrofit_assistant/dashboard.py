"""Development-only dashboard: fleet overview from the per-pump JSON, then operator pages.

Numbers come only from the JSON passed as --table; nothing here recomputes them.
"""

import argparse
from html import escape
import json
from pathlib import Path
import sys

from . import report
from .pump_table import COUNTS, TEST_STATUS

HEADERS = ("Pump", "Split", "Tier", "Scored events", "Detected", "Type correct",
           "Class correct", "False-alert episodes", "Excess repeats")


def fleet_page(table, links):
    esc = lambda value: escape(str(value), quote=True)
    rows = []
    for pump in table["pumps"]:
        if pump["split"] == "test":
            if any(key in pump for key in COUNTS) or pump.get("status") != TEST_STATUS:
                raise ValueError(f"{pump['asset_id']}: test pumps carry only tier and status")
            rows.append(f'<tr><td>{esc(pump["asset_id"])}</td><td>test</td><td>{esc(pump["tier"])}</td>'
                        f'<td colspan="{len(COUNTS)}">{esc(TEST_STATUS)}</td></tr>')
            continue
        name = esc(pump["asset_id"])
        cell = f'<a href="{esc(links[pump["asset_id"]])}">{name}</a>' if pump["asset_id"] in links else name
        rows.append(f'<tr><td>{cell}</td><td>{esc(pump["split"])}</td><td>{esc(pump["tier"])}</td>'
                    + "".join(f"<td>{esc(pump[key])}</td>" for key in COUNTS) + "</tr>")
    for split, total in table["split_totals"].items():
        rows.append(f"<tr><th>{esc(split)} total</th><td>{esc(split)}</td><td>mixed</td>"
                    + "".join(f"<th>{esc(total[key])}</th>" for key in COUNTS) + "</tr>")
    roles = "".join(f"<li><strong>{esc(split)}:</strong> {esc(role)}</li>"
                    for split, role in table["split_roles"].items())
    composite = ", ".join(f"{esc(split)} {total['composite']:.3f}" for split, total in table["split_totals"].items())
    ablation = "".join(
        f"<tr><td>{esc(a['tier'])}</td><td>{esc(a['split'])}</td><td>{esc(', '.join(a['assets']))}</td>"
        f"<td>{a['composite']:.3f}</td><td>{esc(a['detected'])} / {esc(a['scored_events'])}</td><td>{esc(a['type_correct'])}</td></tr>"
        for a in table["ablation"])
    notes = "".join(f"<li>{esc(note)}</li>" for note in table["notes"])
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Fleet overview</title>
<style>{report.CSS}</style></head><body><h1>Fleet overview</h1>
<p><strong>Advisory only: human review required.</strong> Generated at commit {esc(table["commit"])}.</p>
<table><thead><tr>{"".join(f"<th>{h}</th>" for h in HEADERS)}</tr></thead><tbody>{"".join(rows)}</tbody></table>
<p>Official composite: {composite}.</p><h2>What each split means</h2><ul>{roles}</ul>
<h2>Instrumentation ablation (same T2 events, channels masked)</h2>
<table><thead><tr><th>Tier</th><th>Split</th><th>Pumps</th><th>Composite</th><th>Detected / scored</th><th>Type correct</th></tr></thead>
<tbody>{ablation}</tbody></table><ul>{notes}</ul></body></html>'''


def build(table_path, data, predictions, out):
    destination = Path(out)
    if not destination.resolve().is_relative_to(Path("build").resolve()):
        raise ValueError("Dashboard output must be inside build/")
    table = json.loads(Path(table_path).read_text(encoding="utf-8"))
    # Validate the held-out rows before loading any operator-page inputs.
    fleet_page(table, {})
    links = {}
    for pump in table["pumps"]:
        if pump["split"] in ("train", "validation") and pump["split"] in predictions:
            page = report.generate(pump["asset_id"], data, predictions[pump["split"]], destination)
            links[pump["asset_id"]] = page.name
    index = destination / "index.html"
    destination.mkdir(parents=True, exist_ok=True)
    index.write_text(fleet_page(table, links), encoding="utf-8")
    return index


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m retrofit_assistant.dashboard")
    parser.add_argument("--table", required=True, help="build/scores/pump_table.json")
    parser.add_argument("--data", required=True)
    parser.add_argument("--train-predictions", required=True)
    parser.add_argument("--validation-predictions", required=True)
    parser.add_argument("--out", default="build/dashboard")
    args = parser.parse_args(argv)
    predictions = {"train": args.train_predictions, "validation": args.validation_predictions}
    print(build(args.table, args.data, predictions, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
