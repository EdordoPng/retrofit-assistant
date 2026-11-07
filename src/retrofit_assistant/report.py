"""Self-contained operator reports for development assets."""

import base64
from html import escape
from datetime import timezone
from io import BytesIO
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from .data import load_assets, load_features
from .output import COLUMNS

SIGNALS = ("vibration_rms_mm_s", "bearing_temp_c", "suction_pressure_kpa",
           "discharge_pressure_kpa", "flow_m3_h", "motor_current_a")
COLORS = {"MACHINE": "#b33b32", "SENSOR": "#306ba3"}


class Refused(ValueError):
    pass


def generate(asset, data, predictions, out):
    assets = load_assets(data)
    selected = assets.loc[(assets.asset_id == asset) & assets.split.isin(["train", "validation"])]
    if len(selected) != 1:
        raise Refused(f"{asset} is not a train or validation asset")
    metadata = selected.iloc[0]
    alerts = pd.read_csv(predictions, keep_default_na=False)
    missing = [column for column in COLUMNS if column not in alerts.columns]
    if missing:
        raise ValueError(f"Missing prediction columns: {', '.join(missing)}")
    alerts = alerts.loc[alerts.asset_id == asset].copy()
    alerts["_time"] = pd.to_datetime(alerts.alert_time_utc, utc=True, errors="raise")
    alerts = alerts.sort_values("_time", kind="stable")
    features = load_features(data, selected)
    signals = [(name, name + "__mean") for name in SIGNALS
               if name + "__mean" in features and features[name + "__mean"].notna().any()]
    figure, axes = plt.subplots(max(1, len(signals)), 1, sharex=True,
                                figsize=(11, max(2.5, 1.8 * len(signals))), squeeze=False)
    for ax, (name, column) in zip(axes[:, 0], signals):
        observed = features.loc[features[column].notna(), ["window_start_utc", column]]
        groups = observed.window_start_utc.diff().gt(pd.Timedelta(minutes=10)).cumsum()
        for _, segment in observed.groupby(groups):
            ax.plot(segment.window_start_utc, segment[column], linewidth=0.7,
                    marker=".", markersize=2, color="#334e68")
        ax.set_ylabel(name.replace("_", " "), fontsize=8)
    if not signals:
        axes[0, 0].text(0.5, 0.5, "No signal data available", ha="center", transform=axes[0, 0].transAxes)
    for ax in axes[:, 0]:
        for _, row in alerts.iterrows():
            ax.axvline(row["_time"], color=COLORS.get(row.event_class, "#777777"),
                       alpha=0.7, linewidth=0.8)
    from matplotlib.lines import Line2D
    axes[0, 0].legend(handles=[Line2D([0], [0], color=color, label=label)
                                for label, color in COLORS.items()], loc="upper right")
    axes[-1, 0].xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M", tz=timezone.utc))
    axes[-1, 0].set_xlabel("UTC")
    figure.tight_layout()
    buffer = BytesIO()
    figure.savefig(buffer, format="png", dpi=90)
    plt.close(figure)
    chart = base64.b64encode(buffer.getvalue()).decode("ascii")
    esc = lambda value: escape(str(value), quote=True)
    cards = []
    for _, row in alerts.iterrows():
        fields = (("Time (UTC)", row.alert_time_utc), ("Class", row.event_class),
                  ("Fault type", row.fault_type), ("Confidence", row.confidence),
                  ("Evidence", row.evidence), ("Recommended action", row.recommended_action))
        cards.append('<article class="alert">' + ''.join(
            f'<p><strong>{esc(label)}:</strong> {esc(value)}</p>' for label, value in fields) + '</article>')
    if not cards:
        cards.append('<p>No alerts for this asset.</p>')
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Report {esc(asset)}</title>
<style>body{{font-family:sans-serif;max-width:1100px;margin:2em auto;padding:0 1em;color:#243342}} img{{max-width:100%}} .alert{{border:1px solid #ccd4dc;border-radius:6px;padding:0 1em;margin:1em 0}}</style></head><body>
<h1>Report: {esc(asset)}</h1><p>Split: {esc(metadata['split'])} | Tier: {esc(metadata['instrumentation_tier'])}</p>
<p>UTC window: {esc(metadata['window_start_utc'])} — {esc(metadata['window_end_utc'])} | Alerts: {len(alerts)}</p>
<p><strong>Advisory only: human review required</strong></p><h2>Signal timeline</h2>
<img alt="Signal timeline and alert markers" src="data:image/png;base64,{chart}"><h2>Alerts</h2>{''.join(cards)}</body></html>'''
    destination = Path(out) / f"{asset}.html"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(page, encoding="utf-8")
    return destination

