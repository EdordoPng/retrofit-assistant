"""Recompute real pipeline prefixes; never report hidden alert contents."""

import contextlib
import io
import logging
import os
from pathlib import Path
import random
import subprocess
import sys
import warnings
import zlib

import pandas as pd
import pytest

from retrofit_assistant import pipeline
from retrofit_assistant.data import load_assets
from retrofit_assistant.output import COLUMNS
from retrofit_assistant.params import ALERT_SPACING_MIN
from retrofit_assistant.policy import apply_guarantees

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "challenge/RETROFIT_AI_PARTICIPANTS_2026/data/full"
SEED = 60206
HIDDEN = {"PUMP-10", "PUMP-11", "PUMP-12"}


def _normal(frame):
    result = frame.copy().reset_index(drop=True)
    for column in result.columns:
        if column == "alert_time_utc":
            result[column] = pd.to_datetime(result[column], utc=True).map(lambda t: t.isoformat())
        result[column] = result[column].astype(object).where(result[column].notna(), None)
    return result


def _difference(left, right):
    if list(left.columns) != list(right.columns):
        return "columns"
    if left.empty and right.empty:
        return None
    left, right = _normal(left), _normal(right)
    if len(left) != len(right):
        return "rows"
    for column in left.columns:
        if left[column].tolist() != right[column].tolist():
            return column
    return None


def _prefix(frame, cut):
    return frame.loc[pd.to_datetime(frame.alert_time_utc, utc=True) <= cut]


def _compare(complete, truncated, candidates, cut, detector):
    actual = truncated if detector == "causal_b1" else _prefix(truncated, cut)
    difference = _difference(_prefix(complete, cut), actual)
    if difference or detector == "causal_b1":
        return difference
    # Match emitted rows to distinct candidates in candidate order. Dropped
    # candidates do not advance the previous emission, just as in the policy.
    emitted = _normal(truncated)
    source = _normal(candidates)
    positions, previous = {}, {}
    spacing = pd.Timedelta(minutes=ALERT_SPACING_MIN)
    for row in emitted.to_dict("records"):
        asset = row["asset_id"]
        time = pd.Timestamp(row["alert_time_utc"])
        match = None
        for index in range(positions.get(asset, 0), len(source)):
            candidate = source.iloc[index].to_dict()
            if candidate["asset_id"] != asset:
                continue
            candidate_time = pd.Timestamp(candidate["alert_time_utc"])
            last = previous.get(asset)
            expected = candidate_time if last is None else max(candidate_time, last + spacing)
            if time == expected:
                match = index, candidate_time
                break
        if match is None:
            return "spacing"
        index, candidate_time = match
        positions[asset] = index + 1
        if time > cut:
            last = previous.get(asset)
            if (last is None or candidate_time > cut or candidate_time >= time
                    or time != max(candidate_time, last + spacing)):
                return "spacing"
        previous[asset] = time
    return None


def _random_cuts(asset, start, end):
    rng = random.Random(SEED ^ zlib.crc32(asset.encode()))
    seconds = int((end - start).total_seconds())
    return [start + pd.Timedelta(seconds=rng.randrange(60, seconds)) for _ in range(10)]


