"""Single source of truth for public table schemas (written to schema.json and DATA_DICTIONARY.md, checked by tests)."""
from __future__ import annotations

# column: (type, unit, nullable, valid_range or allowed values, description)
TELEMETRY = {
    "asset_id": ("string", "-", False, None, "Stable asset identifier (PUMP-01 ... PUMP-12)."),
    "timestamp_utc": ("timestamp[ms, UTC]", "-", False, None, "Sample time, UTC. 1 s grid in the full tier, 10 s in the starter tier; rows are absent during gateway outages."),
    "operating_mode": ("category", "-", False, ["STOPPED", "STARTING", "RUNNING", "STOPPING", "LOCKED_OUT"],
                       "PLC operating state of the pump drive (from the motor starter / drive status, not from the fault model)."),
    "motor_speed_rpm": ("float32", "rpm", True, [0, 4000], "Motor speed reported by the variable-speed drive. NULL for fixed-speed (DOL) assets."),
    "motor_current_a": ("float32", "A", True, [0, 600], "Motor line current (RMS). Includes start-up inrush on direct-on-line assets."),
    "motor_power_kw": ("float32", "kW", True, [0, 200], "Electrical input power (drive or power meter). NULL where no power measurement exists."),
    "suction_pressure_kpa": ("float32", "kPa(g)", True, [-100, 600], "Pump suction pressure, gauge. NULL on assets without a suction transmitter."),
    "discharge_pressure_kpa": ("float32", "kPa(g)", True, [-100, 1600], "Pump discharge pressure, gauge."),
    "flow_m3_h": ("float32", "m³/h", True, [0, 1200], "Volumetric flow. NULL on assets without a flow meter."),
    "fluid_temp_c": ("float32", "°C", True, [-20, 120], "Pumped-liquid temperature at the pump."),
    "bearing_temp_c": ("float32", "°C", True, [-20, 150], "Pump drive-end bearing housing temperature. Sparse (every 300 s) on wireless retrofit sensors."),
    "motor_winding_temp_c": ("float32", "°C", True, [-20, 200], "Motor stator winding temperature (PT100). Fully instrumented assets only."),
    "vibration_rms_mm_s": ("float32", "mm/s", True, [0, 50], "Overall vibration velocity RMS, 10-1000 Hz, pump bearing housing, radial."),
    "vibration_accel_rms_g": ("float32", "g", True, [0, 16], "Overall acceleration RMS (high-frequency band) from the same sensor."),
    "vibration_crest_factor": ("float32", "-", True, [1, 20], "Crest factor (peak/RMS) of the acceleration signal."),
    "ambient_temp_c": ("float32", "°C", True, [-30, 70], "Machinery-space / pump-room air temperature (10 s update)."),
    "valve_position_pct": ("float32", "%", True, [0, 100], "Control-valve position feedback (process / pressure-controlled loops only)."),
    "quality_flags": ("int16", "bitmask", False, [0, 31], "1 COMM_LOSS, 2 OUT_OF_RANGE, 4 STALE, 8 BAD_SENSOR_STATUS, 16 STARTUP_INHIBIT (4 and 8 reserved, not set in this release)."),
    "sensor_source": ("string", "-", False, None, "Data sources present on the asset (PLC, VFD, WIRELESS, IOLINK, POWER_METER, FLOW_METER), separated by a pipe character."),
    "sample_interval_s": ("int16", "s", False, [1, 10], "Nominal sampling interval of the row grid: 1 (full tier) or 10 (starter tier)."),
}

