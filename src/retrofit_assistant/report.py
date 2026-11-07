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

from .confidence import TRAIN_LEVELS, evidence_level
from .data import AVAILABILITY, load_assets, load_features
from .consistency import coupled_channels, observations
from .detectors import score_features
from .output import COLUMNS
from .params import B1_K, COUPLED_STILL_FRACTION, NOISE_RECENT_MIN, STOP_MODES

TIERS = {'T0_LEGACY': 'Legacy (T0)', 'T1_RETROFIT': 'Retrofit (T1)', 'T2_FULL': 'Full (T2)'}
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
COLORS = {"MACHINE": "#D55E00", "SENSOR": "#CC79A7"}
# Okabe-Ito states: fill or line, text on white, dark theme. Always shown with a text label.
STATES = {
    "normal": ("#009E73", "#00775A", "#3CC79E"),
    "attention": ("#E69F00", "#8A5A00", "#F2B33D"),
    "sensor": ("#CC79A7", "#9C4A7A", "#E5A3C8"),
    "machine": ("#D55E00", "#A84400", "#FF8A3D"),
}
BRAND = "#0033A0"
CLASS_READING = {
    "MACHINE": "The label reads this as a change in the machine rather than in one instrument",
    "SENSOR": "The label reads this as an instrument fault rather than a change in the machine",
}
PATTERN_HOURS = 24
LONG_STOP = pd.Timedelta(minutes=30)
STOP_WIDTH_MIN = 12  # drawn width of a compressed stop, in axis minutes
PATTERN_LINE = {"sensor": "#CC79A7", "machine": "#D55E00", "attention": "#8A5A00", "normal": "#00775A"}
WITNESS_LINE = "#7A8591"
SENSOR_VERBS = {"SENSOR_NOISE_SPIKES": "is noisy", "SENSOR_CALIBRATION_SHIFT": "shifts",
                "SENSOR_DRIFT": "drifts"}
# Plain-language reason, fixed per fault type; the raw code stays in the detail.
REASONS = {
    "SENSOR_NOISE_SPIKES": "Noise spikes on the {signal} sensor (instrument fault)",
    "SENSOR_CALIBRATION_SHIFT": "Calibration shift of the {signal} sensor (instrument fault)",
    "SENSOR_DRIFT": "Drift of the {signal} sensor (instrument fault)",
    "SENSOR_STUCK": "The {signal} sensor is stuck at one value (instrument fault)",
    "COMMUNICATION_LOSS": "Data from the pump stopped arriving (communication loss)",
    "BEARING_WEAR": "Bearing wear (machine fault)",
    "SUCTION_STRAINER_CLOGGING": "Clogging of the suction strainer (machine fault)",
    "CAVITATION": "Cavitation at the pump inlet (machine fault)",
    "DISCHARGE_RESTRICTION": "Restriction on the discharge side (machine fault)",
    "MISALIGNMENT": "Shaft misalignment (machine fault)",
    "IMBALANCE": "Rotor imbalance (machine fault)",
    "IMPELLER_WEAR": "Impeller wear (machine fault)",
    "AIR_ENTRAINMENT": "Air entering the pumped liquid (machine fault)",
    "UNKNOWN": "Unclassified deviation on {signal} (needs review)",
}
ACTION_PARTS = ("Inspect:", "Do:", "Rule out first:", "Note:")
VARIANCE_PATTERN_HOURS = 6  # variance alerts are short; a day hides them
# Rules not decided by a z of the mean: (evidence marker, name). No new chart for these.
OTHER_RULES = (("envelope peak", "spectrum"), ("after lockout", "spectrum"), ("NPSHa", "NPSH margin"),
               ("unchanged across", "stuck value"), (" frozen", "stuck value"))
PATTERN_INPUTS = {"window_start_utc", "operating_mode", "running_fraction"}
CONFIDENCE_MEDIUM = 0.4
CONFIDENCE_HIGH = 0.7


