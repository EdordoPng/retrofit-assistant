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
    pd.DataFrame([dict(asset_id='A', split='train', instrumentation_tier='T0',
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
