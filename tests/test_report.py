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
    alerts = html[html.index('<h2>Alerts</h2>'):]
    assert alerts.index('first evidence') < alerts.index('&lt;script&gt;')
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


@pytest.fixture
def history_report(sample):
    def render(rows, until=None):
        import re

        assets = pd.read_csv(sample / 'assets.csv')
        assets['window_end_utc'] = '2026-01-03T00:00:00Z'
        assets.to_csv(sample / 'assets.csv', index=False)
        pd.DataFrame(rows, columns=COLUMNS).to_csv(sample / 'predictions.csv', index=False)
        args = ['report', '--asset', 'A', '--data', str(sample),
                '--predictions', str(sample / 'predictions.csv'), '--out', str(sample / 'out')]
        if until is not None:
            args.extend(['--until', until])
        assert main(args) == 0
        suffix = f'_{pd.Timestamp(until).strftime("%Y%m%dT%H%MZ")}' if until else ''
        html = (sample / f'out/A{suffix}.html').read_text()
        return html, re.findall(r'<article class="alert">(.*?)</article>', html)

    return render


@pytest.mark.parametrize('event_class,fault_type', [('MACHINE', 'CAVITATION'), ('SENSOR', 'BEARING_WEAR')])
def test_diagnosis_changed_from_previous_alert(history_report, event_class, fault_type):
    _, cards = history_report([
        ['A', '2026-01-01T00:01:00Z', 'MACHINE', 'BEARING_WEAR', .9375, 'first', 'Inspect'],
        ['A', '2026-01-01T03:01:00Z', event_class, fault_type, .5, 'second', 'Review'],
    ])
    assert len(cards) == 2
    assert 'Previous alerts on this pump within 12 h' not in cards[0]
    assert 'Diagnosis changed from' not in cards[0]
    assert 'Diagnosis changed from:</strong> MACHINE/BEARING_WEAR' in cards[1]
    assert 'Previous alerts on this pump within 12 h:</strong> 01 Jan 2026, 00:01 UTC MACHINE/BEARING_WEAR (high)' in cards[1]
    assert cards[1].index('Diagnosis changed from') < cards[1].index('Time (UTC)')
    assert cards[1].index('Previous alerts on this pump within 12 h') < cards[1].index('Time (UTC)')


def test_same_diagnosis_has_history_despite_different_evidence_channels(history_report):
    html, cards = history_report([
        ['A', '2026-01-01T00:01:00Z', 'MACHINE', 'UNKNOWN', .617647, 'full: fluid_temp_c z=2', 'Inspect'],
        ['A', '2026-01-01T03:01:00Z', 'MACHINE', 'UNKNOWN', .5, 'full: vibration_crest_factor z=3', 'Review'],
    ])
    assert 'Diagnosis changed from' not in html
    assert 'Previous alerts on this pump within 12 h' in cards[1]
    assert '01 Jan 2026, 00:01 UTC MACHINE/UNKNOWN (medium)' in cards[1]


@pytest.mark.parametrize('second_time,has_history', [
    ('2026-01-01T12:01:00Z', True),
    ('2026-01-01T12:01:01Z', False),
    ('2026-01-01T00:01:00Z', False),
])
def test_previous_alert_time_boundaries(history_report, second_time, has_history):
    _, cards = history_report([
        ['A', '2026-01-01T00:01:00Z', 'MACHINE', 'BEARING_WEAR', .5, 'first', 'Inspect'],
        ['A', second_time, 'SENSOR', 'UNKNOWN', .5, 'second', 'Review'],
    ])
    assert ('Previous alerts on this pump within 12 h' in cards[1]) == has_history
    assert ('Diagnosis changed from' in cards[1]) == has_history
    if has_history:
        assert '01 Jan 2026, 00:01 UTC MACHINE/BEARING_WEAR (-)' in cards[1]


