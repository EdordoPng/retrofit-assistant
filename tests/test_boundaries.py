"""Enforce runtime input, causality and advisory boundaries."""

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from retrofit_sim.baselines import regime_frame

from retrofit_assistant.data import AVAILABILITY, InputContract, _read_input, load_assets, load_features


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "retrofit_assistant"
DATA = ROOT / "challenge" / "RETROFIT_AI_PARTICIPANTS_2026" / "data" / "full"
DEVELOPMENT = {"evaluate", "ablation", "report", "pump_table", "dashboard"}
READERS = {"read_csv", "read_parquet", "read_table", "ParquetFile", "open"}
SIM_EXPORTS = {"regime_frame", "b1_threshold", "CH", "COUPLED"}
BLOCKED_IMPORTS = {
    "socket", "ssl", "http", "urllib", "ftplib", "smtplib", "telnetlib", "socketserver",
    "requests", "httpx", "aiohttp", "websockets", "paho", "pymodbus", "minimalmodbus",
    "snap7", "opcua", "asyncua", "pycomm3", "can", "serial", "subprocess", "importlib",
}


def _name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _name(node.value) + "." + node.attr
    return ""


def _literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return None


def _scan(source, filename):
    """Return explicit violations, resolving import aliases before checking calls."""
    tree = ast.parse(source)
    runtime = Path(filename).stem not in DEVELOPMENT
    loader = Path(filename).name == "data.py"
    aliases = {}
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".")[0]] = (
                    item.name if item.asname else item.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom):
            for item in node.names:
                aliases[item.asname or item.name] = ".".join(filter(None, [node.module, item.name]))

    def resolved(node):
        parts = _name(node).split(".")
        return ".".join([aliases.get(parts[0], parts[0]), *parts[1:]])

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                imports = [item.name for item in node.names]
            else:
                imports = [".".join(filter(None, [node.module, item.name])) for item in node.names]
            for name in imports:
                parts = name.split(".")
                if parts[0] in BLOCKED_IMPORTS:
                    violations.append("advisory: import " + name)
                if runtime:
                    if Path(filename).name != "cli.py" and any(part in DEVELOPMENT for part in parts):
                        violations.append("runtime: development import")
                    if parts[0] == "retrofit_sim" and not (
                        isinstance(node, ast.ImportFrom)
                        and node.module == "retrofit_sim.baselines"
                        and parts[-1] in SIM_EXPORTS
                    ):
                        violations.append("runtime: simulator import")
        if runtime and isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "events_" in node.value or "benign_windows" in node.value:
                violations.append("runtime: label string")
            if "in_window" in node.value and not loader:
                violations.append("runtime: maintenance string")
        if runtime and isinstance(node, ast.Name) and node.id == "in_window" and not loader:
            violations.append("runtime: maintenance field")
        if runtime and isinstance(node, ast.Attribute):
            if node.attr in {"bfill", "backfill", "interpolate"}:
                violations.append("runtime: future fill")
            if node.attr == "in_window" and not loader:
                violations.append("runtime: maintenance field")
        if not isinstance(node, ast.Call):
            continue
        name = resolved(node.func).split(".")[-1]
        if name == "__import__":
            violations.append("advisory: dynamic import")
        if not runtime:
            continue
        reader_exception = Path(filename).name == "output.py" and name == "read_bytes"
        if (name in READERS or name.startswith("read_")) and not loader and not reader_exception:
            violations.append("runtime: file reader")
        kwargs = {kw.arg: kw.value for kw in node.keywords}
        if _literal(kwargs.get("method")) in {"bfill", "backfill", "nearest"}:
            violations.append("runtime: future method")
        if any(isinstance(arg, ast.Constant) and isinstance(arg.value, str)
               and arg.value in {"bfill", "backfill", "nearest"} for arg in node.args):
            violations.append("runtime: future method")
        if _literal(kwargs.get("center")) is True:
            violations.append("runtime: centered window")
        if name == "rolling" and len(node.args) >= 3 and _literal(node.args[2]) is True:
            violations.append("runtime: centered window")
        if name == "merge_asof" and _literal(kwargs.get("direction")) != "backward":
            violations.append("runtime: asof direction")
        if name in {"shift", "diff", "pct_change"} and not resolved(node.func).startswith("numpy."):
            periods = kwargs.get("periods", node.args[0] if node.args else None)
            values = periods.elts if isinstance(periods, (ast.List, ast.Tuple)) else [periods]
            if any(isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.USub)
                   for value in values):
                violations.append("runtime: future periods")
    return violations


