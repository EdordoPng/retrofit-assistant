# Benchmark rules

This document covers the splits, the prediction task, the submission format, how alerts are scored, and the reference baselines. The scorer is `src/retrofit_sim/scoring.py`. The same code scores the public validation split for you and the hidden test split for the organizers.

## 1. Splits and integrity

| Split | Assets | Telemetry | Labels |
|---|---|---|---|
| train | PUMP-01 ... PUMP-07 | public | public (`events_train.csv`, benign windows, in-window maintenance log) |
| validation | PUMP-08, PUMP-09 | public | public (`events_validation.csv`) |
| test | PUMP-10, PUMP-11, PUMP-12 | public, unlabeled | organizers only |

- **Held-out assets.** The test pumps are different physical assets, and two of them are on a vessel and a plant that do not appear in train or validation.
- **No time overlap.** Each asset has its own 7-day window. Windows of different splits do not overlap in time, and no incident spans two splits.
- **Different randomness.** Test data come from a private configuration and a different seed, with different onset times and some combinations that are not in train or validation. For example, a drifting suction transmitter masks a clogging strainer.
- **Hidden records.** For test assets, the public maintenance log contains only routine history before the window. Work orders inside the window, labels and true states are private. Locked-out stops in the telemetry include routine planned work on every asset, so a lockout is not by itself a label.
- **Neutral identifiers.** Asset IDs, event IDs and file names do not encode labels.
- **Checks.** `tests/test_07_splits_leakage.py` checks disjointness and the absence of hidden labels in your copy. The organizers additionally scan the released archive.

## 2. Task

Build an operator-assist layer that, for each asset, raises **alerts** about developing machine or instrument problems. Each alert carries a class, a likely fault type, a confidence, evidence and a human-reviewable recommendation.

- **Causal operation (no peeking at future data).** An alert at time t may only use data with timestamps <= t, plus static information (`assets.csv`, profile documentation). Batch-processing the whole week is fine as long as each alert time respects this. The organizers may re-run finalists' code on test telemetry truncated at random cut points to confirm causality.
- **No tuning on test data.** Do not hand-label or tune on the test telemetry. Use train for fitting and validation for model selection.
- **Physics and context are allowed.** Using the pump-curve parameters in `assets.csv`, the simulator source code, or your own physics model is explicitly permitted. Reconstructing the hidden test configuration is not possible (private seed and scenario) and is not a goal.

### Fault taxonomy (`fault_type`)

| Class | Types |
|---|---|
| MACHINE | `BEARING_WEAR`, `SUCTION_STRAINER_CLOGGING`, `CAVITATION`, `DISCHARGE_RESTRICTION`, `MISALIGNMENT`, `IMBALANCE`, `IMPELLER_WEAR`, `AIR_ENTRAINMENT` |
| SENSOR | `SENSOR_DRIFT`, `SENSOR_STUCK`, `SENSOR_CALIBRATION_SHIFT`, `SENSOR_NOISE_SPIKES`, `COMMUNICATION_LOSS` |
| either | `UNKNOWN`: honest "something is wrong, cause unclear". It earns detection credit but no fault-type credit. |

## 3. Submission file

Submit a CSV in the format of `submission_template/predictions_template.csv`:

| Column | Required | Content |
|---|---|---|
| `asset_id` | yes | asset |
| `alert_time_utc` | yes | ISO-8601 UTC time the alert is raised |
| `event_class` | yes | `MACHINE` or `SENSOR` |
| `fault_type` | yes | taxonomy value or `UNKNOWN` |
| `confidence` | yes | 0-1 |
| `evidence` | no | short text: channels, deviations, context |
| `recommended_action` | no | inspection or maintenance recommendation for a human |

Submit one file for the test assets. Your validation file can be scored locally (after `python -m pip install -e . --no-deps`, see `README_FIRST.md`):

```
python -m retrofit_sim score --predictions my_validation.csv --events data/full/events_validation.csv --assets data/full/assets.csv --benign data/full/benign_windows_train_validation.csv --split validation
```

## 4. Scoring

**In plain words.** You raise alerts. An alert counts when it falls inside the time window of a real labeled problem on that pump. Earlier is better, especially before a conventional alarm limit would be reached. Naming the right cause earns more, and so does telling a sensor problem from a machine problem. False alerts and constant re-alerting cost points, and listing many guesses at once earns nothing extra.

### Definitions

- **Bursts.** Alerts on one asset that come less than 5 min after the first alert of a group are merged into that group (a burst). The burst is scored as a single alert at its first time. A burst that names more than one fault type earns no fault-type credit, and one that names both classes earns no class credit, so listing several guesses at once does not help.
- **Vocabulary.** `event_class` must be `MACHINE` or `SENSOR`, otherwise the file is rejected. A `fault_type` outside the taxonomy counts as an alert with no type credit.
- **Event window.** Starts at the later of the physical onset and the detectable time minus 6 h (the asset window start for pre-existing conditions). Alerts that are earlier than any instrument could show cannot match. The window ends:
  - at `end_utc` for machine faults that end with a repair. An alert raised after the pump is locked out for that repair is late, not a detection. Routine planned lockouts also occur on every asset, so a lockout alone does not reveal a repair.
  - at `end_utc` + 30 min for events that end without a repair: cavitation and air-entrainment episodes, and instrument faults.
  - at the asset window end for open-ended events.