def _cuts(asset, start, end, complete, fast):
    groups = {
        "edge": [start + pd.Timedelta(seconds=59)],
        "minute": [start + pd.Timedelta(hours=h, seconds=s) for h in (6, 48) for s in (-1, 1)],
        "hour": [start + pd.Timedelta(hours=h) for h in (1, 12, 24, 25)],
        "random": _random_cuts(asset, start, end),
    }
    alerts = sorted({pd.Timestamp(t) for frame in complete.values() for t in frame.alert_time_utc})
    groups["alert"] = [t + pd.Timedelta(seconds=s) for t in alerts for s in (-1, 0, 1)]
    derived = set(groups["alert"])
    if fast:
        # Start from one cut per category: edge, minute +/-1 s, freeze,
        # first alert +/-1 s (and exact), and one random cut.
        groups = {key: values[:1] for key, values in groups.items()}
        groups["minute"] = [start + pd.Timedelta(hours=6, seconds=s) for s in (-1, 1)]
        groups["hour"] = [start + pd.Timedelta(hours=24)]
        groups["alert"] = [alerts[0] + pd.Timedelta(seconds=s) for s in (-1, 0, 1)] if alerts else []
        if asset not in {"PUMP-01", "PUMP-08", "PUMP-10"}:
            # The full category selection on every pump exceeds the fast budget.
            # Keep every category on one training and one validation pump;
            # retain an exact alert cut on each remaining pump (or the edge
            # when the complete stream has no alerts).
            groups = {"sample": [alerts[0]] if alerts else groups["edge"]}
        # Every causal alert is covered, regardless of the asset name.
        groups["all_causal_alerts"] = [pd.Timestamp(t) for t in complete["causal_b1"].alert_time_utc]
        candidates = complete.get("candidates")
        if candidates is not None and "decided_by" in candidates:
            sources = candidates.loc[candidates.decided_by.isin(("source_stuck", "source_cavitation"))]
            groups["all_source_alerts"] = [pd.Timestamp(t) for t in sources.alert_time_utc]
        # Also cut at scheduled emissions, including sources deferred by spacing.
        groups["all_emissions"] = [pd.Timestamp(t) for t in complete["full"].alert_time_utc]
    return [(cut, cut in derived) for cut in sorted(set(sum(groups.values(), []))) if start <= cut < end]


def _safe_run(operation, *args):
    failed = False
    result = None
    # Captured diagnostics must not escape through exceptions or pytest sections.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        prior = logging.root.manager.disable
        logging.disable(sys.maxsize)
        try:
            result = operation(*args)
        except Exception:
            failed = True
        finally:
            logging.disable(prior)
    return result, failed


def _check_assets(assets, run_factory, fast):
    failures = []
    counts = {}

    def record(asset, cut, derived, detector, column):
        label = "alert-derived" if derived and asset in HIDDEN else str(cut)
        message = f"asset={asset} cut={label}"
        if asset in HIDDEN:
            pytest.fail(message, pytrace=False)
        failures.append(message + f" pipeline={detector} column={column}")

    def check_asset(metadata, context):
        asset = metadata.asset_id
        run = run_factory(asset)
        complete = {}
        for detector in ("causal_b1", "full", "candidates"):
            context["detector"] = detector
            frame, failed = _safe_run(run, detector, None)
            if failed:
                record(asset, "full-run", False, detector, "exception")
            else:
                complete[detector] = frame
        if len(complete) != 3:
            return
        context["detector"] = "both"
        cuts, failed = _safe_run(
            _cuts, asset, metadata.window_start_utc, metadata.window_end_utc, complete, fast,
        )
        if failed:
            record(asset, "full-run", False, "both", "exception")
            return
        counts[asset] = len(cuts)
        for cut, derived in cuts:
            context.update(cut=cut.isoformat(), derived=derived)
            truncated = {}
            for detector in ("causal_b1", "full", "candidates"):
                context["detector"] = detector
                frame, failed = _safe_run(run, detector, cut)
                if failed:
                    record(asset, context["cut"], derived, detector, "exception")
                else:
                    truncated[detector] = frame
            for detector, frame in truncated.items():
                if detector == "candidates":
                    continue
                context["detector"] = detector
                if "candidates" not in truncated:
                    continue
                difference, failed = _safe_run(
                    _compare, complete[detector], frame, truncated["candidates"], cut, detector,
                )
                if failed or difference:
                    record(asset, context["cut"], derived, detector, "exception" if failed else difference)

    for metadata in assets.itertuples(index=False):
        context = {"cut": "full-run", "derived": False, "detector": "both"}
        # Also contain unexpected errors in the factory and per-asset bookkeeping.
        # pytest.fail inherits BaseException, so a hidden failure still stops at once.
        _, failed = _safe_run(check_asset, metadata, context)
        if failed:
            record(metadata.asset_id, context["cut"], context["derived"], context["detector"], "exception")
    if failures:
        pytest.fail("; ".join(failures), pytrace=False)
    return counts


