import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
FULL = os.environ.get("RETROFIT_DATA_FULL", os.path.join(ROOT, "data", "full"))
STARTER = os.environ.get("RETROFIT_DATA_STARTER", os.path.join(ROOT, "data", "starter"))


def need(path):
    if not os.path.exists(path):
        pytest.skip(f"data not present: {path} (generate with make_dataset.py)")
    return path


@pytest.fixture(scope="session")
def full_dir():
    return need(os.path.join(FULL, "assets.csv")) and FULL


@pytest.fixture(scope="session")
def starter_dir():
    return need(os.path.join(STARTER, "assets.csv")) and STARTER


@pytest.fixture(scope="session")
def fleet():
    from retrofit_sim.fleet import load_fleet
    return load_fleet(os.path.join(ROOT, "configs", "fleet_public.yaml"))