CSS = (':root{--brand:%s;--bg:#FFFFFF;--ink:#243342;--border:#ccd4dc;--summary:#f1f5f8;%s} '
       'body{font-family:Nunito,system-ui,sans-serif;font-weight:400;max-width:1100px;margin:2em auto;padding:0 1em;color:var(--ink);background:var(--bg)} '
       'h1,h2,h3{font-weight:800;color:var(--brand)} img{max-width:100%%} '
       '.alert,.condition,.summary,.operator,.pattern{border:1px solid var(--border);border-radius:6px;padding:0 1em;margin:1em 0} '
       '.summary{background:var(--summary)} .operator{border-width:2px} '
       '.state{display:inline-block;padding:.1em .6em;border-radius:1em;font-weight:600;border:2px solid} %s '
       'table{border-collapse:collapse} td,th{border:1px solid var(--border);padding:.2em .5em}'
       ) % (BRAND, ''.join(f'--{n}:{f};--{n}-text:{t};--{n}-dark:{d};' for n, (f, t, d) in STATES.items()),
            ' '.join(f'.state.{n}{{border-color:var(--{n if n != "attention" else n + "-text"});color:var(--{n}-text)}}' for n in STATES))


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


def _condition_title(row):
    title = f'{row.fault_type} — {row.event_class}'
    return f'{title} — {deviating_signal(row.evidence)}' if row.fault_type == 'UNKNOWN' else title


def _time(value):
    return pd.Timestamp(value).tz_convert('UTC').strftime('%d %b %Y, %H:%M UTC')


def _confidence(value):
    value = float(value)
    name = evidence_level(value)
    if name is not None:
        level = TRAIN_LEVELS[name]
        return (f'confidence {name} · alert {level.alert_reliability:.2f} (n={level.n})'
                f' · type {level.type_reliability:.2f} (n={level.n})')
    label = 'low' if value < CONFIDENCE_MEDIUM else 'medium' if value < CONFIDENCE_HIGH else 'high'
    return f'{value:.2f} {label}'


def _state(alert):
    if alert is None:
        return "normal"
    if alert.fault_type == "UNKNOWN":
        return "attention"
    state = str(alert.event_class).lower()
    return state if state in ("machine", "sensor") else "attention"


def pattern_channels(evidence, installed, limit=3):
    """The deviating channel, then the installed COUPLED witnesses the detector uses, at most `limit`."""
    name = _channel(evidence)
    if name is None:
        return []
    keys = {channel: key for key, channel in CH.items()}
    key = keys[name]
    # Same exclusion as consistency_state: suction may mask a hydraulic fault.
    witnesses = [c for c in coupled_channels(key, installed) if not (key in ("pd", "q") and c == "ps")]
    return [(key, CH[key]) for key in (key, *witnesses)][:limit]


def _signal_name(name):
    label = re.sub(r" \(.*\)$", "", SIGNAL_LABELS.get(name, name))
    return label[:1].lower() + label[1:]


def reason_text(alert):
    template = REASONS.get(alert.fault_type, "{code}")
    channel = _channel(alert.evidence)
    signal = _signal_name(channel) if channel else "a signal"
    return template.format(signal=signal, code=alert.fault_type)


def action_lines(action):
    """Split the CSV action at its fixed labels without changing any character of it."""
    text = str(action)
    starts = sorted(i for i in (text.find(label) for label in ACTION_PARTS) if i >= 0)
    if not starts or starts[0] != 0:
        return [text]
    return [text[a:b].strip() for a, b in zip(starts, starts[1:] + [len(text)])]


