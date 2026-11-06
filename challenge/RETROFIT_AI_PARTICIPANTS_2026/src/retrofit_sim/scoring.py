"""Event-based scorer for alert predictions (used for validation by participants and for the hidden test by organizers).

Rules (see BENCHMARK_RULES.md section 4):
  * Bursts: alerts on the same asset within 5 min of the first alert of a burst form one burst, scored as one alert at the
    burst's first time. A burst that names more than one fault type earns no fault-type credit (more than one class: no
    class credit). Listing several guesses at once therefore does not help.
  * Scored events: label rows with observable == True. Unobservable events are neither rewarded nor penalised and
    alerts that match them are neutral.
  * Event window: starts at max(onset, detectable - 6 h) (window start for pre-existing conditions). It ends at end_utc
    for machine faults that end with a repair (a locked-out intervention), and at end_utc + 30 min for events that end
    without one (cavitation and air-entrainment episodes, instrument faults); open-ended events run to the asset window
    end. Alerts outside every window are false alerts.
  * Each burst is matched to at most one event whose window contains it, preferring same fault_type, then same
    event_class, then not-yet-detected events, then the earliest onset. The first matched burst detects the event (true
    positive). Later bursts on a detected event are repeats: repeats starting within 30 min of an episode start join that
    episode; one reminder episode per 12 h is free; further repeat episodes are "excess" and count like false alerts.
  * False-alert bursts form episodes of 30 min anchored at the first alert of the episode (no chaining). False alerts
    inside benign windows are reported as nuisance alerts (a subset of false alerts).
  * Timeliness per scored event: 1.0 if the first alert is at or before the reference time (action deadline if one
    exists, otherwise detectable time + 6 h), decaying linearly to 0.1 at the window end; 0 if missed.
  * Composite = 100 x (0.35 F1 + 0.20 timeliness + 0.25 fault-type recall + 0.10 class recall + 0.10 alert burden),
    alert burden = max(0, 1 - (false-alert + excess-repeat episodes) per asset-day / 2).
    Precision = TP / (TP + false-alert episodes + excess-repeat episodes).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import pandas as pd

POST_TOL = pd.Timedelta(minutes=30)
PRE_TOL = pd.Timedelta(hours=6)
BURST = pd.Timedelta(minutes=5)
EPISODE = pd.Timedelta(minutes=30)
GRACE_NO_DEADLINE = pd.Timedelta(hours=6)
REMINDER = pd.Timedelta(hours=12)
WEIGHTS = {"f1": 0.35, "timeliness": 0.20, "fault_type_recall": 0.25, "class_recall": 0.10, "alert_burden": 0.10}
REQUIRED = ["asset_id", "alert_time_utc", "event_class", "fault_type", "confidence"]
CLASSES = {"MACHINE", "SENSOR"}
FAULT_TYPES = {"BEARING_WEAR", "SUCTION_STRAINER_CLOGGING", "CAVITATION", "DISCHARGE_RESTRICTION", "MISALIGNMENT", "IMBALANCE",
               "IMPELLER_WEAR", "AIR_ENTRAINMENT", "SENSOR_DRIFT", "SENSOR_STUCK", "SENSOR_CALIBRATION_SHIFT",
               "SENSOR_NOISE_SPIKES", "COMMUNICATION_LOSS", "UNKNOWN"}
SOFT_END = {"CAVITATION", "AIR_ENTRAINMENT"}          # episodes that end without a locked-out repair


def _ts(s):
    return pd.to_datetime(s, utc=True, format="ISO8601")


def load_predictions(path_or_df) -> pd.DataFrame:
    p = pd.read_csv(path_or_df) if isinstance(path_or_df, (str, os.PathLike)) else path_or_df.copy()
    missing = [c for c in REQUIRED if c not in p.columns]
    if missing:
        raise ValueError(f"prediction file is missing columns {missing}; required {REQUIRED}")
    p["alert_time_utc"] = _ts(p["alert_time_utc"])
    p["event_class"] = p["event_class"].astype(str).str.strip().str.upper()
    p["fault_type"] = p["fault_type"].astype(str).str.strip().str.upper()
    bad = sorted(set(p["event_class"]) - CLASSES)
    if bad:
        raise ValueError(f"invalid event_class values {bad}; allowed {sorted(CLASSES)}")
    p.loc[~p["fault_type"].isin(FAULT_TYPES), "fault_type"] = "INVALID"
    p["confidence"] = pd.to_numeric(p["confidence"], errors="coerce").fillna(0.5)
    return p.sort_values(["asset_id", "alert_time_utc"], kind="stable").reset_index(drop=True)


def bursts(pred: pd.DataFrame) -> pd.DataFrame:
    """Collapse alerts on one asset within 5 min of a burst's first alert into one scored alert."""
    rows = []
    for a, g in pred.groupby("asset_id", sort=True):
        start, members = None, []
        for _, r in g.iterrows():
            if start is None or r["alert_time_utc"] - start > BURST:
                if members:
                    rows.append(_burst_row(a, start, members))
                start, members = r["alert_time_utc"], []
            members.append(r)
        if members:
            rows.append(_burst_row(a, start, members))
    return pd.DataFrame(rows, columns=["asset_id", "alert_time_utc", "event_class", "fault_type", "n_alerts"])


