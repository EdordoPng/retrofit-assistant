import os
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from retrofit_assistant.cli import main
from retrofit_assistant import report
from retrofit_assistant.output import COLUMNS

DATA = Path('challenge/RETROFIT_AI_PARTICIPANTS_2026/data/full')


@pytest.fixture
def sample(tmp_path):
    start = pd.Timestamp('2026-01-01T00:00:00Z')
    pd.DataFrame([dict(asset_id='A', split='train', instrumentation_tier='T0_LEGACY',
                       window_start_utc=start, window_end_utc=start + pd.Timedelta(minutes=3))]).to_csv(tmp_path / 'assets.csv', index=False)
    pd.DataFrame(dict(asset_id=['A', 'A'], window_start_utc=[start, start + pd.Timedelta(minutes=1)],
                      rows=[60, 60], discharge_pressure_kpa__mean=[1., 2.], motor_current_a__mean=[3., 4.])).to_parquet(tmp_path / 'features_1min.parquet', index=False)
    rows = [dict(zip(COLUMNS, row)) for row in [
        ['A', '2026-01-01T00:02:00Z', 'SENSOR', 'UNKNOWN', .7, '<script>alert(1)</script>', 'Review'],
        ['B', '2026-01-01T00:01:00Z', 'MACHINE', 'OTHER', .5, 'other asset secret', 'Check'],
        ['A', '2026-01-01T00:01:00Z', 'MACHINE', 'OTHER', .8, 'first evidence', 'Inspect'],
    ]]
    pd.DataFrame(rows).to_csv(tmp_path / 'predictions.csv', index=False)
    return tmp_path


def invoke(data, asset='A', predictions=None):
    return main(['report', '--asset', asset, '--data', str(data), '--predictions', str(predictions or data / 'predictions.csv'), '--out', str(data / 'out')])


def test_html_and_filtering(sample):
    assert invoke(sample) == 0
    html = (sample / 'out/A.html').read_text()
    assert 'data:image/png;base64,' in html
    assert '<script' not in html.lower() and 'http://' not in html and 'https://' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
    assert 'other asset secret' not in html
    assert html.index('first evidence') < html.index('&lt;script&gt;')
    for value in ['MACHINE', 'SENSOR', 'UNKNOWN', '0.7', 'Review', 'Inspect', '2026-01-01T00:02:00Z']:
        assert value in html
    assert html.count('<article class="alert">') == 2


def test_no_alerts_and_missing_columns(sample, capsys):
    pd.DataFrame(columns=COLUMNS).to_csv(sample / 'predictions.csv', index=False)
    assert invoke(sample) == 0
    assert 'No alerts for this asset.' in (sample / 'out/A.html').read_text()
    pd.DataFrame(columns=COLUMNS[:-1]).to_csv(sample / 'predictions.csv', index=False)
    assert invoke(sample) == 2
    assert 'Report failed: ' in capsys.readouterr().err


@pytest.mark.parametrize('data,asset', [(DATA, 'PUMP-10'), (DATA, 'missing')])
def test_refused_before_inputs(data, asset, tmp_path, monkeypatch, capsys):
    def fail(*args, **kwargs):
        pytest.fail('features must not be loaded')
    monkeypatch.setattr(report, 'load_features', fail)
    assert main(['report', '--asset', asset, '--data', str(data), '--predictions', str(tmp_path / 'missing.csv'), '--out', str(tmp_path / 'out')]) == 2
    assert f'Report refused: {asset} is not a train or validation asset' in capsys.readouterr().err
    assert not (tmp_path / 'out').exists()


def test_cli_import_isolation():
    code = "import sys; import retrofit_assistant.cli; assert 'retrofit_assistant.report' not in sys.modules; assert 'matplotlib' not in sys.modules"
    subprocess.run([sys.executable, '-c', code], check=True, env=os.environ.copy())


def test_real_validation(tmp_path):
    prediction = tmp_path / 'validation.csv'
    assert main(['predict', '--data', str(DATA), '--split', 'validation', '--out', str(prediction)]) == 0
    assert main(['report', '--asset', 'PUMP-08', '--data', str(DATA), '--predictions', str(prediction), '--out', str(tmp_path)]) == 0
    assert (tmp_path / 'PUMP-08.html').is_file()


def test_sparse_signal_uses_only_observed_values(sample, monkeypatch):
    from matplotlib.axes import Axes

    start = pd.Timestamp('2026-01-01T00:00:00Z')
    assets = pd.read_csv(sample / 'assets.csv')
    assets['window_end_utc'] = start + pd.Timedelta(minutes=16)
    assets.to_csv(sample / 'assets.csv', index=False)
    values = [float(i) if i % 5 == 0 else float('nan') for i in range(16)]
    pd.DataFrame({'asset_id': ['A'] * 16,
                  'window_start_utc': [start + pd.Timedelta(minutes=i) for i in range(16)],
                  'rows': [60] * 16, 'vibration_rms_mm_s__mean': values}).to_parquet(
                      sample / 'features_1min.parquet', index=False)
    original = Axes.plot
    plotted = []

    def record(ax, x, y, *args, **kwargs):
        plotted.extend(y.tolist())
        return original(ax, x, y, *args, **kwargs)

    monkeypatch.setattr(Axes, 'plot', record)
    assert invoke(sample) == 0
    assert plotted == [0., 5., 10., 15.]
    assert not pd.isna(plotted).any()


