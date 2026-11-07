"""Self-contained operator reports for development assets."""

import base64
from datetime import timezone
from html import escape
from io import BytesIO
from pathlib import Path
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import pandas as pd
from retrofit_sim.baselines import CH

from .data import load_assets, load_features
from .output import COLUMNS
from .params import STOP_MODES

SIGNALS = ("vibration_rms_mm_s", "bearing_temp_c", "suction_pressure_kpa",
           "discharge_pressure_kpa", "flow_m3_h", "motor_current_a")
SIGNAL_LABELS = {
    "vibration_rms_mm_s": "Vibration RMS (mm/s)",
    "vibration_accel_rms_g": "Vibration acceleration RMS (g)",
    "vibration_crest_factor": "Vibration crest factor",
    "bearing_temp_c": "Bearing temperature (°C)",
    "suction_pressure_kpa": "Suction pressure (kPa(g))",
    "discharge_pressure_kpa": "Discharge pressure (kPa(g))",
    "motor_current_a": "Motor current (A)",
    "motor_power_kw": "Motor power (kW)",
    "flow_m3_h": "Flow (m³/h)",
    "motor_speed_rpm": "Motor speed (rpm)",
    "motor_winding_temp_c": "Motor winding temperature (°C)",
    "fluid_temp_c": "Fluid temperature (°C)",
    "valve_position_pct": "Valve position (%)",
}
COLORS = {"MACHINE": "#b32d26", "SENSOR": "#d87800"}
# Provisional confidence labels; replace in P3-2.
CONFIDENCE_MEDIUM = 0.4
CONFIDENCE_HIGH = 0.7


class Refused(ValueError):
    pass


def _channel(evidence):
    matches = [(m.start(), name) for name in CH.values()
               for m in re.finditer(r'(?<![\w])' + re.escape(name) + r'(?![\w])', str(evidence))]
    return min(matches)[1] if matches else None


def deviating_signal(evidence):
    channel = _channel(evidence)
    if channel:
        return SIGNAL_LABELS[channel]
    if 'missing rows' in str(evidence).lower():
        return 'Gateway data'
    return '-'


def _time(value):
    return pd.Timestamp(value).tz_convert('UTC').strftime('%d %b %Y, %H:%M UTC')


def _confidence(value):
    value = float(value)
    label = 'low' if value < CONFIDENCE_MEDIUM else 'medium' if value < CONFIDENCE_HIGH else 'high'
    return f'{value:.2f} {label} (provisional)'