def _burst_row(a, t, members):
    types = {m["fault_type"] for m in members}
    classes = {m["event_class"] for m in members}
    return {"asset_id": a, "alert_time_utc": t, "event_class": classes.pop() if len(classes) == 1 else "AMBIGUOUS",
            "fault_type": types.pop() if len(types) == 1 else "AMBIGUOUS", "n_alerts": len(members)}


def _episodes(times):
    """Number of 30-min episodes, each anchored at its first alert (no chaining)."""
    n, start = 0, None
    for t in sorted(times):
        if start is None or t - start > EPISODE:
            n += 1
            start = t
    return n


def score(pred, events: pd.DataFrame, assets: pd.DataFrame, benign: pd.DataFrame | None = None, split: str | None = None,
          min_confidence: float = 0.0) -> dict:
    pred = load_predictions(pred)
    assets = assets.copy()
    if split:
        assets = assets[assets["split"] == split]
    scope = set(assets["asset_id"])
    ws = dict(zip(assets["asset_id"], _ts(assets["window_start_utc"])))
    we = dict(zip(assets["asset_id"], _ts(assets["window_end_utc"])))
    pred = pred[pred["asset_id"].isin(scope) & (pred["confidence"] >= min_confidence)].copy()
    if len(pred):
        pred = pred[[ws[a] <= t < we[a] for a, t in zip(pred["asset_id"], pred["alert_time_utc"])]]
    n_raw = len(pred)
    n_invalid = int((pred["fault_type"] == "INVALID").sum()) if n_raw else 0
    bu = bursts(pred) if n_raw else pd.DataFrame(columns=["asset_id", "alert_time_utc", "event_class", "fault_type", "n_alerts"])

    ev = events[events["asset_id"].isin(scope)].copy()
    for c in ("onset_utc", "detectable_utc", "action_deadline_utc", "end_utc"):
        ev[c] = _ts(ev[c])
    ev["observable"] = ev["observable"].astype(str).str.lower().isin(["true", "1"])

    def w_start(e):
        s = max(e["onset_utc"], ws[e["asset_id"]])
        if pd.notna(e["detectable_utc"]):
            s = max(s, e["detectable_utc"] - PRE_TOL)
        return s

    def w_end(e):
        if pd.isna(e["end_utc"]):
            return we[e["asset_id"]]
        soft = e["fault_type"] in SOFT_END or e["event_class"] == "SENSOR"
        return min(e["end_utc"] + (POST_TOL if soft else pd.Timedelta(0)), we[e["asset_id"]])

    ev["w_start"] = [w_start(e) for _, e in ev.iterrows()]
    ev["w_end"] = [w_end(e) for _, e in ev.iterrows()]
    bn = None
    if benign is not None and len(benign):
        bn = benign[benign["asset_id"].isin(scope)].copy()
        bn["start_utc"], bn["end_utc"] = _ts(bn["start_utc"]), _ts(bn["end_utc"])

    first_alert, first_row, dup_times = {}, {}, {}
    fa_times, nuisance = {}, 0
    for _, r in bu.iterrows():
        a, t = r["asset_id"], r["alert_time_utc"]
        e_a = ev[ev["asset_id"] == a]
        cand = e_a[(e_a["w_start"] <= t) & (t <= e_a["w_end"])]
        if len(cand):
            cand = cand.assign(_type=(cand["fault_type"] != r["fault_type"]).astype(int),
                               _cls=(cand["event_class"] != r["event_class"]).astype(int),
                               _det=cand["event_id"].isin(first_alert).astype(int))
            eid = cand.sort_values(["_type", "_cls", "_det", "onset_utc"]).iloc[0]["event_id"]
            if eid in first_alert:
                dup_times.setdefault(eid, []).append(t)
            else:
                first_alert[eid], first_row[eid] = t, r
            continue
        fa_times.setdefault(a, []).append(t)
        if bn is not None and ((bn["asset_id"] == a) & (bn["start_utc"] <= t) & (t <= bn["end_utc"])).any():
            nuisance += 1
    episodes = sum(_episodes(v) for v in fa_times.values())
    observable = dict(zip(ev["event_id"], ev["observable"]))
    excess = 0
    for eid, times in dup_times.items():
        if not observable.get(eid, True):
            continue                                    # unobservable events: neutral
        ep_start, last_counted = first_alert[eid], first_alert[eid]
        for t in sorted(times):
            if t - ep_start <= EPISODE:
                continue
            ep_start = t
            if t - last_counted >= REMINDER:
                last_counted = t
            else:
                excess += 1
    asset_days = float(sum((we[a] - ws[a]).total_seconds() for a in scope) / 86400.0)

    per_event = []
    for _, e in ev[ev["observable"]].iterrows():
        eid = e["event_id"]
        hit = eid in first_alert
        t = first_alert.get(eid)
        ref = e["action_deadline_utc"] if pd.notna(e["action_deadline_utc"]) else (
            (e["detectable_utc"] if pd.notna(e["detectable_utc"]) else e["w_start"]) + GRACE_NO_DEADLINE)
        if not hit:
            tl = 0.0
        elif t <= ref:
            tl = 1.0
        else:
            span = max((e["w_end"] - ref).total_seconds(), 1.0)
            tl = max(0.1, 1.0 - (t - ref).total_seconds() / span)
        r = first_row.get(eid)
        lead_h = (e["action_deadline_utc"] - t).total_seconds() / 3600 if hit and pd.notna(e["action_deadline_utc"]) else None
        delay_h = (t - e["detectable_utc"]).total_seconds() / 3600 if hit and pd.notna(e["detectable_utc"]) else None
        per_event.append({"event_id": eid, "asset_id": e["asset_id"], "event_class": e["event_class"], "fault_type": e["fault_type"],
                          "detected": hit, "first_alert_utc": t.isoformat() if hit else None,
                          "predicted_fault_type": r["fault_type"] if hit else None, "predicted_class": r["event_class"] if hit else None,
                          "type_correct": bool(hit and r["fault_type"] == e["fault_type"]),
                          "class_correct": bool(hit and r["event_class"] == e["event_class"]),
                          "timeliness": tl, "lead_time_to_deadline_h": lead_h, "delay_after_detectable_h": delay_h,
                          "repeats": len(dup_times.get(eid, []))})
    pe = pd.DataFrame(per_event)
    n_ev = len(pe)
    tp = int(pe["detected"].sum()) if n_ev else 0
    recall = tp / n_ev if n_ev else 0.0
    denom = tp + episodes + excess
    precision = tp / denom if denom else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    fa_day = (episodes + excess) / asset_days if asset_days else 0.0
    comp = {"f1": f1, "timeliness": float(pe["timeliness"].mean()) if n_ev else 0.0,
            "fault_type_recall": float(pe["type_correct"].mean()) if n_ev else 0.0,
            "class_recall": float(pe["class_correct"].mean()) if n_ev else 0.0,
            "alert_burden": max(0.0, 1.0 - fa_day / 2.0)}
    leads = pe["lead_time_to_deadline_h"].dropna() if n_ev else pd.Series(dtype=float)
    return {
        "split": split, "assets": sorted(scope), "asset_days": round(asset_days, 2), "alerts_scored": n_raw,
        "alert_bursts": int(len(bu)), "invalid_fault_type_alerts": n_invalid,
        "events_scored": n_ev, "events_unobservable_excluded": int((~ev["observable"]).sum()),
        "true_positive_events": tp, "false_alert_episodes": episodes, "false_alerts_raw": int(sum(len(v) for v in fa_times.values())),
        "nuisance_alerts_in_benign_windows": nuisance, "repeat_alerts": int(sum(len(v) for v in dup_times.values())),
        "excess_repeat_episodes": excess,
        "event_recall": recall, "alert_precision": precision, "event_f1": f1, "false_alerts_per_asset_day": fa_day,
        "timeliness": comp["timeliness"], "fault_type_recall": comp["fault_type_recall"], "class_recall": comp["class_recall"],
        "early_warning_rate": float((leads > 0).mean()) if len(leads) else None,
        "median_lead_time_h": float(leads.median()) if len(leads) else None,
        "median_delay_after_detectable_h": float(pe["delay_after_detectable_h"].dropna().median()) if n_ev and pe["delay_after_detectable_h"].notna().any() else None,
        "recall_machine": float(pe[pe.event_class == "MACHINE"]["detected"].mean()) if n_ev and (pe.event_class == "MACHINE").any() else None,
        "recall_sensor": float(pe[pe.event_class == "SENSOR"]["detected"].mean()) if n_ev and (pe.event_class == "SENSOR").any() else None,
        "composite_score": 100.0 * sum(WEIGHTS[k] * comp[k] for k in WEIGHTS),
        "weights": WEIGHTS, "per_event": per_event,
    }


