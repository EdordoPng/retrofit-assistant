# Data dictionary

Generated from `src/retrofit_sim/schema.py`, which is the same definition used to write `schema.json` and checked by the tests.

## `telemetry`

File: data/full/telemetry/asset_id=<ID>/day=<YYYY-MM-DD>/part-0.parquet (1 Hz); data/starter/telemetry.csv.gz (10 s)

| Column | Type | Unit | Nullable | Valid range / values | Description |
|---|---|---|---|---|---|
| `asset_id` | string | - | no |  | Stable asset identifier (PUMP-01 ... PUMP-12). |
| `timestamp_utc` | timestamp[ms, UTC] | - | no |  | Sample time, UTC. 1 s grid in the full tier, 10 s in the starter tier; rows are absent during gateway outages. |
| `operating_mode` | category | - | no | STOPPED, STARTING, RUNNING, STOPPING, LOCKED_OUT | PLC operating state of the pump drive (from the motor starter / drive status, not from the fault model). |
| `motor_speed_rpm` | float32 | rpm | yes | 0 .. 4000 | Motor speed reported by the variable-speed drive. NULL for fixed-speed (DOL) assets. |
| `motor_current_a` | float32 | A | yes | 0 .. 600 | Motor line current (RMS). Includes start-up inrush on direct-on-line assets. |
| `motor_power_kw` | float32 | kW | yes | 0 .. 200 | Electrical input power (drive or power meter). NULL where no power measurement exists. |
| `suction_pressure_kpa` | float32 | kPa(g) | yes | -100 .. 600 | Pump suction pressure, gauge. NULL on assets without a suction transmitter. |
| `discharge_pressure_kpa` | float32 | kPa(g) | yes | -100 .. 1600 | Pump discharge pressure, gauge. |
| `flow_m3_h` | float32 | m³/h | yes | 0 .. 1200 | Volumetric flow. NULL on assets without a flow meter. |
| `fluid_temp_c` | float32 | °C | yes | -20 .. 120 | Pumped-liquid temperature at the pump. |
| `bearing_temp_c` | float32 | °C | yes | -20 .. 150 | Pump drive-end bearing housing temperature. Sparse (every 300 s) on wireless retrofit sensors. |
| `motor_winding_temp_c` | float32 | °C | yes | -20 .. 200 | Motor stator winding temperature (PT100). Fully instrumented assets only. |
| `vibration_rms_mm_s` | float32 | mm/s | yes | 0 .. 50 | Overall vibration velocity RMS, 10-1000 Hz, pump bearing housing, radial. |
| `vibration_accel_rms_g` | float32 | g | yes | 0 .. 16 | Overall acceleration RMS (high-frequency band) from the same sensor. |
| `vibration_crest_factor` | float32 | - | yes | 1 .. 20 | Crest factor (peak/RMS) of the acceleration signal. |
| `ambient_temp_c` | float32 | °C | yes | -30 .. 70 | Machinery-space / pump-room air temperature (10 s update). |
| `valve_position_pct` | float32 | % | yes | 0 .. 100 | Control-valve position feedback (process / pressure-controlled loops only). |
| `quality_flags` | int16 | bitmask | no | 0 .. 31 | 1 COMM_LOSS, 2 OUT_OF_RANGE, 4 STALE, 8 BAD_SENSOR_STATUS, 16 STARTUP_INHIBIT (4 and 8 reserved, not set in this release). |
| `sensor_source` | string | - | no |  | Data sources present on the asset (PLC, VFD, WIRELESS, IOLINK, POWER_METER, FLOW_METER), separated by a pipe character. |
| `sample_interval_s` | int16 | s | no | 1 .. 10 | Nominal sampling interval of the row grid: 1 (full tier) or 10 (starter tier). |

## `assets`

