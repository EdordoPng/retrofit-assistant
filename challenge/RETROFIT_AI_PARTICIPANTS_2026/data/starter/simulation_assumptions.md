# Simulation assumptions

Profile defaults used by the generator (from `configs/fleet_public.yaml`). Equations, fault models and limits are in `TECHNICAL_MODEL.md`. Values are engineering assumptions chosen to be consistent with the references in `LICENSE_AND_PROVENANCE.md`; they do not describe any real installation.

| Parameter | SHIP_SW_COOLING | SHIP_LT_FRESHWATER | INDUSTRIAL_CW | PROCESS_TRANSFER |
|---|---|---|---|---|
| `control` | VFD_TEMPERATURE | FIXED_SPEED | VFD_PRESSURE | FLOW_VALVE |
| `voltage_v` | 440 | 440 | 400 | 400 |
| `supply_hz` | 60 | 60 | 50 | 50 |
| `h0_shutoff_ratio` | 1.22 | 1.2 | 1.2 | 1.18 |
| `system_static_m` | 3.0 | 0.0 | 7.0 | 8.0 |
| `loop_pressurisation_kpa` | - | 120.0 | - | - |
| `suction_loss_m_at_design` | 0.9 | 0.6 | 0.7 | 0.5 |
| `strainer_share` | 0.65 | 0.5 | 0.6 | 0.7 |
| `valve_share_of_K` | 0.15 | 0.2 | 0.3 | 0.35 |
| `design_supply_temp_c` | 25.0 | - | - | - |
| `controlled_temp_setpoint_c` | 36.0 | - | - | - |
| `loop_temp_c` | - | 34.0 | - | - |
| `min_flow_frac` | 0.4 | - | - | - |
| `r_min` | 0.5 | - | 0.55 | - |
| `speed_tau_s` | 25.0 | - | 15.0 | - |
| `startup_ramp_s` | 12.0 | 4.0 | 10.0 | 3.0 |
| `bearing_rise_k` | 24.0 | 22.0 | 24.0 | 26.0 |
| `bearing_tau_s` | 1500.0 | 1500.0 | 1500.0 | 1100.0 |
| `winding_rise_k` | 70.0 | 72.0 | 72.0 | 75.0 |
| `winding_tau_s` | 2400.0 | 2400.0 | 2400.0 | 1500.0 |
| `wireless_update_s` | 300 | 300 | 300 | 300 |

Context parameters per profile:

- **SHIP_SW_COOLING**: `sea_leg_h`=10.5, `manoeuvre_h`=0.6, `port_h`=1.4, `demand_sea`=0.88, `demand_manoeuvre`=0.62, `demand_port`=0.38, `engine_room_c`=36.0, `sea_chest_submergence_m`=4.8, `standby_prob`=0.5, `storm_prob`=0.5, `startup_s`=12, `shutdown_s`=15
- **SHIP_LT_FRESHWATER**: `sea_leg_h`=10.5, `manoeuvre_h`=0.6, `port_h`=1.4, `demand_sea`=0.9, `demand_manoeuvre`=0.65, `demand_port`=0.4, `engine_room_c`=36.0, `sea_chest_submergence_m`=4.8, `standby_prob`=0.4, `storm_prob`=0.4, `startup_s`=6, `shutdown_s`=12
- **INDUSTRIAL_CW**: `shift_hours`=[6, 22], `demand_shift`=0.9, `demand_night`=0.55, `demand_weekend`=0.45, `hall_c`=22.0, `suction_static_m`=2.5, `stop_prob`=0.5, `startup_s`=10, `shutdown_s`=10
- **PROCESS_TRANSFER**: `run_h`=[1.0, 4.0], `idle_h`=[0.2, 1.5], `setpoints`=[0.6, 0.75, 0.9, 1.0], `process_temp_c`=62.0, `hall_c`=26.0, `suction_static_m`=2.2, `startup_s`=4, `shutdown_s`=6

Common assumptions:

- 1 s simulation step; quasi-steady hydraulics; first-order thermal and transmitter lags.
- Alarm limits: ISO 10816-7 category-based vibration alarm and trip; bearing 85/95 °C; winding 140 °C; process limits set from the healthy envelope of each installed system, as at commissioning.
- Instrument faults affect the monitoring copy of a signal only; control loops use their own transmitters.
- Fault growth is compressed into 7-day windows for benchmark purposes.
