# RETROFIT AI — Make Existing Machines Intelligent

**Since AI Hackathon 2026, Turku (6-8 Nov). Challenge owner: Business Turku. Technical sparring partner: Elomatic.**

All data in this package are **synthetic**, produced by a documented, reduced-order pump simulator for this challenge. None of it is a measurement from a ship, a factory, Elomatic or any person. New to pumps or condition monitoring? Open `START_HERE.html` in a browser first, and keep `GLOSSARY.md` at hand.

## The story

A cooling-water pump pushes water through heat exchangers to carry heat away from engines and machines. If it delivers too little water, equipment overheats. If it fails without warning, the ship or the production line has to slow down or stop.

A passenger ferry and a few Finnish plants run such pumps, 10-25 years old:

- some have nothing but motor current and a pressure gauge;
- some got a battery wireless vibration sensor last year;
- a few are fully instrumented.

Strainers clog with mussels in late summer, bearings wear out, a valve is left half-closed after maintenance, and a pressure transmitter starts to drift. Operators see an alarm only when a fixed limit is already crossed. Your task is to build the assistant that notices earlier, explains why, admits uncertainty and suggests what a human should check. It must not touch the machine.

## Objective

Detect developing machine and instrument problems on 12 simulated pumps, explain the evidence, and recommend human-reviewable actions. This is scored by an event-based benchmark (`BENCHMARK_RULES.md`) and judged on the official criteria (`CHALLENGE_BRIEF.md`).

Separating instrument faults from machine faults matters: a drifting gauge can trigger a needless repair or hide a real fault, so a good assistant says which one it believes it is seeing.

## Quick start (copy-paste)

```bash
python -m venv .venv
source .venv/bin/activate                               # Windows PowerShell: .venv\Scripts\Activate.ps1   cmd: .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python -m pip install -e . --no-deps                    # makes 'python -m retrofit_sim' available
python examples/quickstart.py                           # starter data: look, detect, score (about 1 min)
python baselines/run_baselines.py --data data/full --out my_results   # all baselines on the full data (about 1 min)
python -m pytest -q                                     # data and tool checks (about 1 min)
python -m retrofit_sim what_if --data data/full --asset PUMP-01 --time 2025-08-12T15:00:00Z --action speed_setpoint --value 0.72 --hypothesis clog=2.0
```

Use Python 3.10 or newer. Everything runs offline on a laptop. Notebook users can open `examples/01_quickstart.ipynb` (outputs included; to re-run it, `python -m pip install jupyter` and start Jupyter in `examples/`).

## What is in the box

| Path | Content |
|---|---|
| `START_HERE.html`, `START_HERE.md`, `GLOSSARY.md` | plain-language overview and glossary |
| `data/starter/` | 5 pumps, 10-s resolution, CSV.gz (about 300 k rows). Start here. |
| `data/full/telemetry/asset_id=*/day=*/` | 12 pumps x 7 days x 1-s rows, Parquet (about 7.2 M rows) |
| `data/full/features_1min.parquet` | 1-minute summaries (mean, std, min, max, count) per signal |
| `data/full/vibration_snapshots.parquet` | 1-s raw vibration recordings at 10.24 kHz, every 4 h (pumps with a vibration sensor) |
| `data/full/assets.csv` | pump and motor ratings, pump-curve values, bearing defect frequencies, instruments, split |
| `data/full/operating_context.csv` | schedule, cooling demand, inlet and sea temperature, sea state (1 min) |
| `data/full/alarms.csv`, `maintenance.csv` | plant alarms; work orders with operator notes |
| `data/full/events_train.csv`, `events_validation.csv` | labeled problems (test labels are held by the organizers) |
| `data/full/benign_windows_train_validation.csv` | start-ups, load changes, heavy weather and other normal-but-unusual periods |
| `src/retrofit_sim/` | simulator, dataset writer, scorer, baselines, what-if sandbox, replay |
| `baselines/` | reference baselines and their measured results |
| `examples/`, `figures/` | notebook, scripts and figures made from the data |
| `tests/` | executable checks of the data and tools |
| `make_dataset.py` | regenerates the data |

### Figures (made from the data)

| Figure | What it shows |
|---|---|
| `fig01_operating_envelopes.png` | how pumps with different control strategies operate |
| `fig02_clogging_to_cavitation_PUMP-06.png` | a clogging strainer that turns into cavitation |
| `fig03_bearing_wear_PUMP-04.png` | bearing wear: acceleration rises days before velocity and temperature |
| `fig04_sensor_vs_machine_PUMP-03.png` | a machine fault and a sensor fault with the same symptom on one channel |
| `fig05_season_speed_ship_SW.png` | how sea temperature and season drive the seawater pump speed |
| `fig06_operator_timeline_PUMP-08.png` | events, baseline alerts, plant alarms and work orders on one timeline |
| `fig07_snapshot_spectrum_PUMP-04.png` | a bearing defect in the vibration spectrum |

### Data tiers

