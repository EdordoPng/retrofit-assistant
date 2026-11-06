"""Asset-window generator: scenario -> context -> latent states -> truth -> observations -> records/labels."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib

import numpy as np
import pandas as pd

from . import context as C
from .faults import MACHINE_FAULTS, SENSOR_FAULTS, FaultSpec, build_latent
from .labels import cavitation_episodes, detectable_time, first_crossing, severity_class
from .plant import simulate_truth
from .records import ACTION, alarms, operator_text
from .sensors import QUALITY_BITS, channel_specs, observe

PLC_MODE = {"OFF": "STOPPED", "STANDBY": "STOPPED", "STARTUP": "STARTING", "SHUTDOWN": "STOPPING",
            "MAINTENANCE": "LOCKED_OUT", "STEADY": "RUNNING", "LOAD_CHANGE": "RUNNING"}


def _key(*parts) -> int:
    return int.from_bytes(hashlib.blake2b("|".join(map(str, parts)).encode(), digest_size=8).digest(), "little")


def rngs(seed: int, asset_id: str):
    ss = np.random.SeedSequence([int(seed), _key(asset_id)])
    names = ["scenario", "context", "plant", "sensor", "records", "snapshot"]
    return dict(zip(names, (np.random.default_rng(s) for s in ss.spawn(len(names)))))


def plan_faults(acfg: dict, R, n: int):
    """Scenario entries -> FaultSpec lists with seeded onset jitter; repairs become locked-out maintenance stops."""
    machine, sensor, gateway, stops, process = [], [], [], [], []
    r = R["scenario"]
    entries = acfg.get("scenario", [])
    ids = [f"{acfg['asset_id']}-E{k + 1:02d}" for k in range(len(entries))]
    prev_end, onsets = {}, {}
    for k, e in enumerate(entries):
        jitter = float(e.get("jitter_h", 2.0))
        dj = r.uniform(-jitter, jitter) if jitter > 0 else 0.0
        onset = int((e.get("onset_h", 0.0) + dj) * 3600)
        end = None
        if e["type"] == "PLANNED_MAINTENANCE":
            e = dict(e, end_h=e.get("onset_h", 0.0))
        if e.get("end_h") is not None:
            end = int((e["end_h"] + dj + (r.uniform(-jitter / 4, jitter / 4) if jitter > 0 else 0.0)) * 3600)
            end = min(max(end, onset + 1800), n - 1)
        rc = e.get("root_cause")
        root = ids[rc - 1] if isinstance(rc, int) else rc
        # follow-on events (root cause given, zero jitter) start right after the cause's repair stop
        if isinstance(rc, int) and e.get("align") == "onset" and rc - 1 in onsets:
            # concurrent consequence of the cause: same jitter, fixed offset from the cause's onset
            shift = onsets[rc - 1] - int(entries[rc - 1].get("onset_h", 0.0) * 3600)
            onset = int(e.get("onset_h", 0.0) * 3600) + shift
            end = None if e.get("end_h") is None else min(n - 1, int(e["end_h"] * 3600) + shift)
        elif isinstance(rc, int) and jitter == 0 and rc - 1 in prev_end and prev_end[rc - 1] is not None:
            cause_end_h = entries[rc - 1].get("end_h", entries[rc - 1].get("onset_h", 0.0))
            delay = int(max(e.get("onset_h", 0.0) * 3600 - cause_end_h * 3600, 0))
            onset = prev_end[rc - 1] + delay
            if end is not None:
                end = max(end, onset + 1800)
        f = FaultSpec(e["type"], onset, end, dict(e.get("params", {})), ids[k], root, e.get("sensor_tag"))
        # actual locked-out duration varies around the planned figure (whole seconds)
        rep_s = int(round(float(e.get("repair_h", 0.0)) * 3600 * r.uniform(0.8, 1.3)))
        f.params["_repair_h"] = rep_s / 3600.0
        if e["type"] in MACHINE_FAULTS or e["type"] == "AIR_ENTRAINMENT":
            machine.append(f)
        elif e["type"] == "COMMUNICATION_LOSS" and e.get("sensor_tag") == "GATEWAY":
            gateway.append(f)
        elif e["type"] in SENSOR_FAULTS:
            sensor.append(f)
        elif e["type"] in ("PLANNED_MAINTENANCE", "SUCTION_LEVEL_DROP"):
            process.append(f)
        if end is not None and rep_s > 0:
            stops.append((end, min(n, end + rep_s), "MAINTENANCE"))
        prev_end[k] = None if end is None else end + rep_s
        onsets[k] = onset
    # routine planned work (inspection, lubrication) with a locked-out stop: unrelated to faults, so that a lockout
    # in the telemetry is not by itself evidence of a repair
    n_routine = max(1, int(r.poisson(acfg.get("routine_lockouts_per_week", 1.5) * n / 604800)))
    for j in range(n_routine):
        for _try in range(50):                      # place without overlapping other stops (2 h clearance)
            a = int(r.uniform(0.03, 0.97) * n)
            dur = int(r.uniform(0.75, 4.0) * 3600)
            if not any(a < b0 + 7200 and a + dur > a0 - 7200 for a0, b0, _ in stops):
                break
        else:
            continue
        eid = f"{acfg['asset_id']}-R{j + 1:02d}"
        wt, note = [("ROUTINE_INSPECTION", "Routine inspection, no abnormal findings."),
                    ("LUBRICATION", "Bearings regreased per schedule."),
                    ("COUPLING_INSPECTION", "Coupling guard removed and coupling checked, OK."),
                    ("INSTRUMENT_CHECK", "Transmitters loop-checked, OK.")][int(r.integers(0, 4))]
        f = FaultSpec("PLANNED_MAINTENANCE", a, a, {"_repair_h": dur / 3600.0, "work_type": wt, "note": note}, eid)
        process.append(f)
        stops.append((a, min(n, a + dur), "MAINTENANCE"))
    return machine, sensor, gateway, stops, process


def build_context(acfg, R, n, stops):
    start = dt.datetime.fromisoformat(acfg["start_utc"])
    prof = acfg["profile"]
    pc = acfg.get("context", {})
    if prof.startswith("SHIP"):
        ctx = C.ship_ropax(R["context"], n, start.month, pc, stops)
    elif prof == "INDUSTRIAL_CW":
        ctx = C.industrial_shift(R["context"], n, start.month, start.weekday(), pc, stops)
    else:
        ctx = C.process_batch(R["context"], n, start.month, pc, stops)
    # benign voltage sags (supply disturbances)
    r = R["context"]
    sags = []
    for _ in range(int(r.poisson(acfg.get("voltage_sags_per_week", 1.0) * n / 604800))):
        a = int(r.integers(0, n - 30))
        d = int(r.integers(1, 8))
        ctx.supply_voltage_pu[a:a + d] *= r.uniform(0.75, 0.9)
        sags.append((a, a + d))
    ctx.benign_events = [("VOLTAGE_SAG", a, b) for a, b in sags]
    # slow fluctuation of the heat load / duty around the schedule value
    ctx.demand = np.where(ctx.running, np.clip(ctx.demand * (1.0 + C._smooth_noise(r, n, acfg.get("demand_noise", 0.04), 1800)), 0.0, 1.2), 0.0)
    ctx.sea_temp_c = ctx.supply_temp_c.copy() if prof.startswith("SHIP") else np.full(n, np.nan)
    if prof == "SHIP_LT_FRESHWATER":
        # closed LT loop: temperature held by the central-cooler three-way valve, rises with heat load
        ctx.supply_temp_c = acfg.get("loop_temp_c", 34.0) + 3.0 * (ctx.demand - 0.6) + C._smooth_noise(r, n, 0.5, 1800)
    return ctx


def steady_mask(ctx, truth, settle_s=600):
    """Running in a scheduled (non-transient) mode, at least `settle_s` after the last start."""
    run = (truth["speed_ratio"] > 0.3) & np.isin(ctx.mode, ["STEADY", "LOAD_CHANGE"])
    n = len(run)
    starts = np.r_[0, np.nonzero(np.diff(run.astype(np.int8)) == 1)[0] + 1]
    last = np.zeros(n, dtype=np.int64)
    last[starts] = starts
    last = np.maximum.accumulate(last)
    return run & ((np.arange(n) - last) >= settle_s)


def simulate_asset(acfg: dict, seed: int, n_days: float, want_detectability=True):
    from .fleet import commissioning_limits
    n = int(n_days * 86400)
    R = rngs(seed, acfg["asset_id"])
    machine, sensor, gateway, stops, process = plan_faults(acfg, R, n)
    ctx = build_context(acfg, R, n, stops)
    for f in process:
        if f.fault_type == "SUCTION_LEVEL_DROP":       # e.g. cooling-tower basin make-up valve failure
            a, b = max(0, f.onset_s), (n if f.end_s is None else min(n, f.end_s))
            t = np.arange(a, b)
            ramp = np.minimum(1.0, (t - a) / (f.params.get("ramp_h", 1.0) * 3600)) * np.minimum(1.0, (b - t) / 1800.0)
            ctx.suction_static_m[a:b] -= f.params["drop_m"] * ramp
    base = acfg.get("baseline_condition", {})
    plant_seed = int(R["plant"].integers(0, 2 ** 31))
    lat = build_latent(n, machine, base)
    truth = simulate_truth(acfg, ctx, lat, np.random.default_rng(plant_seed))
    healthy = build_latent(n, [], base)
    truth_h = simulate_truth(acfg, ctx, healthy, np.random.default_rng(plant_seed))
    steady_h = steady_mask(ctx, truth_h)
    acfg = dict(acfg)
    acfg["limits"] = commissioning_limits(acfg, truth_h, steady_h)
    specs = channel_specs(acfg)
    comm = {"gateway_outages": [(max(0, f.onset_s), n if f.end_s is None else min(n, f.end_s)) for f in gateway]}
    obs, qual, present = observe(truth, acfg, specs, sensor, comm, R["sensor"])
    qual[np.isin(ctx.mode, ["STARTUP"])] |= QUALITY_BITS["STARTUP_INHIBIT"]
    # channels whose reading cannot be trusted at a given time (instrument fault active, gateway outage)
    unusable = {c: ~present.copy() for c in specs}
    for f in sensor:
        if f.sensor_tag in unusable:
            unusable[f.sensor_tag][max(0, f.onset_s):(n if f.end_s is None else min(n, f.end_s))] = True
    det = {}
    if want_detectability:
        for f in machine:
            lat_f = build_latent(n, [f], base)
            truth_f = simulate_truth(acfg, ctx, lat_f, np.random.default_rng(plant_seed))
            active = np.zeros(n, dtype=bool)
            active[max(0, f.onset_s): (n if f.end_s is None else min(n, f.end_s))] = True
            det[f.event_id] = detectable_time(truth_f, truth_h, specs, active, unusable=unusable) + (truth_f,)
    return dict(acfg=acfg, n=n, ctx=ctx, lat=lat, truth=truth, truth_h=truth_h, obs=obs, qual=qual, present=present,
                specs=specs, machine=machine, sensor=sensor, gateway=gateway, stops=stops, process=process, det=det, R=R,
                steady=steady_mask(ctx, truth))


def _sustained(mask, w=300):
    """True where `mask` has held for the preceding w seconds."""
    from .labels import rolling_mean
    return rolling_mean(mask.astype(float), w) > 0.999


def _cav_severity(min_margin: float) -> str:
    return "severe" if min_margin < 0.95 else "moderate" if min_margin < 1.05 else "minor"


def _ms(t0_ms, i):
    return None if i is None else int(t0_ms + int(i) * 1000)


def events_for(res) -> list:
    acfg, truth, n = res["acfg"], res["truth"], res["n"]
    proc = {f.event_id: f.fault_type for f in res["process"]}
    rc = lambda x: (f"{proc[x]}:{x}" if x in proc else x)
    lim = acfg["limits"]
    t0 = int(pd.Timestamp(acfg["start_utc"]).tz_localize("UTC").value // 10 ** 6)
    rows = []
    healthy_q = res["truth_h"]["flow_m3h"]
    cat_zone_b = lim["vib_alarm_mm_s"] / 1.25          # ISO 10816-7: alarm ~ 1.25 x zone-B upper limit
    for f in res["machine"]:
        d_i, chans, tf = res["det"].get(f.event_id, (None, [], truth))
        a = max(0, f.onset_s)
        b = n if f.end_s is None else min(n, f.end_s)
        act = np.zeros(n, dtype=bool)
        act[a:b] = True
        running = steady_mask(res["ctx"], tf)
        run_act = res["steady"]
        # action deadline = first time (while this fault is active) the plant reaches a conventional limit (sustained):
        #   vibration-type faults: ISO 10816-7 alarm (entry to zone C) or bearing temperature alarm;
        #   hydraulic faults: cooling-flow shortfall (>10 % below the healthy system at the same duty, or <95 % of the
        #   controller's required flow) or NPSH margin below 1.1.
        if f.fault_type in ("BEARING_WEAR", "MISALIGNMENT", "IMBALANCE"):
            th = res["truth_h"]
            contrib = (tf["vib_rms_mm_s"] - th["vib_rms_mm_s"]) >= 0.25 * (truth["vib_rms_mm_s"] - th["vib_rms_mm_s"])
            dl = first_crossing(act & contrib & _sustained(run_act & ((truth["vib_rms_mm_s"] > lim["vib_alarm_mm_s"]) | (truth["bearing_temp_c"] > lim["bearing_alarm_c"])), 60))
            peak = float(np.nanmax(np.where(act & running, tf["vib_rms_mm_s"], np.nan))) if (act & running).any() else 0.0
            sev = severity_class(peak, (cat_zone_b, lim["vib_trip_mm_s"]))
        else:
            q_req = truth["flow_required_m3h"]
            short = (truth["flow_m3h"] < 0.9 * healthy_q) | (np.nan_to_num(truth["flow_m3h"] - 0.95 * q_req, nan=1.0) < 0) | (truth["npsh_margin"] < 1.1)
            # this fault must carry a material share (>= 25 %) of the flow deficit, or itself push NPSH margin below 1.3
            contrib = ((healthy_q - tf["flow_m3h"]) >= 0.25 * (healthy_q - truth["flow_m3h"])) & (healthy_q - tf["flow_m3h"] > 0.02 * healthy_q)
            contrib |= tf["npsh_margin"] < 1.3
            dl = first_crossing(act & contrib & _sustained(run_act & short, 300))
            if f.fault_type == "IMPELLER_WEAR":
                sev = severity_class(float(res["lat"].impeller_wear[b - 1]), (0.05, 0.10))
            elif (act & running).any():
                loss = float(np.nanmax(np.where(act & running, 1.0 - tf["flow_m3h"] / np.maximum(healthy_q, 1e-3), np.nan)))
                min_sig = float(np.nanmin(np.where(act & running, tf["npsh_margin"], np.nan)))
                sev = "severe" if (loss > 0.2 or min_sig < 1.0) else "moderate" if (loss > 0.08 or min_sig < 1.3) else "minor"
            else:
                sev = "minor"
        rows.append({"event_id": f.event_id, "asset_id": acfg["asset_id"], "event_class": "MACHINE", "fault_type": f.fault_type,
                     "onset_ms": _ms(t0, a), "pre_existing": f.onset_s < 0,
                     "detectable_ms": _ms(t0, d_i), "action_deadline_ms": _ms(t0, dl), "end_ms": _ms(t0, b) if f.end_s is not None else None,
                     "severity": sev, "evidence_channels": ",".join(chans[:4]) if chans else None,
                     "observable": d_i is not None, "root_cause_event_id": rc(f.root_cause), "sensor_tag": None,
                     "label_confidence": "HIGH" if f.end_s is not None else "MEDIUM"})
    # emergent cavitation episodes, attributed to an active clog / level-drop / air root cause
    from .labels import OBS_KEYS
    n_scn = len(acfg.get("scenario", []))
    th = res["truth_h"]
    for k, (a, b) in enumerate(cavitation_episodes(truth)):
        cause = None
        for f in res["machine"] + res["process"]:
            if f.fault_type in ("SUCTION_STRAINER_CLOGGING", "SUCTION_LEVEL_DROP", "AIR_ENTRAINMENT") and f.onset_s <= a and (f.end_s is None or f.end_s > a):
                cause = f.event_id
        # evidence: instrumented channels whose episode mean departs from the healthy system by > 3 sigma (10-min mean)
        ev_ch = []
        for col, c in res["specs"].items():
            key = OBS_KEYS.get(col)
            if key is None:
                continue
            d = float(np.nanmean(np.abs(np.nan_to_num(truth[key][a:b]) - np.nan_to_num(th[key][a:b]))))
            ref = float(np.nanmean(np.abs(np.nan_to_num(th[key][a:b]))))
            sig = max((c.sigma + c.rel_sigma * ref) / np.sqrt(max(1, min(b - a, 600) // max(c.update_s, 1))), c.resolution)
            thr = 3 * sig + (0.02 * ref if (col.startswith("vibration") or col == "motor_current_a") else 0.0)
            if d > thr:
                ev_ch.append((d / max(thr, 1e-9), col))
        ev_ch = [c for _, c in sorted(ev_ch, reverse=True)]
        obs_ok = len(ev_ch) > 0
        dl = first_crossing(_sustained(np.r_[np.zeros(a, bool), truth["npsh_margin"][a:b] < 1.1, np.zeros(n - b, bool)], 60))
        rows.append({"event_id": f"{acfg['asset_id']}-E{n_scn + k + 1:02d}", "asset_id": acfg["asset_id"], "event_class": "MACHINE",
                     "fault_type": "CAVITATION", "onset_ms": _ms(t0, a), "pre_existing": False,
                     "detectable_ms": _ms(t0, min(a + 300, b - 1)) if obs_ok else None,
                     "action_deadline_ms": _ms(t0, dl), "end_ms": _ms(t0, b),
                     "severity": _cav_severity(float(np.nanmin(truth["npsh_margin"][a:b]))),
                     "evidence_channels": ",".join(ev_ch[:4]) if ev_ch else None, "observable": obs_ok,
                     "root_cause_event_id": rc(cause) if cause else "OPERATING_CONDITION",
                     "sensor_tag": None, "label_confidence": "MEDIUM"})
    for f in res["sensor"] + res["gateway"]:
        a = max(0, f.onset_s)
        b = n if f.end_s is None else min(n, f.end_s)
        c = res["specs"].get(f.sensor_tag)
        observable = f.sensor_tag == "GATEWAY" or c is not None
        d_i = a
        sig10 = max(c.sigma / np.sqrt(max(1, 600 // max(c.update_s, 1))), c.resolution) if c is not None else 0.0
        if f.fault_type == "SENSOR_DRIFT" and c is not None:
            # drift exceeds 3 sigma of a 10-min mean (same rule as machine faults)
            d_i = a + int(3 * sig10 / max(abs(f.params["drift_per_h"]), 1e-9) * 3600)
        elif f.fault_type == "SENSOR_CALIBRATION_SHIFT" and c is not None:
            d_i = a + 300 if abs(f.params["step"]) > 3 * sig10 else b
        elif f.fault_type == "SENSOR_NOISE_SPIKES":
            d_i = a + 300
        elif f.fault_type == "SENSOR_STUCK" and c is not None:
            # a frozen value is only distinguishable once it lasts longer than the channel's normal constant runs
            d_i = a + max(600, normal_constant_run_s(res["obs"][f.sensor_tag], c.update_s, a, b))
        rows.append({"event_id": f.event_id, "asset_id": acfg["asset_id"], "event_class": "SENSOR", "fault_type": f.fault_type,
                     "onset_ms": _ms(t0, a), "pre_existing": f.onset_s < 0, "detectable_ms": _ms(t0, d_i) if observable and d_i < b else None,
                     "action_deadline_ms": None, "end_ms": _ms(t0, b) if f.end_s is not None else None, "severity": "minor",
                     "evidence_channels": f.sensor_tag, "observable": observable and d_i < b, "root_cause_event_id": rc(f.root_cause),
                     "sensor_tag": f.sensor_tag, "label_confidence": "HIGH"})
    return rows


def normal_constant_run_s(y, update_s, a, b, q=99.9):
    """Longest normal run of identical consecutive readings (p99.9, seconds) outside the fault window [a, b)."""
    y = np.asarray(y, dtype=float)
    m = np.ones(len(y), dtype=bool)
    m[a:b] = False
    v = y[m]
    v = v[~np.isnan(v)]
    if v.size < 10:
        return 0
    change = np.r_[True, v[1:] != v[:-1]]
    starts = np.nonzero(change)[0]
    runs = np.diff(np.r_[starts, v.size])
    return int(np.percentile(runs, q) * max(update_s, 1))


def benign_for(res) -> list:
    """Benign but visually abnormal windows (alerts here are nuisance alerts)."""
    acfg, ctx, n = res["acfg"], res["ctx"], res["n"]
    t0 = int(pd.Timestamp(acfg["start_utc"]).tz_localize("UTC").value // 10 ** 6)
    rows = []
    for s in ctx.segments:
        kind = {"STARTUP": "STARTUP", "SHUTDOWN": "SHUTDOWN", "LOAD_CHANGE": "LOAD_CHANGE"}.get(s.mode)
        if s.mode == "STANDBY":
            kind = "STANDBY_CHANGEOVER"
        if s.mode == "MAINTENANCE":
            kind = "MAINTENANCE_RESTART"
        if s.mode == "OFF" and s.note == "planned stop":
            kind = "PLANNED_STOP"
        if s.note == "set-point change":
            kind = "SETPOINT_CHANGE"
        if kind and 0 <= s.start < n:
            rows.append({"asset_id": acfg["asset_id"], "benign_type": kind, "start_ms": _ms(t0, max(0, s.start)),
                         "end_ms": _ms(t0, min(n, s.end + {"STARTUP": 300, "SHUTDOWN": 120, "LOAD_CHANGE": 300, "SETPOINT_CHANGE": 300, "MAINTENANCE_RESTART": 1800}.get(kind, 0))), "note": s.note})
    for kind, a, b in ctx.benign_events:
        rows.append({"asset_id": acfg["asset_id"], "benign_type": kind, "start_ms": _ms(t0, a), "end_ms": _ms(t0, b + 120), "note": "supply dip"})
    from .records import _runs
    for a, b in _runs(ctx.sea_state > 2.2):
        if b - a > 1800:
            rows.append({"asset_id": acfg["asset_id"], "benign_type": "HEAVY_WEATHER", "start_ms": _ms(t0, a), "end_ms": _ms(t0, b), "note": "Hs > 2.2 m"})
    return rows


def telemetry_frame(res) -> pd.DataFrame:
    acfg, obs, n = res["acfg"], res["obs"], res["n"]
    t0 = pd.Timestamp(acfg["start_utc"]).tz_localize("UTC")
    ts = (t0 + pd.to_timedelta(np.arange(n), unit="s")).astype("datetime64[ms, UTC]")
    df = pd.DataFrame({"asset_id": acfg["asset_id"], "timestamp_utc": ts})
    df["operating_mode"] = pd.Categorical(pd.Series(res["ctx"].mode).map(PLC_MODE).values)
    for col in ALL_TELEMETRY_COLUMNS:
        df[col] = obs[col] if col in obs else np.full(n, np.nan, dtype=np.float32)
    df["quality_flags"] = res["qual"].astype(np.int16)
    df["sensor_source"] = "|".join(sorted({c.source for c in res["specs"].values()}))
    df["sample_interval_s"] = np.int16(1)
    return df[res["present"]].reset_index(drop=True)


ALL_TELEMETRY_COLUMNS = ["motor_speed_rpm", "motor_current_a", "motor_power_kw", "suction_pressure_kpa", "discharge_pressure_kpa",
                         "flow_m3_h", "fluid_temp_c", "bearing_temp_c", "motor_winding_temp_c", "vibration_rms_mm_s",
                         "vibration_accel_rms_g", "vibration_crest_factor", "ambient_temp_c", "valve_position_pct"]


def alarms_for(res) -> list:
    acfg = res["acfg"]
    t0 = int(pd.Timestamp(acfg["start_utc"]).tz_localize("UTC").value // 10 ** 6)
    hours = (pd.Timestamp(acfg["start_utc"]).hour + np.arange(res["n"]) / 3600.0) % 24
    night = (hours < 6) | (hours >= 22)
    # process alarms are active only while the pump is commanded to run (PLC run feedback); a stopping pump does not
    # raise low-pressure / low-flow alarms
    commanded = np.isin(res["ctx"].mode, ["STEADY", "LOAD_CHANGE", "STARTUP"])
    return alarms(acfg["asset_id"], res["obs"], res["present"], (res["truth"]["speed_ratio"] > 0.05) & commanded, acfg["limits"], t0,
                  res["R"]["records"], res["qual"], night)


def maintenance_for(res, history_days=540) -> list:
    acfg, n, r = res["acfg"], res["n"], res["R"]["records"]
    t0 = pd.Timestamp(acfg["start_utc"]).tz_localize("UTC")
    rows = []
    # history (before the window): routine service records, some with findings
    k = 0
    for typ, every_d in (("ROUTINE_INSPECTION", 30), ("STRAINER_CLEANING", acfg.get("strainer_interval_d", 21)),
                         ("LUBRICATION", 90), ("VIBRATION_ROUTE_MEASUREMENT", 60), ("ALIGNMENT_CHECK", 365)):
        d = -float(r.uniform(1, every_d))
        while d > -history_days:
            k += 1
            obs_txt = {"ROUTINE_INSPECTION": "No abnormal findings.", "STRAINER_CLEANING": r.choice(["Light debris.", "Moderate fouling.", "Clean."]),
                       "LUBRICATION": "Bearings regreased.", "VIBRATION_ROUTE_MEASUREMENT": f"Portable reading {r.uniform(1.0, 3.2):.1f} mm/s RMS, zone A/B.",
                       "ALIGNMENT_CHECK": "Within tolerance."}[typ]
            rows.append({"record_id": f"{acfg['asset_id']}-M{k:04d}", "asset_id": acfg["asset_id"], "work_type": typ,
                         "start_ms": int((t0 + pd.Timedelta(days=d)).value // 10 ** 6), "end_ms": int((t0 + pd.Timedelta(days=d, hours=float(r.uniform(0.3, 2)))).value // 10 ** 6),
                         "operator_observation": str(obs_txt), "diagnosis_confidence": "CONFIRMED", "planned": True, "in_window": False})
            d -= every_d * float(r.uniform(0.85, 1.2))
    # in-window planned work
    for f in res["process"]:
        if f.fault_type != "PLANNED_MAINTENANCE":
            continue
        k += 1
        rows.append({"record_id": f"{acfg['asset_id']}-M{k:04d}", "asset_id": acfg["asset_id"], "work_type": f.params.get("work_type", "PLANNED_SERVICE"),
                     "start_ms": int((t0 + pd.Timedelta(seconds=int(f.end_s))).value // 10 ** 6),
                     "end_ms": int((t0 + pd.Timedelta(seconds=int(f.end_s + f.params["_repair_h"] * 3600))).value // 10 ** 6),
                     "operator_observation": f.params.get("note", "Planned work completed, pump restarted."), "diagnosis_confidence": "CONFIRMED",
                     "planned": True, "in_window": True})
    # in-window interventions for repaired faults
    for f in res["machine"] + res["sensor"] + res["gateway"]:
        if f.end_s is None or f.end_s >= n - 1 or f.fault_type == "AIR_ENTRAINMENT":
            continue
        k += 1
        txt, conf = operator_text(f.fault_type, r, tag=f.sensor_tag)
        dur = max(f.params.get("_repair_h", 0.5), 0.25)
        rows.append({"record_id": f"{acfg['asset_id']}-M{k:04d}", "asset_id": acfg["asset_id"], "work_type": ACTION.get(f.fault_type, "INSPECTION"),
                     "start_ms": int((t0 + pd.Timedelta(seconds=int(f.end_s))).value // 10 ** 6),
                     "end_ms": int((t0 + pd.Timedelta(seconds=int(f.end_s + dur * 3600))).value // 10 ** 6),
                     "operator_observation": txt, "diagnosis_confidence": conf, "planned": False, "in_window": True})
    return sorted(rows, key=lambda x: x["start_ms"])


def setpoint_text(a: dict) -> str:
    c = a["control"]
    if c == "VFD_TEMPERATURE":
        return f"LT temperature {a.get('controlled_temp_setpoint_c', 36.0):.0f} degC (SW pump speed)"
    if c == "VFD_PRESSURE":
        return f"Header differential pressure {a.get('dp_setpoint_m', 0.9 * a['h_design_m']) * 9.81:.0f} kPa"
    if c == "FLOW_VALVE":
        return "Batch flow set-point (recipe)"
    return "None (fixed speed)"


def context_frame(res) -> pd.DataFrame:
    """Operating context at 1-min resolution (as recorded by ship/plant systems, with their own noise)."""
    acfg, ctx, n, r = res["acfg"], res["ctx"], res["n"], res["R"]["records"]
    idx = np.arange(0, n, 60)
    t0 = pd.Timestamp(acfg["start_utc"]).tz_localize("UTC")
    seg_note = np.empty(n, dtype=object)
    for s in ctx.segments:
        seg_note[max(0, s.start):min(n, s.end)] = s.note
    df = pd.DataFrame({
        "asset_id": acfg["asset_id"], "timestamp_utc": t0 + pd.to_timedelta(idx, unit="s"),
        "schedule_state": seg_note[idx],
        "duty_demand_pct": np.round(100 * ctx.demand[idx], 1),
        "supply_water_temp_c": np.round(ctx.supply_temp_c[idx] + r.normal(0, 0.15, idx.size), 1),
        "sea_temp_c": np.round(ctx.sea_temp_c[idx] + r.normal(0, 0.2, idx.size), 1) if acfg["profile"].startswith("SHIP") else np.nan,
        "ambient_temp_c": np.round(ctx.ambient_c[idx] + r.normal(0, 0.3, idx.size), 1),
        "sea_state_hs_m": np.round(ctx.sea_state[idx], 1) if acfg["profile"].startswith("SHIP") else np.nan,
        "suction_static_head_m": np.round(ctx.suction_static_m[idx], 2) if acfg.get("level_measured", False) else np.nan,
        "controlled_setpoint": setpoint_text(acfg),
    })
    return df