def test_summary_groups_and_signals(sample):
    rows = [
        ['A', '2026-01-01T00:01:00Z', 'MACHINE', 'OTHER', .77, 'full: fluid_temp_c z=2', 'Keep <action>'],
        ['A', '2026-01-01T00:02:00Z', 'MACHINE', 'OTHER', .3, 'no channel', 'Second'],
        ['A', '2026-01-01T00:03:00Z', 'SENSOR', 'OTHER', .5, 'full: missing rows', 'Latest'],
    ]
    pd.DataFrame(rows, columns=COLUMNS).to_csv(sample / 'predictions.csv', index=False)
    assert invoke(sample) == 0
    html = (sample / 'out/A.html').read_text()
    for expected in ['Distinct conditions: 2', 'Repetitions: 1', 'C1:', 'C2:', 'Alert 1', 'Alert 3',
                     '01 Jan 2026, 00:01 UTC', '01 Jan 2026, 00:02 UTC', '0.77 high',
                     'Fluid temperature (°C)', 'Gateway data', 'Keep &lt;action&gt;',
                     'full: fluid_temp_c z=2', 'Suggested action: Latest']:
        assert expected in html
    assert report.deviating_signal('no channel') == '-'
    assert report.deviating_signal('full: missing rows') == 'Gateway data'


def test_until_filters_completed_minutes_and_alerts(sample, monkeypatch):
    from matplotlib.axes import Axes
    original_load = report.load_features
    received, plotted = [], []
    original_plot = Axes.plot

    def load(*args, **kwargs):
        received.append(kwargs['until'])
        return original_load(*args, **kwargs)

    def plot(ax, x, y, *args, **kwargs):
        plotted.extend(y.tolist())
        return original_plot(ax, x, y, *args, **kwargs)

    monkeypatch.setattr(report, 'load_features', load)
    monkeypatch.setattr(Axes, 'plot', plot)
    args = ['report', '--asset', 'A', '--data', str(sample), '--predictions', str(sample / 'predictions.csv'),
            '--out', str(sample / 'out'), '--until', '2026-01-01T00:01:30Z']
    assert main(args) == 0
    assert received == [pd.Timestamp('2026-01-01T00:01:30Z')]
    assert plotted == [1., 3.]
    html = (sample / 'out/A_20260101T0001Z.html').read_text()
    assert 'first evidence' in html and '&lt;script&gt;' not in html
    frame = pd.read_parquet(sample / 'features_1min.parquet')
    frame.loc[1, 'discharge_pressure_kpa__mean'] = 9999
    frame.to_parquet(sample / 'features_1min.parquet', index=False)
    plotted.clear()
    assert main(args) == 0
    assert plotted == [1., 3.]
    args[-1] = '2026-01-01T00:01:30'
    assert main(args) == 2


def test_graph_annotations_and_stops(sample, monkeypatch):
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure
    start = pd.Timestamp('2026-01-01T00:00:00Z')
    frame = pd.read_parquet(sample / 'features_1min.parquet')
    frame['operating_mode'] = ['STOPPED', 'LOCKED_OUT']
    frame['fluid_temp_c__mean'] = [10., 11.]
    frame.to_parquet(sample / 'features_1min.parquet', index=False)
    predictions = pd.read_csv(sample / 'predictions.csv', keep_default_na=False)
    predictions.loc[predictions.asset_id == 'A', 'evidence'] = 'fluid_temp_c z=3'
    predictions.to_csv(sample / 'predictions.csv', index=False)
    spans, texts, labels, lines, legends = [], [], [], [], []
    old_span, old_annotate, old_title, old_line, old_legend = Axes.axvspan, Axes.annotate, Axes.set_title, Axes.axvline, Figure.legend
    def span(ax, x1, x2, *args, **kwargs):
        spans.append((x1, x2, kwargs))
        return old_span(ax, x1, x2, *args, **kwargs)
    def annotate(ax, s, *args, **kwargs):
        texts.append(str(s))
        return old_annotate(ax, s, *args, **kwargs)
    def label(ax, s, *args, **kwargs):
        labels.append((s, kwargs))
        return old_title(ax, s, *args, **kwargs)
    def line(ax, x, *args, **kwargs):
        lines.append(kwargs.get('color'))
        return old_line(ax, x, *args, **kwargs)
    def legend(fig, *args, **kwargs):
        legends.append(kwargs)
        return old_legend(fig, *args, **kwargs)
    monkeypatch.setattr(Axes, 'axvspan', span)
    monkeypatch.setattr(Axes, 'annotate', annotate)
    monkeypatch.setattr(Axes, 'set_title', label)
    def no_ylabel(*args, **kwargs):
        pytest.fail('signal names must not use rotated y labels')
    monkeypatch.setattr(Axes, 'set_ylabel', no_ylabel)
    monkeypatch.setattr(Axes, 'axvline', line)
    monkeypatch.setattr(Figure, 'legend', legend)
    assert invoke(sample) == 0
    assert any(a == start and b == start + pd.Timedelta(minutes=2) and kw['color'] == '#888888' for a, b, kw in spans)
    assert {'1', '2', 'C1', 'C2'} <= set(texts)
    assert (report.SIGNAL_LABELS['fluid_temp_c'], {'loc': 'left', 'fontsize': 10, 'fontweight': 'bold', 'pad': 3}) in labels
    assert [s for s, _ in labels] == [report.SIGNAL_LABELS[n] for n in CH_NAMES if n in ('discharge_pressure_kpa', 'motor_current_a', 'fluid_temp_c')]
    assert all(kwargs['fontweight'] == ('bold' if name == report.SIGNAL_LABELS['fluid_temp_c'] else 'normal')
               for name, kwargs in labels)
    assert report.SIGNAL_LABELS['vibration_crest_factor'] == 'Vibration crest factor'
    assert set(report.COLORS.values()) <= set(lines)
    assert legends[0]['bbox_to_anchor'] == (.5, 1.0)