def test_history_is_ordered_and_compares_most_recent_alert_on_same_pump(history_report):
    _, cards = history_report([
        ['A', '2026-01-01T03:01:00Z', 'MACHINE', 'BEARING_WEAR', .5, 'third', 'Review'],
        ['A', '2026-01-01T01:01:00Z', 'MACHINE', 'BEARING_WEAR', .2, 'second', 'Inspect'],
        ['B', '2026-01-01T02:01:00Z', 'SENSOR', 'UNKNOWN', .5, 'other pump', 'Review'],
        ['A', '2026-01-01T00:01:00Z', 'SENSOR', 'UNKNOWN', .2, 'first', 'Inspect'],
    ])
    last = next(card for card in cards if '<h4>Alert 3</h4>' in card)
    assert 'Diagnosis changed from' not in last
    first = '01 Jan 2026, 00:01 UTC SENSOR/UNKNOWN (low)'
    second = '01 Jan 2026, 01:01 UTC MACHINE/BEARING_WEAR (low)'
    assert first + '; ' + second in last
    assert '02:01 UTC' not in last


@pytest.mark.parametrize('until,expected_cards', [
    ('2026-01-01T00:00:30Z', 0),
    ('2026-01-01T01:01:00Z', 1),
])
def test_until_history_uses_only_visible_alerts(history_report, until, expected_cards):
    html, cards = history_report([
        ['A', '2026-01-01T00:01:00Z', 'MACHINE', 'BEARING_WEAR', .2, 'first', 'Inspect'],
        ['A', '2026-01-01T03:01:00Z', 'SENSOR', 'UNKNOWN', .5, 'second', 'Review'],
    ], until=until)
    assert len(cards) == expected_cards
    assert 'Previous alerts on this pump within 12 h' not in html
    assert 'Diagnosis changed from' not in html


def test_history_and_previous_diagnosis_are_html_escaped(history_report):
    html, cards = history_report([
        ['A', '2026-01-01T00:01:00Z', '<class>', '"type"&', .2, 'first', 'Inspect'],
        ['A', '2026-01-01T03:01:00Z', 'SENSOR', 'UNKNOWN', .5, 'second', 'Review'],
    ])
    assert '<class>' not in html
    assert 'Diagnosis changed from:</strong> &lt;class&gt;/&quot;type&quot;&amp;' in cards[1]
    assert '01 Jan 2026, 00:01 UTC &lt;class&gt;/&quot;type&quot;&amp; (low)' in cards[1]


@pytest.fixture
def pattern_sample():
    """Enough completed minutes for the real causal estimator to warm up."""
    import numpy as np
    from retrofit_sim.baselines import CH

    start = pd.Timestamp('2026-01-01T00:00:00Z')
    time = start + pd.Timedelta(minutes=120, seconds=30)
    metadata = pd.Series(dict(asset_id='A', split='train', instrumentation_tier='T2_FULL',
                              motor_rated_rpm=1500., window_start_utc=start,
                              window_end_utc=start + pd.Timedelta(minutes=180),
                              channels_available='|'.join(CH[k] for k in ('q', 'pd', 'i', 'pw', 'n', 'vp'))))
    frame = pd.DataFrame(dict(asset_id=['A'] * 180,
                              window_start_utc=pd.date_range(start, periods=180, freq='min'),
                              rows=60., operating_mode='RUNNING', running_fraction=1.))
    for key, base in [('q', 100.), ('pd', 200.), ('i', 20.)]:
        frame[CH[key] + '__mean'] = base + .1 * np.sin(np.arange(180))
        frame[CH[key] + '__std'] = .1 + .002 * np.sin(np.arange(180))
        frame[CH[key] + '__count'] = 60.
    frame.loc[110:119, 'flow_m3_h__mean'] = 140.
    frame.loc[110:119, 'flow_m3_h__std'] = 2.
    alert = pd.Series(dict(asset_id='A', _time=time, alert_time_utc=time.isoformat(),
                           event_class='SENSOR', fault_type='SENSOR_NOISE', confidence=.5,
                           evidence='full: flow_m3_h isolated variance', recommended_action='Review'))
    return frame, metadata, alert


