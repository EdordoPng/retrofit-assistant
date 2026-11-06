"""Transparent reference baselines on 1-minute feature windows.

B0 SCADA alarms      - the existing PLC/SCADA alarm list used as an alert stream (what operators have today).
B1 Mode-aware z      - per-asset robust baseline from the first 24 h of steady running, by speed regime; sustained
                       |z| > k raises an alert; rule-based diagnosis from which channels deviate and in which direction.
B2 CUSUM             - one-sided CUSUM change-point detector on the same regime-normalised residuals.
B3 Isolation Forest  - sklearn IsolationForest on regime-normalised features, trained on training-split minutes outside
                       labelled event windows; same rule-based diagnosis.
Thresholds (k, persistence, CUSUM h, IF quantile) are tuned on the TRAINING split only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CH = {"v": "vibration_rms_mm_s", "a": "vibration_accel_rms_g", "c": "vibration_crest_factor", "bt": "bearing_temp_c",
      "ps": "suction_pressure_kpa", "pd": "discharge_pressure_kpa", "i": "motor_current_a", "pw": "motor_power_kw",
      "q": "flow_m3_h", "n": "motor_speed_rpm", "wt": "motor_winding_temp_c", "tf": "fluid_temp_c", "vp": "valve_position_pct"}
# channels that physically co-move with each channel (used to flag single-instrument deviations as sensor problems)
COUPLED = {"pd": ["i", "pw", "q", "n", "ps"], "ps": ["pd", "q", "n", "i"], "q": ["pd", "i", "pw", "n", "vp"],
           "i": ["pw", "pd", "q", "n"], "pw": ["i", "pd", "q"], "bt": ["v", "a", "wt", "tf"], "v": ["a", "bt", "c"],
           "a": ["v", "c", "bt"], "wt": ["i", "pw"], "tf": ["bt"]}
SENSOR_TAG = {k: v for k, v in CH.items()}
BASELINE_H = 24
REFRACTORY = pd.Timedelta(hours=12)


def regime_frame(feat: pd.DataFrame, assets: pd.DataFrame) -> pd.DataFrame:
    """Add per-minute regime key and steadiness flags."""
    f = feat.copy()
    f["window_start_utc"] = pd.to_datetime(f["window_start_utc"], utc=True)
    # complete 1-min grid per asset: minutes without any telemetry row (gateway outage) appear with rows = 0
    full = []
    for a, g in f.groupby("asset_id", sort=False):
        grid = pd.date_range(g["window_start_utc"].min(), g["window_start_utc"].max(), freq="1min")
        g = g.set_index("window_start_utc").reindex(grid)
        g.index.name = "window_start_utc"
        g["asset_id"] = a
        g["rows"] = g["rows"].fillna(0)
        g["operating_mode"] = g["operating_mode"].fillna("NO_DATA")
        g["running_fraction"] = g["running_fraction"].fillna(0.0)
        full.append(g.reset_index())
    f = pd.concat(full, ignore_index=True)
    rated = dict(zip(assets.asset_id, assets.motor_rated_rpm))
    sp = f.get("motor_speed_rpm__mean")
    f["speed_ratio"] = sp / f["asset_id"].map(rated) if sp is not None else np.nan
    f["regime"] = np.where(f["speed_ratio"].notna(), (f["speed_ratio"] / 0.05).round().fillna(-1).astype(int), 0)
    run = (f["operating_mode"] == "RUNNING") & (f["running_fraction"] >= 0.99)
    # minutes since the last non-running minute (start-up transients excluded)
    f["steady"] = False
    for a, idx in f.groupby("asset_id").groups.items():
        r = run.loc[idx].values
        cnt = np.zeros(len(r), dtype=int)
        c = 0
        for j, x in enumerate(r):
            c = c + 1 if x else 0
            cnt[j] = c
        f.loc[idx, "steady"] = cnt >= 10
    return f


def zscores(f: pd.DataFrame) -> pd.DataFrame:
    """Robust z per asset/regime/channel from the first BASELINE_H hours of steady running (commissioning baseline)."""
    out = []
    for a, g in f.groupby("asset_id", sort=False):
        g = g.copy()
        t0 = g["window_start_utc"].min()
        base = g[(g["window_start_utc"] < t0 + pd.Timedelta(hours=BASELINE_H)) & g["steady"]]
        for k, col in CH.items():
            m = f"{col}__mean"
            if m not in g or g[m].notna().sum() == 0:
                g["z_" + k] = np.nan
                continue
            med = base.groupby("regime")[m].median()
            mad = base.groupby("regime")[m].apply(lambda s: (s - s.median()).abs().median())
            glob_med, glob_mad = base[m].median(), (base[m] - base[m].median()).abs().median()
            mu = g["regime"].map(med).fillna(glob_med)
            sd = 1.4826 * g["regime"].map(mad).fillna(glob_mad)
            floor = {"v": 0.05, "a": 0.01, "c": 0.05, "bt": 0.3, "ps": 1.0, "pd": 2.0, "i": 0.3, "pw": 0.2, "q": 2.0,
                     "n": 5.0, "wt": 0.5, "tf": 0.3, "vp": 0.5}[k]
            g["z_" + k] = (g[m] - mu) / np.maximum(sd, floor)
            s = f"{col}__std"
            if s in g:
                sb = base[s].median()
                g["zs_" + k] = (g[s] - sb) / max(1.4826 * (base[s] - sb).abs().median(), 1e-3 + 0.05 * abs(sb))
                g["flat_" + k] = (g[s] == 0) & g[f"{col}__count"].ge(30)
        g["gap"] = g["rows"] < 30
        out.append(g)
    return pd.concat(out, ignore_index=True)


def diagnose(row: pd.Series, k: float) -> tuple[str, str, str, str]:
    """Rule-based (class, fault_type, evidence, recommended action) from regime-normalised deviations."""
    z = {c: row.get("z_" + c) for c in CH}
    z = {c: (0.0 if pd.isna(v) else float(v)) for c, v in z.items()}
    big = {c for c, v in z.items() if abs(v) > k}
    flag = lambda key: (not pd.isna(row.get(key, False))) and bool(row.get(key, False))
    if flag("gap"):
        return "SENSOR", "COMMUNICATION_LOSS", "missing rows", "Check gateway / network; data gap."
    for c in z:
        if flag("flat_" + c) and flag("steady") and c in ("pd", "ps", "q", "bt", "i", "tf"):
            return "SENSOR", "SENSOR_STUCK", f"{CH[c]} frozen", f"Check transmitter {CH[c]}."
    for c in list(big):
        cpl = [x for x in COUPLED.get(c, []) if abs(z.get(x, 0.0)) > 0]
        if c in COUPLED and cpl and max(abs(z[x]) for x in cpl) < k / 3:
            zs = row.get("zs_" + c, 0.0)
            ftype = "SENSOR_NOISE_SPIKES" if (not pd.isna(zs) and zs > k) else "SENSOR_CALIBRATION_SHIFT"
            return "SENSOR", ftype, f"{CH[c]} deviates alone (z={z[c]:.1f})", f"Verify {CH[c]} against a reference gauge."
    ev = ", ".join(f"{CH[c]} z={z[c]:+.1f}" for c in sorted(big, key=lambda c: -abs(z[c]))[:3])
    if z["a"] > k and (z["c"] > k / 2 or z["bt"] > k / 2 or z["a"] > 2 * k):
        return "MACHINE", "BEARING_WEAR", ev, "Inspect pump bearing; plan replacement; check lubrication."
    if z["ps"] < -k and z["a"] > k:
        return "MACHINE", "CAVITATION", ev, "Check suction strainer / level; reduce flow if allowed."
    if z["ps"] < -k:
        return "MACHINE", "SUCTION_STRAINER_CLOGGING", ev, "Inspect / clean suction strainer."
    if z["v"] > k:
        if z["bt"] > k / 2 or z["wt"] > k / 2:
            return "MACHINE", "MISALIGNMENT", ev, "Check coupling alignment."
        return "MACHINE", "IMBALANCE", ev, "Inspect impeller for fouling / damage; balance."
    if z["pd"] > k and (z["q"] < -k / 2 or z["i"] < -k / 2 or z["pw"] < -k / 2):
        return "MACHINE", "DISCHARGE_RESTRICTION", ev, "Check discharge valves and heat-exchanger fouling."
    if z["q"] < -k and z["n"] <= k / 2:
        return "MACHINE", "DISCHARGE_RESTRICTION", ev, "Check discharge valves and heat-exchanger fouling."
    if z["pd"] < -k and z["i"] < 0:
        return "MACHINE", "IMPELLER_WEAR", ev, "Performance test; inspect impeller / wear rings."
    if z["n"] > k or z["pw"] > k:
        return "MACHINE", "SUCTION_STRAINER_CLOGGING", ev, "Inspect / clean suction strainer."
    return "MACHINE", "UNKNOWN", ev, "Inspect pump."


def _alerts_from_flag(g: pd.DataFrame, flag: np.ndarray, persist: int, k: float, method: str, score: np.ndarray) -> list:
    """Alert when the flag has persisted `persist` minutes; refractory period per diagnosed fault type."""
    rows, run, last = [], 0, {}
    for j in range(len(g)):
        run = run + 1 if flag[j] else 0
        if run == persist or (run > persist and (run - persist) % 720 == 0):
            t = g["window_start_utc"].iloc[j] + pd.Timedelta(minutes=1)
            r = g.iloc[j]
            cls, ft, evd, act = diagnose(r, k)
            if ft not in last or t - last[ft] > REFRACTORY:
                rows.append({"asset_id": r["asset_id"], "alert_time_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "event_class": cls, "fault_type": ft,
                             "confidence": float(np.clip(score[j] / (2 * k), 0.05, 0.99)), "evidence": f"{method}: {evd}",
                             "recommended_action": act})
                last[ft] = t
    return rows


def _zmax(g, k):
    zc = [c for c in g.columns if c.startswith("z_")]
    Z = g[zc].abs().fillna(0.0).values
    zs = [c for c in g.columns if c.startswith("zs_")]
    S = g[zs].fillna(0.0).values if zs else np.zeros((len(g), 1))
    return np.maximum(Z.max(axis=1), S.max(axis=1) / 2.0)


def b1_threshold(zf: pd.DataFrame, k=6.0, persist=10) -> pd.DataFrame:
    rows = []
    for a, g in zf.groupby("asset_id", sort=False):
        g = g.reset_index(drop=True)
        zm = _zmax(g, k)
        flag = (g["steady"].values & (zm > k)) | g["gap"].values | _flat_any(g)
        rows += _alerts_from_flag(g, flag, persist, k, "B1 mode-aware z", zm)
    return pd.DataFrame(rows, columns=_COLS)


def _flat_any(g):
    fl = [c for c in g.columns if c.startswith("flat_")]
    return (g[fl].fillna(False).any(axis=1).values & g["steady"].values) if fl else np.zeros(len(g), dtype=bool)


def b2_cusum(zf: pd.DataFrame, kappa=2.0, h=60.0, k_diag=4.0) -> pd.DataFrame:
    rows = []
    for a, g in zf.groupby("asset_id", sort=False):
        g = g.reset_index(drop=True)
        zc = [c for c in g.columns if c.startswith("z_")]
        Z = g[zc].fillna(0.0).values * g["steady"].values[:, None]
        sp = np.zeros(Z.shape[1])
        sn = np.zeros(Z.shape[1])
        stat = np.zeros(len(g))
        for j in range(len(g)):
            sp = np.maximum(0, sp + Z[j] - kappa)
            sn = np.maximum(0, sn - Z[j] - kappa)
            stat[j] = max(sp.max(), sn.max())
            if stat[j] > h:          # reset after an alarm so the next change can be found
                sp[:] = 0
                sn[:] = 0
        flag = (stat > h) | g["gap"].values | _flat_any(g)
        rows += _alerts_from_flag(g, flag, 1, k_diag, "B2 CUSUM", np.maximum(stat / h * 2 * k_diag, 0))
    return pd.DataFrame(rows, columns=_COLS)


def _if_matrix(zf):
    cols = [c for c in zf.columns if c.startswith("z_") or c.startswith("zs_")]
    X = zf[cols].fillna(0.0).clip(-50, 50).values
    return X, cols


def b3_iforest(zf_train: pd.DataFrame, train_events: pd.DataFrame, zf_eval: pd.DataFrame, q=0.995, persist=10, k_diag=4.0,
               seed=0) -> tuple[pd.DataFrame, object, float]:
    from sklearn.ensemble import IsolationForest
    tr = zf_train[zf_train["steady"]].copy()
    if len(train_events):
        ev = train_events.copy()
        ev["onset_utc"] = pd.to_datetime(ev["onset_utc"], utc=True, format="ISO8601")
        ev["end_utc"] = pd.to_datetime(ev["end_utc"], utc=True, format="ISO8601")
        bad = np.zeros(len(tr), dtype=bool)
        for _, e in ev.iterrows():
            end = e["end_utc"] if pd.notna(e["end_utc"]) else pd.Timestamp.max.tz_localize("UTC")
            bad |= ((tr["asset_id"] == e["asset_id"]) & (tr["window_start_utc"] >= e["onset_utc"]) & (tr["window_start_utc"] <= end)).values
        tr = tr[~bad]
    X, cols = _if_matrix(tr)
    model = IsolationForest(n_estimators=200, max_samples=4096, random_state=seed).fit(X)
    thr = float(np.quantile(-model.score_samples(X), q))
    rows = []
    for a, g in zf_eval.groupby("asset_id", sort=False):
        g = g.reset_index(drop=True)
        Xe = g.reindex(columns=cols).fillna(0.0).clip(-50, 50).values
        s = -model.score_samples(Xe)
        flag = (g["steady"].values & (s > thr)) | g["gap"].values | _flat_any(g)
        rows += _alerts_from_flag(g, flag, persist, k_diag, "B3 IsolationForest", s / thr * 2 * k_diag)
    return pd.DataFrame(rows, columns=_COLS), model, thr


def b0_scada(alarms: pd.DataFrame, assets_in_scope) -> pd.DataFrame:
    al = alarms[alarms["asset_id"].isin(assets_in_scope)].copy()
    rows = []
    for _, r in al.iterrows():
        sensor = r["alarm_type"] in ("BAD_QUALITY", "COMM_LOSS")
        rows.append({"asset_id": r["asset_id"], "alert_time_utc": r["raised_utc"], "event_class": "SENSOR" if sensor else "MACHINE",
                     "fault_type": "COMMUNICATION_LOSS" if r["alarm_type"] == "COMM_LOSS" else "UNKNOWN", "confidence": 0.9,
                     "evidence": f"SCADA {r['tag']} {r['alarm_type']}", "recommended_action": "Follow alarm response procedure."})
    return pd.DataFrame(rows, columns=_COLS)


_COLS = ["asset_id", "alert_time_utc", "event_class", "fault_type", "confidence", "evidence", "recommended_action"]
