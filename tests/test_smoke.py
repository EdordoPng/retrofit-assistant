from pathlib import Path

import pandas as pd
from retrofit_sim.scoring import score


PACKAGE = Path(__file__).resolve().parents[1] / "challenge" / "RETROFIT_AI_PARTICIPANTS_2026"
DATA = PACKAGE / "data" / "full"


def test_parquet_utc_timestamp():
    frame = pd.read_parquet(
        DATA / "features_1min.parquet",
        columns=["window_start_utc"],
        filters=[("asset_id", "==", "PUMP-08")],
    )
    assert not frame.empty
    assert isinstance(frame["window_start_utc"].dtype, pd.DatetimeTZDtype)
    assert str(frame["window_start_utc"].dt.tz) == "UTC"


def test_official_scorer_validation_baseline():
    result = score(
        PACKAGE / "baselines" / "results" / "predictions_B1_mode_aware_z_validation.csv",
        pd.read_csv(DATA / "events_validation.csv"),
        pd.read_csv(DATA / "assets.csv"),
        pd.read_csv(DATA / "benign_windows_train_validation.csv"),
        split="validation",
    )
    assert round(result["composite_score"], 1) == 78.0