@pytest.mark.parametrize('rule,prefix,hours', [('mean', 'z_', 24), ('variance', 'zs_', 6)])
def test_pattern_uses_detector_scores_and_is_causal(pattern_sample, monkeypatch, rule, prefix, hours):
    from matplotlib.axes import Axes
    from pandas.testing import assert_series_equal

    frame, metadata, alert = pattern_sample
    alert.evidence = 'flow_m3_h isolated variance' if rule == 'variance' else 'flow_m3_h deviation'
    frame.loc[115:116, 'operating_mode'] = ['STOPPED', 'LOCKED_OUT']
    available = frame.loc[frame.window_start_utc + pd.Timedelta(minutes=1) <= alert['_time']]
    expected = report.score_features(available, metadata.to_frame().T.infer_objects())
    expected.loc[expected.operating_mode.isin(report.STOP_MODES), [prefix + key for key in ('q', 'pd', 'i')]] = float('nan')
    scored_inputs, plotted, limits, spans, axes_limits = [], [], [], [], []
    real_score, real_plot = report.score_features, Axes.plot
    real_hline, real_span, real_ylim = Axes.axhline, Axes.axvspan, Axes.set_ylim

    def score(features, assets):
        scored_inputs.append(features.copy())
        return real_score(features, assets)

    def plot(ax, x, y, *args, **kwargs):
        plotted.append((x.copy(), y.copy(), kwargs['label']))
        return real_plot(ax, x, y, *args, **kwargs)

    def hline(ax, y, *args, **kwargs):
        limits.append(y)
        return real_hline(ax, y, *args, **kwargs)

    def span(ax, x1, x2, *args, **kwargs):
        spans.append((x1, x2, kwargs['color']))
        return real_span(ax, x1, x2, *args, **kwargs)

    def ylim(ax, *args, **kwargs):
        if len(args) == 2:
            axes_limits.append(args)
        return real_ylim(ax, *args, **kwargs)

    monkeypatch.setattr(report, 'score_features', score)
    monkeypatch.setattr(Axes, 'plot', plot)
    monkeypatch.setattr(Axes, 'axhline', hline)
    monkeypatch.setattr(Axes, 'axvspan', span)
    monkeypatch.setattr(Axes, 'set_ylim', ylim)
    original = report.pattern_panel(alert, frame, metadata)
    assert len(plotted) == 3
    assert len(scored_inputs[0]) == 120
    assert scored_inputs[0].window_start_utc.max() == metadata.window_start_utc + pd.Timedelta(minutes=119)
    for (x, y, label), key in zip(plotted, ('q', 'pd', 'i')):
        assert_series_equal(x, expected.window_start_utc)
        assert_series_equal(y, expected[prefix + key])
        assert y.iloc[115:117].isna().all()
        assert ('deviating' if key == 'q' else 'witness') in label
    expected_limit = max(2 * report.B1_K, *(1.5 * abs(expected[prefix + key].dropna().iloc[-1]) for key in ('q', 'pd', 'i')))
    assert axes_limits[-1] == (-expected_limit, expected_limit)
    assert {6., -6.} <= set(limits)
    if rule == 'variance':
        assert {2., -2.} <= set(limits)
        assert 'variance: Flow (m³/h) zs=' in original
        assert 'within ±2' in original
    else:
        assert set(limits) == {6., -6.}
        assert 'mean: Flow (m³/h) z=' in original
    assert f'Last {hours} h up to the alert' in original
    assert (metadata.window_start_utc + pd.Timedelta(minutes=115),
            metadata.window_start_utc + pd.Timedelta(minutes=117), '#888888') in spans
    # Also mutate a minute already started at the alert but not yet complete.
    changed = frame.copy()
    future = changed.window_start_utc + pd.Timedelta(minutes=1) > alert['_time']
    for column in [c for c in changed if c.endswith(('__mean', '__std'))]:
        changed.loc[future, column] = 1e12
    changed.loc[future, 'operating_mode'] = 'LOCKED_OUT'
    assert report.pattern_panel(alert, changed, metadata) == original
    assert report.pattern_panel(alert, available, metadata) == original


@pytest.mark.parametrize('evidence,rule', [
    ('vibration_rms_mm_s envelope peak', 'spectrum'),
    ('vibration_rms_mm_s after lockout', 'spectrum'),
    ('suction_pressure_kpa NPSHa below margin', 'NPSH margin'),
    ('flow_m3_h unchanged across observations', 'stuck value'),
    ('flow_m3_h frozen', 'stuck value'),
])
def test_non_z_pattern_explains_rule_and_shows_only_text(pattern_sample, monkeypatch, evidence, rule):
    frame, metadata, alert = pattern_sample
    alert.evidence = evidence

    def forbidden(*args, **kwargs):
        pytest.fail('Non-z rules must not compute a new plot')

    monkeypatch.setattr(report, 'score_features', forbidden)
    html = report.pattern_panel(alert, frame, metadata)
    assert f'Decided by {rule}, not by the z of the mean' in html
    assert 'witnesses:' in html and f'Evidence: {evidence}' in html
    assert '<img' not in html


