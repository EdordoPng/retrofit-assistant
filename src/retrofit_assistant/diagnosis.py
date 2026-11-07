"""Re-diagnose existing candidates using only each alert's available prefix."""

import pandas as pd
from retrofit_sim.baselines import CH

from .consistency import channel_snapshot, consistency_state, noise_channel, sensor_shape, steady_minutes
from .data import AVAILABILITY
from .params import ACCELEROMETER_CHANNELS, ACTUATOR_CHANNELS


def rediagnose(candidates, scored, assets):
    """Preserve candidate identity/order and attach audit states outside the CSV."""
    result = candidates.copy()
    result["decided_by"] = "official"
    states = []
    metadata = assets.set_index("asset_id")
    latency = AVAILABILITY["features_1min.parquet"].latency
    for index, alert in result.iterrows():
        time = pd.Timestamp(alert.alert_time_utc)
        # Explicit availability filter per alert, even for a full-week score frame.
        history = scored.loc[(scored.asset_id == alert.asset_id)
                             & (scored.window_start_utc + latency <= time)].sort_values("window_start_utc").reset_index(drop=True)
        snapshot = channel_snapshot(history, metadata.loc[alert.asset_id], time)
        installed = str(metadata.loc[alert.asset_id].get("channels_available", "")).split("|")
        state, key, deviating = consistency_state(snapshot, installed, steady_minutes(history))
        protected = alert.fault_type in ("COMMUNICATION_LOSS", "SENSOR_STUCK")
        noisy = None if protected else noise_channel(history, snapshot, installed, metadata.loc[alert.asset_id])
        if noisy is not None:
            state, key = "noise", noisy
        accelerometer = state == "unverifiable" and bool(deviating) and all(c in ACCELEROMETER_CHANNELS for c in deviating)
        states.append({"asset_id": alert.asset_id, "alert_time_utc": alert.alert_time_utc,
                       "state": state, "accelerometer_exception": accelerometer,
                       "protected": protected})
        if protected:
            result.loc[index, "decided_by"] = "official_protected"
            continue
        cls, fault = alert.event_class, alert.fault_type
        reason = ""
        if state == "noise":
            result.loc[index, "decided_by"] = "rediagnose_noise"
            cls, fault = "SENSOR", "SENSOR_NOISE_SPIKES"
            reason = "persistent isolated variance; recent median mean deviation and fresh coupled variance deviations remain still"
        elif state == "confirmed":
            result.loc[index, "decided_by"] = "rediagnose_confirmed"
            cls = "SENSOR"
            fault, reason = sensor_shape(history, key, metadata.loc[alert.asset_id], time)
            if fault == "UNKNOWN" and alert.event_class == "SENSOR":
                fault = alert.fault_type
            reason = "fresh coupled channels remain still; " + reason
        elif (state == "refuted" or accelerometer) and cls == "SENSOR":
            result.loc[index, "decided_by"] = "rediagnose_refuted" if state == "refuted" else "rediagnose_accelerometer"
            cls, fault = "MACHINE", "UNKNOWN"
            reason = "fresh coupled channel follows deviation" if state == "refuted" else "accelerometer-only deviation; no independent sensor evidence"
        if (cls, fault) != (alert.event_class, alert.fault_type):
            value = snapshot[key][CH[key] + "__mean"]
            result.loc[index, ["event_class", "fault_type", "evidence", "recommended_action"]] = [
                cls, fault, f"{CH[key]}={value:.6g}; {reason}",
                f"Verify {CH[key]} against an independent reference; review instrument history." if cls == "SENSOR"
                else f"Inspect pump and verify {CH[key]} with independent measurements; cause uncertain.",
            ]
        # Actuator readings describe the controller's response, never determine
        # the diagnosis of a process variable. Keep them visible as context even
        # when the official class/type is preserved.
        context = [f"{CH[c]}={snapshot[c][CH[c] + '__mean']:.6g} (context only)"
                   for c in ACTUATOR_CHANNELS if c in snapshot and c != key]
        if context:
            result.loc[index, "evidence"] = str(result.loc[index, "evidence"]) + "; actuator context: " + ", ".join(context)
    result.attrs["diagnosis_states"] = states
    return result