| Tier | What it is | Command |
|---|---|---|
| starter | 5 pumps resampled to 10 s, CSV.gz; quick look and laptop-friendly | shipped in `data/starter/` |
| full | all 12 pumps at 1 s, Parquet, plus features and vibration snapshots | shipped in `data/full/` |
| stress | new random pumps (unseen ratings, seasons, missing sensors), only about 30 % of events labeled (`events_stress_labeled_subset.csv`); for testing how a model trained on the main data generalizes | `python make_dataset.py --tier stress --seed 7 --output build/stress` |

`python make_dataset.py --tier full --output build/full` regenerates the shipped train and validation data exactly.

## The pumps

| Split | Pumps | Mix |
|---|---|---|
| train | PUMP-01 ... 07 | ship seawater (variable speed), ship fresh-water loop (fixed speed), cooling-tower pumps, hot process pump; all three sensor levels |
| validation | PUMP-08, 09 | ship seawater (wireless retrofit), cooling-tower pump (full instrumentation) |
| test | PUMP-10, 11, 12 | unlabeled; a new vessel and a new plant; all three sensor levels |

Sensor levels (instrumentation tiers):

| Tier | Signals | Meaning |
|---|---|---|
| T0 legacy | motor current, discharge pressure, liquid and room temperature (+ drive speed and power if the pump has a variable-speed drive) | what old installations typically have |
| T1 retrofit | T0 + suction pressure + a battery wireless vibration and bearing-temperature sensor reporting every 5 min | a low-cost upgrade |
| T2 full | T1 at 1 s (wired vibration) + flow, electrical power, motor winding temperature, valve position | well instrumented |

Problems in the data: bearing wear, strainer clogging, cavitation, valve or heat-exchanger restriction, misalignment, imbalance, impeller wear, air entrainment, sensor drift, stuck sensors, calibration shifts, noisy signals and communication loss. Some events cannot be seen with legacy instruments, and the labels say so (`observable = False`).

## What a team can do

| Time | Realistic scope |
|---|---|
| 30 min | Run the quick start, plot one pump against its labeled events (`figures/` shows examples), read `START_HERE`, score the baseline on validation. |
| 4 h | Build a detector that takes the operating situation (speed, cooling demand, temperature) into account on the 1-min features. Separate sensor from machine faults. Write a validation prediction file and beat baseline B1. |
| 48-72 h | Pick from the list below. |

Options for 48-72 h:
- physics-informed checks: compare measured pressure, flow and power with what the pump curve says they should be at this speed;
- vibration snapshots: spectra that reveal bearing defects (`bearing_bpfo_order` in `assets.csv`);
- calibrated confidence;
- an operator interface that shows evidence and a recommendation;
- a live demo driven by `python -m retrofit_sim replay`;
- the sandbox what-if for the recommended action;
- an edge-device footprint, a retrofit bill of materials and pilot plan (`RETROFIT_FEASIBILITY.md`);
- honest limitations.

## What to build

- An assistant that a watchkeeper or maintenance planner would trust: early but not noisy, with an explanation and stated uncertainty.
- Recommendations a human approves: inspect, clean, re-align, recalibrate, plan a bearing change.
- Read-only integration that would fit existing operational technology: replay or MQTT-style messages, an edge box, no write path.

## What not to build

- No commands to real devices, PLCs, drives, valves, safety systems or ship systems.
- No controllers. The sandbox is for simulated what-if comparison only.
- No claims of certified safety, class approval, guaranteed fault identification or proven savings.
- Do not hand-label or tune on the test telemetry, and do not use future data when raising an alert (`BENCHMARK_RULES.md` §2).

## Baseline results (measured on this data)

The composite score runs from 0 to 100, and higher is better. It combines catching problems, catching them early, naming the right cause and avoiding false alerts (`BENCHMARK_RULES.md` §4). B0 is what the plant's own alarm list achieves today. B1 is the simple baseline to beat.

| Baseline | Validation composite | Event F1 | False + excess alerts / asset-day | Fault-type recall |
|---|---|---|---|---|
| B0_scada_alarms | 23.1 | 0.20 | 0.00 | 0.11 |
| B1_mode_aware_z | 78.0 | 0.89 | 0.07 | 0.44 |
| B2_cusum | 50.9 | 0.45 | 1.07 | 0.33 |
| B3_isolation_forest | 69.2 | 0.74 | 0.21 | 0.44 |

Measured by `baselines/run_baselines.py` (tuned on train only). Full table in `BENCHMARK_RULES.md` §5.

## Read next

`START_HERE.md` · `CHALLENGE_BRIEF.md` · `BENCHMARK_RULES.md` · `DATA_DICTIONARY.md` · `TECHNICAL_MODEL.md` · `RETROFIT_FEASIBILITY.md` · `GLOSSARY.md` · `LICENSE_AND_PROVENANCE.md`

Contact: Reetta Vuorinen, Business Turku, reetta.vuorinen@businessturku.fi
