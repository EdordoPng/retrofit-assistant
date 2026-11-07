"""Fleet output uses supplied numbers and never opens a held-out pump page."""

import json
import re
from pathlib import Path

import pytest

from retrofit_assistant import dashboard, pump_table, report


@pytest.fixture
def table():
    pumps = []
    for number in range(1, 13):
        split = 'train' if number <= 7 else 'validation' if number <= 9 else 'test'
        row = dict(asset_id=f'PUMP-{number:02}', split=split, tier='T2')
        if split == 'test':
            row['status'] = pump_table.TEST_STATUS
        else:
            row.update({key: 917 + number * 10 + i for i, key in enumerate(pump_table.COUNTS)})
        pumps.append(row)
    # Deliberately inconsistent totals: the dashboard must display, never recompute.
    totals = {split: dict(composite=12.345, **dict.fromkeys(pump_table.COUNTS, 1234))
              for split in ('train', 'validation')}
    return dict(commit='synthetic', pumps=pumps, split_totals=totals,
                split_roles=pump_table.SPLIT_ROLES,
                ablation=[dict(tier='T0', split='validation', assets=['PUMP-08'],
                               composite=98.765, detected=917, scored_events=918, type_correct=919)],
                notes=['Synthetic <note>'])


def pump_rows(html):
    fleet = html.split('<tbody>', 1)[1].split('</tbody>', 1)[0]
    return [row for row in re.findall(r'<tr>(.*?)</tr>', fleet) if '<td>PUMP-' in row or '>PUMP-' in row]


def test_fleet_reads_all_counts_from_json_and_links_only_visible_pumps(table):
    links = {row['asset_id']: row['asset_id'] + '.html' for row in table['pumps']}
    html = dashboard.fleet_page(table, links)
    rows = pump_rows(html)
    assert len(rows) == 12
    for source, row in zip(table['pumps'], rows):
        if source['split'] == 'test':
            assert '<a' not in row
            assert pump_table.TEST_STATUS in row
        else:
            assert f'href="{source["asset_id"]}.html"' in row
            for key in pump_table.COUNTS:
                assert f'<td>{source[key]}</td>' in row
    assert '<th>1234</th>' in html
    assert 'Official composite: train 12.345, validation 12.345.' in html
    assert '<td>917 / 918</td><td>919</td>' in html
    assert '&lt;note&gt;' in html


@pytest.mark.parametrize('count', pump_table.COUNTS)
def test_fleet_rejects_any_counts_on_test_pumps(table, count):
    table['pumps'][-1][count] = 0
    with pytest.raises(ValueError, match='test pumps carry only tier and status'):
        dashboard.fleet_page(table, {})


def test_fleet_requires_held_out_status(table):
    table['pumps'][-1]['status'] = 'scored'
    with pytest.raises(ValueError, match='test pumps carry only tier and status'):
        dashboard.fleet_page(table, {})