ASSETS = {
    "asset_id": ("string", "-", False, None, "Asset identifier."),
    "split": ("string", "-", False, ["train", "validation", "test"], "Benchmark split. Test labels are not public."),
    "site": ("string", "-", False, None, "Fictional site / vessel."),
    "system": ("string", "-", False, None, "Duty within the site."),
    "profile": ("string", "-", False, ["SHIP_SW_COOLING", "SHIP_LT_FRESHWATER", "INDUSTRIAL_CW", "PROCESS_TRANSFER"], "Equipment profile."),
    "control": ("string", "-", False, ["VFD_TEMPERATURE", "VFD_PRESSURE", "FLOW_VALVE", "FIXED_SPEED"], "Capacity control method."),
    "instrumentation_tier": ("string", "-", False, ["T0_LEGACY", "T1_RETROFIT", "T2_FULL"], "Instrumentation level (see TECHNICAL_MODEL.md)."),
    "window_start_utc": ("timestamp", "-", False, None, "First timestamp of the asset's data window."),
    "window_end_utc": ("timestamp", "-", False, None, "End (exclusive) of the data window."),
    "commissioned_year": ("int", "year", False, [1980, 2026], "Installation year."),
    "pump_rated_flow_m3_h": ("float", "m³/h", False, None, "Best-efficiency-point flow at rated speed."),
    "pump_rated_head_m": ("float", "m", False, None, "Best-efficiency-point head at rated speed."),
    "pump_shutoff_head_m": ("float", "m", False, None, "Head at zero flow, rated speed."),
    "pump_bep_efficiency": ("float", "-", False, [0.5, 0.9], "Pump efficiency at BEP (nameplate / curve)."),
    "npsh3_at_bep_m": ("float", "m", False, None, "NPSH3 (3 % head drop) at BEP flow, rated speed."),
    "design_flow_m3_h": ("float", "m³/h", False, None, "System design flow."),
    "design_head_m": ("float", "m", False, None, "System design head."),
    "static_head_m": ("float", "m", False, None, "Static head of the system curve (0 for closed loops)."),
    "motor_rated_kw": ("float", "kW", False, None, "Motor rated output."),
    "motor_rated_current_a": ("float", "A", False, None, "Motor rated current (derived from nameplate)."),
    "motor_rated_rpm": ("float", "rpm", False, None, "Motor rated speed."),
    "supply_voltage_v": ("float", "V", False, None, "Line voltage."),
    "supply_frequency_hz": ("float", "Hz", False, [50, 60], "Line frequency."),
    "min_speed_ratio": ("float", "-", True, [0.3, 1.0], "Minimum drive speed (VFD assets)."),
    "fluid": ("string", "-", False, None, "Pumped liquid."),
    "bearing_designation": ("string", "-", False, None, "Pump drive-end bearing (deep-groove ball bearing series)."),
    "bearing_bpfo_order": ("float", "x running speed", False, None, "Outer-race defect frequency order (computed from bearing geometry)."),
    "bearing_bpfi_order": ("float", "x running speed", False, None, "Inner-race defect frequency order."),
    "impeller_vanes": ("int", "-", False, None, "Number of impeller vanes (vane-pass frequency = vanes x running speed)."),
    "vibration_alarm_mm_s": ("float", "mm/s", True, None, "Configured vibration alarm (ISO 10816-7 category based)."),
    "vibration_trip_mm_s": ("float", "mm/s", True, None, "Configured vibration trip / HIHI."),
    "channels_available": ("string", "-", False, None, "Telemetry columns that carry data for this asset, separated by a pipe character."),
    "wireless_update_s": ("int", "s", True, None, "Update interval of battery wireless sensors (T1)."),
}

EVENTS = {
    "event_id": ("string", "-", False, None, "Event identifier."),
    "asset_id": ("string", "-", False, None, "Asset identifier."),
    "event_class": ("string", "-", False, ["MACHINE", "SENSOR"], "True fault class."),
    "fault_type": ("string", "-", False, None, "True fault type (see BENCHMARK_RULES.md taxonomy)."),
    "onset_utc": ("timestamp", "-", False, None, "Physical onset (clipped to window start for pre-existing conditions)."),
    "pre_existing": ("bool", "-", False, None, "Condition already present at window start."),
    "detectable_utc": ("timestamp", "-", True, None, "First time the effect exceeds 3 sigma of sensor noise on an instrumented channel (10-min mean). NULL = not observable with this asset's instrumentation."),
    "action_deadline_utc": ("timestamp", "-", True, None, "First time a conventional limit is reached while the fault is active (vibration alarm, cooling-flow shortfall, NPSH margin < 1.1). NULL if never reached in the window."),
    "end_utc": ("timestamp", "-", True, None, "Repair / resolution time. NULL = persists past window end."),
    "severity": ("string", "-", False, ["minor", "moderate", "severe"], "Peak severity within the window."),
    "evidence_channels": ("string", "-", True, None, "Instrumented channels that carried the earliest evidence, in order."),
    "observable": ("bool", "-", False, None, "Whether the event is detectable with the asset's instruments (unobservable events are not scored)."),
    "root_cause_event_id": ("string", "-", True, None, "Causing event for compound incidents. Process events that are not scored are written as TYPE:ID (PLANNED_MAINTENANCE:..., SUCTION_LEVEL_DROP:...); OPERATING_CONDITION when no fault caused it."),
    "sensor_tag": ("string", "-", True, None, "Affected telemetry column for instrument faults (GATEWAY for communication loss)."),
    "label_confidence": ("string", "-", False, ["HIGH", "MEDIUM"], "MEDIUM when the end time is not observed in the window or the episode is emergent."),
}

