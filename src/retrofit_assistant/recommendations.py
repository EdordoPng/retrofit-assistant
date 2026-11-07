"""Deterministic, advisory repair guidance for existing alerts."""

import re

import pandas as pd
from retrofit_sim.baselines import CH

DECIDED_BY = (
    "official", "official_protected", "rediagnose_confirmed",
    "rediagnose_refuted", "rediagnose_accelerometer", "rediagnose_noise",
    "source_stuck", "source_cavitation",
    "rediagnose_spectrum",
)

# Each pair is inspect / proposed action / alternative to rule out.
# TECHNICAL_MODEL sections 3, 7 and 9 describe the physical mechanisms.
_MACHINE = {
    # Section 9: acceleration, crest factor, temperature and friction from wear.
    "BEARING_WEAR": ("bearing housing and lubrication", "review bearing condition and plan bearing service", "lubrication and measurement faults"),
    # Sections 3 and 9: suction loss rises with strainer clogging.
    "SUCTION_STRAINER_CLOGGING": ("suction strainer and inlet pressure", "review the strainer and consider cleaning under site procedures", "low suction level and pressure instrument error"),
    # Sections 3 and 9: low NPSH causes head loss and broadband vibration.
    "CAVITATION": ("suction conditions and pump noise", "review suction losses and consider reducing flow if operating procedures allow", "air ingress and suction instrument error"),
    # Sections 3 and 9: discharge restriction reduces flow and raises pressure.
    "DISCHARGE_RESTRICTION": ("discharge piping, valve position and heat exchanger", "review the restriction and consider cleaning under site procedures", "normal load changes and pressure instrument error"),
    # Sections 7 and 9: misalignment produces vibration and heat.
    "MISALIGNMENT": ("coupling alignment and bearing temperatures", "review alignment and plan a coupling inspection", "accelerometer mounting and normal load changes"),
    # Sections 7 and 9: unbalance produces speed-dependent vibration.
    "IMBALANCE": ("rotor and impeller deposits", "review vibration with speed and plan rotor inspection", "accelerometer mounting and misalignment"),
    # Sections 3 and 9: impeller wear reduces head at a given flow.
    "IMPELLER_WEAR": ("pump head, flow and impeller", "compare the operating point with the pump curve and plan inspection", "process changes and pressure instrument error"),
    # Sections 3 and 9: entrained air reduces head and causes vibration.
    "AIR_ENTRAINMENT": ("suction level and possible air ingress", "review inlet conditions and plan an air ingress inspection", "cavitation and suction instrument error"),
    # Section 9: instrument faults affect readings, not the plant.
    "SENSOR_DRIFT": ("instrument trend and process condition", "compare the reading with an independent measurement", "instrument drift before mechanical work"),
    # Section 9: a stuck instrument shows a frozen reading.
    "SENSOR_STUCK": ("instrument reading and connection", "compare the reading with an independent measurement", "a frozen instrument before mechanical work"),
    # Section 9: calibration shift is a step in the reading.
    "SENSOR_CALIBRATION_SHIFT": ("instrument calibration and process condition", "compare the reading with an independent measurement", "calibration error before mechanical work"),
    # Section 9: noise and spikes affect the reading.
    "SENSOR_NOISE_SPIKES": ("instrument wiring and reading", "compare the reading with an independent measurement", "electrical noise before mechanical work"),
    # Section 9: communication loss causes missing gateway rows or channel data.
    "COMMUNICATION_LOSS": ("gateway, network and instrument connection", "review data availability and instrument status", "communication loss before mechanical work"),
    # Sections 3 and 9: process conditions can affect pump readings.
    "UNKNOWN": ("process conditions and pump condition", "compare measurements and review the operating history", "process changes and instrument error before mechanical work"),
}

# TECHNICAL_MODEL section 9: instrument faults alter readings; the pump may also
# have a fault, so independent verification precedes any opening.
_SENSOR_DETAIL = {
    "SENSOR_DRIFT": "instrument trend for drift",
    "SENSOR_STUCK": "instrument for a frozen reading",
    "SENSOR_CALIBRATION_SHIFT": "instrument calibration for a sudden shift",
    "SENSOR_NOISE_SPIKES": "instrument wiring and reading for noise or spikes",
    "COMMUNICATION_LOSS": "gateway, network and instrument connection for missing data",
}
_PROCESS = ("fluid_temp_c", "suction_pressure_kpa", "discharge_pressure_kpa", "flow_m3_h")
_CHANNEL_LABELS = {
    "vibration_rms_mm_s": "vibration velocity",
    "vibration_accel_rms_g": "vibration acceleration",
    "vibration_crest_factor": "vibration crest factor",
    "bearing_temp_c": "bearing temperature",
    "suction_pressure_kpa": "suction pressure",
    "discharge_pressure_kpa": "discharge pressure",
    "motor_current_a": "motor current",
    "motor_power_kw": "motor power",
    "flow_m3_h": "flow",
    "motor_speed_rpm": "motor speed",
    "motor_winding_temp_c": "motor winding temperature",
    "fluid_temp_c": "fluid temperature",
    "valve_position_pct": "valve position",
}
_RULE_OUT = {
    "rediagnose_refuted": "a process cause before a mechanical one (an independent witness follows the deviation)",
    "rediagnose_accelerometer": "accelerometer mounting; vibration channels share one sensor",
}
_NOTES = {
    "official": "the class was not verified with independent witnesses",
    "source_cavitation": "the NPSH margin needs site verification",
}


def _channel(evidence):
    matches = [(match.start(), name) for name in CH.values()
               for match in re.finditer(r"(?<![\w])" + re.escape(name) + r"(?![\w])", str(evidence))]
    return min(matches)[1] if matches else None


def _action(row):
    fault, cls = row["fault_type"], row["event_class"]
    channel = _channel(row["evidence"])
    inspect, action, rule_out = _MACHINE.get(fault, _MACHINE["UNKNOWN"])
    if cls == "SENSOR":
        detail = _SENSOR_DETAIL.get(fault, "instrument and the reported condition")
        inspect = detail
        action = "verify the instrument using an independent measurement or calibration check before opening the pump"
        if fault == "COMMUNICATION_LOSS":
            action = "check gateway, network and instrument power, and confirm that data returns before any work on the pump"
        rule_out = "instrument error before opening the pump"
    if fault == "UNKNOWN" and channel in _PROCESS:
        inspect = "inlet water temperature, load, suction level, valve position reading and instrument, then pump condition"
    if channel:
        inspect = f"{_CHANNEL_LABELS[channel]} ({channel}); {inspect}"
    provenance = _RULE_OUT.get(row["decided_by"])
    if provenance:
        rule_out = f"{rule_out}; {provenance}"
    result = f"Inspect: {inspect}. Do: {action}. Rule out first: {rule_out}."
    note = _NOTES.get(row["decided_by"])
    return f"{result} Note: {note}." if note else result


def recommend(alerts: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with only the recommended action replaced."""
    if "decided_by" not in alerts:
        raise ValueError("decided_by is required")
    if not alerts["decided_by"].isin(DECIDED_BY).all():
        raise ValueError("unknown decided_by value")
    result = alerts.copy()
    if not result.empty:
        result["recommended_action"] = [_action(row) for _, row in result.iterrows()]
    return result
