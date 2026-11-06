# Units

Simulation runs in SI units (m, s, kg, Pa, W, K). Displayed units in the tables:

| Unit | Meaning | Used in |
|---|---|---|
| % | percent | operating_context.duty_demand_pct, telemetry.valve_position_pct |
| A | ampere (RMS) | assets.motor_rated_current_a, telemetry.motor_current_a |
| Hz | hertz | assets.supply_frequency_hz |
| V | volt (line-to-line) | assets.supply_voltage_v |
| bitmask | integer bit flags | telemetry.quality_flags |
| g | standard gravity 9.80665 m/s2, RMS | telemetry.vibration_accel_rms_g |
| kPa(g) | kilopascal gauge (absolute = gauge + 101.3) | telemetry.discharge_pressure_kpa, telemetry.suction_pressure_kpa |
| kW | kilowatt | assets.motor_rated_kw, telemetry.motor_power_kw |
| m | meter (head or water column) | assets.design_head_m, assets.npsh3_at_bep_m, assets.pump_rated_head_m, assets.pump_shutoff_head_m, assets.static_head_m, operating_context.sea_state_hs_m ... |
| mm/s | millimeter per second, RMS 10-1000 Hz | assets.vibration_alarm_mm_s, assets.vibration_trip_mm_s, telemetry.vibration_rms_mm_s |
| m³/h | cubic meters per hour | assets.design_flow_m3_h, assets.pump_rated_flow_m3_h, telemetry.flow_m3_h |
| rpm | revolutions per minute | assets.motor_rated_rpm, telemetry.motor_speed_rpm |
| s | second | assets.wireless_update_s, telemetry.sample_interval_s |
| tag unit | unit of the alarmed tag | alarms.limit, alarms.value_at_raise |
| x running speed | order of shaft rotation frequency | assets.bearing_bpfi_order, assets.bearing_bpfo_order |
| year | calendar year | assets.commissioned_year |
| °C | degree Celsius | operating_context.ambient_temp_c, operating_context.sea_temp_c, operating_context.supply_water_temp_c, telemetry.ambient_temp_c, telemetry.bearing_temp_c, telemetry.fluid_temp_c ... |
