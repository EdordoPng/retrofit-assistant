#!/usr/bin/env python3
"""Generate the documentation figures from the synthetic dataset (data/full). All figures are labeled SYNTHETIC.

  python examples/make_figures.py --data data/full --out figures
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

S1, S2, S3, S4 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
EVENT, DEADLINE, ALARM = "#d9d7d0", "#e34948", "#6250d6"
plt.rcParams.update({"figure.facecolor": SURF, "axes.facecolor": SURF, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
                     "axes.spines.top": False, "axes.spines.right": False, "font.size": 9, "axes.titlesize": 10,
                     "axes.titleweight": "bold", "axes.titlecolor": INK, "lines.linewidth": 1.4, "legend.frameon": False})


def stamp(fig, text):
    fig.text(0.995, 0.005, "SYNTHETIC DATA - RETROFIT AI 2026 - " + text, ha="right", va="bottom", fontsize=7, color=INK2)


def tele(d, aid, cols):
    t = pd.read_parquet(os.path.join(d, "telemetry", f"asset_id={aid}"), columns=["timestamp_utc", "operating_mode"] + cols)
    t["timestamp_utc"] = pd.to_datetime(t["timestamp_utc"], utc=True)
    return t.sort_values("timestamp_utc").set_index("timestamp_utc")


def events(d):
    ev = pd.concat([pd.read_csv(os.path.join(d, f)) for f in ("events_train.csv", "events_validation.csv")])
    for c in ("onset_utc", "detectable_utc", "action_deadline_utc", "end_utc"):
        ev[c] = pd.to_datetime(ev[c], utc=True, format="ISO8601")
    return ev


def shade(ax, ev, aid, types, wend):
    for _, e in ev[(ev.asset_id == aid) & ev.fault_type.isin(types)].iterrows():  # noqa: B007
        ax.axvspan(e.onset_utc, e.end_utc if pd.notna(e.end_utc) else wend, color=EVENT, alpha=0.5, lw=0, zorder=0)
        if pd.notna(e.action_deadline_utc):
            ax.axvline(e.action_deadline_utc, color=DEADLINE, lw=1.0, ls="--", zorder=1)


def minute(t, col):
    run = t["operating_mode"].astype(str) == "RUNNING"
    return t[col].where(run).resample("10min").mean()


def fig_clog(d, ev, out):
    t = tele(d, "PUMP-06", ["suction_pressure_kpa", "discharge_pressure_kpa", "vibration_accel_rms_g"])
    wend = t.index.max()
    fig, axs = plt.subplots(3, 1, figsize=(9, 6.2), sharex=True)
    for ax, (c, lab, col) in zip(axs, [("suction_pressure_kpa", "Suction\n[kPa(g)]", S1),
                                       ("discharge_pressure_kpa", "Discharge\n[kPa(g)]", S2),
                                       ("vibration_accel_rms_g", "Accel. RMS [g]\n(wireless, 5 min)", S3)]):
        y = t[c].where(t["operating_mode"].astype(str) == "RUNNING")
        y = y.resample("10min").mean() if c != "vibration_accel_rms_g" else y.dropna()
        ax.plot(y.index, y.values, color=col, lw=1.2 if c != "vibration_accel_rms_g" else 0, marker="." if c == "vibration_accel_rms_g" else None, ms=3)
        ax.set_ylabel(lab)
        shade(ax, ev, "PUMP-06", ["SUCTION_STRAINER_CLOGGING"], wend)
        for _, e in ev[(ev.asset_id == "PUMP-06") & (ev.fault_type == "CAVITATION")].iterrows():
            ax.axvspan(e.onset_utc, e.end_utc, color="#a9a59a", alpha=0.55, lw=0, zorder=0)
    axs[0].set_title("PUMP-06 hot process-water pump: strainer clogging develops into cavitation\n"
                     "light grey = clogging event, dark grey = cavitation episodes, red dashed = action deadline", loc="left")
    axs[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    stamp(fig, "pressures: 10-min means while running; acceleration: individual wireless readings (every 5 min)")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig02_clogging_to_cavitation_PUMP-06.png"), dpi=150)
    plt.close(fig)


def fig_bearing(d, ev, out):
    t = tele(d, "PUMP-04", ["vibration_rms_mm_s", "vibration_accel_rms_g", "bearing_temp_c"])
    a = pd.read_csv(os.path.join(d, "assets.csv")).set_index("asset_id").loc["PUMP-04"]
    al = pd.read_csv(os.path.join(d, "alarms.csv"))
    al = al[(al.asset_id == "PUMP-04") & al.tag.str.startswith("vibration")]
    wend = t.index.max()
    fig, axs = plt.subplots(3, 1, figsize=(9, 6.2), sharex=True)
    specs = [("vibration_rms_mm_s", "Velocity RMS\n[mm/s]", S1), ("vibration_accel_rms_g", "Accel. RMS\n[g]", S2),
             ("bearing_temp_c", "Bearing temp.\n[°C]", S3)]
    for ax, (c, lab, col) in zip(axs, specs):
        y = minute(t, c)
        ax.plot(y.index, y.values, color=col)
        ax.set_ylabel(lab)
        shade(ax, ev, "PUMP-04", ["BEARING_WEAR"], wend)
    axs[0].axhline(a.vibration_alarm_mm_s, color=INK2, lw=0.8, ls=":")
    axs[0].set_ylim(top=a.vibration_alarm_mm_s * 1.15)
    axs[0].text(t.index.max(), a.vibration_alarm_mm_s, f"ISO 10816-7 Cat. II alarm {a.vibration_alarm_mm_s} mm/s ", ha="right", va="bottom",
                color=INK2, fontsize=8)
    for _, r in al.iterrows():
        axs[0].axvline(pd.Timestamp(r.raised_utc), color=ALARM, lw=0.8)
    alarm_note = ("violet = SCADA vibration alarms" if len(al) else
                  "no plant vibration alarm fired")
    axs[0].set_title("PUMP-04 cooling-tower pump: bearing wear (acceleration rises first); imbalance grows in parallel (not shaded)\n"
                     f"grey = bearing-wear event, red dashed = action deadline; {alarm_note}", loc="left", fontsize=9.5)
    axs[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    stamp(fig, "10-min means while running")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig03_bearing_wear_PUMP-04.png"), dpi=150)
    plt.close(fig)


def fig_sensor_vs_machine(d, ev, out):
    t = tele(d, "PUMP-03", ["discharge_pressure_kpa", "motor_current_a"])
    wend = t.index.max()
    fig, axs = plt.subplots(2, 1, figsize=(9, 4.6), sharex=True)
    for ax, (c, lab, col) in zip(axs, [("discharge_pressure_kpa", "Discharge\n[kPa(g)]", S1), ("motor_current_a", "Motor current\n[A]", S2)]):
        y = minute(t, c)
        ax.plot(y.index, y.values, color=col)
        ax.set_ylabel(lab)
        shade(ax, ev, "PUMP-03", ["DISCHARGE_RESTRICTION", "SENSOR_CALIBRATION_SHIFT"], wend)
    e = ev[(ev.asset_id == "PUMP-03")].set_index("fault_type")
    for ft, lab in (("DISCHARGE_RESTRICTION", "machine: DISCHARGE_RESTRICTION\n(valve partly closed): pressure up,\ncurrent down"),
                    ("SENSOR_CALIBRATION_SHIFT", "sensor: SENSOR_CALIBRATION_SHIFT\n(transmitter offset): pressure up,\ncurrent unchanged")):
        x = e.loc[ft, "onset_utc"]
        axs[1].annotate(lab, (x, 0.04), xycoords=("data", "axes fraction"), xytext=(10, 0), textcoords="offset points", va="bottom",
                        fontsize=8, color=INK, bbox=dict(boxstyle="round,pad=0.3", fc=SURF, ec=GRID, lw=0.6))
    axs[0].set_title("PUMP-03 legacy (T0) fresh-water pump: machine fault vs instrument fault\nboth raise discharge pressure; only the machine fault moves motor current", loc="left")
    axs[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    stamp(fig, "10-min means while running")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig04_sensor_vs_machine_PUMP-03.png"), dpi=150)
    plt.close(fig)


def fig_envelope(d, out):
    f = pd.read_parquet(os.path.join(d, "features_1min.parquet"), columns=["asset_id", "operating_mode", "flow_m3_h__mean",
                                                                           "discharge_pressure_kpa__mean", "motor_power_kw__mean",
                                                                           "motor_current_a__mean"])
    a = pd.read_csv(os.path.join(d, "assets.csv")).set_index("asset_id")
    f = f[f.operating_mode == "RUNNING"]
    fig, axs = plt.subplots(1, 3, figsize=(10.5, 3.6))
    for ax, aid, col in zip(axs, ["PUMP-01", "PUMP-04", "PUMP-09"], [S1, S2, S3]):
        g = f[f.asset_id == aid].dropna(subset=["flow_m3_h__mean"]) if f[f.asset_id == aid]["flow_m3_h__mean"].notna().any() else None
        r = a.loc[aid]
        if g is None or len(g) == 0:
            g = f[f.asset_id == aid]
            ax.hist(g["motor_current_a__mean"].dropna(), bins=60, color=col)
            ax.set_xlabel("Motor current [A]")
            ax.set_ylabel("minutes")
        else:
            ax.scatter(g["flow_m3_h__mean"], g["discharge_pressure_kpa__mean"], s=2, color=col, alpha=0.35, lw=0)
            ax.set_xlabel("Flow [m³/h]")
            ax.set_ylabel("Discharge pressure [kPa(g)]")
        ctl = {"VFD_TEMPERATURE": "variable speed, temperature control", "VFD_PRESSURE": "variable speed, pressure control",
               "FIXED_SPEED": "fixed speed", "FLOW_VALVE": "fixed speed, flow valve"}[r.control]
        ax.set_title(f"{aid}: {ctl}" + ("\n(no flow meter: motor current shown)" if g is None or "flow" not in ax.get_xlabel().lower() else ""),
                     loc="left", fontsize=9)
    fig.suptitle("Operating envelopes differ by control strategy (1-min means, running)", x=0.01, ha="left", fontweight="bold", color=INK)
    stamp(fig, "1-min means while running")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig01_operating_envelopes.png"), dpi=150)
    plt.close(fig)


def fig_season(d, out):
    c = pd.read_csv(os.path.join(d, "operating_context.csv"))
    f = pd.read_parquet(os.path.join(d, "features_1min.parquet"), columns=["asset_id", "window_start_utc", "operating_mode", "running_fraction",
                                                                           "motor_speed_rpm__mean"])
    a = pd.read_csv(os.path.join(d, "assets.csv")).set_index("asset_id")
    ships = [x for x in a.index if a.loc[x, "profile"] == "SHIP_SW_COOLING" and a.loc[x, "split"] != "test"]
    c["timestamp_utc"] = pd.to_datetime(c.timestamp_utc, utc=True)
    f["window_start_utc"] = pd.to_datetime(f.window_start_utc, utc=True)
    m = f.merge(c, left_on=["asset_id", "window_start_utc"], right_on=["asset_id", "timestamp_utc"])
    m = m[(m.operating_mode == "RUNNING") & (m.running_fraction >= 1.0) & m.asset_id.isin(ships)]   # drop start/stop minutes
    m["speed_ratio"] = m.motor_speed_rpm__mean / m.asset_id.map(a.motor_rated_rpm)
    fig, ax = plt.subplots(figsize=(7, 4))
    for (x, g), col in zip(m.groupby("asset_id"), [S1, S2, S3, S4]):
        ax.scatter(g.sea_temp_c, g.speed_ratio, s=3, color=col, alpha=0.3, lw=0)
        ax.annotate(f"{x} ({pd.Timestamp(a.loc[x, 'window_start_utc']).strftime('%b')}, min. speed {a.loc[x, 'min_speed_ratio']:.1f})",
                    (g.sea_temp_c.median(), g.speed_ratio.max()), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8, color=INK)
    ax.set_xlabel("Sea temperature [°C]")
    ax.set_ylabel("Pump speed / rated speed")
    ax.set_title("Seawater pumps on temperature control: speed follows season and heat load,\nand sits at each pump's minimum drive speed in cold water", loc="left")
    stamp(fig, "1-min means, steady running")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig05_season_speed_ship_SW.png"), dpi=150)
    plt.close(fig)


def fig_timeline(d, ev, out, preds):
    aid = "PUMP-08"
    t = tele(d, aid, ["suction_pressure_kpa", "motor_speed_rpm"])
    al = pd.read_csv(os.path.join(d, "alarms.csv"))
    al = al[al.asset_id == aid]
    mt = pd.read_csv(os.path.join(d, "maintenance.csv"))
    mt = mt[(mt.asset_id == aid) & mt.in_window]
    e = ev[ev.asset_id == aid]
    fig, axs = plt.subplots(2, 1, figsize=(10, 6.0), sharex=True, gridspec_kw={"height_ratios": [2.0, 2.0]})
    y = minute(t, "suction_pressure_kpa")
    axs[0].plot(y.index, y.values, color=S1)
    axs[0].set_ylabel("Suction pressure [kPa(g)]")
    ax = axs[1]
    es = e.sort_values("onset_utc").reset_index(drop=True)
    lanes = {"Baseline B1 alerts": 3, "SCADA alarms": 2, "Work orders": 1, "Pump stopped": 0}
    ev_lanes = {}
    for k, r in es.iterrows():
        y0 = 4 + (len(es) - 1 - k)
        ev_lanes[r.fault_type.replace("_", " ").lower()] = y0
        end = r.end_utc if pd.notna(r.end_utc) else t.index.max()
        ax.barh(y0, (end - r.onset_utc).total_seconds() / 86400, left=r.onset_utc, height=0.55, color="#b9b5aa", edgecolor=SURF)
    lanes = {**{f"event: {k}": v for k, v in ev_lanes.items()}, **lanes}
    if preds is not None:
        p = preds[preds.asset_id == aid]
        for _, r in p.iterrows():
            ax.plot(pd.Timestamp(r.alert_time_utc), lanes["Baseline B1 alerts"], marker="v", color=S2, ms=8)
    for _, r in al.iterrows():
        ax.plot(pd.Timestamp(r.raised_utc), lanes["SCADA alarms"], marker="o", color=ALARM, ms=6)
    for _, r in mt.iterrows():
        ax.plot(pd.Timestamp(r.start_utc), lanes["Work orders"], marker="s", color=S3, ms=7)
    stopped = (t["operating_mode"].astype(str) != "RUNNING").resample("10min").mean() > 0.5
    ax.fill_between(stopped.index, -0.25, 0.25, where=stopped.values, color=INK2, step="post", lw=0)
    ax.set_yticks(list(lanes.values()), list(lanes.keys()))
    ax.set_ylim(-0.6, max(lanes.values()) + 0.6)
    ax.grid(axis="y", visible=False)
    axs[0].set_title(f"{aid} operator timeline (validation asset): labeled events (grey bars),\nbaseline alerts (orange), plant alarms (violet), work orders (green), pump stopped (dark)", loc="left")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    stamp(fig, "validation split")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig06_operator_timeline_PUMP-08.png"), dpi=150)
    plt.close(fig)


def fig_spectrum(d, out):
    s = pd.read_parquet(os.path.join(d, "vibration_snapshots.parquet"))
    a = pd.read_csv(os.path.join(d, "assets.csv")).set_index("asset_id")
    g = s[s.asset_id == "PUMP-04"].sort_values("timestamp_utc")
    early, late = g.iloc[1], g[pd.to_datetime(g.timestamp_utc, utc=True) < pd.Timestamp("2025-06-21T06:00Z")].iloc[-1]
    fig, axs = plt.subplots(2, 1, figsize=(9, 5.2))
    for r, col, lab in ((early, S1, "start of window"), (late, S2, "shortly before bearing replacement")):
        x = np.asarray(r.samples, dtype=float)
        fs = r.sample_rate_hz
        env = np.abs(x - x.mean())
        f = np.fft.rfftfreq(x.size, 1 / fs)
        X = np.abs(np.fft.rfft(x * np.hanning(x.size))) / x.size * 4
        E = np.abs(np.fft.rfft((env - env.mean()) * np.hanning(x.size))) / x.size * 4
        axs[0].plot(f, X, color=col, lw=0.8, label=f"{pd.Timestamp(r.timestamp_utc).strftime('%d %b %H:%M')} ({lab})")
        axs[1].plot(f, E, color=col, lw=0.9)
        fr = r.rpm_at_capture / 60
    bpfo = a.loc["PUMP-04", "bearing_bpfo_order"] * fr
    for k in range(1, 7):
        axs[1].axvline(k * bpfo, color=INK2, lw=0.7, ls=":")
    axs[1].text(0.99, 0.95, f"dotted lines: BPFO harmonics, BPFO = {a.loc['PUMP-04', 'bearing_bpfo_order']:.3f} x {fr:.1f} Hz",
                transform=axs[1].transAxes, ha="right", va="top", fontsize=8, color=INK2, bbox=dict(fc=SURF, ec="none", pad=1.5))
    axs[0].set_xlim(0, 5000)
    axs[1].set_xlim(0, 400)
    axs[0].set_ylabel("Spectrum amplitude [g]")
    axs[1].set_ylabel("Envelope amplitude [g]")
    axs[0].set_xlabel("Frequency [Hz]")
    axs[1].set_xlabel("Frequency [Hz]")
    axs[0].legend(loc="upper right", fontsize=8)
    axs[0].set_title("PUMP-04 waveform snapshots: bearing-resonance energy (top)\nand outer-race defect harmonics in the envelope spectrum (bottom)", loc="left")
    stamp(fig, "1-s snapshots at 10.24 kHz")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig07_snapshot_spectrum_PUMP-04.png"), dpi=150)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", default=os.path.join(ROOT, "data", "full"))
    p.add_argument("--out", default=os.path.join(ROOT, "figures"))
    p.add_argument("--predictions", default=os.path.join(ROOT, "baselines", "results", "predictions_B1_mode_aware_z_validation.csv"))
    a = p.parse_args()
    os.makedirs(a.out, exist_ok=True)
    ev = events(a.data)
    preds = pd.read_csv(a.predictions) if os.path.exists(a.predictions) else None
    fig_envelope(a.data, a.out)
    fig_clog(a.data, ev, a.out)
    fig_bearing(a.data, ev, a.out)
    fig_sensor_vs_machine(a.data, ev, a.out)
    fig_season(a.data, a.out)
    fig_timeline(a.data, ev, a.out, preds)
    fig_spectrum(a.data, a.out)
    print("figures written to", a.out)


if __name__ == "__main__":
    main()