def _real_check(monkeypatch, fast):
    requested = os.environ.get("RETROFIT_CAUSALITY_ASSETS", ",".join(f"PUMP-{i:02}" for i in range(1, 10)))
    selected = [value.strip() for value in requested.split(",")]
    if not all(selected):
        pytest.fail("Invalid RETROFIT_CAUSALITY_ASSETS", pytrace=False)

    def selected_metadata():
        available = load_assets(DATA)
        if any(value not in set(available.asset_id) for value in selected):
            return None
        return available.set_index("asset_id").loc[list(dict.fromkeys(selected))].reset_index()

    metadata, failed = _safe_run(selected_metadata)
    if failed:
        suffix = "" if selected[0] in HIDDEN else " pipeline=both column=exception"
        pytest.fail(f"asset={selected[0]} cut=full-run" + suffix, pytrace=False)
    if metadata is None:
        pytest.fail("Invalid RETROFIT_CAUSALITY_ASSETS", pytrace=False)
    real_loader = pipeline.load_assets
    real_candidates = pipeline.candidate_stream

    def factory(asset):
        captured = {}

        def only_asset(data, split=None):
            fresh = real_loader(data, split)
            return fresh.loc[fresh.asset_id == asset].copy().reset_index(drop=True)

        monkeypatch.setattr(pipeline, "load_assets", only_asset)

        def capture_candidates(features, assets):
            result = real_candidates(features, assets)
            captured["candidates"] = result
            return result

        monkeypatch.setattr(pipeline, "candidate_stream", capture_candidates)

        def run(detector, until):
            if detector == "candidates":
                return captured["candidates"]
            return pipeline.run_detector(DATA, None, detector=detector, until=until)

        return run

    counts = _check_assets(metadata, factory, fast)
    if not set(selected) & HIDDEN:
        print("cuts " + " ".join(f"{asset}={count}" for asset, count in counts.items()))


def test_truncation_fast(monkeypatch):
    _real_check(monkeypatch, True)


@pytest.mark.slow
def test_truncation_complete(monkeypatch):
    _real_check(monkeypatch, False)


def _rows(start, offsets=(0,)):
    return pd.DataFrame([
        ["A", (start + pd.Timedelta(minutes=offset)).isoformat(), "MACHINE", "UNKNOWN", 0.5, f"e{index}", "inspect"]
        for index, offset in enumerate(offsets)
    ], columns=COLUMNS)


@pytest.mark.parametrize("column", COLUMNS)
def test_comparator_rejects_each_column(column):
    frame = _rows(pd.Timestamp("2026-01-01T00:00:00Z"))
    changed = frame.copy()
    changed.loc[0, column] = 0.6 if column == "confidence" else (
        "2026-01-01T00:00:01Z" if column == "alert_time_utc" else "changed")
    assert _difference(frame, changed) == column


def test_empty_normalization_and_column_order():
    frame = _rows(pd.Timestamp("2026-01-01T00:00:00Z"))
    assert _difference(frame.iloc[:0], frame.iloc[:0].astype(object)) is None
    assert _difference(frame.iloc[:0], frame.iloc[:0, ::-1]) == "columns"
    assert _difference(frame, frame.assign(confidence=float("nan"))) == "confidence"
    assert _difference(frame.assign(evidence=None), frame.assign(evidence=float("nan"))) is None


def test_centered_detector_rejected():
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    series = pd.Series([0., 0., 9., 0., 0.])

    def detect(values):
        mask = values.rolling(3, center=True, min_periods=1).mean() > 2
        return _rows(start, tuple(mask[mask].index))

    cut = start + pd.Timedelta(minutes=1)
    assert _compare(detect(series), detect(series.iloc[:2]), None, cut, "causal_b1") is not None


