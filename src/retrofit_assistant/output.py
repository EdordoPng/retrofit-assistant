"""Deterministic prediction serialization and strict, content-safe validation."""

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import io
import math
from pathlib import Path
import re

import pandas as pd

from .data import AVAILABILITY
from .params import EVENT_CLASSES, FAULT_TYPES


COLUMNS = [
    "asset_id", "alert_time_utc", "event_class", "fault_type", "confidence",
    "evidence", "recommended_action",
]


@dataclass(frozen=True)
class Check:
    passed: bool
    rows: int
    rule: str


def write_predictions(frame, path):
    if any(column not in frame.columns for column in COLUMNS):
        raise ValueError("Missing prediction columns")
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    ordered = frame.sort_values(["asset_id", "alert_time_utc"], kind="stable")
    for row in ordered[COLUMNS].itertuples(index=False, name=None):
        writer.writerow([
            format(float(value), ".6f") if column == "confidence"
            else ("" if pd.isna(value) else str(value))
            for column, value in zip(COLUMNS, row)
        ])
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(buffer.getvalue(), encoding="utf-8", newline="")


def validate_file(path, assets) -> Check:
    rows = []
    try:
        text = Path(path).read_bytes().decode("utf-8")
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader, None)
        for row in reader:
            rows.append(row)
    except Exception:
        return Check(False, len(rows), "file_unreadable")
    count = len(rows)

    def fail(rule):
        return Check(False, count, rule)

    if header != COLUMNS:
        return fail("columns")
    if not rows:
        return fail("0 alerts – likely pipeline error")
    if any(len(row) != len(COLUMNS) for row in rows):
        return fail("row_shape")
    try:
        metadata = assets.set_index("asset_id")
        if any(row[0] not in metadata.index for row in rows):
            return fail("asset_id")
        if any(row[2] not in EVENT_CLASSES for row in rows):
            return fail("event_class")
        if any(row[3] not in FAULT_TYPES for row in rows):
            return fail("fault_type")
        for row in rows:
            try:
                confidence = float(row[4])
            except (ValueError, OverflowError):
                return fail("confidence")
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                return fail("confidence")
        timestamps = []
        for row in rows:
            if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", row[1]) is None:
                return fail("utc_timestamp")
            try:
                timestamp = datetime.strptime(row[1], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            except ValueError:
                return fail("utc_timestamp")
            timestamps.append(pd.Timestamp(timestamp))
        latency = AVAILABILITY["features_1min.parquet"].latency
        for row, timestamp in zip(rows, timestamps):
            start = pd.to_datetime(metadata.loc[row[0], "window_start_utc"], utc=True)
            if timestamp < start + latency:
                return fail("window_start")
        for row, timestamp in zip(rows, timestamps):
            end = pd.to_datetime(metadata.loc[row[0], "window_end_utc"], utc=True)
            if timestamp >= end:
                return fail("window_end")
    except Exception:
        # Invalid metadata or unexpected input must never expose row values or
        # escape as a traceback from the submission checker.
        return fail("file_unreadable")
    return Check(True, count, "")