def test_dashboard_build_passes_paths_and_uses_only_train_validation(table, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'table.json'
    source.write_text(json.dumps(table))
    calls = []

    def generate(asset, data, predictions, out, *, pump):
        assert asset not in {'PUMP-10', 'PUMP-11', 'PUMP-12'}
        calls.append((asset, data, predictions, out, pump))
        return Path(out) / f'{asset}.html'

    monkeypatch.setattr(report, 'generate', generate)
    # The generator/scorer imported by pump_table must never be used by dashboard.
    def forbidden(*args, **kwargs):
        pytest.fail('Fleet numbers must not be recalculated')

    monkeypatch.setattr(pump_table, 'run_detector', forbidden)
    monkeypatch.setattr(pump_table, 'score', forbidden)
    predictions = dict(train='train.csv', validation='validation.csv', test='forbidden.csv')
    index = dashboard.build(source, 'data-path', predictions, 'build/dashboard')
    assert index == Path('build/dashboard/index.html')
    assert len(calls) == 9
    for asset, data, prediction, out, pump in calls:
        assert pump == next(row for row in table['pumps'] if row['asset_id'] == asset)
        assert data == 'data-path'
        assert prediction == ('train.csv' if int(asset[-2:]) <= 7 else 'validation.csv')
        assert out == Path('build/dashboard')
    assert len(pump_rows(index.read_text())) == 12
    assert 'href="PUMP-09.html"' in index.read_text()


def test_invalid_fleet_rejected_before_operator_inputs(table, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    table['pumps'][-1]['detected'] = 917
    source = tmp_path / 'table.json'
    source.write_text(json.dumps(table))

    def forbidden(*args, **kwargs):
        pytest.fail('Invalid fleet must be refused before operator input is opened')

    monkeypatch.setattr(report, 'generate', forbidden)
    with pytest.raises(ValueError, match='test pumps carry only tier and status'):
        dashboard.build(source, 'data', dict(train='train.csv'), 'build/dashboard')
    assert not Path('build/dashboard').exists()


@pytest.mark.parametrize('destination', ['elsewhere', '../escape', '/tmp/dashboard-escape'])
def test_output_must_be_inside_build(destination, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match='inside build/'):
        dashboard.build('missing.json', 'missing-data', {}, destination)


def test_symlink_cannot_escape_build(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path('build').mkdir()
    Path('elsewhere').mkdir()
    Path('build/link').symlink_to(tmp_path / 'elsewhere', target_is_directory=True)
    with pytest.raises(ValueError, match='inside build/'):
        dashboard.build('missing.json', 'missing-data', {}, 'build/link')


def test_dashboard_cli_passes_table_and_prediction_arguments(monkeypatch, capsys):
    calls = []

    def build(*args):
        calls.append(args)
        return Path('build/dashboard/index.html')

    monkeypatch.setattr(dashboard, 'build', build)
    assert dashboard.main(['--table', 'custom-table.json', '--data', 'data',
                           '--train-predictions', 't.csv', '--validation-predictions', 'v.csv']) == 0
    assert calls == [('custom-table.json', 'data', dict(train='t.csv', validation='v.csv'), 'build/dashboard')]
    assert 'build/dashboard/index.html' in capsys.readouterr().out


def test_fleet_is_self_contained_and_uses_brand_css_variables(table):
    html = dashboard.fleet_page(table, {})
    assert not any(value in html.lower() for value in ('http://', 'https://', '<script'))
    assert ':root{' in html and '--brand:#0033A0' in html
    assert 'font-family:Nunito,system-ui,sans-serif' in html
    assert 'font-weight:800' in html
    expected = dict(normal=('#009E73', '#00775A', '#3CC79E'),
                    attention=('#E69F00', '#8A5A00', '#F2B33D'),
                    sensor=('#CC79A7', '#9C4A7A', '#E5A3C8'),
                    machine=('#D55E00', '#A84400', '#FF8A3D'))
    assert report.STATES == expected
    for name, colors in expected.items():
        assert report.BRAND not in colors
        assert f'--{name}:{colors[0]};--{name}-text:{colors[1]};--{name}-dark:{colors[2]};' in html
    assert '.state.attention{border-color:var(--attention-text);color:var(--attention-text)}' in html


def test_fleet_tier_legend_follows_pump_table_once(table):
    html = dashboard.fleet_page(table, {})
    legend = ('T0: existing signals only (legacy) · T1: low-cost retrofit '
              '(suction pressure, wireless vibration and temperature) · T2: fully instrumented.')
    assert html.count(legend) == 1
    assert html.index('</table>') < html.index(legend) < html.index('Official composite:')
    assert html.split('</table>', 1)[1].startswith(f'\n<p>{legend}</p>')


@pytest.mark.parametrize('commit,escaped', [('abc1234', 'abc1234'), ('<abc>&', '&lt;abc&gt;&amp;')])
def test_fleet_distinguishes_frozen_detector_from_table_commit(table, commit, escaped):
    table['commit'] = commit
    html = dashboard.fleet_page(table, {})
    assert dashboard.DETECTOR_FREEZE == 'v1.0-freeze (c355e31)'
    expected = (f'Detector: v1.0-freeze (c355e31). Table generated at {escaped} '
                '(evaluation code only).')
    assert expected in html
    assert html.index('Advisory only: human review required.') < html.index(expected)
    for row in pump_rows(html):
        source = next(pump for pump in table['pumps'] if pump['asset_id'] in row)
        if source['split'] != 'test':
            assert all(f'<td>{source[key]}</td>' in row for key in pump_table.COUNTS)