def hidden_minutes(window):
    """Stopped minutes and the non-steady minutes next to them carry no z in the panel."""
    stopped = window.operating_mode.isin(STOP_MODES).to_numpy()
    steady = window["steady"].fillna(False).to_numpy(dtype=bool) if "steady" in window else ~stopped
    hidden = stopped.copy()
    for order in (range(len(window)), range(len(window) - 1, -1, -1)):
        previous = False
        for i in order:
            if stopped[i]:
                previous = True
            elif previous and not steady[i]:
                hidden[i] = True
            else:
                previous = False
    return pd.Series(hidden, index=window.index), pd.Series(stopped, index=window.index)


def compressed_axis(times, hidden, stopped):
    """Axis minutes with every hidden run longer than LONG_STOP drawn STOP_WIDTH_MIN wide.

    Returns positions (same order as times) and the compressed runs as
    (start position, end position, stopped duration)."""
    positions, runs, x, i = [], [], 0.0, 0
    times, hidden, stopped = list(times), list(hidden), list(stopped)
    while i < len(times):
        j = i
        while j < len(times) and hidden[j] == hidden[i]:
            j += 1
        span = times[j - 1] - times[i] + pd.Timedelta(minutes=1)
        if hidden[i] and span > LONG_STOP:
            step = STOP_WIDTH_MIN / (j - i)
            runs.append((x, x + STOP_WIDTH_MIN, sum(stopped[i:j]) * pd.Timedelta(minutes=1)))
            positions += [x + step * k for k in range(j - i)]
            x += STOP_WIDTH_MIN
        else:
            positions += [x + (times[k] - times[i]) / pd.Timedelta(minutes=1) for k in range(i, j)]
            x = positions[-1] + 1
        i = j
    return positions, runs


def _duration(delta):
    minutes = int(delta / pd.Timedelta(minutes=1))
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if hours else f"{minutes} min"


def shown_value(value, limit):
    """Signed value with enough decimals that its rounding never crosses or equals the limit."""
    for digits in (1, 2, 3):
        shown = round(abs(value), digits)
        if shown != limit and (shown > limit) == (abs(value) > limit):
            break
    return f"{value:+.{digits}f}"


def pattern_rule(evidence):
    """'mean', 'variance', or the name of a rule that is not decided by a z-score."""
    evidence = str(evidence)
    for marker, name in OTHER_RULES:
        if marker in evidence:
            return name
    return "variance" if "isolated variance" in evidence else "mean"


