"""Read-only telemetry replay: streams stored synthetic telemetry as MQTT-style JSON messages.

Default output is JSON Lines on stdout (one message per row): {"topic": ..., "payload": {...}}. Topic naming follows a
Sparkplug-like hierarchy (retrofit/<site>/<asset>/telemetry) but is plain JSON. With --mqtt-host and the optional
paho-mqtt package installed, the same messages are published to a broker you run yourself. The adapter only
publishes; it never subscribes to command topics and has no write path to any device.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time

import pandas as pd


def _load(data_dir, asset, start=None, end=None):
    tdir = os.path.join(data_dir, "telemetry", f"asset_id={asset}")
    if os.path.isdir(tdir):
        df = pd.read_parquet(tdir)
    else:
        df = pd.read_csv(os.path.join(data_dir, "telemetry.csv.gz"))
        df = df[df.asset_id == asset]
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    if start:
        df = df[df.timestamp_utc >= pd.Timestamp(start)]
    if end:
        df = df[df.timestamp_utc < pd.Timestamp(end)]
    return df.sort_values("timestamp_utc")


def messages(data_dir, asset, start=None, end=None, limit=None, site="site"):
    df = _load(data_dir, asset, start, end)
    if limit:
        df = df.head(int(limit))
    topic = f"retrofit/{re.sub(r'[^A-Za-z0-9]+', '_', site).strip('_').lower()}/{asset}/telemetry"
    cols = [c for c in df.columns if c not in ("asset_id", "day")]
    for rec in df[cols].itertuples(index=False):
        p = {}
        for c, v in zip(cols, rec):
            if c == "timestamp_utc":
                p[c] = v.isoformat()
                continue
            if hasattr(v, "item"):
                v = v.item()
            if isinstance(v, float):
                if math.isnan(v):
                    continue
                p[c] = float(f"{v:.6g}")
            else:
                p[c] = v if isinstance(v, (int, str)) else str(v)
        yield {"topic": topic, "payload": p}


def replay_main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m retrofit_sim replay", description=__doc__.splitlines()[0])
    ap.add_argument("--data", default="data/full")
    ap.add_argument("--asset", required=True)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--limit", type=int, default=None, help="Maximum number of messages.")
    ap.add_argument("--speed", type=float, default=0.0, help="Replay speed factor (0 = as fast as possible, 1 = real time).")
    ap.add_argument("--mqtt-host", default=None, help="Optional broker you run yourself (requires paho-mqtt).")
    ap.add_argument("--mqtt-port", type=int, default=1883)
    a = ap.parse_args(argv)
    assets = pd.read_csv(os.path.join(a.data, "assets.csv"))
    site = assets.set_index("asset_id").loc[a.asset, "site"] if a.asset in set(assets.asset_id) else "site"
    client = None
    if a.mqtt_host:
        try:
            import paho.mqtt.client as mqtt  # optional dependency
        except ImportError:
            print("paho-mqtt is not installed; install it or omit --mqtt-host to stream to stdout", file=sys.stderr)
            return 2
        client = mqtt.Client()
        client.connect(a.mqtt_host, a.mqtt_port)
        client.loop_start()
    prev = None
    n = 0
    for m in messages(a.data, a.asset, a.start, a.end, a.limit, site):
        if a.speed > 0:
            ts = pd.Timestamp(m["payload"]["timestamp_utc"])
            if prev is not None:
                time.sleep(max(0.0, (ts - prev).total_seconds() / a.speed))
            prev = ts
        line = json.dumps(m, separators=(",", ":"))
        if client is not None:
            client.publish(m["topic"], json.dumps(m["payload"]), qos=0, retain=False)
        else:
            sys.stdout.write(line + "\n")
        n += 1
    if client is not None:
        client.loop_stop()
        client.disconnect()
    print(f"replayed {n} messages", file=sys.stderr)
    return 0