@pytest.mark.parametrize('missing', ['operating_mode', 'running_fraction', 'channel', 'completed'])
def test_pattern_missing_inputs_fall_back(pattern_sample, monkeypatch, missing):
    frame, metadata, alert = pattern_sample
    if missing == 'channel':
        alert.evidence = 'missing rows <unknown>'
    elif missing == 'completed':
        alert['_time'] = metadata.window_start_utc
    else:
        frame = frame.drop(columns=missing)

    def forbidden(*args, **kwargs):
        pytest.fail('Missing inputs must use the fallback')

    monkeypatch.setattr(report, 'score_features', forbidden)
    html = report.pattern_panel(alert, frame, metadata)
    assert 'No z-score pattern for this alert.' in html and '<img' not in html
    if missing == 'channel':
        assert '&lt;unknown&gt;' in html


def test_pattern_selects_deviating_then_installed_coupled_witnesses():
    from retrofit_sim.baselines import CH

    assert report.pattern_channels('flow_m3_h; discharge_pressure_kpa', set(CH.values())) == [
        ('q', CH['q']), ('pd', CH['pd']), ('i', CH['i'])]
    assert report.pattern_channels('flow_m3_h', {CH['q'], CH['pw'], CH['n'], CH['vp']}) == [
        ('q', CH['q']), ('pw', CH['pw'])]
    assert report.pattern_channels('no channel', set(CH.values())) == []


def fixed_pattern_scores(monkeypatch, frame, values, prefix):
    """Prescribe only detector outputs to exercise presentation at exact thresholds."""
    scored = frame.copy()
    for key, value in values.items():
        scored[prefix + key] = value
    monkeypatch.setattr(report, 'score_features', lambda features, assets: scored)


@pytest.mark.parametrize('rule,prefix,symbol', [('mean', 'z_', 'z'), ('variance', 'zs_', 'zs')])
@pytest.mark.parametrize('value,display,judgment', [
    (5.96, '+5.96', 'within'), (-5.96, '-5.96', 'within'),
    (5.996, '+5.996', 'within'), (6.04, '+6.04', 'beyond'), (-6.04, '-6.04', 'beyond'),
])
def test_pattern_rounding_agrees_with_shown_value(pattern_sample, monkeypatch, rule, prefix, symbol, value, display, judgment):
    frame, metadata, alert = pattern_sample
    alert.evidence = 'flow_m3_h isolated variance' if rule == 'variance' else 'flow_m3_h deviation'
    fixed_pattern_scores(monkeypatch, frame.iloc[:120], dict(q=value, pd=0., i=0.), prefix)
    html = report.pattern_panel(alert, frame, metadata)
    assert f'{symbol}={display} ({judgment} ±6)' in html
    assert f'{symbol}=+6.0 ' not in html and f'{symbol}=-6.0 ' not in html


@pytest.mark.parametrize('rule,prefix', [('mean', 'z_'), ('variance', 'zs_')])
@pytest.mark.parametrize('witness,still', [(0., True), (2., True), (-2., True), (2.01, False)])
def test_machine_reading_with_still_witnesses(pattern_sample, monkeypatch, rule, prefix, witness, still):
    frame, metadata, alert = pattern_sample
    alert.event_class = 'MACHINE'
    alert.evidence = 'flow_m3_h isolated variance' if rule == 'variance' else 'flow_m3_h deviation'
    fixed_pattern_scores(monkeypatch, frame.iloc[:120], dict(q=8., pd=witness, i=0.), prefix)
    html = report.pattern_panel(alert, frame, metadata)
    required = ('Witnesses stay within ±2, so they do not explain this label; '
                'it comes from another rule (see evidence).')
    assert (required in html) == still
    assert (report.CLASS_READING['MACHINE'] in html) != still


@pytest.mark.parametrize('rule,prefix', [('mean', 'z_'), ('variance', 'zs_')])
def test_stopped_scores_do_not_enter_pattern_sentence(pattern_sample, monkeypatch, rule, prefix):
    frame, metadata, alert = pattern_sample
    alert.evidence = 'flow_m3_h isolated variance' if rule == 'variance' else 'flow_m3_h deviation'
    scored = frame.iloc[:120].copy()
    scored.loc[118:119, 'operating_mode'] = ['STOPPED', 'LOCKED_OUT']
    for key, value in dict(q=8., pd=0., i=0.).items():
        scored[prefix + key] = value
        scored.loc[118:119, prefix + key] = 12345.
    monkeypatch.setattr(report, 'score_features', lambda *args: scored)
    html = report.pattern_panel(alert, frame, metadata)
    assert '=+8.0 (beyond ±6)' in html
    assert '12345' not in html.split('<img')[0]
    assert 'stopped minutes shaded and not scored' in html