def test_cli_development_import_exception_is_narrow():
    snippet = "from . import evaluate"
    assert not any(v.startswith("runtime:") for v in _scan(snippet, "cli.py"))
    for filename in ("detectors.py", "pipeline.py", "__main__.py"):
        assert "runtime: development import" in _scan(snippet, filename)
    for source in ("pd.read_csv('x')", "x = 'events_train.csv'", "x.bfill()",
                   "from retrofit_sim.scoring import score"):
        assert any(v.startswith("runtime:") for v in _scan(source, "cli.py"))
    assert any(v.startswith("advisory:") for v in _scan("import socket", "cli.py"))


def _sources():
    sources = {path: path.read_text() for path in SOURCE.rglob("*.py")}
    assert {"data.py", "cli.py"} <= {path.name for path in sources}
    return sources


def test_runtime_inputs_source_boundaries():
    violations = {
        str(path.relative_to(ROOT)): [v for v in _scan(source, path.name) if v.startswith("runtime:")]
        for path, source in _sources().items()
    }
    assert not {path: found for path, found in violations.items() if found}


@pytest.mark.parametrize("snippet", [
    "pd.read_csv('x')", "pd.read_parquet('x')", "pd.read_table('x')",
    "pq.ParquetFile('x')", "open('x')", "from pandas import read_csv as read; read('x')",
    "import retrofit_assistant.evaluate", "from . import ablation", "from .report import x",
    "from retrofit_sim.scoring import score", "import retrofit_sim.baselines",
    "from retrofit_sim.baselines import zscores", "x = 'events_train.csv'",
    "x = 'benign_windows_train_validation.csv'", "x = 'in_window'", "x.in_window",
    "x.bfill()", "x.backfill()", "x.interpolate()",
    "x.fillna(method='bfill')", "x.fillna(method='backfill')", "x.reindex(method='nearest')",
    "x.rolling(3, center=True)", "pd.merge_asof(x, y, direction='nearest')",
    "pd.merge_asof(x, y, direction='forward')", "pd.merge_asof(x, y)",
    "x.shift(-1)", "x.shift(periods=-2)",
    "y = x.interpolate", "pd.merge_asof(x, y, direction=d)",
    "from pandas import merge_asof as join; join(x, y, direction='forward')",
    "idx.get_indexer(t, 'nearest')", "x.f(t, 'bfill')", "x.f(t, 'backfill')",
    "x.rolling(3, None, True)",
    "pd.read_json('x')", "pd.read_excel('x')", "pd.read_feather('x')",
    "pd.read_pickle('x')", "x.read_text()", "x.read_bytes()",
    "from pandas import read_json as read; read('x')",
    *[f"x.{method}({argument})" for method in ("shift", "diff", "pct_change")
      for argument in ("-n", "periods=-n", "[-1]", "[1, -1]", "(1, -1)",
                       "periods=[1, -1]", "periods=(1, -1)")],
])
def test_runtime_inputs_scanner_rejects_synthetic(snippet):
    assert any(v.startswith("runtime:") for v in _scan(snippet, "detectors.py"))


def test_runtime_inputs_scanner_accepts_causal_operations():
    snippet = """
from retrofit_sim.baselines import regime_frame, b1_threshold, CH, COUPLED
x.ffill()
x.rolling(3, center=False)
pd.merge_asof(x, y, direction='backward')
x.shift(1)
x.shift(n)
x.diff()
x.diff(1)
import numpy as np
np.diff(-x)
from numpy import diff as delta
delta(-x)
"""
    assert _scan(snippet, "baseline.py") == []
    assert _scan("pd.read_csv('events_train.csv')", "evaluate.py") == []
    assert _scan("pd.read_parquet('x'); x = 'in_window'", "data.py") == []
    assert _scan("x.read_bytes(); x.write_text('x')", "output.py") == []
    assert "runtime: file reader" in _scan("x.read_text()", "output.py")
    assert "runtime: file reader" in _scan("x.read_bytes()", "detectors.py")


def test_advisory_only_source_boundaries():
    violations = {
        str(path.relative_to(ROOT)): [v for v in _scan(source, path.name) if v.startswith("advisory:")]
        for path, source in _sources().items()
    }
    assert not {path: found for path, found in violations.items() if found}