def generate(asset, data, predictions, out, until=None):
    assets = load_assets(data)
    selected = assets.loc[(assets.asset_id == asset) & assets.split.isin(['train', 'validation'])]
    if len(selected) != 1:
        raise Refused(f'{asset} is not a train or validation asset')
    if until is not None:
        until = pd.Timestamp(until)
        if until.tzinfo is None:
            raise ValueError('until must be timezone-aware')
        until = until.tz_convert('UTC')
    metadata = selected.iloc[0]
    alerts = pd.read_csv(predictions, keep_default_na=False)
    missing = [column for column in COLUMNS if column not in alerts.columns]
    if missing:
        raise ValueError(f"Missing prediction columns: {', '.join(missing)}")
    alerts = alerts.loc[alerts.asset_id == asset].copy()
    alerts['_time'] = pd.to_datetime(alerts.alert_time_utc, utc=True, errors='raise')
    if until is not None:
        alerts = alerts.loc[alerts['_time'] <= until]
    alerts = alerts.sort_values('_time', kind='stable').reset_index(drop=True)
    alerts['_number'] = range(1, len(alerts) + 1)
    conditions = []
    by_key = {}
    for _, row in alerts.iterrows():
        key = (row.fault_type, row.event_class)
        if key not in by_key:
            by_key[key] = len(conditions)
            conditions.append([])
        conditions[by_key[key]].append(row)
    features = load_features(data, selected, until=until)
    deviating = {_channel(evidence) for evidence in alerts.evidence}
    signals = [(name, name + '__mean') for name in CH.values()
               if (name in SIGNALS or name in deviating) and name + '__mean' in features
               and features[name + '__mean'].notna().any()]
    figure, axes = plt.subplots(max(1, len(signals)), 1, sharex=True,
                                figsize=(11, max(2.5, 2 * len(signals))), squeeze=False)
    for ax, (name, column) in zip(axes[:, 0], signals):
        observed = features.loc[features[column].notna(), ['window_start_utc', column]]
        groups = observed.window_start_utc.diff().gt(pd.Timedelta(minutes=10)).cumsum()
        for _, segment in observed.groupby(groups):
            ax.plot(segment.window_start_utc, segment[column], linewidth=0.7, color='#888888')
        ax.set_title(SIGNAL_LABELS[name], loc='left', fontsize=10,
                     fontweight='bold' if name in deviating else 'normal', pad=3)
    if not signals:
        axes[0, 0].text(.5, .5, 'No signal data available', ha='center', transform=axes[0, 0].transAxes)
    if 'operating_mode' in features:
        stopped = features.loc[features.operating_mode.isin(STOP_MODES), 'window_start_utc'].sort_values()
        groups = stopped.diff().ne(pd.Timedelta(minutes=1)).cumsum()
        intervals = [(group.iloc[0], group.iloc[-1] + pd.Timedelta(minutes=1)) for _, group in stopped.groupby(groups)]
    else:
        intervals = []
    for ax in axes[:, 0]:
        for start, end in intervals:
            ax.axvspan(start, end, color='#888888', alpha=.16)
        for group in conditions:
            start, end = group[0]['_time'], group[-1]['_time']
            if start == end:
                start -= pd.Timedelta(minutes=2)
                end += pd.Timedelta(minutes=2)
            ax.axvspan(start, end, color=COLORS.get(group[0].event_class, '#777777'), alpha=.08)
        for _, row in alerts.iterrows():
            ax.axvline(row['_time'], color=COLORS.get(row.event_class, '#777777'), alpha=.8, linewidth=1.3)
    top = axes[0, 0]
    figure.legend(handles=[Line2D([0], [0], color=color, label=label) for label, color in COLORS.items()]
                  + [Patch(color='#888888', alpha=.3, label='Stopped')], loc='upper center', ncol=3,
                  bbox_to_anchor=(.5, 1.0))
    axes[-1, 0].xaxis.set_major_locator(mdates.DayLocator(tz=timezone.utc))
    axes[-1, 0].xaxis.set_major_formatter(mdates.DateFormatter('%d %b', tz=timezone.utc))
    axes[-1, 0].set_xlabel('UTC')
    # Reserve a physical margin for the legend and two rows of annotations.
    figure.tight_layout(rect=(0, 0, 1, 1 - 1.05 / figure.get_figheight()))
    annotations = [(row['_time'], str(row['_number']), COLORS.get(row.event_class, '#777777'))
                   for _, row in alerts.iterrows()]
    annotations += [(group[0]['_time'], f'C{index}', COLORS.get(group[0].event_class, '#777777'))
                    for index, group in enumerate(conditions, 1)]
    annotations.sort(key=lambda item: item[0])
    # Use the other row when labels close in time would overlap.
    last_right = [float('-inf'), float('-inf')]
    for timestamp, label, color in annotations:
        x_pixels = top.transData.transform((mdates.date2num(timestamp), 0))[0]
        width = max(18, len(label) * 8) * figure.dpi / 72
        available = [i for i in range(2) if x_pixels - width / 2 > last_right[i] + 3]
        row = available[0] if available else min(range(2), key=lambda i: last_right[i])
        last_right[row] = x_pixels + width / 2
        top.annotate(label, (timestamp, 1), xycoords=('data', 'axes fraction'),
                     xytext=(0, 25 + row * 16), textcoords='offset points',
                     color=color, ha='center', va='bottom', fontsize=11, fontweight='bold',
                     annotation_clip=False)
    buffer = BytesIO()
    figure.savefig(buffer, format='png', dpi=90)
    plt.close(figure)
    chart = base64.b64encode(buffer.getvalue()).decode('ascii')
    esc = lambda value: escape(str(value), quote=True)
    cards = []
    for index, group in enumerate(conditions, 1):
        first, last = group[0], group[-1]
        items = []
        for row in group:
            fields = (('Time (UTC)', _time(row['_time'])), ('Class', row.event_class),
                      ('Fault type', row.fault_type), ('Confidence', _confidence(row.confidence)),
                      ('Deviating signal', deviating_signal(row.evidence)), ('Evidence', row.evidence),
                      ('Recommended action', row.recommended_action))
            items.append('<article class="alert"><time datetime="' + esc(row.alert_time_utc) + '"></time><h4>Alert ' + str(row['_number']) + '</h4>' + ''.join(
                f'<p><strong>{esc(label)}:</strong> {esc(value)}</p>' for label, value in fields) + '</article>')
        cards.append(f'<section class="condition"><h3>C{index}: {esc(first.fault_type)} — {esc(first.event_class)}</h3>'
                     f'<p>First: {esc(_time(first["_time"]))} | Last: {esc(_time(last["_time"]))} | Repetitions: {len(group)-1}</p>' + ''.join(items) + '</section>')
    if not cards:
        cards.append('<p>No alerts for this asset.</p>')
    observed = features.loc[features['rows'].notna()].sort_values('window_start_utc')
    if observed.empty:
        state = 'No data available'
    else:
        last_data = observed.iloc[-1]
        mode = last_data.get('operating_mode', '-')
        state = f'{_time(last_data.window_start_utc)} — {mode if pd.notna(mode) else "-"}'
    if alerts.empty:
        latest = 'No alerts up to the last data'
        action = '-'
    else:
        last_alert = alerts.iloc[-1]
        latest = f'{last_alert.fault_type} — {last_alert.event_class}'
        action = last_alert.recommended_action
    horizon = until if until is not None else metadata['window_end_utc']
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Report {esc(asset)}</title>
<style>body{{font-family:sans-serif;max-width:1100px;margin:2em auto;padding:0 1em;color:#243342}} img{{max-width:100%}} .alert,.condition,.summary{{border:1px solid #ccd4dc;border-radius:6px;padding:0 1em;margin:1em 0}} .summary{{background:#f1f5f8}}</style></head><body>
<h1>Report: {esc(asset)}</h1><p>Split: {esc(metadata['split'])} | Tier: {esc(metadata['instrumentation_tier'])}</p>
<p>UTC window: {esc(_time(metadata['window_start_utc']))} — {esc(_time(horizon))} | Alerts: {len(alerts)}</p>
<section class="summary"><h2>Summary</h2><p><strong>Advisory only: human review required</strong></p>
<p>Data up to {esc(_time(horizon))}</p><p>Last data: {esc(state)}</p><p>Distinct conditions: {len(conditions)}</p>
<p>Most recent condition: {esc(latest)}</p><p>Suggested action: {esc(action)}</p></section><h2>Signal timeline</h2>
<img alt="Signal timeline and alert markers" src="data:image/png;base64,{chart}"><h2>Alerts</h2>{''.join(cards)}</body></html>'''
    suffix = f'_{until.strftime("%Y%m%dT%H%MZ")}' if until is not None else ''
    destination = Path(out) / f'{asset}{suffix}.html'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(page, encoding='utf-8')
    return destination