def test_missing_candidate_score_does_not_promote_witness(pattern_sample, monkeypatch):
    frame, metadata, alert = pattern_sample
    fixed_pattern_scores(monkeypatch, frame.iloc[:120], dict(q=float('nan'), pd=8., i=0.), 'zs_')
    html = report.pattern_panel(alert, frame, metadata)
    assert 'No z-score pattern for this alert.' in html
    assert '<img' not in html


@pytest.mark.parametrize('until,minute', [(None, 150), ('2026-01-01T02:01:00Z', 120)])
def test_operator_order_and_pattern_use_last_visible_alert(pattern_sample, tmp_path, monkeypatch, until, minute):
    frame, metadata, alert = pattern_sample
    metadata.to_frame().T.to_csv(tmp_path / 'assets.csv', index=False)
    frame.to_parquet(tmp_path / 'features_1min.parquet', index=False)
    rows = []
    for m in (150, 120):
        row = {column: alert[column] for column in COLUMNS}
        row['alert_time_utc'] = (metadata.window_start_utc + pd.Timedelta(minutes=m)).isoformat()
        rows.append(row)
    pd.DataFrame(rows).to_csv(tmp_path / 'predictions.csv', index=False)
    received = []
    real_panel = report.pattern_panel

    def panel(selected, features, asset):
        received.append(selected['_time'])
        return real_panel(selected, features, asset)

    monkeypatch.setattr(report, 'pattern_panel', panel)
    html = report.generate('A', tmp_path, tmp_path / 'predictions.csv', tmp_path / 'out', until=until).read_text()
    assert received == [metadata.window_start_utc + pd.Timedelta(minutes=minute)]
    assert html.index('<section class="operator">') < html.index('<h2>Pattern</h2>') < html.index('<h2>Detail</h2>')
    assert '<span class="state sensor">sensor</span>' in html
    for label in ('Action:', 'Reason:', 'Confidence:'):
        assert label in html[:html.index('<h2>Pattern</h2>')]
    assert not any(value in html.lower() for value in ('http://', 'https://', '<script'))


@pytest.mark.parametrize('event_class,fault_type,state', [
    ('MACHINE', 'OTHER', 'machine'), ('SENSOR', 'OTHER', 'sensor'),
    ('MACHINE', 'UNKNOWN', 'attention'), ('<script>', 'OTHER', 'attention'),
])
def test_operator_has_textual_safe_state(sample, event_class, fault_type, state):
    rows = [['A', '2026-01-01T00:01:00Z', event_class, fault_type, .5, 'no channel', 'Review']]
    pd.DataFrame(rows, columns=COLUMNS).to_csv(sample / 'predictions.csv', index=False)
    html = report.generate('A', sample, sample / 'predictions.csv', sample / 'out').read_text()
    assert f'<span class="state {state}">{state}</span>' in html
    assert '<script' not in html


def test_operator_without_alerts_is_normal(sample):
    pd.DataFrame(columns=COLUMNS).to_csv(sample / 'predictions.csv', index=False)
    html = report.generate('A', sample, sample / 'predictions.csv', sample / 'out').read_text()
    assert '<span class="state normal">normal</span>' in html


@pytest.mark.parametrize('asset', ['PUMP-10', 'PUMP-11', 'PUMP-12'])
def test_generate_refuses_test_asset_before_predictions_or_features(asset, monkeypatch):
    metadata = pd.DataFrame([dict(asset_id=asset, split='test')])
    monkeypatch.setattr(report, 'load_assets', lambda data: metadata)

    def forbidden(*args, **kwargs):
        pytest.fail('Refused asset must not read predictions or features')

    monkeypatch.setattr(report.pd, 'read_csv', forbidden)
    monkeypatch.setattr(report, 'load_features', forbidden)
    with pytest.raises(report.Refused, match='not a train or validation asset'):
        report.generate(asset, 'missing', 'missing.csv', 'build/refused')
