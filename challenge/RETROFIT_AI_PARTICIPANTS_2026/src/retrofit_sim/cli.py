"""Command-line entry points: dataset generation, scoring, what-if sandbox and read-only replay."""
from __future__ import annotations

import argparse
import json
import sys


def dataset_main(argv=None) -> int:
    from .dataset import build
    p = argparse.ArgumentParser(prog="make_dataset.py", description="Generate the RETROFIT AI 2026 synthetic pump dataset.")
    p.add_argument("--tier", choices=["starter", "full", "stress"], default="starter")
    p.add_argument("--seed", type=int, default=None, help="Seed. Default: public seed from the fleet config (reproduces the published data).")
    p.add_argument("--output", required=True, help="Output directory (public/ and private/ are created inside).")
    p.add_argument("--profile", choices=["public", "test", "all"], default="public",
                   help="public = train+validation assets; test/all need the organizer --private-config.")
    p.add_argument("--private-config", default=None, help="Organizer-only test fleet configuration (YAML).")
    p.add_argument("--fleet-config", default=None, help="Alternative public fleet YAML.")
    p.add_argument("--assets", nargs="*", default=None, help="Subset of asset IDs.")
    p.add_argument("--days", type=float, default=None, help="Window length in days (default 7; stress 3).")
    p.add_argument("--no-snapshots", action="store_true", help="Skip vibration waveform snapshots.")
    p.add_argument("--stress-assets", type=int, default=6)
    p.add_argument("--label-fraction", type=float, default=0.3, help="Stress tier: share of events published as labels.")
    a = p.parse_args(argv)
    days = a.days if a.days is not None else (3.0 if a.tier == "stress" else 7.0)
    print(f"RETROFIT AI 2026 dataset | tier={a.tier} profile={a.profile} days={days} output={a.output}")
    rep = build(a.tier, a.seed, a.output, a.profile, a.private_config, a.fleet_config, a.assets, days,
                snapshots=not a.no_snapshots, stress_assets=a.stress_assets, label_fraction=a.label_fraction)
    rows = sum(v["telemetry_rows"] for v in rep["assets"].values())
    print(f"done: {len(rep['assets'])} assets, {rows} telemetry rows, {rep['seconds_total']} s")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: python -m retrofit_sim {what_if,replay,score,make_dataset} ...")
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "what_if":
        from .sandbox import what_if_main
        return what_if_main(rest)
    if cmd == "replay":
        from .replay import replay_main
        return replay_main(rest)
    if cmd == "score":
        from .scoring import score_main
        return score_main(rest)
    if cmd == "make_dataset":
        return dataset_main(rest)
    print(f"unknown command {cmd!r}", file=sys.stderr)
    return 2