@pytest.mark.parametrize("offsets,cut_minutes", [((0, 3), 4), ((0, 1, 2), 3)])
def test_spacing_with_real_policy(offsets, cut_minutes):
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    candidates = _rows(start, offsets)
    minutes = pd.DataFrame(columns=["asset_id", "window_start_utc", "operating_mode"])
    assets = pd.DataFrame({"asset_id": ["A"], "window_end_utc": [start + pd.Timedelta(days=1)]})
    emitted = apply_guarantees(candidates, minutes, assets)
    cut = start + pd.Timedelta(minutes=cut_minutes)
    assert _compare(emitted, emitted, candidates, cut, "full") is None
    changed = emitted.copy()
    changed.loc[len(changed) - 1, "alert_time_utc"] = (pd.Timestamp(changed.iloc[-1].alert_time_utc) + pd.Timedelta(minutes=1)).isoformat()
    assert _compare(emitted, changed, candidates, cut, "full") == "spacing"
    assert _compare(emitted, emitted, candidates.iloc[:1], cut, "full") == "spacing"
    assert _compare(candidates.iloc[:1], emitted, candidates, cut, "causal_b1") is not None


def test_spacing_matches_rediagnosed_candidate_by_asset_and_time():
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    candidates = _rows(start, (0, 3))
    emitted = candidates.copy()
    emitted.loc[1, "alert_time_utc"] = (start + pd.Timedelta(minutes=6)).isoformat()
    emitted["fault_type"] = "SENSOR_DRIFT"
    emitted["evidence"] = "physical ramp with stable coupled channels"
    assert _compare(emitted, emitted, candidates, start + pd.Timedelta(minutes=4), "full") is None


@pytest.mark.parametrize("asset", ["ARBITRARY", "PUMP-01", "PUMP-08"])
def test_fast_plan_contains_every_causal_alert(asset):
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    causal = _rows(start, (10, 23, 81)).assign(asset_id=asset)
    complete = {"causal_b1": causal, "full": causal.copy()}
    end = start + pd.Timedelta(days=4)
    fast = dict(_cuts(asset, start, end, complete, True))
    exhaustive = dict(_cuts(asset, start, end, complete, False))
    for time in pd.to_datetime(causal.alert_time_utc, utc=True):
        assert time in fast and fast[time]
    assert set(fast) <= set(exhaustive)


def test_source_deferred_by_official_spacing_matches_merged_stream():
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    candidates = _rows(start, (0, 3)).assign(decided_by=["official", "source_stuck"])
    candidates.loc[1, ["event_class", "fault_type"]] = ["SENSOR", "SENSOR_STUCK"]
    minutes = pd.DataFrame(columns=["asset_id", "window_start_utc", "operating_mode"])
    assets = pd.DataFrame({"asset_id": ["A"], "window_end_utc": [start + pd.Timedelta(days=1)]})
    emitted = apply_guarantees(candidates, minutes, assets)
    cut = start + pd.Timedelta(minutes=4)
    assert _compare(emitted, emitted, candidates, cut, "full") is None
    assert _compare(emitted, emitted, candidates.iloc[:1], cut, "full") == "spacing"
    changed = emitted.copy()
    changed.loc[1, "alert_time_utc"] = (pd.Timestamp(emitted.iloc[1].alert_time_utc) + pd.Timedelta(minutes=1)).isoformat()
    assert _compare(emitted, changed, candidates, cut, "full") == "spacing"


@pytest.mark.parametrize("source", ["source_stuck", "source_cavitation"])
def test_fast_plan_cuts_every_source_candidate_and_scheduled_emission(source):
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    causal = _rows(start, (10,))
    candidates = _rows(start, (10, 13, 40)).assign(decided_by=["official", source, source])
    full = _rows(start, (10, 16, 40))
    complete = {"causal_b1": causal, "full": full, "candidates": candidates}
    fast = dict(_cuts("ARBITRARY", start, start + pd.Timedelta(days=4), complete, True))
    exhaustive = dict(_cuts("ARBITRARY", start, start + pd.Timedelta(days=4), complete, False))
    for offset in (13, 16, 40):
        assert fast[start + pd.Timedelta(minutes=offset)]
    assert set(fast) <= set(exhaustive)