File: data/*/assets.csv

| Column | Type | Unit | Nullable | Valid range / values | Description |
|---|---|---|---|---|---|
| `asset_id` | string | - | no |  | Asset identifier. |
| `split` | string | - | no | train, validation, test | Benchmark split. Test labels are not public. |
| `site` | string | - | no |  | Fictional site / vessel. |
| `system` | string | - | no |  | Duty within the site. |
| `profile` | string | - | no | SHIP_SW_COOLING, SHIP_LT_FRESHWATER, INDUSTRIAL_CW, PROCESS_TRANSFER | Equipment profile. |
| `control` | string | - | no | VFD_TEMPERATURE, VFD_PRESSURE, FLOW_VALVE, FIXED_SPEED | Capacity control method. |
| `instrumentation_tier` | string | - | no | T0_LEGACY, T1_RETROFIT, T2_FULL | Instrumentation level (see TECHNICAL_MODEL.md). |
| `window_start_utc` | timestamp | - | no |  | First timestamp of the asset's data window. |
| `window_end_utc` | timestamp | - | no |  | End (exclusive) of the data window. |
| `commissioned_year` | int | year | no | 1980 .. 2026 | Installation year. |
| `pump_rated_flow_m3_h` | float | m³/h | no |  | Best-efficiency-point flow at rated speed. |
| `pump_rated_head_m` | float | m | no |  | Best-efficiency-point head at rated speed. |
| `pump_shutoff_head_m` | float | m | no |  | Head at zero flow, rated speed. |
| `pump_bep_efficiency` | float | - | no | 0.5 .. 0.9 | Pump efficiency at BEP (nameplate / curve). |
| `npsh3_at_bep_m` | float | m | no |  | NPSH3 (3 % head drop) at BEP flow, rated speed. |
| `design_flow_m3_h` | float | m³/h | no |  | System design flow. |
| `design_head_m` | float | m | no |  | System design head. |
| `static_head_m` | float | m | no |  | Static head of the system curve (0 for closed loops). |
| `motor_rated_kw` | float | kW | no |  | Motor rated output. |
| `motor_rated_current_a` | float | A | no |  | Motor rated current (derived from nameplate). |
| `motor_rated_rpm` | float | rpm | no |  | Motor rated speed. |
| `supply_voltage_v` | float | V | no |  | Line voltage. |
| `supply_frequency_hz` | float | Hz | no | 50 .. 60 | Line frequency. |
| `min_speed_ratio` | float | - | yes | 0.3 .. 1.0 | Minimum drive speed (VFD assets). |
| `fluid` | string | - | no |  | Pumped liquid. |
| `bearing_designation` | string | - | no |  | Pump drive-end bearing (deep-groove ball bearing series). |
| `bearing_bpfo_order` | float | x running speed | no |  | Outer-race defect frequency order (computed from bearing geometry). |
| `bearing_bpfi_order` | float | x running speed | no |  | Inner-race defect frequency order. |
| `impeller_vanes` | int | - | no |  | Number of impeller vanes (vane-pass frequency = vanes x running speed). |
| `vibration_alarm_mm_s` | float | mm/s | yes |  | Configured vibration alarm (ISO 10816-7 category based). |
| `vibration_trip_mm_s` | float | mm/s | yes |  | Configured vibration trip / HIHI. |
| `channels_available` | string | - | no |  | Telemetry columns that carry data for this asset, separated by a pipe character. |
| `wireless_update_s` | int | s | yes |  | Update interval of battery wireless sensors (T1). |

## `events`

File: data/*/events_train.csv, data/*/events_validation.csv

| Column | Type | Unit | Nullable | Valid range / values | Description |
|---|---|---|---|---|---|
| `event_id` | string | - | no |  | Event identifier. |
| `asset_id` | string | - | no |  | Asset identifier. |
| `event_class` | string | - | no | MACHINE, SENSOR | True fault class. |
| `fault_type` | string | - | no |  | True fault type (see BENCHMARK_RULES.md taxonomy). |
| `onset_utc` | timestamp | - | no |  | Physical onset (clipped to window start for pre-existing conditions). |
| `pre_existing` | bool | - | no |  | Condition already present at window start. |
| `detectable_utc` | timestamp | - | yes |  | First time the effect exceeds 3 sigma of sensor noise on an instrumented channel (10-min mean). NULL = not observable with this asset's instrumentation. |
| `action_deadline_utc` | timestamp | - | yes |  | First time a conventional limit is reached while the fault is active (vibration alarm, cooling-flow shortfall, NPSH margin < 1.1). NULL if never reached in the window. |
| `end_utc` | timestamp | - | yes |  | Repair / resolution time. NULL = persists past window end. |
| `severity` | string | - | no | minor, moderate, severe | Peak severity within the window. |
| `evidence_channels` | string | - | yes |  | Instrumented channels that carried the earliest evidence, in order. |
| `observable` | bool | - | no |  | Whether the event is detectable with the asset's instruments (unobservable events are not scored). |
| `root_cause_event_id` | string | - | yes |  | Causing event for compound incidents. Process events that are not scored are written as TYPE:ID (PLANNED_MAINTENANCE:..., SUCTION_LEVEL_DROP:...); OPERATING_CONDITION when no fault caused it. |
| `sensor_tag` | string | - | yes |  | Affected telemetry column for instrument faults (GATEWAY for communication loss). |
| `label_confidence` | string | - | no | HIGH, MEDIUM | MEDIUM when the end time is not observed in the window or the episode is emergent. |

## `alarms`

File: data/*/alarms.csv

