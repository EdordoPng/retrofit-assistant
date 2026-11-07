"""Synthetic tier, input isolation, reporting and causal-prefix contracts."""

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from retrofit_sim.baselines import CH

from retrofit_assistant import ablation, cli, pipeline
from retrofit_assistant.consistency import coupled_channels
from retrofit_assistant.output import COLUMNS, write_predictions
from retrofit_assistant.sources import INTERNAL_COLUMNS, cavitation_candidates


@pytest.fixture
def inputs(monkeypatch):
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    assets = pd.DataFrame([{
        "asset_id": "A", "split": "train", "control": "VFD_PRESSURE",
        "instrumentation_tier": "T2_FULL", "channels_available": "|".join(CH.values()),
        "wireless_update_s": np.nan, "window_start_utc": start,
        "window_end_utc": start + pd.Timedelta(hours=4), "motor_rated_rpm": 1500.,
        "npsh3_at_bep_m": 4., "pump_rated_flow_m3_h": 100., "pump_rated_head_m": 30.,
        "motor_rated_current_a": 30., "motor_rated_kw": 20.,
    }])
    times = pd.date_range(start, periods=240, freq="min")
    features = pd.DataFrame({
        "asset_id": "A", "window_start_utc": times, "rows": 60.,
        "operating_mode": "RUNNING", "running_fraction": 1., "quality_any": 0.,
    })
    for key, channel in CH.items():
        level = {"n": 1500., "tf": 25., "v": 2., "a": .1, "c": 3.,
                 "bt": 40., "wt": 45., "i": 20., "pw": 10.}.get(key, 100.)
        features[channel + "__mean"] = level + .001 * np.sin(np.arange(240))
        features[channel + "__std"] = .1
        features[channel + "__count"] = 60.
        features[channel + "__min"] = features[channel + "__mean"] - .2
        features[channel + "__max"] = features[channel + "__mean"] + .2
    features.loc[100:, CH["ps"] + "__mean"] = -85. + .001 * np.sin(np.arange(140))
    features.loc[100:, CH["pd"] + "__mean"] -= 40.
    snapshots = pd.DataFrame({"asset_id": ["A"], "timestamp_utc": [start], "rpm_at_capture": [np.nan]})
    snapshot_reads = []
    monkeypatch.setattr(pipeline, "load_assets", lambda data, split: assets.copy(deep=True))

    def load_features(data, selected, until=None):
        frame = features.loc[features.asset_id.isin(selected.asset_id)]
        if until is not None:
            frame = frame.loc[frame.window_start_utc + pd.Timedelta(minutes=1) <= until]
        return frame.copy(deep=True)

    def load_snapshots(data, selected, until=None):
        snapshot_reads.append(selected.copy(deep=True))
        return snapshots.loc[snapshots.asset_id.isin(selected.asset_id)].copy(deep=True)

    monkeypatch.setattr(pipeline, "load_features", load_features)
    monkeypatch.setattr(pipeline, "load_snapshots", load_snapshots)
    return assets, features, snapshots, snapshot_reads


@pytest.mark.parametrize("tier", ["T1", "T0"])
@pytest.mark.parametrize("control", ["VFD_PRESSURE", "FIXED_SPEED", "FLOW_VALVE"])
def test_masks_all_channel_statistics_and_metadata_before_baseline(inputs, monkeypatch, tier, control):
    assets, features, _, reads = inputs
    assets["control"] = control
    original_assets, original_features = assets.copy(deep=True), features.copy(deep=True)
    captured = {}

    def baseline(frame, metadata):
        captured.update(frame=frame, metadata=metadata)
        return pd.DataFrame(columns=COLUMNS)

    monkeypatch.setattr(pipeline, "causal_b1", baseline)
    pipeline.run_detector("unused", "train", detector="causal_b1", mask_tier=tier)
    expected = {"q", "wt", "vp"}
    if tier == "T0":
        expected |= {"ps", "v", "a", "c", "bt"}
    if control != "VFD_PRESSURE":
        expected |= {"pw", "n"}
    metadata = captured["metadata"].iloc[0]
    assert metadata.instrumentation_tier == {"T1": "T1_RETROFIT", "T0": "T0_LEGACY"}[tier]
    assert pd.isna(metadata.wireless_update_s)
    assert metadata.channels_available.split("|") == [c for k, c in CH.items() if k not in expected]
    for key, channel in CH.items():
        columns = [c for c in features if c.startswith(channel + "__")]
        if key in expected:
            assert captured["frame"][columns].isna().all().all()
        else:
            assert_frame_equal(captured["frame"][columns], features[columns], check_exact=True)
    assert_frame_equal(assets, original_assets, check_exact=True)
    assert_frame_equal(features, original_features, check_exact=True)
    assert not reads  # causal_b1 never loads spectra.


