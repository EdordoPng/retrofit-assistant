#!/usr/bin/env python3
"""RETROFIT AI 2026 - dataset generator CLI.

Examples
  python make_dataset.py --tier starter --output build/starter
  python make_dataset.py --tier full    --output build/full                 # train + validation (public seed)
  python make_dataset.py --tier stress  --seed 7 --output build/stress      # unseen random assets, scarce labels
  python make_dataset.py --tier full --profile all --private-config <organizer yaml> --output build/full_all
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from retrofit_sim.cli import dataset_main  # noqa: E402

if __name__ == "__main__":
    sys.exit(dataset_main(sys.argv[1:]))