| Column | Type | Unit | Nullable | Valid range / values | Description |
|---|---|---|---|---|---|
| `asset_id` | string | - | no |  | Asset identifier. |
| `tag` | string | - | no |  | Alarmed telemetry column, INSTRUMENT or GATEWAY. |
| `alarm_type` | string | - | no | HI, HIHI, LO, BAD_QUALITY, COMM_LOSS | Alarm kind. |
| `priority` | int | - | no | 1 .. 3 | 1 = high. |
| `raised_utc` | timestamp | - | no |  | Alarm raised (after on-delay). |
| `cleared_utc` | timestamp | - | yes |  | Alarm returned to normal (after deadband). |
| `acknowledged_utc` | timestamp | - | yes |  | Operator acknowledgement (NULL = not acknowledged in time). |
| `value_at_raise` | float | tag unit | yes |  | Displayed value when raised. |
| `limit` | float | tag unit | yes |  | Configured limit. |

## `maintenance`

File: data/*/maintenance.csv

| Column | Type | Unit | Nullable | Valid range / values | Description |
|---|---|---|---|---|---|
| `record_id` | string | - | no |  | Work-order identifier. |
| `asset_id` | string | - | no |  | Asset identifier. |
| `work_type` | string | - | no |  | Intervention type. |
| `start_utc` | timestamp | - | no |  | Work start. |
| `end_utc` | timestamp | - | no |  | Work end. |
| `operator_observation` | string | - | no |  | Free-text observation as recorded (may contain a wrong suspicion). |
| `diagnosis_confidence` | string | - | no | CONFIRMED, PROBABLE, UNCERTAIN | Recorded confidence of the finding. |
| `planned` | bool | - | no |  | Planned (routine) or corrective work. |
| `in_window` | bool | - | no |  | Inside the telemetry window. |

## `operating_context`

File: data/*/operating_context.csv (1 min)

| Column | Type | Unit | Nullable | Valid range / values | Description |
|---|---|---|---|---|---|
| `asset_id` | string | - | no |  | Asset identifier. |
| `timestamp_utc` | timestamp | - | no |  | 1-min grid. |
| `schedule_state` | string | - | yes |  | Schedule / voyage state from the vessel or plant system (sea passage, port, production, batch, ...). |
| `duty_demand_pct` | float | % | no | 0 .. 120 | Heat-load / duty demand signal from the plant system. |
| `supply_water_temp_c` | float | °C | no |  | Inlet water temperature reported by the plant system (seawater, tower basin, LT loop or process tank). |
| `sea_temp_c` | float | °C | yes |  | Sea temperature at the sea chest (vessels only). |
| `ambient_temp_c` | float | °C | no |  | Space ambient temperature from the building / vessel automation. |
| `sea_state_hs_m` | float | m | yes |  | Significant wave height from the vessel's weather routing (vessels only). |
| `suction_static_head_m` | float | m | yes |  | Suction level / submergence where a level transmitter exists. |
| `controlled_setpoint` | string | - | yes |  | Control set-point description. |