def pattern_panel(alert, features, metadata):
    """One panel: the detector's z (mean) or zs (variance) of the deviating channel and its
    witnesses, from minutes available at the alert only, plus one sentence."""
    esc = lambda value: escape(str(value), quote=True)
    installed = set(str(metadata.get("channels_available", "")).split("|"))
    # Every detector witness decides the sentence; at most three lines are drawn.
    channels = pattern_channels(alert.evidence, installed, limit=None)
    rule = pattern_rule(alert.evidence)
    labels = [SIGNAL_LABELS.get(name, name) for _, name in channels]
    reading = CLASS_READING.get(alert.event_class, "See the evidence below")
    if rule not in ("mean", "variance"):
        witnesses = ", ".join(labels[1:]) or "none installed"
        return (f'<section class="pattern"><h2>Pattern</h2><p>{esc(f"Decided by {rule}, not by the z of the mean. Deviating signal: {labels[0] if labels else deviating_signal(alert.evidence)}; witnesses: {witnesses}. {reading}.")}</p>'
                f'<p><small>Evidence: {esc(alert.evidence)}</small></p></section>')
    fallback = ('<section class="pattern"><h2>Pattern</h2><p>No z-score pattern for this alert. '
                f'Evidence: {esc(alert.evidence)}</p></section>')
    time = alert['_time']
    latency = AVAILABILITY["features_1min.parquet"].latency
    available = features.loc[features.window_start_utc + latency <= time]
    if not channels or available.empty or not PATTERN_INPUTS <= set(available.columns):
        return fallback
    prefix = "zs_" if rule == "variance" else "z_"
    scored = score_features(available, metadata.to_frame().T.infer_objects())
    hours = VARIANCE_PATTERN_HOURS if rule == "variance" else PATTERN_HOURS
    window = scored.loc[scored.window_start_utc >= time - pd.Timedelta(hours=hours)].copy()
    hidden, stopped = hidden_minutes(window)
    deviating = channels[0]
    if prefix + deviating[0] not in window or not window[prefix + deviating[0]].notna().any():
        return fallback
    for key, _ in channels:
        # Keep missing witnesses in the decision: absence cannot establish stillness.
        if prefix + key not in window:
            window[prefix + key] = float("nan")
        window.loc[hidden, prefix + key] = float("nan")
    still = B1_K * COUPLED_STILL_FRACTION
    limits = {key: B1_K if i == 0 else still for i, (key, _) in enumerate(channels)}
    symbol = "zs" if rule == "variance" else "z"
    positions, runs = compressed_axis(window.window_start_utc, hidden, stopped)
    x = pd.Series(positions, index=window.index)
    figure, ax = plt.subplots(figsize=(11, 3))
    ax.axhspan(-still, still, color="#888888", alpha=.10, linewidth=0)
    for sign in (1, -1):
        ax.axhline(sign * B1_K, color="#555555", linewidth=.8, linestyle="--")
    for start_x, end_x, stop in runs:
        ax.axvspan(start_x, end_x, color="#888888", alpha=.25, linewidth=0)
        ax.text((start_x + end_x) / 2, 0, f"stopped {_duration(stop)}", rotation=90, ha="center",
                va="center", fontsize=8, color="#444444")
    flags = hidden.to_numpy()
    for i in range(len(flags)):
        if flags[i] and not any(start_x <= positions[i] < end_x for start_x, end_x, _ in runs):
            ax.axvspan(positions[i], positions[i] + 1, color="#888888", alpha=.16, linewidth=0)
    status = _state(alert)
    for (key, name), style in zip(channels, ("-", "--", ":")):
        role = "deviating" if key == channels[0][0] else "witness"
        color = PATTERN_LINE[status] if role == "deviating" else WITNESS_LINE
        ax.plot(x, window[prefix + key], linestyle=style, color=color,
                linewidth=1.4 if role == "deviating" else 1.1, label=f"{SIGNAL_LABELS.get(name, name)} ({role})")
    alert_x = x.iloc[-1] + 1 if len(x) else 0
    ax.axvline(alert_x, color=PATTERN_LINE[status], linewidth=1.5)
    visible = window.loc[~hidden]
    at_alert = [visible[prefix + key].dropna().iloc[-1] for key, _ in channels if visible[prefix + key].notna().any()]
    # Values beyond the limit are clipped; the caption says so.
    limit = max([2 * B1_K] + [1.5 * abs(v) for v in at_alert])
    ax.set_ylim(-limit, limit)
    ax.text(.995, still / (2 * limit) + .5, "witness band", transform=ax.transAxes, ha="right", va="bottom",
            fontsize=8, color="#444444")
    ax.text(.995, B1_K / (2 * limit) + .5, "deviation threshold", transform=ax.transAxes, ha="right",
            va="bottom", fontsize=8, color="#444444")
    ax.set_ylabel(symbol)
    ax.legend(loc="upper left", fontsize=9)
    ticks = [(position, t) for position, t, h in zip(positions, window.window_start_utc, hidden)
             if not h and t.minute == 0 and t.hour % (1 if hours <= 6 else 3) == 0]
    ax.set_xticks([p for p, _ in ticks], [t.strftime("%d %b %H:%M") for _, t in ticks])
    for start_x, end_x, _ in runs:
        for edge in (start_x, end_x):
            ax.text(edge, -limit, "//", ha="center", va="center", fontsize=9, color="#444444", clip_on=False)
    figure.tight_layout()
    buffer = BytesIO()
    figure.savefig(buffer, format="png", dpi=90)
    plt.close(figure)
    image = base64.b64encode(buffer.getvalue()).decode("ascii")
    recent_start = visible.window_start_utc.max() - pd.Timedelta(minutes=NOISE_RECENT_MIN)
    def last(key):
        """The statistic the detector judges: latest real z (mean); for variance the
        median zs of the deviating channel and the median |zs| of a witness over the
        last NOISE_RECENT_MIN minutes, as in noise_channel."""
        obs = observations(visible, key)
        values = obs[prefix + key].dropna() if prefix + key in obs else obs.iloc[:0, :0]
        if rule == "variance":
            values = values[obs.loc[values.index, "window_start_utc"] > recent_start]
            if values.empty:
                return None
            return values.median() if key == channels[0][0] else values.abs().median()
        return None if values.empty else values.iloc[-1]
    def z_text(key, name):
        value = last(key)
        if value is None:
            return f"{SIGNAL_LABELS.get(name, name)} has no score"
        beyond = abs(value) > limits[key]
        shown = f"|{symbol}|" if rule == "variance" and key != channels[0][0] else symbol
        text = shown_value(value, limits[key])
        text = text.lstrip("+") if shown.startswith("|") else text
        return (f"{SIGNAL_LABELS.get(name, name)} {shown}={text} "
                f"({'beyond' if beyond else 'within'} ±{limits[key]:g})")
    (key, name), witnesses = channels[0], channels[1:]
    measure = f"variance, median of the last {NOISE_RECENT_MIN} min" if rule == "variance" else "mean"
    numbers = f"At {_time(time)}, {measure}: {z_text(key, name)}"
    numbers += ("; witnesses: " + ", ".join(z_text(*w) for w in witnesses)) if witnesses else "; no installed witness"
    def names(items):
        words = [_signal_name(n) for _, n in items]
        return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]
    scored_witnesses = [w for w in witnesses if last(w[0]) is not None]
    following = [w for w in scored_witnesses if abs(last(w[0])) >= still]
    all_still = bool(witnesses) and len(scored_witnesses) == len(witnesses) and not following
    deviating_name = _signal_name(name)[:1].upper() + _signal_name(name)[1:]
    # Same rule as consistency_state: a sensor fault needs at least two still witnesses.
    still_count = len(scored_witnesses) - len(following)
    if alert.event_class == "SENSOR" and all_still and len(witnesses) >= 2:
        verb = SENSOR_VERBS.get(alert.fault_type, "deviates")
        plural = len(witnesses) > 1
        sentence = (f"{deviating_name} {verb} while {names(witnesses)}, which it should affect, "
                    f"{'stay' if plural else 'stays'} normal: the instrument is the likely cause, not the pump.")
    elif alert.event_class == "SENSOR" and not following and still_count < 2:
        available_text = "Only one independent witness is" if still_count == 1 else "No independent witness is"
        sentence = (f"{available_text} available, so the instrument fault cannot be confirmed; "
                    "the official diagnosis stands.")
    elif alert.event_class == "MACHINE" and following:
        sentence = (f"{deviating_name} moves and {names(following)} "
                    f"{'move' if len(following) > 1 else 'moves'} with it: the change is real, in the machine.")
    elif alert.event_class == "MACHINE" and all_still:
        sentence = (f"Witnesses stay within ±{still:g}, so they do not explain this label; "
                    "it comes from another rule (see evidence).")
    else:
        sentence = f"{reading}."
    return (f'<section class="pattern"><h2>Pattern</h2><p><strong>{esc(sentence)}</strong></p><p>{esc(numbers)}.</p>'
            f'<img alt="Detector {symbol} of the deviating channel and its witnesses up to the alert" src="data:image/png;base64,{image}">'
            f'<p><small>Last {hours} h up to the alert; only minutes available at the alert time; axis clipped at ±{limit:.0f}; '
            f'grey: no {symbol} while stopped or settling after a stop; stops longer than 30 min are compressed. '
            f'Evidence: {esc(alert.evidence)}</small></p></section>')