@pytest.mark.parametrize("tier", ["T0", "T1"])
def test_mask_reaches_witnesses_sources_and_spectra(inputs, monkeypatch, tier):
    _, _, _, reads = inputs
    original = pipeline.candidate_stream
    captured = {}

    def candidates(frame, metadata, snapshots):
        installed = metadata.iloc[0].channels_available.split("|")
        witnesses = coupled_channels("pd", installed)
        assert "q" not in witnesses
        if tier == "T0":
            assert "ps" not in witnesses
            assert snapshots is None
        else:
            assert "ps" in witnesses
            assert snapshots is not None and len(snapshots) == 1
        scored = pipeline.score_features(frame, metadata)
        captured["cavitation"] = cavitation_candidates(scored, metadata, pd.DataFrame(columns=INTERNAL_COLUMNS))
        return original(frame, metadata, snapshots)

    monkeypatch.setattr(pipeline, "candidate_stream", candidates)
    predictions = pipeline.run_detector("unused", "train", mask_tier=tier)
    assert not predictions.empty
    if tier == "T0":
        assert captured["cavitation"].empty
        assert not predictions.fault_type.eq("CAVITATION").any()
        assert not reads
    else:
        assert not captured["cavitation"].empty  # fixture would cavitate if observable.
        assert len(reads) == 1


@pytest.mark.parametrize("tier", ["T0", "T1"])
def test_other_assets_and_their_snapshots_are_unchanged(inputs, monkeypatch, tier):
    assets, features, _, reads = inputs
    for real_tier in ("T1_RETROFIT", "T0_LEGACY"):
        assets["instrumentation_tier"] = real_tier
        expected_assets = assets.copy(deep=True)

        def candidates(frame, metadata, snapshots):
            assert_frame_equal(metadata, expected_assets, check_exact=True)
            assert_frame_equal(frame, features, check_exact=True)
            assert len(snapshots) == 1
            return pd.DataFrame(columns=INTERNAL_COLUMNS)

        monkeypatch.setattr(pipeline, "candidate_stream", candidates)
        pipeline.run_detector("unused", "train", mask_tier=tier)
    assert len(reads) == 2


def test_t0_snapshot_reader_receives_only_unmasked_assets(inputs, monkeypatch):
    assets, features, _, reads = inputs
    assets.loc[1] = assets.iloc[0].copy()
    assets.loc[1, ["asset_id", "instrumentation_tier"]] = ["B", "T1_RETROFIT"]
    other = features.assign(asset_id="B")
    combined = pd.concat([features, other], ignore_index=True)
    monkeypatch.setattr(pipeline, "load_features", lambda *a, **kw: combined.copy(deep=True))

    def candidates(frame, metadata, snapshots):
        assert snapshots.empty
        assert frame.loc[frame.asset_id == "A", CH["ps"] + "__mean"].isna().all()
        assert_frame_equal(frame.loc[frame.asset_id == "B"].reset_index(drop=True), other, check_exact=True)
        return pd.DataFrame(columns=INTERNAL_COLUMNS)

    monkeypatch.setattr(pipeline, "candidate_stream", candidates)
    pipeline.run_detector("unused", "train", mask_tier="T0")
    assert reads[0].asset_id.tolist() == ["B"]