ALARMS = {
    "asset_id": ("string", "-", False, None, "Asset identifier."),
    "tag": ("string", "-", False, None, "Alarmed telemetry column, INSTRUMENT or GATEWAY."),
    "alarm_type": ("string", "-", False, ["HI", "HIHI", "LO", "BAD_QUALITY", "COMM_LOSS"], "Alarm kind."),
    "priority": ("int", "-", False, [1, 3], "1 = high."),
    "raised_utc": ("timestamp", "-", False, None, "Alarm raised (after on-delay)."),
    "cleared_utc": ("timestamp", "-", True, None, "Alarm returned to normal (after deadband)."),
    "acknowledged_utc": ("timestamp", "-", True, None, "Operator acknowledgement (NULL = not acknowledged in time)."),
    "value_at_raise": ("float", "tag unit", True, None, "Displayed value when raised."),
    "limit": ("float", "tag unit", True, None, "Configured limit."),
}

MAINTENANCE = {
    "record_id": ("string", "-", False, None, "Work-order identifier."),
    "asset_id": ("string", "-", False, None, "Asset identifier."),
    "work_type": ("string", "-", False, None, "Intervention type."),
    "start_utc": ("timestamp", "-", False, None, "Work start."),
    "end_utc": ("timestamp", "-", False, None, "Work end."),
    "operator_observation": ("string", "-", False, None, "Free-text observation as recorded (may contain a wrong suspicion)."),
    "diagnosis_confidence": ("string", "-", False, ["CONFIRMED", "PROBABLE", "UNCERTAIN"], "Recorded confidence of the finding."),
    "planned": ("bool", "-", False, None, "Planned (routine) or corrective work."),
    "in_window": ("bool", "-", False, None, "Inside the telemetry window."),
}

CONTEXT = {
    "asset_id": ("string", "-", False, None, "Asset identifier."),
    "timestamp_utc": ("timestamp", "-", False, None, "1-min grid."),
    "schedule_state": ("string", "-", True, None, "Schedule / voyage state from the vessel or plant system (sea passage, port, production, batch, ...)."),
    "duty_demand_pct": ("float", "%", False, [0, 120], "Heat-load / duty demand signal from the plant system."),
    "supply_water_temp_c": ("float", "°C", False, None, "Inlet water temperature reported by the plant system (seawater, tower basin, LT loop or process tank)."),
    "sea_temp_c": ("float", "°C", True, None, "Sea temperature at the sea chest (vessels only)."),
    "ambient_temp_c": ("float", "°C", False, None, "Space ambient temperature from the building / vessel automation."),
    "sea_state_hs_m": ("float", "m", True, None, "Significant wave height from the vessel's weather routing (vessels only)."),
    "suction_static_head_m": ("float", "m", True, None, "Suction level / submergence where a level transmitter exists."),
    "controlled_setpoint": ("string", "-", True, None, "Control set-point description."),
}

TABLES = {"telemetry": TELEMETRY, "assets": ASSETS, "events": EVENTS, "alarms": ALARMS, "maintenance": MAINTENANCE,
          "operating_context": CONTEXT}

PREDICTION_SCHEMA = {
    "asset_id": ("string", "-", False, None, "Asset the alert refers to."),
    "alert_time_utc": ("timestamp ISO-8601", "-", False, None, "Time the alert would have been raised (must only use data up to this time)."),
    "event_class": ("string", "-", False, ["MACHINE", "SENSOR"], "Predicted class: machine condition or instrument / data problem."),
    "fault_type": ("string", "-", False, None, "Predicted fault type (taxonomy in BENCHMARK_RULES.md) or UNKNOWN."),
    "confidence": ("float", "-", False, [0, 1], "Model confidence."),
    "evidence": ("string", "-", True, None, "Short human-readable evidence (channels, deviations)."),
    "recommended_action": ("string", "-", True, None, "Human-reviewable recommendation (inspection, maintenance, sensor check)."),
}


def to_json_schema() -> dict:
    out = {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "RETROFIT AI 2026 dataset tables", "tables": {}}
    for name, cols in list(TABLES.items()) + [("predictions", PREDICTION_SCHEMA)]:
        out["tables"][name] = {c: {"type": t, "unit": u, "nullable": nl, **({"valid": v} if v is not None else {}), "description": d}
                               for c, (t, u, nl, v, d) in cols.items()}
    return out