@pytest.mark.parametrize("module", sorted(BLOCKED_IMPORTS))
@pytest.mark.parametrize("form", ["import {m}", "import {m}.client", "from {m} import client"])
def test_advisory_only_scanner_rejects_imports(module, form):
    assert any(v.startswith("advisory:") for v in _scan(form.format(m=module), "cli.py"))


def test_advisory_only_scanner_rejects_dynamic_import():
    assert "advisory: dynamic import" in _scan("__import__('socket')", "cli.py")


@pytest.fixture
def synthetic(tmp_path):
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    assets = pd.DataFrame({
        "asset_id": ["A", "B"], "split": ["train", "validation"],
        "window_start_utc": [start, start],
        "window_end_utc": [start + pd.Timedelta(minutes=6)] * 2,
        "motor_rated_rpm": [1500, 1500],
    })
    assets.to_csv(tmp_path / "assets.csv", index=False)
    # Deliberately unordered, with initial, ongoing and final gaps on A.
    features = pd.DataFrame({
        "asset_id": ["B", "A", "B", "A", "B"],
        "window_start_utc": pd.Series(
            [start + pd.Timedelta(minutes=m) for m in [5, 4, 0, 1, 1]],
            dtype="datetime64[ms, UTC]",
        ),
        "rows": [60] * 5, "operating_mode": ["RUNNING"] * 5,
        "running_fraction": [1.0] * 5,
        "motor_speed_rpm__mean": [1500.0] * 5,
    })
    features.to_parquet(tmp_path / "features_1min.parquet", index=False)
    return tmp_path, start, features


def test_runtime_inputs_availability_contract():
    allowed = {
        "assets.csv", "features_1min.parquet", "operating_context.csv", "alarms.csv",
        "vibration_snapshots.parquet", "maintenance.csv",
    }
    assert set(AVAILABILITY) <= allowed
    assert set(AVAILABILITY) == {"assets.csv", "features_1min.parquet", "vibration_snapshots.parquet"}
    assert AVAILABILITY["vibration_snapshots.parquet"] == InputContract("timestamp_utc", pd.Timedelta(seconds=1))
    assert not any("events" in name or "benign" in name for name in AVAILABILITY)
    assert AVAILABILITY["assets.csv"] == InputContract(None, pd.Timedelta(0))
    contract = AVAILABILITY["features_1min.parquet"]
    assert contract == InputContract("window_start_utc", pd.Timedelta(seconds=60))
    with pytest.raises(FrozenInstanceError):
        contract.latency = pd.Timedelta(0)


@pytest.mark.parametrize("name", [
    "events_train.csv", "events_validation.csv", "benign_windows_train_validation.csv",
    "maintenance.csv", "alarms.csv",
])
def test_runtime_inputs_reject_unavailable_files(tmp_path, monkeypatch, name):
    (tmp_path / name).write_text("forbidden\n")

    def fail_read(*args, **kwargs):
        pytest.fail("An uncontracted file reached disk I/O")

    monkeypatch.setattr(pd, "read_csv", fail_read)
    monkeypatch.setattr(pd, "read_parquet", fail_read)
    with pytest.raises(ValueError):
        _read_input(tmp_path, name)


def test_runtime_inputs_assets_and_parquet_filter(synthetic, monkeypatch):
    data, start, _ = synthetic
    assets = load_assets(data)
    assert assets.asset_id.tolist() == ["A", "B"]
    assert assets.window_start_utc.iloc[0] == start
    assert str(assets.window_end_utc.dt.tz) == "UTC"
    assert load_assets(data, "train").asset_id.tolist() == ["A"]
    assert load_assets(data, "validation").asset_id.tolist() == ["B"]
    assert load_assets(data, "test").empty
    with pytest.raises(ValueError):
        load_assets(data, "other")
    reader = pd.read_parquet
    calls = []

    def recording_reader(*args, **kwargs):
        calls.append(kwargs)
        return reader(*args, **kwargs)

    monkeypatch.setattr(pd, "read_parquet", recording_reader)
    result = load_features(data, assets.iloc[:1])
    assert calls == [{"filters": [("asset_id", "in", ["A"])]}]
    assert result.asset_id.unique().tolist() == ["A"]


