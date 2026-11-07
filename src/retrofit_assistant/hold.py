"""Hold thermal/crest-only candidates until a restart's settling time has elapsed."""

import pandas as pd
from retrofit_sim.baselines import CH

from .data import AVAILABILITY
from .params import B1_K, B1_PERSIST, HELD_CHANNELS, STOP_MODES, THERMAL_SETTLE_MIN


def sustained_channels(history, k=B1_K, persist=B1_PERSIST):
    """Return CH-ordered channels exceeding k in every available persistence minute."""
    tail = history.tail(persist)
    if len(tail) < persist:
        return ()
    return tuple(key for key in CH if "z_" + key in tail
                 and tail["z_" + key].abs().gt(k).fillna(False).all())


def hold_after_restart(candidates, scored):
    """Recheck held candidates using only the minute available at restart + H.

    A stopped minute clears pending candidates. Missing minutes never imply a
    stop, but an absent recheck minute cannot produce an emission.
    """
    result = candidates.copy()
    result["held_from_utc"] = pd.NA
    latency = AVAILABILITY["features_1min.parquet"].latency
    hold = pd.Timedelta(minutes=THERMAL_SETTLE_MIN)
    rows = []
    for _, candidate in result.iterrows():
        if candidate.decided_by.startswith("source_"):
            rows.append(candidate)
            continue
        time = pd.Timestamp(candidate.alert_time_utc)
        minutes = scored.loc[scored.asset_id == candidate.asset_id].sort_values("window_start_utc")
        history = minutes.loc[minutes.window_start_utc + latency <= time]
        channels = sustained_channels(history)
        if not channels or not all(key in HELD_CHANNELS for key in channels):
            rows.append(candidate)
            continue
        restarts = history.loc[
            history.operating_mode.eq("RUNNING") & history.operating_mode.shift().isin(STOP_MODES),
            "window_start_utc",
        ]
        if restarts.empty or time >= restarts.iloc[-1] + hold:
            rows.append(candidate)
            continue
        restart = restarts.iloc[-1]
        due = restart + hold
        waiting = minutes.loc[(minutes.window_start_utc > restart)
                              & (minutes.window_start_utc + latency <= due)]
        if waiting.operating_mode.isin(STOP_MODES).any():
            continue
        recheck = minutes.loc[minutes.window_start_utc == due - latency]
        if recheck.empty:
            continue
        last = recheck.iloc[0]
        if any(pd.notna(last["z_" + key]) and abs(last["z_" + key]) > B1_K for key in channels):
            held = candidate.copy()
            held["held_from_utc"] = candidate.alert_time_utc
            held["alert_time_utc"] = due.strftime("%Y-%m-%dT%H:%M:%SZ")
            rows.append(held)
    if not rows:
        return result.iloc[:0].copy()
    return pd.DataFrame(rows).sort_values(
        ["asset_id", "alert_time_utc"], kind="stable",
    ).reset_index(drop=True)
