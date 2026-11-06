# Glossary

Plain-language definitions of the terms used in this package, grouped by topic and alphabetical within each group.

## Pumps and hydraulics

| Term | Meaning |
|---|---|
| **Affinity laws** | Rules of thumb for centrifugal pumps when speed changes: flow ∝ speed, head ∝ speed², power ∝ speed³. Slowing a pump to 80 % speed cuts power to about half. |
| **Air entrainment** | Air or gas bubbles drawn into the pump (e.g. sea-chest aeration in heavy weather, a vortex at low tank level). Reduces head and makes vibration erratic. |
| **BEP (best efficiency point)** | The flow and head at which a pump runs most efficiently. Running far from BEP wastes energy and increases wear. |
| **Cavitation** | Vapor bubbles form where pressure at the pump inlet drops below the liquid's vapor pressure and then collapse violently. Causes noise, vibration, lost head and impeller erosion. Here it is a simplified model, not a fluid-dynamics simulation. |
| **Centrifugal pump** | A pump that moves liquid with a spinning impeller. The most common pump type for cooling water. |
| **Cooling-tower water** | Water cooled by evaporation in a tower and pumped through the heat exchangers of a plant. |
| **Discharge pressure** | Pressure on the outlet side of the pump. |
| **Duty / demand** | How much cooling the plant or ship needs at a given moment, here 0-100 % (`duty_demand_pct`). |
| **Head (m)** | The energy a pump adds to the liquid, expressed as the height of a water column it could lift. 10 m of water is about 1 bar. |
| **Heat exchanger (HX), central cooler** | Device that transfers heat between two water circuits without mixing them, e.g. ship fresh water to seawater. Fouling inside it increases flow resistance. |
| **Impeller, impeller / wear-ring wear** | The rotating part of the pump. Wear opens internal clearances, so the pump delivers less head at the same flow. |
| **LT fresh-water loop** | On a ship, the closed low-temperature circuit that carries engine and equipment heat to the central cooler. |
| **NPSH (net positive suction head)** | How far the pressure at the pump inlet is above the liquid's vapor pressure, in meters. NPSHa is what the system provides, NPSH3 is what the pump needs (the point where head drops 3 %). When NPSHa approaches NPSH3, cavitation starts. |
| **Operating point** | Where the pump curve (what the pump can deliver) crosses the system curve (what the piping resists). This sets the actual flow and head. |
| **Pump curve** | Head versus flow for a pump at a given speed. Head falls as flow rises. |
| **Restriction** | Extra resistance in the circuit, for example a valve left partly closed or a fouled heat exchanger. |
| **Seawater (SW) cooling pump** | On a ship, the pump that takes seawater from the sea chest, passes it through the central cooler and discharges it overboard. |
| **Sea chest** | Opening in the hull, below the waterline, through which seawater enters. |
| **Strainer (suction strainer)** | A filter in front of the pump that catches debris, mussels and similar. When it clogs, suction pressure and flow fall. |
| **Suction pressure** | Pressure on the inlet side of the pump. |
| **System curve** | Resistance of the piping: static lift plus friction that grows with flow². |

## Motors, drives and control

| Term | Meaning |
|---|---|
| **Control valve / valve position** | A valve that a controller opens or closes to set the flow, reported 0-100 %. |
| **DOL (direct-on-line), fixed speed** | The motor is switched straight onto the supply and always runs at full speed. Starting draws 6-7 x rated current for a few seconds. |
| **Inrush current** | The short current peak when a direct-on-line motor starts. Normal, not a fault. |
| **Motor current (A), power (kW)** | Electrical measures from the motor starter, drive or power meter. Power rises with pump load. Current also includes a no-load magnetising part. |
| **Power factor** | Ratio of real to apparent electrical power. Lower at light motor load. |
| **Slip** | How much slower an induction motor turns than the rotating magnetic field, about 1-2.5 % at full load. |
| **VFD (variable-frequency drive)** | Electronic drive that changes motor speed. Here it is used to hold a temperature or a pressure set-point. |
| **Winding temperature** | Temperature inside the motor stator. |

## Vibration and condition monitoring