def test_random_cuts_hash_seed_independent():
    code = f"""import runpy, pandas as pd
m = runpy.run_path({str(Path(__file__).resolve())!r})
s = pd.Timestamp('2026-01-01T00:00:00Z')
print([t.isoformat() for t in m['_random_cuts']('A', s, s + pd.Timedelta(days=4))])
"""
    outputs = [subprocess.run([sys.executable, "-c", code], env={**os.environ, "PYTHONHASHSEED": seed},
                              capture_output=True, text=True, check=True).stdout for seed in ("1", "3")]
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize("mode", ["difference", "exception", "comparison", "cuts"])
@pytest.mark.parametrize("slow", [False, True])
def test_hidden_failure_is_redacted(tmp_path, mode, slow):
    sentinel = "PRIVATE_SENTINEL_49203"
    module = tmp_path / "test_private.py"
    module.write_text(f'''
import runpy, sys, logging, warnings
import pandas as pd
import pytest
warnings.warn("{sentinel} import")
m = runpy.run_path({str(Path(__file__).resolve())!r})
start = pd.Timestamp("2026-01-01T00:00:00Z")
def pytest_generate_tests(metafunc):
    warnings.warn("{sentinel} collection")
@pytest.mark.slow
 def_placeholder
'''.replace(" def_placeholder", f'''def test_private():
    assets = pd.DataFrame({{"asset_id": ["PUMP-10"], "window_start_utc": [start], "window_end_utc": [start + pd.Timedelta(days=4)]}})
    def factory(asset):
        def run(detector, until):
            print("{sentinel}")
            print("{sentinel}", file=sys.stderr)
            logging.error("{sentinel}")
            warnings.warn("{sentinel}")
            if until is None and {mode!r} == "cuts":
                return m['_rows'](start, (10,)).assign(asset_id=asset, alert_time_utc="{sentinel}")
            if until is not None and until >= start + pd.Timedelta(minutes=10) - pd.Timedelta(seconds=1):
                if {mode!r} == "exception":
                    raise ValueError("{sentinel}")
                if {mode!r} == "comparison":
                    return m['_rows'](start, (10,)).assign(asset_id=asset, alert_time_utc="{sentinel}")
                return m['_rows'](start, (10,)).assign(asset_id=asset, evidence="{sentinel}")
            frame = m['_rows'](start, (10,)).assign(asset_id=asset)
            return frame if until is None else m['_prefix'](frame, until)
        return run
    m['_check_assets'](assets, factory, True)
'''))
    # Exercise both P3-3 marker selections, including collection warnings.
    if not slow:
        module.write_text(module.read_text().replace("@pytest.mark.slow\n", ""))
    # tmp_path is outside the repository: explicitly load its pytest config so
    # the slow selection really overrides addopts='-m "not slow"'.
    configuration = ["-c", str(ROOT / "pyproject.toml")]
    command = [sys.executable, "-m", "pytest", "-q", "--tb=line", "--show-capture=no", "-p", "no:warnings", *configuration]
    if slow:
        command += ["-m", "slow"]
    process = subprocess.run(command + [str(module)], cwd=ROOT, capture_output=True, text=True, timeout=60)
    output = process.stdout + process.stderr
    assert process.returncode == 1
    assert sentinel not in output
    assert "2026-01-01" not in output
    label = "full-run" if mode == "cuts" else "alert-derived"
    assert "asset=PUMP-10" in output and f"cut={label}" in output
    unprotected = [sys.executable, "-m", "pytest", "-q", *configuration] + (["-m", "slow"] if slow else [])
    exposed = subprocess.run(unprotected + [str(module)], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert exposed.returncode == 1
    assert sentinel in exposed.stdout + exposed.stderr