@pytest.mark.parametrize("detector", ["full", "causal_b1"])
def test_none_preserves_original_pipeline_bytes(inputs, tmp_path, detector):
    assets, features, snapshots, _ = inputs
    expected = (pipeline.causal_b1(features, assets) if detector == "causal_b1" else
                pipeline.apply_guarantees(pipeline.candidate_stream(features, assets, snapshots), features, assets))
    explicit = pipeline.run_detector("unused", "train", detector=detector, mask_tier=None)
    default = pipeline.run_detector("unused", "train", detector=detector)
    for name, frame in (("original", expected), ("explicit", explicit), ("default", default)):
        write_predictions(frame, tmp_path / f"{name}.csv")
    assert (tmp_path / "original.csv").read_bytes() == (tmp_path / "explicit.csv").read_bytes()
    assert (tmp_path / "original.csv").read_bytes() == (tmp_path / "default.csv").read_bytes()


@pytest.mark.parametrize("tier", ["T1", "T0"])
def test_cli_refuses_mask_on_test_before_any_input(monkeypatch, capsys, tier):
    monkeypatch.setattr(cli, "run_detector", lambda *a, **kw: pytest.fail("detector must not run"))
    result = cli.main(["predict", "--data", "unused", "--split", "test", "--mask-tier", tier,
                       "--out", "build/submission/predictions_test_20260101T000000Z_abcdef0.csv"])
    assert result == 2
    assert "--mask-tier" in capsys.readouterr().err


def test_ablate_has_no_test_split(monkeypatch):
    monkeypatch.setattr(ablation, "ablate", lambda *a, **kw: pytest.fail("ablation must not run"))
    with pytest.raises(SystemExit) as exc:
        cli.main(["ablate", "--data", "unused", "--out", "build/scores/ablation.md", "--split", "test"])
    assert exc.value.code == 2


@pytest.mark.parametrize("tier", [None, "T1", "T0"])
def test_future_rows_do_not_change_alerts_up_to_cut(inputs, tier):
    _, features, _, _ = inputs
    cut = features.window_start_utc.iloc[150] + pd.Timedelta(minutes=1)
    full = pipeline.run_detector("unused", "train", mask_tier=tier)
    expected = full.loc[pd.to_datetime(full.alert_time_utc, utc=True) <= cut].reset_index(drop=True)
    assert not expected.empty
    prefix = pipeline.run_detector("unused", "train", mask_tier=tier, until=cut)
    prefix = prefix.loc[pd.to_datetime(prefix.alert_time_utc, utc=True) <= cut].reset_index(drop=True)
    assert_frame_equal(prefix, expected, check_exact=True)
    columns = [c for c in features if "__" in c]
    features.loc[features.window_start_utc >= cut, columns] = 99999.
    changed = pipeline.run_detector("unused", "train", mask_tier=tier)
    changed = changed.loc[pd.to_datetime(changed.alert_time_utc, utc=True) <= cut].reset_index(drop=True)
    assert_frame_equal(changed, expected, check_exact=True)


def test_invalid_masks_fail_before_reading(monkeypatch):
    monkeypatch.setattr(pipeline, "load_assets", lambda *a, **kw: pytest.fail("input must not be read"))
    with pytest.raises(ValueError, match="mask tier"):
        pipeline.run_detector("unused", "train", mask_tier="T2")
    with pytest.raises(ValueError, match="train and validation"):
        pipeline.run_detector("unused", "test", mask_tier="T1")


def test_table_has_lead_time_counts_and_caveat():
    result = {"assets": ["A"], "composite_score": 42.125, "true_positive_events": 2, "events_scored": 3,
              "per_event": [{"type_correct": True}, {"type_correct": False}],
              "median_lead_time_h": 5.25, "early_warning_rate": .5}
    table = ablation.markdown_table([(ablation.T1_LABEL, "train", result)])
    assert "T1 simulato ottimistico (cadenza wireless non emulata)" in table
    assert "median_lead_time_h" in table and "early_warning_rate" in table
    assert "| 42.125 | 2/3 | 1 | 5.25 | 0.500 |" in table
    result.update(median_lead_time_h=None, early_warning_rate=None)
    assert "| - | - |" in ablation.markdown_table([("T0", "validation", result)])
