"""Mandatory emission guarantees for reference detector candidates."""

import pandas as pd

from .data import AVAILABILITY
from .params import ALERT_SPACING_MIN, EVENT_CLASSES, FAULT_TYPES, STOP_MODES


def apply_guarantees(candidates, minutes, assets) -> pd.DataFrame:
    """Space alerts per pump and discard emissions crossing a known stopped minute."""
    columns = [
        "asset_id", "alert_time_utc", "event_class", "fault_type", "confidence",
        "evidence", "recommended_action",
    ]
    for name, frame, required in (
        ("candidates", candidates, columns),
        ("minutes", minutes, ["asset_id", "window_start_utc", "operating_mode"]),
        ("assets", assets, ["asset_id", "window_end_utc"]),
    ):
        missing = [column for column in required if column not in frame.columns]
        if missing:
            raise ValueError(f"{name} is missing columns: {missing}")
    for column, allowed in (("event_class", EVENT_CLASSES), ("fault_type", FAULT_TYPES)):
        if not all(isinstance(value, str) and value in allowed for value in candidates[column]):
            raise ValueError(f"Invalid {column}: expected one allowed string per alert")
    result = candidates[columns].copy().reset_index(drop=True)
    if result.empty:
        return result
    times = pd.to_datetime(result["alert_time_utc"], utc=True)
    ends = dict(zip(assets["asset_id"], pd.to_datetime(assets["window_end_utc"], utc=True)))
    stopped = minutes.loc[minutes["operating_mode"].isin(STOP_MODES)]
    latency = AVAILABILITY["features_1min.parquet"].latency
    stop_times = {
        asset_id: pd.DatetimeIndex(pd.to_datetime(group["window_start_utc"], utc=True) + latency).sort_values()
        for asset_id, group in stopped.groupby("asset_id", sort=False)
    }
    spacing = pd.Timedelta(minutes=ALERT_SPACING_MIN)
    kept, emitted = [], []
    for asset_id, group in result.groupby("asset_id", sort=False):
        last = None
        stops = stop_times.get(asset_id)
        for index in times.loc[group.index].sort_values(kind="stable").index:
            start = times.loc[index]
            emit = start if last is None else max(start, last + spacing)
            if emit >= ends[asset_id]:
                continue
            if stops is not None:
                left = stops.searchsorted(start, side="left")
                right = stops.searchsorted(emit, side="right")
                if left < right:
                    continue
            kept.append(index)
            emitted.append(emit.strftime("%Y-%m-%dT%H:%M:%SZ"))
            last = emit
    result = result.loc[kept].reset_index(drop=True)
    result["alert_time_utc"] = pd.Series(emitted, dtype="str")
    return result