- **Scored events.** Only labeled events with `observable = True`. Events that the asset's instruments cannot reveal are excluded: they are neither penalized when missed nor rewarded. Alerts and repeats that fall inside their windows are neutral.
- **Matching.** Each burst is assigned to at most one event whose window contains it. The preference order is: same fault type, then same class, then a not-yet-detected event, then the earliest onset.
- **Detection (true positive).** The first burst assigned to an event.
- **Repeats.** Later bursts on an already-detected event. A repeat starting within 30 min of the current repeat episode's start joins that episode. One reminder episode per 12 h is free. Further repeat episodes are **excess** and count like false alerts.
- **False alert.** A burst matched to no event. False alerts form 30-min episodes anchored at the episode's first alert, with no chaining: a steady stream of alerts produces one episode every 30 min. Those inside benign windows (start-up, load change, heavy weather, voltage sag, maintenance restart, ...) are also reported as nuisance alerts.
- **No-event periods.** Assets or periods without events earn nothing, and any alert there is a false alert.
- **Early warning.** A detection at or before the event's `action_deadline_utc`, which is when a conventional limit is reached (see `TECHNICAL_MODEL.md` §11).
- **Lead time.** Deadline minus the first alert, in hours. It is reported as a median over events that have a deadline.

### Metrics

| Metric | Definition |
|---|---|
| Event recall | detected scored events / scored events (also reported per class: machine and sensor) |
| Alert precision | TP / (TP + false-alert episodes + excess-repeat episodes), counted on bursts |
| Event F1 | harmonic mean of the two above |
| False + excess alerts per asset-day | (false-alert episodes + excess-repeat episodes) / asset-days; an asset-day is one pump for one day |
| Alert burden | max(0, 1 - (false + excess alerts per asset-day) / 2) |
| Timeliness | per event: 1 if the first alert is at or before the reference time (deadline, or detectable + 6 h when there is no deadline), decaying linearly to 0.1 at the window end; 0 if missed |
| Fault-type recall | share of scored events whose detecting alert names the correct `fault_type` |
| Class recall | share of scored events whose detecting alert names the correct class (machine vs sensor) |

**Composite technical score (0-100)**

= 100 x (0.35 F1 + 0.20 timeliness + 0.25 fault-type recall + 0.10 class recall + 0.10 alert burden)

Point-adjusted F1 is deliberately not used, because it rewards random detectors on long anomaly segments (Kim et al., AAAI 2022).

### How this relates to judging

The official challenge evaluation (`CHALLENGE_BRIEF.md`) is:

- business usefulness 25 %
- technical validity and measured performance 25 %
- reliability/safety 20 %
- low-cost retrofit feasibility and transfer 20 %
- working demo and clarity 10 %

The composite score is the measured-performance evidence for the technical criterion. It does not replace the jury's judgement of the other criteria. Explanation quality and honest uncertainty (for example correctly separating instrument faults from machine faults, or saying `UNKNOWN`) are part of reliability/safety.

## 5. Reference baselines (measured)

`baselines/run_baselines.py` tunes parameters on the **training split only** and evaluates on validation. It also writes test predictions in the submission format (`baselines/results/`).

| Baseline | Method |
|---|---|
| B0 SCADA alarms | the plant's existing fixed-limit alarm list used as the alert stream; it gives no diagnosis |
| B1 mode-aware z | per-asset robust baseline from the first 24 h of steady running, by speed regime; sustained deviation raises an alert; rule-based diagnosis from deviation patterns |
| B2 CUSUM | change-point detection on the same regime-normalized residuals |
| B3 Isolation Forest | trained on training-split minutes outside labeled event windows |

| Baseline | Split | Composite | Event F1 | Recall | Precision | False + excess alerts / asset-day | Timeliness | Fault-type recall | Class recall | Median lead to deadline (h) |
|---|---|---|---|---|---|---|---|---|---|---|
| B0_scada_alarms | train | 27.6 | 0.31 | 0.23 | 0.46 | 0.14 | 0.21 | 0.04 | 0.23 | -0.0 |
| B0_scada_alarms | validation | 23.1 | 0.20 | 0.11 | 1.00 | 0.00 | 0.11 | 0.11 | 0.11 | - |
| B1_mode_aware_z | train | 58.2 | 0.72 | 0.69 | 0.75 | 0.12 | 0.58 | 0.27 | 0.54 | 55.8 |
| B1_mode_aware_z | validation | 78.0 | 0.89 | 0.89 | 0.89 | 0.07 | 0.86 | 0.44 | 0.89 | 8.3 |
| B2_cusum | train | 53.3 | 0.48 | 0.88 | 0.33 | 0.94 | 0.81 | 0.27 | 0.81 | -0.1 |
| B2_cusum | validation | 50.9 | 0.45 | 0.78 | 0.32 | 1.07 | 0.77 | 0.33 | 0.67 | 13.6 |
| B3_isolation_forest | train | 39.4 | 0.47 | 0.42 | 0.52 | 0.20 | 0.41 | 0.08 | 0.38 | 108.9 |
| B3_isolation_forest | validation | 69.2 | 0.74 | 0.78 | 0.70 | 0.21 | 0.78 | 0.44 | 0.78 | 6.8 |

Validation has 2 assets and 9 scored events. Treat differences of a few points as noise, and use train and validation together when you compare methods. Median lead times are computed over the few events that have an action deadline and were caught before it, so they can swing widely (for example B3).

The baselines leave obvious room for improvement:

- diagnosis is rule-based and often wrong;
- detection is late for slow faults on variable-speed assets;
- there is no use of the pump curve, the vibration snapshots or uncertainty;
- every alert is treated as equally certain.