| Term | Meaning |
|---|---|
| **Acceleration RMS (g)** | High-frequency vibration level. It rises early when a rolling bearing starts to get damaged. |
| **Bearing wear** | Progressive damage of a rolling-element bearing: first visible in high-frequency acceleration, later in velocity and temperature. |
| **BPFO / BPFI** | Ball-pass frequencies of the outer and inner race, in multiples of running speed, where a damaged bearing produces repeating impacts. Listed per pump in `assets.csv`. |
| **Condition monitoring** | Measuring machine health (vibration, temperature, performance) to plan maintenance before failure. |
| **Crest factor** | Peak of the vibration signal divided by its RMS. It rises with early, localized bearing damage (impacts), then falls again as damage spreads. |
| **Envelope spectrum** | A signal-processing view that reveals repeating impacts (such as bearing defects) in a vibration waveform. |
| **Imbalance (unbalance)** | Uneven mass on the rotor, e.g. deposits on the impeller. It gives vibration at 1 x running speed that grows with speed². |
| **ISO 10816-7 / ISO 20816-3** | International standards that classify vibration severity of pumps and machines into zones (A good ... D damaging) and guide alarm and trip levels. |
| **Misalignment** | Pump and motor shafts not in line, often after maintenance. It gives vibration at 1x and 2x running speed and warmer bearings. |
| **Velocity RMS (mm/s)** | The standard overall vibration value (10-1000 Hz). Typical healthy pumps sit at about 1-3 mm/s. |
| **Waveform snapshot** | A short raw vibration recording (here 1 s at 10,240 samples/s) for frequency analysis. |

## Automation, data and integration

| Term | Meaning |
|---|---|
| **4-20 mA, Modbus, IO-Link, OPC UA, MQTT** | Common industrial ways to transmit measurements: analog current loop, serial or Ethernet register protocol, smart-sensor link, industrial data model protocol, publish/subscribe messaging. |
| **Alarm (HI, HIHI, LO), trip** | A fixed limit in the control system that warns the operator (alarm) or stops the machine (trip). Alarms come late by design, which is the gap this challenge targets. |
| **Edge device** | A small industrial computer next to the machine that runs analytics locally. |
| **Gateway outage, communication loss** | Data stop arriving, so rows or values are missing. It is an instrument problem, not a machine fault. |
| **Instrumentation tier T0 / T1 / T2** | How well a pump is measured here. T0 legacy: current, discharge pressure, temperatures. T1 low-cost retrofit: adds suction pressure and a battery wireless vibration and temperature sensor (one value every 5 min). T2 full: adds flow, power, winding temperature, valve feedback and 1-s wired vibration. |
| **Locked out (LOCKED_OUT)** | The pump is isolated for maintenance and cannot be started. |
| **PLC** | Programmable logic controller: the industrial computer that runs the machine's control logic. |
| **Quality flags** | Bit flags on each telemetry row, for example communication loss or out of range (see `DATA_DICTIONARY.md`). |
| **Read-only integration** | Reading data from the plant without any ability to write commands back. Required in this challenge. |
| **SCADA** | Supervisory control and data acquisition: the operator screens, alarms and historian of a plant or ship. |
| **Sensor drift, stuck sensor, calibration shift, noise / spikes** | Instrument faults: the reading slowly walks away from the truth, freezes, jumps by a constant offset, or becomes noisy. The machine itself is fine. |
| **Telemetry** | The time series of measurements (here one row per second per pump). |

## Benchmark and scoring

| Term | Meaning |
|---|---|
| **Action deadline** | When a conventional limit would be reached, e.g. the vibration alarm or a cooling-flow shortfall. Alerts before it are early warnings. |
| **Alert** | Your system's notice that something is developing on an asset, with class, fault type, confidence, evidence and recommended action. |
| **Benign window** | A normal situation that looks unusual: start-up, load change, heavy weather, voltage dip, maintenance restart. Alerts here are nuisance alerts. |
| **Composite score** | The 0-100 measured-performance score: detection F1, timeliness, diagnosis and alert burden combined (`BENCHMARK_RULES.md`). |
| **Detectable time** | The first moment the fault's effect rises above sensor noise on the pump's instruments. |
| **Event** | A labeled problem with onset, end, type and severity. |
| **Lead time** | Hours between your first alert and the action deadline. |
| **Observable** | Whether a fault can be seen at all with the pump's instruments. Unobservable faults are not scored. |
| **Precision, recall, F1** | Precision is the share of your alerts that were about real events. Recall is the share of real events you caught. F1 is their harmonic mean. |
| **Synthetic data** | Data produced by a simulator, not measured on real equipment. Everything in this package is synthetic. |
| **Train / validation / test split** | Train: labeled data to learn from. Validation: labeled data to check your method. Test: unlabeled data on which you are scored by the organizers. |