## `predictions (submission format)`

File: your submission CSV (template: submission_template/predictions_template.csv)

| Column | Type | Unit | Nullable | Valid range / values | Description |
|---|---|---|---|---|---|
| `asset_id` | string | - | no |  | Asset the alert refers to. |
| `alert_time_utc` | timestamp ISO-8601 | - | no |  | Time the alert would have been raised (must only use data up to this time). |
| `event_class` | string | - | no | MACHINE, SENSOR | Predicted class: machine condition or instrument / data problem. |
| `fault_type` | string | - | no |  | Predicted fault type (taxonomy in BENCHMARK_RULES.md) or UNKNOWN. |
| `confidence` | float | - | no | 0 .. 1 | Model confidence. |
| `evidence` | string | - | yes |  | Short human-readable evidence (channels, deviations). |
| `recommended_action` | string | - | yes |  | Human-reviewable recommendation (inspection, maintenance, sensor check). |


## Other files

| File | Content |
|---|---|
| `data/full/features_1min.parquet` | One row per asset and minute (`window_start_utc`). For every telemetry channel that carries data: `<channel>__mean`, `__std`, `__min`, `__max`, `__count` (valid samples in the minute). Plus `operating_mode` (most frequent in the minute), `running_fraction`, `quality_any` (bitwise OR of quality flags) and `rows` (telemetry rows present; < 60 means missing rows). Minutes without any row (gateway outage) are absent. |
| `data/full/vibration_snapshots.parquet` | `asset_id`, `snapshot_id`, `timestamp_utc`, `sample_rate_hz` (10240), `n_samples` (10240), `axis` (radial), `unit` (g), `rpm_at_capture`, `samples` (list of float32 acceleration values, 1 s). Every 4 h while running, on assets with a vibration sensor (T1, T2). |
| `data/*/benign_windows_train_validation.csv` | `asset_id`, `benign_type` (STARTUP, SHUTDOWN, LOAD_CHANGE, SETPOINT_CHANGE, STANDBY_CHANGEOVER, PLANNED_STOP, MAINTENANCE_RESTART, HEAVY_WEATHER, VOLTAGE_SAG), `start_utc`, `end_utc`, `note`. Normal operation that looks abnormal. An alert here that matches no labeled event counts as a false (nuisance) alert. |
| `data/*/schema.json` | Machine-readable version of this dictionary. |
| `data/*/manifest.json` | File list with byte sizes and SHA-256, telemetry row counts per asset. |
| `data/full/provenance.md` | Generator version, seed and configuration hash for this build. |

## Conventions

- **Time.** All timestamps are UTC (ISO-8601 with `Z` or `+00:00`). Telemetry rows are on a 1 s grid (10 s in the starter tier). Rows are absent during gateway outages, and single values can be missing (NULL) because of sample drops or sparse sensors.
- **Pressures.** Gauge pressure in kPa(g). Absolute pressure = gauge + 101.3 kPa. 100 kPa = 1 bar.
- **NULL.** NULL means "not measured at this time" or "no such instrument on this asset". `assets.csv:channels_available` lists the instruments that exist.
- **Stopped pump.** While the pump is stopped, current, power and speed read about 0, the crest factor is NULL, and vibration reads background.
- **Parquet layout.** Telemetry is partitioned as `asset_id=<ID>/day=<date>/part-0.parquet`; `asset_id` and `day` are partition keys, not columns inside each file. `pandas.read_parquet('data/full/telemetry')` or `pandas.read_parquet('data/full/telemetry/asset_id=PUMP-01')` restores them as columns.
- **Identifiers.** IDs are stable across tiers. The starter tier uses the same assets, seeds and events as the full tier, resampled to 10 s: means for dense channels, the last value for sparse channels, and the OR of quality flags.
