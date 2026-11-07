import argparse
from datetime import datetime
from pathlib import Path
import re
import sys

from .data import load_assets
from .output import Check, validate_file, write_predictions
from .pipeline import run_detector


def _test_destination(path):
    destination = Path(path)
    if destination.resolve().parent != (Path("build") / "submission").resolve():
        return False
    match = re.fullmatch(r"predictions_test_([0-9]{8}T[0-9]{6}Z)_[0-9a-fA-F]{7,40}\.csv", destination.name)
    if match is None:
        return False
    try:
        datetime.strptime(match[1], "%Y%m%dT%H%M%SZ")
    except ValueError:
        return False
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m retrofit_assistant",
        description="Advisory-only operator assistance for the RETROFIT AI challenge.",
    )
    commands = parser.add_subparsers(dest="command")
    predict = commands.add_parser("predict", help="Write advisory predictions")
    predict.add_argument("--data", required=True)
    predict.add_argument("--split", choices=("train", "validation", "test"), required=True)
    predict.add_argument("--out", required=True)
    predict.add_argument("--detector", choices=("full", "causal_b1"), default="full")
    predict.add_argument("--mask-tier", choices=("T1", "T0"))
    check = commands.add_parser("check-submission", help="Validate a prediction CSV")
    check.add_argument("--predictions", required=True)
    check.add_argument("--data", required=True)
    check.add_argument("--split", choices=("train", "validation", "test"), required=True)
    compare = commands.add_parser("compare", help="Compare train and validation scores")
    compare.add_argument("--data", required=True)
    compare.add_argument("--out", required=True)
    compare.add_argument("--gate", action="store_true")
    ablate = commands.add_parser("ablate", help="Compare T2 instruments with T1 and T0 masks")
    ablate.add_argument("--data", required=True)
    ablate.add_argument("--out", required=True)
    report_parser = commands.add_parser("report", help="Write a static operator report")
    report_parser.add_argument("--asset", required=True)
    report_parser.add_argument("--data", required=True)
    report_parser.add_argument("--predictions", required=True)
    report_parser.add_argument("--out", required=True)
    report_parser.add_argument("--until")
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "ablate":
        from . import ablation
        try:
            destination = ablation.ablate(args.data, args.out)
        except Exception as exc:
            print(f"Ablation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        print(destination)
        return 0
    if args.command == "report":
        from . import report
        try:
            destination = report.generate(args.asset, args.data, args.predictions, args.out, until=args.until)
        except report.Refused as exc:
            print(f"Report refused: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:
            print(f"Report failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        print(destination)
        return 0
    if args.command == "compare":
        try:
            from . import evaluate
            passed = evaluate.compare(args.data, args.out, use_gate=args.gate)
        except Exception as exc:
            print(f"Compare failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        if args.gate:
            print("GATE PASS" if passed else "GATE FAIL")
        return 0 if passed else 1
    if args.command == "predict":
        if args.split == "test" and args.mask_tier is not None:
            print("--mask-tier is limited to train and validation", file=sys.stderr)
            return 2
        if args.split == "test" and not _test_destination(args.out):
            print("Invalid test output path", file=sys.stderr)
            return 2
        try:
            frame = run_detector(args.data, args.split, detector=args.detector, mask_tier=args.mask_tier)
            write_predictions(frame, args.out)
        except Exception:
            print("Prediction failed", file=sys.stderr)
            return 1
        print(args.out)
        return 0
    try:
        assets = load_assets(args.data, args.split)
        result = validate_file(args.predictions, assets)
    except Exception:
        result = Check(False, 0, "file_unreadable")
    if result.passed:
        print(f"PASS rows={result.rows}")
        return 0
    print(f"FAIL rows={result.rows} rule={result.rule}")
    return 1