def format_report(r: dict) -> str:
    def f(x, nd=3):
        return "-" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))
    return "\n".join([
        f"split={r['split']} assets={len(r['assets'])} asset-days={r['asset_days']} alerts={r['alerts_scored']} (bursts={r['alert_bursts']}, invalid types={r['invalid_fault_type_alerts']})",
        f"events scored={r['events_scored']} (unobservable excluded={r['events_unobservable_excluded']})",
        f"detected={r['true_positive_events']}  false-alert episodes={r['false_alert_episodes']} "
        f"(nuisance in benign windows={r['nuisance_alerts_in_benign_windows']})  repeats={r['repeat_alerts']} "
        f"(excess repeat episodes={r['excess_repeat_episodes']})",
        f"recall={f(r['event_recall'])} precision={f(r['alert_precision'])} F1={f(r['event_f1'])} "
        f"(false + excess repeat) episodes/asset-day={f(r['false_alerts_per_asset_day'], 2)}",
        f"timeliness={f(r['timeliness'])} fault-type recall={f(r['fault_type_recall'])} class recall={f(r['class_recall'])}",
        f"early-warning rate={f(r['early_warning_rate'])} median lead to deadline [h]={f(r['median_lead_time_h'], 1)}",
        f"COMPOSITE = {r['composite_score']:.1f} / 100"])


def score_main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m retrofit_sim score", description="Score an alert prediction file.")
    p.add_argument("--predictions", required=True)
    p.add_argument("--events", required=True, help="Label file (events_validation.csv for participants).")
    p.add_argument("--assets", required=True, help="assets.csv")
    p.add_argument("--benign", default=None, help="Benign-window file (optional; only affects the nuisance count).")
    p.add_argument("--split", default=None)
    p.add_argument("--out", default=None, help="Write the full JSON report here.")
    a = p.parse_args(argv)
    ev = pd.read_csv(a.events)
    assets = pd.read_csv(a.assets)
    split = a.split or (ev["asset_id"].map(dict(zip(assets.asset_id, assets.split))).mode().iloc[0] if len(ev) else None)
    bn = pd.read_csv(a.benign) if a.benign else None
    r = score(a.predictions, ev, assets, bn, split)
    print(format_report(r))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(r, fh, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(score_main())
