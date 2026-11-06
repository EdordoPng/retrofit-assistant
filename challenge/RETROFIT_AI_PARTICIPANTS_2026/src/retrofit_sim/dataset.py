"""Dataset writer: runs the simulator per asset and writes the public / private tables."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from . import __version__
from . import generate as G
from .fleet import load_fleet, merge_profiles, rated_current_a
from .schema import TABLES, to_json_schema
from .waveform import snapshot, snapshot_schedule

BEARINGS = {  # deep-groove ball bearings; orders computed from NSK geometry, pitch diameter (bore+OD)/2 (assumption)
    "6309": (3.037, 4.963), "6311": (3.057, 4.943), "6312": (3.064, 4.936),
}
FEATURE_CHANNELS = [c for c in G.ALL_TELEMETRY_COLUMNS]
TRUTH_EXPORT = ["speed_ratio", "flow_m3h", "flow_required_m3h", "head_m", "q_rel", "suction_kpa_g", "discharge_kpa_g",
                "npsha_m", "npshr_m", "npsh_margin", "shaft_kw", "input_kw", "hydraulic_kw", "current_a", "motor_load",
                "fluid_temp_c", "bearing_temp_c", "winding_temp_c", "vib_rms_mm_s", "vib_accel_rms_g", "vib_crest",
                "cavitation_intensity", "K_total", "K_suction"]
LATENT_EXPORT = ["bearing_wear", "clog", "restriction", "misalignment", "unbalance", "impeller_wear", "air_entrainment"]


def bearing_for(a: dict) -> str:
    return a.get("bearing_designation") or ("6309" if a["motor_kw"] <= 37 else "6311" if a["motor_kw"] <= 55 else "6312")


def enrich_asset(a: dict) -> dict:
    a = dict(a)
    b = bearing_for(a)
    a["bearing_designation"] = b
    a["bearing_bpfo_order"], a["bearing_bpfi_order"] = BEARINGS[b]
    a.setdefault("impeller_vanes", 5 if a["motor_kw"] <= 15 else 6)
    return a


def asset_row(a: dict, specs: dict, limits: dict, n_days: float) -> dict:
    start = pd.Timestamp(a["start_utc"]).tz_localize("UTC")
    fluid = {"SHIP_SW_COOLING": "Seawater (brackish, ~6 PSU)", "SHIP_LT_FRESHWATER": "Treated fresh water (closed loop)",
             "INDUSTRIAL_CW": "Cooling-tower water", "PROCESS_TRANSFER": "Hot process water"}[a["profile"]]
    return {
        "asset_id": a["asset_id"], "split": a["split"], "site": a["site"], "system": a["system"], "profile": a["profile"],
        "control": a["control"], "instrumentation_tier": a["instrumentation_tier"],
        "window_start_utc": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "window_end_utc": (start + pd.Timedelta(days=n_days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commissioned_year": a["commissioned_year"], "pump_rated_flow_m3_h": a["q_bep_m3h"], "pump_rated_head_m": a["h_bep_m"],
        "pump_shutoff_head_m": round(a["h_bep_m"] * a["h0_shutoff_ratio"], 1), "pump_bep_efficiency": a["eta_bep"],
        "npsh3_at_bep_m": a["npshr_bep_m"], "design_flow_m3_h": a["q_design_m3h"], "design_head_m": a["h_design_m"],
        "static_head_m": a["system_static_m"], "motor_rated_kw": a["motor_kw"], "motor_rated_current_a": round(rated_current_a(a), 1),
        "motor_rated_rpm": a["rated_rpm"], "supply_voltage_v": a["voltage_v"], "supply_frequency_hz": a["supply_hz"],
        "min_speed_ratio": a.get("r_min") if a["control"].startswith("VFD") else None, "fluid": fluid,
        "bearing_designation": a["bearing_designation"], "bearing_bpfo_order": a["bearing_bpfo_order"],
        "bearing_bpfi_order": a["bearing_bpfi_order"], "impeller_vanes": a["impeller_vanes"],
        "vibration_alarm_mm_s": limits["vib_alarm_mm_s"], "vibration_trip_mm_s": limits["vib_trip_mm_s"],
        "channels_available": "|".join(sorted(specs.keys())),
        "wireless_update_s": a.get("wireless_update_s") if a["instrumentation_tier"] == "T1_RETROFIT" else None,
    }


def _iso(ms):
    if ms is None or (isinstance(ms, float) and np.isnan(ms)):
        return None
    return pd.Timestamp(int(ms), unit="ms", tz="UTC").floor("s").strftime("%Y-%m-%dT%H:%M:%SZ")


def ms_to_iso(df: pd.DataFrame, cols) -> pd.DataFrame:
    df = df.copy()
    for c in cols:
        if c in df:
            df[c.replace("_ms", "_utc")] = [_iso(v) for v in df[c]]
            df = df.drop(columns=c)
    return df


def features_1min(tele: pd.DataFrame) -> pd.DataFrame:
    """1-minute aggregate feature windows (mean/std/min/max/count per channel) from the public telemetry."""
    df = tele.copy()
    df["minute"] = df["timestamp_utc"].dt.floor("min")
    g = df.groupby(["asset_id", "minute"], observed=True, sort=True)
    parts = []
    for c in FEATURE_CHANNELS:
        if df[c].notna().any():
            agg = g[c].agg(["mean", "std", "min", "max", "count"])
            agg.columns = [f"{c}__{s}" for s in agg.columns]
            parts.append(agg.astype({f"{c}__count": "int16"}))
    out = pd.concat(parts, axis=1)
    out["operating_mode"] = _group_mode(df, ["asset_id", "minute"], "operating_mode").values
    out["running_fraction"] = (df["operating_mode"] == "RUNNING").groupby([df["asset_id"], df["minute"]], observed=True).mean().astype("float32").values
    out["quality_any"] = _group_or(df, ["asset_id", "minute"], "quality_flags").values
    out["rows"] = g.size().astype("int16").values
    out = out.reset_index().rename(columns={"minute": "window_start_utc"})
    for c in out.columns:
        if out[c].dtype == "float64":
            out[c] = out[c].astype("float32")
    return out


def _group_mode(df, keys, col):
    d = pd.get_dummies(df[col].astype(str))
    for k in keys:
        d[k] = df[k].values
    return d.groupby(keys, observed=True, sort=True).sum().idxmax(axis=1)


def _group_or(df, keys, col):
    q = df[col].astype(np.int64)
    acc = None
    for bit in (1, 2, 4, 8, 16):
        b = ((q & bit) > 0).groupby([df[k] for k in keys], observed=True, sort=True).max().astype(np.int16) * bit
        acc = b if acc is None else acc + b
    return acc.astype("int16")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_telemetry(df: pd.DataFrame, root: Path):
    days = df["timestamp_utc"].dt.strftime("%Y-%m-%d")
    for d in sorted(days.unique()):
        part = df[days == d]
        out = root / f"asset_id={part['asset_id'].iloc[0]}" / f"day={d}"
        out.mkdir(parents=True, exist_ok=True)
        tbl = pa.Table.from_pandas(part.drop(columns=["asset_id"]), preserve_index=False)
        pq.write_table(tbl, out / "part-0.parquet", compression="zstd", compression_level=6, use_dictionary=True,
                       write_statistics=True)


def truth_1min(res) -> pd.DataFrame:
    import warnings
    warnings.filterwarnings("ignore", message="Mean of empty slice")
    tr, lat, n = res["truth"], res["lat"], res["n"]
    t0 = pd.Timestamp(res["acfg"]["start_utc"]).tz_localize("UTC")
    m = n // 60
    d = {"asset_id": res["acfg"]["asset_id"], "timestamp_utc": t0 + pd.to_timedelta(np.arange(m) * 60, unit="s")}
    for k in TRUTH_EXPORT:
        d[k] = np.nanmean(np.asarray(tr[k][:m * 60], dtype=float).reshape(m, 60), axis=1).astype(np.float32) if not np.all(np.isnan(tr[k])) else np.nan
    for k in LATENT_EXPORT:
        d["latent_" + k] = np.asarray(getattr(lat, k)[:m * 60], dtype=float).reshape(m, 60).mean(axis=1).astype(np.float32)
    d["mode"] = res["ctx"].mode[::60][:m]
    return pd.DataFrame(d)


def snapshots_for(res, interval_s=4 * 3600):
    acfg = res["acfg"]
    if "vibration_accel_rms_g" not in res["specs"]:
        return []
    rng = res["R"]["snapshot"]
    run = res["truth"]["speed_ratio"] > 0.3
    t0 = pd.Timestamp(acfg["start_utc"]).tz_localize("UTC")
    rows = []
    for k, i in enumerate(snapshot_schedule(res["n"], run, interval_s, rng)):
        if not res["present"][i]:
            continue
        x = snapshot(res["truth"], i, acfg, rng)
        rows.append({"asset_id": acfg["asset_id"], "snapshot_id": f"{acfg['asset_id']}-S{k + 1:03d}",
                     "timestamp_utc": t0 + pd.Timedelta(seconds=int(i)), "sample_rate_hz": 10240, "n_samples": int(x.size),
                     "axis": "radial", "unit": "g", "rpm_at_capture": float(np.round(res["truth"]["rpm"][i], 1)),
                     "samples": x})
    return rows


def _write_csv(df: pd.DataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, lineterminator="\n", float_format="%.6g")


def build(tier: str, seed: int | None, output: str, profile: str = "public", private_config: str | None = None,
          fleet_config: str | None = None, assets: list | None = None, days: float = 7.0, snapshots: bool = True,
          stress_assets: int = 6, label_fraction: float = 0.3, log=print) -> dict:
    """Build a dataset tier. profile: public (train+validation), test (needs private config), all."""
    root = Path(__file__).resolve().parents[2]
    fleet_config = fleet_config or str(root / "configs" / "fleet_public.yaml")
    cfg, fleet = load_fleet(fleet_config)
    seeds = {"train": cfg["public_seed"], "validation": cfg["public_seed"]}
    if seed is not None:
        seeds = {"train": int(seed), "validation": int(seed)}
    if profile in ("test", "all"):
        if not private_config or not os.path.exists(private_config):
            raise SystemExit("profile '%s' needs --private-config (organizer test configuration)" % profile)
        import yaml
        with open(private_config, encoding="utf-8") as fh:
            pcfg = yaml.safe_load(fh)
        test_assets = merge_profiles(cfg, pcfg)
        seeds["test"] = int(pcfg["test_seed"])
        fleet = (fleet if profile == "all" else []) + test_assets
    if tier == "stress":
        from .stress import sample_fleet
        fleet = sample_fleet(cfg, seed if seed is not None else 1, n_assets=stress_assets, days=days)
        seeds["stress"] = int(seed if seed is not None else 1)
    if tier == "starter":
        assets = assets or ["PUMP-01", "PUMP-03", "PUMP-04", "PUMP-06", "PUMP-08"]
    if assets:
        fleet = [a for a in fleet if a["asset_id"] in assets]
    out = Path(output)
    pub = out / "public"
    priv = out / "private"
    for d in (pub, priv):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
    tables = {k: [] for k in ("assets", "events", "benign", "alarms", "maint", "context", "features", "truth", "snap")}
    report = {"tier": tier, "profile": profile, "days": days, "assets": {}, "generator_version": __version__,
              "seeds_public": {k: v for k, v in seeds.items() if k != "test"}}
    t_all = time.time()
    for a in fleet:
        a = enrich_asset(a)
        t1 = time.time()
        res = G.simulate_asset(a, seeds[a["split"]], days)
        tele = G.telemetry_frame(res)
        if tier == "starter":
            tele = downsample(tele, 10)
            tele_path = pub / "starter_parts" / f"{a['asset_id']}.csv.gz"
            tele_path.parent.mkdir(parents=True, exist_ok=True)
            tele.to_csv(tele_path, index=False, float_format="%.4g", compression={"method": "gzip", "mtime": 0},
                        date_format="%Y-%m-%dT%H:%M:%SZ")
        else:
            write_telemetry(tele, pub / "telemetry")
            tables["features"].append(features_1min(tele))
        tables["assets"].append(asset_row(res["acfg"], res["specs"], res["acfg"]["limits"], days))
        ev = pd.DataFrame(G.events_for(res))
        ev["split"] = a["split"]
        tables["events"].append(ev)
        bn = pd.DataFrame(G.benign_for(res))
        bn["split"] = a["split"]
        tables["benign"].append(bn)
        tables["alarms"].append(pd.DataFrame(G.alarms_for(res)))
        mt = pd.DataFrame(G.maintenance_for(res))
        mt["split"] = a["split"]
        tables["maint"].append(mt)
        tables["context"].append(G.context_frame(res))
        tables["truth"].append(truth_1min(res))
        if snapshots and tier != "starter":
            tables["snap"] += snapshots_for(res)
        report["assets"][a["asset_id"]] = {"split": a["split"], "telemetry_rows": int(len(tele)), "seconds": round(time.time() - t1, 1)}
        log(f"  {a['asset_id']:8s} {a['split']:10s} rows={len(tele):7d}  events={len(ev):2d}  {time.time() - t1:5.1f}s")
        del res, tele
    write_tables(tables, pub, priv, tier, label_fraction, seeds.get("stress", 0))
    report["seconds_total"] = round(time.time() - t_all, 1)
    with open(priv / "generation_record.json", "w", encoding="utf-8") as fh:
        json.dump({**report, "seeds": seeds, "fleet_config": os.path.basename(fleet_config),
                   "private_config": os.path.basename(private_config) if private_config else None}, fh, indent=2)
    manifest(pub, report)
    manifest(priv, report)
    return report


def downsample(tele: pd.DataFrame, step_s: int) -> pd.DataFrame:
    """Starter tier: 10-s mean for dense channels, last valid value for sparse channels, OR of quality flags."""
    df = tele.copy()
    df["bucket"] = df["timestamp_utc"].dt.floor(f"{step_s}s")
    g = df.groupby("bucket", sort=True)
    out = pd.DataFrame({"asset_id": g["asset_id"].first(), "timestamp_utc": g["timestamp_utc"].first().dt.floor(f"{step_s}s")})
    out["operating_mode"] = _group_mode(df, ["bucket"], "operating_mode").values
    for c in G.ALL_TELEMETRY_COLUMNS:
        sparse = c in ("bearing_temp_c",) or c.startswith("vibration")
        out[c] = (g[c].last() if sparse else g[c].mean()).astype("float32")
    out["quality_flags"] = _group_or(df, ["bucket"], "quality_flags").values
    out["sensor_source"] = g["sensor_source"].first()
    out["sample_interval_s"] = np.int16(step_s)
    return out.reset_index(drop=True)


def write_tables(t, pub: Path, priv: Path, tier: str, label_fraction: float = 0.3, stress_seed: int = 0):
    assets = pd.DataFrame(t["assets"])
    _write_csv(assets, pub / "assets.csv")
    ev = pd.concat(t["events"], ignore_index=True)
    ev = ms_to_iso(ev, ["onset_ms", "detectable_ms", "action_deadline_ms", "end_ms"])
    ev = ev.sort_values(["asset_id", "onset_utc", "event_id"]).reset_index(drop=True)
    cols = ["event_id", "asset_id", "event_class", "fault_type", "onset_utc", "pre_existing", "detectable_utc",
            "action_deadline_utc", "end_utc", "severity", "evidence_channels", "observable", "root_cause_event_id",
            "sensor_tag", "label_confidence"]
    for split, name in (("train", "events_train.csv"), ("validation", "events_validation.csv")):
        part = ev[ev.split == split][cols]
        if len(part):
            _write_csv(part, pub / name)
    if (ev.split == "test").any():
        _write_csv(ev[ev.split == "test"][cols], priv / "events_test.csv")
    if (ev.split == "stress").any():
        st = ev[ev.split == "stress"][cols].reset_index(drop=True)
        # scarce labels: a stratified share of machine and sensor events (at least one of each class when present)
        rs = np.random.default_rng([stress_seed, 7])
        keep = np.zeros(len(st), dtype=bool)
        for cls, idx in st.groupby("event_class").groups.items():
            idx = np.array(list(idx))
            m = max(1, int(round(label_fraction * len(idx))))
            keep[rs.choice(idx, min(m, len(idx)), replace=False)] = True
        _write_csv(st[keep], pub / "events_stress_labeled_subset.csv")
        _write_csv(st, priv / "events_stress_all.csv")
    bn = pd.concat(t["benign"], ignore_index=True)
    bn = ms_to_iso(bn, ["start_ms", "end_ms"])
    if (bn.split.isin(["train", "validation"])).any():
        _write_csv(bn[bn.split.isin(["train", "validation"])].drop(columns="split"), pub / "benign_windows_train_validation.csv")
    if (bn.split == "test").any():
        _write_csv(bn[bn.split == "test"].drop(columns="split"), priv / "benign_windows_test.csv")
    if (bn.split == "stress").any():
        _write_csv(bn[bn.split == "stress"].drop(columns="split"), pub / "benign_windows_stress.csv")
    al = pd.concat(t["alarms"], ignore_index=True) if any(len(x) for x in t["alarms"]) else pd.DataFrame(columns=list(TABLES["alarms"]))
    al = ms_to_iso(al, ["raised_ms", "cleared_ms", "acknowledged_ms"]).sort_values(["asset_id", "raised_utc"])
    _write_csv(al[list(TABLES["alarms"])], pub / "alarms.csv")
    mt = pd.concat(t["maint"], ignore_index=True)
    mt = ms_to_iso(mt, ["start_ms", "end_ms"])
    hidden = mt.split.isin(["test", "stress"]) & mt.in_window
    _write_csv(mt[~hidden].drop(columns="split")[list(TABLES["maintenance"])], pub / "maintenance.csv")
    if hidden.any():
        _write_csv(mt[hidden].drop(columns="split")[list(TABLES["maintenance"])], priv / "maintenance_hidden_in_window.csv")
    ctx = pd.concat(t["context"], ignore_index=True)
    ctx["timestamp_utc"] = ctx["timestamp_utc"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_csv(ctx, pub / "operating_context.csv")
    if t["features"]:
        f = pd.concat(t["features"], ignore_index=True)
        pq.write_table(pa.Table.from_pandas(f, preserve_index=False), pub / "features_1min.parquet", compression="zstd")
    tr = pd.concat(t["truth"], ignore_index=True)
    pq.write_table(pa.Table.from_pandas(tr, preserve_index=False), priv / "truth_1min.parquet", compression="zstd")
    if t["snap"]:
        s = pd.DataFrame(t["snap"])
        tbl = pa.table({k: (pa.array(list(s[k]), type=pa.list_(pa.float32())) if k == "samples" else pa.array(s[k]))
                        for k in s.columns})
        pq.write_table(tbl, pub / "vibration_snapshots.parquet", compression="zstd")
    if tier == "starter":
        parts = sorted((pub / "starter_parts").glob("*.csv.gz"))
        frames = [pd.read_csv(p) for p in parts]
        allt = pd.concat(frames, ignore_index=True)
        allt.to_csv(pub / "telemetry.csv.gz", index=False, float_format="%.4g", compression={"method": "gzip", "mtime": 0})
        shutil.rmtree(pub / "starter_parts")
    with open(pub / "schema.json", "w", encoding="utf-8") as fh:
        json.dump(to_json_schema(), fh, indent=2, ensure_ascii=False)


def manifest(d: Path, report: dict):
    files = []
    for p in sorted(d.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            files.append({"path": str(p.relative_to(d)).replace(os.sep, "/"), "bytes": p.stat().st_size, "sha256": _sha256(p)})
    m = {"dataset": "RETROFIT AI 2026 synthetic pump telemetry", "synthetic": True, "tier": report["tier"],
         "generator_version": report["generator_version"], "file_count": len(files),
         "total_bytes": sum(f["bytes"] for f in files),
         "telemetry_rows": {k: v["telemetry_rows"] for k, v in report["assets"].items()}, "files": files}
    with open(d / "manifest.json", "w", encoding="utf-8") as fh:
        json.dump(m, fh, indent=2)