def generate(asset, data, predictions, out, until=None, pump=None):
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
    if pump is not None and (pump["asset_id"], pump["split"]) != (asset, metadata["split"]):
        raise ValueError(f"{asset}: the per-pump table row does not match assets.csv")
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
        # UNKNOWN says nothing about the cause, so different signals are different conditions.
        key = (row.fault_type, row.event_class, deviating_signal(row.evidence) if row.fault_type == 'UNKNOWN' else None)
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
            earlier = alerts.loc[(alerts['_time'] < row['_time'])
                                 & (alerts['_time'] >= row['_time'] - pd.Timedelta(hours=12))]
            fields = []
            if not earlier.empty:
                previous = earlier.iloc[-1]
                if (previous.event_class, previous.fault_type) != (row.event_class, row.fault_type):
                    fields.append(('Diagnosis changed from', f'{previous.event_class}/{previous.fault_type}'))
                history = [f"{_time(alert['_time'])} {alert.event_class}/{alert.fault_type} "
                           f"({evidence_level(alert.confidence) or '-'})" for _, alert in earlier.iterrows()]
                fields.append(('Previous alerts on this pump within 12 h', '; '.join(history)))
            fields.extend((('Time (UTC)', _time(row['_time'])), ('Class', row.event_class),
                      ('Fault type', row.fault_type), ('Confidence', _confidence(row.confidence)),
                      ('Deviating signal', deviating_signal(row.evidence)), ('Evidence', row.evidence),
                      ('Recommended action', row.recommended_action)))
            items.append('<article class="alert"><time datetime="' + esc(row.alert_time_utc) + '"></time><h4>Alert ' + str(row['_number']) + '</h4>' + ''.join(
                f'<p><strong>{esc(label)}:</strong> {esc(value)}</p>' for label, value in fields) + '</article>')
        cards.append(f'<section class="condition"><h3>C{index}: {esc(_condition_title(first))}</h3>'
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
        latest = _condition_title(last_alert)
        action = last_alert.recommended_action
    horizon = until if until is not None else metadata['window_end_utc']
    last_alert = None if alerts.empty else alerts.iloc[-1]
    status = _state(last_alert)
    if last_alert is None:
        operator = ('<section class="operator"><p><span class="state normal">normal</span></p>'
                    '<p><strong>Action:</strong> no action; no alerts up to the last data.</p></section>')
        pattern = ''
    else:
        operator = (f'<section class="operator"><p><span class="state {status}">{status}</span></p>'
                    f'<p><strong>Reason:</strong> {esc(reason_text(last_alert))}</p>'
                    '<p><strong>Action:</strong></p><ul class="action">' + ''.join(
                        f'<li>{esc(line)}</li>' for line in action_lines(last_alert.recommended_action)) + '</ul>'
                    f'<p><strong>Confidence:</strong> {esc(_confidence(last_alert.confidence))}</p>'
                    f'<p><small>Advisory only: human review required. Alert time: {esc(_time(last_alert["_time"]))}</small></p></section>')
        pattern = pattern_panel(last_alert, features, metadata)
    short_tier = {"T2_FULL": "T2", "T1_RETROFIT": "T1", "T0_LEGACY": "T0"}
    heading = (f"{asset} · {pump['split']} · {pump['tier']}" if pump is not None else
               f"{asset} · {metadata['split']} · {short_tier.get(metadata['instrumentation_tier'], metadata['instrumentation_tier'])}")
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Report {esc(asset)}</title>
<style>{CSS}</style></head><body>
<h1>{esc(heading)}</h1>{operator}{pattern}<h2>Detail</h2><p>Instrumentation: {esc(TIERS.get(metadata['instrumentation_tier'], metadata['instrumentation_tier']))}</p><p><small>Split: {esc(metadata['split'])}</small></p>
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