CH_NAMES = list(report.CH.values())


def test_real_evidence_formats():
    from retrofit_assistant.pipeline import run_detector
    for split in ('train', 'validation'):
        predictions = run_detector(DATA, split)
        for evidence in predictions.evidence:
            content = evidence.partition(':')[2].strip()
            if content:
                assert report.deviating_signal(evidence) != '-', evidence


def test_until_refuses_test_asset_before_inputs(tmp_path, monkeypatch, capsys):
    def fail(*args, **kwargs):
        pytest.fail('predictions and features must not be read')
    monkeypatch.setattr(report, 'load_features', fail)
    assert main(['report', '--asset', 'PUMP-10', '--data', str(DATA), '--predictions', str(tmp_path / 'none'),
                 '--out', str(tmp_path), '--until', '2025-09-11T02:00:00Z']) == 2
    assert 'Report refused:' in capsys.readouterr().err


def test_context_actuator_does_not_open_a_panel(sample, monkeypatch):
    from matplotlib.axes import Axes
    frame = pd.read_parquet(sample / 'features_1min.parquet')
    frame['fluid_temp_c__mean'] = [10., 11.]
    frame['motor_speed_rpm__mean'] = [1000., 1001.]
    frame.to_parquet(sample / 'features_1min.parquet', index=False)
    predictions = pd.read_csv(sample / 'predictions.csv', keep_default_na=False)
    predictions.loc[predictions.asset_id == 'A', 'evidence'] = (
        'fluid_temp_c=11; actuator context: motor_speed_rpm=1001 (context only)')
    predictions.to_csv(sample / 'predictions.csv', index=False)
    titles = []
    old_title = Axes.set_title

    def title(ax, s, *args, **kwargs):
        titles.append(s)
        return old_title(ax, s, *args, **kwargs)

    monkeypatch.setattr(Axes, 'set_title', title)
    assert invoke(sample) == 0
    assert report.SIGNAL_LABELS['fluid_temp_c'] in titles
    assert report.SIGNAL_LABELS['motor_speed_rpm'] not in titles


def test_unknown_conditions_split_by_deviating_signal(sample):
    rows = [
        ['A', '2026-01-01T00:01:00Z', 'MACHINE', 'UNKNOWN', .5, 'full: fluid_temp_c z=2', 'Inspect'],
        ['A', '2026-01-01T00:01:30Z', 'MACHINE', 'UNKNOWN', .5, 'full: fluid_temp_c z=3', 'Inspect'],
        ['A', '2026-01-01T00:02:00Z', 'MACHINE', 'UNKNOWN', .5, 'full: vibration_crest_factor z=2', 'Inspect'],
        ['A', '2026-01-01T00:02:30Z', 'MACHINE', 'BEARING_WEAR', .5, 'full: fluid_temp_c z=2', 'Inspect'],
        ['A', '2026-01-01T00:02:40Z', 'MACHINE', 'BEARING_WEAR', .5, 'full: vibration_crest_factor z=2', 'Inspect'],
    ]
    pd.DataFrame(rows, columns=COLUMNS).to_csv(sample / 'predictions.csv', index=False)
    assert invoke(sample) == 0
    html = (sample / 'out/A.html').read_text()
    assert 'Distinct conditions: 3' in html
    assert 'C1: UNKNOWN — MACHINE — Fluid temperature' in html
    assert 'C2: UNKNOWN — MACHINE — Vibration crest factor' in html
    assert 'C3: BEARING_WEAR — MACHINE</h3>' in html


def test_header_shows_readable_instrumentation(sample):
    assert invoke(sample) == 0
    html = (sample / 'out/A.html').read_text()
    assert 'Instrumentation: Legacy (T0)' in html
    assert '<small>Split: train</small>' in html and 'Tier:' not in html