def test_runtime_inputs_minute_boundary_and_until(synthetic):
    data, start, _ = synthetic
    assets = load_assets(data, "validation")
    before = load_features(data, assets, until=start + pd.Timedelta(seconds=59.999))
    exact = load_features(data, assets, until=start + pd.Timedelta(seconds=60))
    assert before.empty
    assert exact.window_start_utc.tolist() == [start]
    assert exact.rows.tolist() == [60.0]
    assert_frame_equal(exact, load_features(data, assets, until=(start + pd.Timedelta(minutes=1)).tz_convert("Europe/Helsinki")))
    with pytest.raises(ValueError, match="timezone-aware"):
        load_features(data, assets, until="2026-01-01 00:01:00")
    assert_frame_equal(load_features(data, assets), load_features(data, assets, until=start + pd.Timedelta(days=1)))


def test_runtime_inputs_anchors_order_and_schema(synthetic):
    data, start, original = synthetic
    assets = load_assets(data)
    full = load_features(data, assets)
    a = full.loc[full.asset_id == "A"]
    assert a.window_start_utc.tolist() == [start + pd.Timedelta(minutes=m) for m in [0, 1, 4, 5]]
    anchors = a.loc[a.window_start_utc.isin([start, start + pd.Timedelta(minutes=5)])]
    assert anchors.drop(columns=["asset_id", "window_start_utc"]).isna().all().all()
    assert full.asset_id.tolist() == ["A"] * 4 + ["B"] * 3
    assert full.index.equals(pd.RangeIndex(len(full)))
    assert full.window_start_utc.dtype == original.window_start_utc.dtype
    assert full.rows.dtype == "float64"
    assert full.columns.tolist() == original.columns.tolist()
    for seconds in [0, 59.999, 60, 120, 240, 299.999, 360]:
        cut = start + pd.Timedelta(seconds=seconds)
        prefix = load_features(data, assets, until=cut)
        assert prefix.dtypes.equals(full.dtypes)
        assert prefix.columns.equals(full.columns)
        if seconds >= 60:
            last = cut.floor("min") - pd.Timedelta(minutes=1)
            assert prefix.groupby("asset_id").window_start_utc.min().eq(start).all()
            assert prefix.groupby("asset_id").window_start_utc.max().eq(last).all()
    # Cut inside A's gap: an end anchor must keep the missing minutes on the grid.
    cut = start + pd.Timedelta(minutes=4, seconds=30)
    truncated = regime_frame(load_features(data, assets, until=cut), assets)
    complete = regime_frame(full, assets)
    expected = complete.loc[complete.window_start_utc + pd.Timedelta(minutes=1) <= cut]
    assert_frame_equal(truncated.reset_index(drop=True), expected.reset_index(drop=True), check_dtype=False)
    reverse = load_features(data, assets.iloc[::-1])
    assert reverse.asset_id.tolist() == ["B"] * 3 + ["A"] * 4
    empty = load_features(data, assets.iloc[:0])
    assert empty.empty and empty.dtypes.equals(full.dtypes)


@pytest.mark.parametrize("split,asset_id", [("train", "PUMP-01"), ("validation", "PUMP-08")])
def test_runtime_inputs_real_gap_prefix(split, asset_id):
    assets = load_assets(DATA, split)
    assets = assets.loc[assets.asset_id == asset_id]
    assert len(assets) == 1
    full = load_features(DATA, assets)
    times = full.window_start_utc
    gaps = times.diff() > pd.Timedelta(minutes=1)
    assert gaps.any(), "Expected a real gateway gap on this asset"
    gap_index = gaps[gaps].index[0]
    gap_cut = times.iloc[gap_index - 1] + pd.Timedelta(minutes=2, seconds=30)
    assert gap_cut < times.iloc[gap_index] + pd.Timedelta(minutes=1)
    ordinary_cut = times.iloc[20] + pd.Timedelta(minutes=1, seconds=30)
    complete = regime_frame(full, assets)
    columns = ["window_start_utc", "rows", "operating_mode", "running_fraction", "regime", "steady"]
    for cut in [gap_cut, ordinary_cut]:
        prefix = load_features(DATA, assets, until=cut)
        assert prefix.dtypes.equals(full.dtypes)
        actual = regime_frame(prefix, assets)
        expected = complete.loc[complete.window_start_utc + pd.Timedelta(minutes=1) <= cut]
        assert_frame_equal(actual[columns].reset_index(drop=True), expected[columns].reset_index(drop=True), check_dtype=False)
