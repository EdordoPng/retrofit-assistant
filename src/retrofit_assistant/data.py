"""Runtime inputs and the time at which their contents become available."""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class InputContract:
    time_column: str | None
    latency: pd.Timedelta


AVAILABILITY = {
    "assets.csv": InputContract(None, pd.Timedelta(0)),
    "features_1min.parquet": InputContract("window_start_utc", pd.Timedelta(seconds=60)),
    "vibration_snapshots.parquet": InputContract("timestamp_utc", pd.Timedelta(seconds=1)),
}


def _read_input(data, name, **kwargs) -> pd.DataFrame:
    if name not in AVAILABILITY:
        raise ValueError(f"Input outside availability contract: {name}")
    path = Path(data) / name
    if name.endswith(".parquet"):
        return pd.read_parquet(path, **kwargs)
    return pd.read_csv(path, **kwargs)


def load_assets(data, split=None) -> pd.DataFrame:
    """Read static metadata, optionally restricted to one benchmark split."""
    if split not in (None, "train", "validation", "test"):
        raise ValueError(f"Invalid split: {split}")
    assets = _read_input(data, "assets.csv")
    for column in ("window_start_utc", "window_end_utc"):
        assets[column] = pd.to_datetime(assets[column], utc=True)
    if split is not None:
        assets = assets.loc[assets["split"] == split]
    return assets.reset_index(drop=True)


def load_features(data, assets, until=None) -> pd.DataFrame:
    """Read completed minutes for the selected assets, anchoring missing grid ends."""
    if until is not None:
        until = pd.Timestamp(until)
        if until.tzinfo is None:
            raise ValueError("until must be timezone-aware")
        until = until.tz_convert("UTC")
    contract = AVAILABILITY["features_1min.parquet"]
    column = contract.time_column
    asset_ids = assets["asset_id"].tolist()
    # Arrow cannot infer the type of an empty IN set. A contradictory string
    # predicate reads the schema without loading any asset's rows.
    filters = [("asset_id", "in", asset_ids)] if asset_ids else [
        ("asset_id", "==", ""), ("asset_id", "!=", ""),
    ]
    features = _read_input(
        data, "features_1min.parquet",
        filters=filters,
    )
    # Missing anchors require nullable values. Normalise integer columns even when
    # this particular run has no anchors, so prefixes keep the same schema.
    for name, dtype in features.dtypes.items():
        if pd.api.types.is_integer_dtype(dtype):
            features[name] = features[name].astype("float64")
    features["rows"] = features["rows"].astype("float64")
    dtypes = features.dtypes
    frames = []
    for asset in assets.itertuples(index=False):
        horizon = asset.window_end_utc
        if until is not None:
            horizon = min(until, horizon)
        if horizon < asset.window_start_utc + contract.latency:
            continue
        group = features.loc[
            (features["asset_id"] == asset.asset_id)
            & (features[column] + contract.latency <= horizon)
        ].copy()
        last = horizon.floor("min") - contract.latency
        anchors = pd.DatetimeIndex([asset.window_start_utc, last]).astype(dtypes[column]).unique()
        group = group.set_index(column)
        group = group.reindex(group.index.union(anchors).sort_values())
        group.index.name = column
        group["asset_id"] = asset.asset_id
        frames.append(group.reset_index()[features.columns].astype(dtypes))
    if not frames:
        return features.iloc[:0].reset_index(drop=True)
    return pd.concat(frames, ignore_index=True).astype(dtypes)


def load_snapshots(data, assets, until=None) -> pd.DataFrame:
    """Read selected assets' one-second captures, completed by ``until``."""
    if until is not None:
        until = pd.Timestamp(until)
        if until.tzinfo is None:
            raise ValueError("until must be timezone-aware")
        until = until.tz_convert("UTC")
    asset_ids = assets["asset_id"].tolist()
    filters = [("asset_id", "in", asset_ids)] if asset_ids else [
        ("asset_id", "==", ""), ("asset_id", "!=", ""),
    ]
    snapshots = _read_input(data, "vibration_snapshots.parquet", filters=filters)
    contract = AVAILABILITY["vibration_snapshots.parquet"]
    snapshots[contract.time_column] = pd.to_datetime(snapshots[contract.time_column], utc=True)
    if until is not None:
        snapshots = snapshots.loc[snapshots[contract.time_column] + contract.latency <= until]
    return snapshots.reset_index(drop=True)
