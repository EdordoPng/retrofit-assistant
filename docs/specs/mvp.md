# MVP operator-assist layer

Status: Approved on 2026-11-06
Related decisions: 0001-mvp-direction (with Amendment 2026-11-06), 0002-stack

## Goal
Turn the accepted direction into a working, causal alert system for the RETROFIT AI submission. An
operator gets one human-reviewable alert per developing problem, with evidence, confidence and a
recommended action. A valid test submission must exist from Saturday 12:00 and be regenerated at
each milestone.

## Out of scope
- LLM features of any kind.
- A server or interactive UI. The report is static HTML.
- Stress data for tuning. A generalisation check needs the owner's explicit approval on Saturday
  evening, and is not part of this spec.
- ML classifiers.
- Writing to devices, PLCs, drives or valves, or any control command.
- Changes under `challenge/`.
- Any look at test-asset output beyond format validity.
- Reminders in the submission.

## Requirements
- R1: every alert at time t depends only on data available by t and on `assets.csv`.
- R2: runtime uses only permitted inputs and stays advisory.
- R3: alerts follow BENCHMARK_RULES §3-4 and form a valid submission for any split.
- R4: every result is measured on train and validation against declared B1 and causal B1.
- R5: diagnosis separates sensor from machine faults and can name all taxonomy types.
- R6: physics and spectral checks adapt to the channels each asset has.
- R7: one CLI command produces a static HTML report for a train or validation pump.
- R8: the value of each instrumentation tier and the reliability of confidence levels are reported
  from measurements.
- R9: the repository stays reproducible, and the official package stays untouched.

## Acceptance criteria
Run from the repo root after `source .venv/bin/activate` and
`D=challenge/RETROFIT_AI_PARTICIPANTS_2026/data/full`.

- [ ] C1 (R1): given PUMP-01..09, seeded random cuts, deterministic cuts just before and just after
  a minute boundary, and a cut at an hourly baseline refresh, when the pipeline runs on input
  truncated at each cut with every intermediate recomputed from scratch, then alerts up to the cut
  equal those of the full run in every column.
  Verify: `python -m pytest -q tests/test_causality.py`
  Final check, pass/fail only, in P3-3:
  `RETROFIT_CAUSALITY_ASSETS=PUMP-10,PUMP-11,PUMP-12 python -m pytest -q tests/test_causality.py`
- [ ] C2 (R1): given the hourly estimator, when z-scores are computed, then a short prefix matches
  values calculated by hand, including the regime fallback and the minimum sample rule, and minutes
  from t0 + 24 h onward equal the published B1 z-scores.
  Verify: `python -m pytest -q tests/test_causal_b1.py`
- [ ] C3 (R2): given any detection module, when it is inspected and run, then it reads inputs only
  through the availability table, joins only backward as-of, and cannot read events, benign windows
  or maintenance rows with `in_window = True`. Backward fill, nearest joins, forward joins, future
  interpolation and centered windows fail the test.
  Verify: `python -m pytest -q tests/test_boundaries.py -k runtime_inputs`
- [ ] C4 (R2): given the package source, when imports are scanned, then no network, fieldbus or
  device-write module is imported.
  Verify: `python -m pytest -q tests/test_boundaries.py -k advisory_only`
- [ ] C5 (R3): given the validation split, when causal B1 predictions are written, then the official
  scorer accepts the file and reports a composite score.
  Verify: `python -m retrofit_assistant predict --data $D --split validation --detector causal_b1 --out build/predictions/causal_b1_validation.csv && python -m retrofit_sim score --predictions build/predictions/causal_b1_validation.csv --events $D/events_validation.csv --assets $D/assets.csv --benign $D/benign_windows_train_validation.csv --split validation`
- [ ] C6 (R3): given a prediction file, when it is validated, then columns, vocabulary, finite
  confidence in [0, 1], UTC timestamps, alert time >= asset window start + 60 s and alert time
  before the exclusive window end are all enforced. Synthetic malformed files fail. A header-only
  file fails without a crash, with the message `0 alerts – likely pipeline error`. On test, the check prints only PASS or FAIL and the
  failed rule, never row content.
  Verify: `python -m pytest -q tests/test_output.py && python -m retrofit_assistant predict --data $D --split test --out build/submission/predictions_test.csv && python -m retrofit_assistant check-submission --predictions build/submission/predictions_test.csv --data $D --split test`
- [ ] C7 (R3): given crafted alert streams, when the policy is applied, then:
  - each alert has one type and one class, and alerts on one pump are at least 6 min apart;
  - an emitted alert is never revised;
  - each condition raises one alert, and no reminder is emitted;
  - a stop or lockout clears pending evidence, and evaluation restarts fresh after restart;
  - official-scorer fixtures cover mixed types and classes, the 5-min boundary, and UNKNOWN followed
    by a correct diagnosis.
  Verify: `python -m pytest -q tests/test_policy.py`
- [ ] C8 (R4): given train and validation, when the comparison runs, then a table reports all
  composite metrics for the pipeline, causal B1 and declared B1 (58.2 and 78.0), and the prediction
  files are written as `build/predictions/<detector>_<split>.csv`.
  Verify: `python -m retrofit_assistant compare --data $D --out build/scores/compare.md`
- [ ] C9 (R4): given the frozen pipeline, when the gate runs, then it exits 0 only if the composite
  beats causal B1 on both train and validation. The gate decides whether a change is kept during
  development. It never blocks generating the submission.
  Verify: `python -m retrofit_assistant compare --data $D --out build/scores/compare.md --gate`
- [ ] C10 (R5): given synthetic minute frames for each signature, when diagnosis runs, then it
  returns the expected type, including SENSOR_DRIFT and AIR_ENTRAINMENT, and separates step from
  ramp.
  Verify: `python -m pytest -q tests/test_diagnosis.py`
- [ ] C11 (R5): given a detection, when the watch state runs, then rotating, slow hydraulic and
  instrument faults wait for confidence or their family budget. CAVITATION, AIR_ENTRAINMENT,
  SENSOR_STUCK and COMMUNICATION_LOSS alert at once. UNKNOWN appears only at budget expiry. Benign
  context holds and re-checks, and never drops an alert.
  Verify: `python -m pytest -q tests/test_watch.py`
- [ ] C12 (R6): given assets with T0, T1 and T2 channels, when physics checks run, then each check
  whose channels are missing is disabled with no error and no alert.
  Verify: `python -m pytest -q tests/test_physics.py`
- [ ] C13 (R6): given a synthetic snapshot with known tones and a known `rpm_at_capture`, when
  spectra run, then BPFO, 1x and 2x levels are recovered.
  Verify: `python -m pytest -q tests/test_spectra.py`
- [ ] C14 (R7): given a validation pump, when the report runs, then one self-contained HTML file is
  written with a timeline, alert markers and alert cards, with no external resource and no script.
  A test asset is refused with a non-zero exit.
  Verify: `python -m retrofit_assistant report --asset PUMP-08 --data $D --predictions build/predictions/full_validation.csv --out build/report/ && python -m pytest -q tests/test_report.py`
- [ ] C15 (R8): given T2 assets with channels masked to T1 and T0, when ablation runs, then a table
  reports the score per tier. It may be reduced to one T2 pump under the cut order.
  Verify: `python -m retrofit_assistant ablate --data $D --out build/scores/ablation.md`
- [ ] C16 (R8): given train and validation alerts, when confidence levels are built, then each level
  has an observed hit rate and sample size. No test data is used, and runtime is a table lookup.
  Verify: `python -m pytest -q tests/test_confidence.py`
- [ ] C17 (R9): given the final tree, when the suite runs, then all tests pass and `challenge/` is
  unchanged.
  Verify: `python -m pytest -q tests && test -z "$(git status --short challenge)"`
- [ ] C18 (R9): given a fresh install, when the smoke gate runs, then `features_1min.parquet` loads
  with a UTC-aware `window_start_utc`, and the official scorer returns 78.0 on the published B1
  validation predictions.
  Verify: `python -m pytest -q tests/test_smoke.py`
- [ ] C19 (R9): given the freeze, when the official tests run once on their own, then they pass.
  Verify: `python -m pytest -q challenge/RETROFIT_AI_PARTICIPANTS_2026/tests`

## Design
Package `src/retrofit_assistant/`, stack per ADR 0002. Runtime and evaluation stay separate.

- Runtime: `data.py` (sole reader of runtime files, `until` cut), `baseline.py`, `detectors.py`,
  `residuals.py`, `consistency.py`, `diagnosis.py`, `watch.py`, `context.py`, `physics.py`,
  `spectra.py`, `confidence.py`, `policy.py`, `params.py`, `pipeline.py`, `output.py`.
- Development only: `evaluate.py` (scores, `compare`, hit rates, budget fitting), `ablation.py`,
  `report.py`. Runtime modules never import these.
- CLI: `predict --data --split --out [--detector {full,causal_b1}] [--mask-tier {T0,T1}]`,
  `report --asset --data --predictions --out`, `check-submission`, `compare [--gate]`, `ablate`.

Availability contract, enforced by `data.py`. Joins are backward as-of only.

| Input | Available from | Enters | Fields and limits |
| --- | --- | --- | --- |
| `assets.csv` | always | P0 | Static |
| `features_1min.parquet` | `window_start_utc` + 60 s | P0 | All feature columns |
| `operating_context.csv` | `timestamp_utc` + 60 s | P1 | Conservative, since the stamp may be a minute start |
| `alarms.csv` | `raised_utc` | P1, if a task needs it | Only `raised_utc` and fields known at raise. `cleared_utc` and `acknowledged_utc` are never read |
| `vibration_snapshots.parquet` | `timestamp_utc` + 1 s | P2 | One-second capture |
| `maintenance.csv` | window start | Only if a task needs it | `in_window = False` rows only |

Alert time is at least `window_start_utc` + 60 s of the newest minute it uses. A truncated run keeps
a minute only when its end is <= cut. `regime_frame` builds its grid up to the last row, so the grid
must extend to the cut, or to the asset window end, or a gap in progress would look different in
truncated and full runs.

Causal B1 reuses `regime_frame`, whose steady flag is causal, and `b1_threshold` with the published
k = 6 and persist = 15. There is one estimator, `causal_zscores`, which keeps B1's column names:
- Statistics are recomputed at t0 + n hours for n = 1..24, on all steady minutes available by that
  time, and applied to the following hour.
- The pool stops growing at t0 + 24 h, so results from then on match published B1 by construction.
  This cap applies to `causal_b1` and is also the default for the `full` pipeline.
- `MIN_POOL_SAMPLES` = 30 steady minutes. Below it, z-scores are NaN.
- `MIN_REGIME_SAMPLES` = 1, as in B1. A regime below it falls back to the statistics pooled across
  regimes.
- Train and validation pools hold 51 steady minutes at t0 + 1 h and at least 808 at t0 + 24 h.

Warm-up limits arrive in P1-1 and use `assets.csv` and generic physical limits. `causal_b1` is then
frozen, with no policy, so that it remains a stable reference. `full` is the evolving pipeline. From
P0 it is the causal core plus the policy, and the submission always comes from `full`.

The policy works causally on a stream. A condition is a pump plus an evidence-channel family
(vibration, thermal, hydraulic-electric, data link), and its evidence families live in `params.py`.
A condition closes when its evidence clears or the pump stops or locks out. An alert candidate
within 6 min of the previous alert on that pump is deferred. An emitted alert is never revised.

Snapshot spectra use `rpm_at_capture`, checked to be present on all train and validation snapshots,
including fixed-speed PUMP-09.

Build backends: the official `pyproject.toml` declares `requires = ["setuptools>=61"]` with
`build-backend = "setuptools.build_meta"`. Our planned `pyproject.toml` uses the same backend and
requirement. No other backend or build requirement is declared, so the P0-1 pin is setuptools
alone, at a version that satisfies `>=61`.

Alternatives rejected: see ADR 0001 and ADR 0002.
Changes the architecture? yes

## Risks and safety
Data integrity is the main risk.
- Test-data leakage: `predict --split test` prints no alert data, `report` refuses test assets, and a
  truncation failure on test assets prints asset and cut only, never alert content.
- Hidden look-ahead: every detection change must keep C1 green.
- Reference drift: `causal_b1` is frozen after P1-1.
- Fitting on validation: budgets and limits are fitted on train. Validation selects only.
- Compound events: 8 of 35 scored events have a root cause. One alert per condition can cost a
  second detection when both events share a channel family, such as clogging then cavitation.
  Measure this on train in P1-5.
- Late safety check: the first safety CSV in P0-5 predates the truncation test. It is regenerated
  in P0-6, once C1 is green.
- Schedule: P0 tasks total 205 of 270 minutes, leaving 65 as margin. P1 tasks total 265 of 240
  minutes, so P1 needs at least 25 minutes of unused P0 margin. Otherwise it runs into P2, and the
  cut order applies: P2 spectra (P2-3), then ablation down to one T2 pump, then P2 residuals
  (P2-1, P2-2).

## Tasks
Durations are estimates. The first end-to-end, data to causal B1 to CSV to score, closes with P0-5.

### P0 (Sat 07:30-12:00)
| # | Task | Files | Min | Done when | Criteria | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| P0-1 | Scaffold, setuptools pin covering both declared backends, reproducible editable installs, smoke gate | `requirements-lock.txt`, `pyproject.toml`, `src/retrofit_assistant/__init__.py`, `__main__.py`, `cli.py`, `tests/test_smoke.py` | 25 | `python -m retrofit_assistant --help` exits 0 and the smoke gate passes | C18 | - |
| P0-2 | Loader with availability contract | `data.py`, `tests/test_boundaries.py` | 30 | Boundary tests pass | C3, C4 | P0-1 |
| P0-3 | Hourly `causal_b1` | `baseline.py`, `detectors.py`, `params.py`, `tests/test_causal_b1.py` | 45 | Hand-calculated prefix and equality with B1 from t0 + 24 h both pass | C2 | P0-2 |
| P0-4 | Minimal policy and scorer fixtures | `policy.py`, `params.py`, `tests/test_policy.py` | 35 | Policy tests pass | C7 | P0-3 |
| P0-5 | Pipeline, writer, validator, first safety CSV: **first end-to-end** | `pipeline.py`, `output.py`, `cli.py`, `tests/test_output.py` | 25 | Official scorer accepts `causal_b1` and `full` on train and validation, scores are recorded, safety CSV passes unopened | C5, C6 | P0-4 |
| P0-6 | Truncation test, regenerate safety CSV | `tests/test_causality.py` | 45 | Green on PUMP-01..09, C6 passes again, and false-alert episodes in the first 24 h are reported, summed over PUMP-01..07. At 3 or more, the P1-1 warm-up limits become mandatory | C1, C6 | P0-5 |

Margin: 65 minutes.

### P1 (Sat 12:00-16:00)
| # | Task | Files | Min | Done when | Criteria | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| P1-1 | Warm-up limits, freeze `causal_b1` | `detectors.py`, `params.py`, `tests/test_causal_b1.py` | 30 | Warm-up tests and C1 pass, reference scores recorded | C1, C2 | P0-6 |
| P1-2 | `compare` automation | `evaluate.py`, `cli.py` | 20 | Table written for both splits | C8 | P1-1 |
| P1-3 | Sensor vs machine, step vs ramp, SENSOR_DRIFT | `consistency.py`, `tests/test_diagnosis.py` | 45 | Sensor cases pass, and gain is recorded | C1, C10 | P1-2 |
| P1-4 | Signature diagnosis, AIR_ENTRAINMENT, evidence and action templates | `diagnosis.py`, `tests/test_diagnosis.py` | 45 | All signature cases pass | C1, C10 | P1-3 |
| P1-5 | Watch state with family budgets fitted on train | `watch.py`, `params.py`, `evaluate.py`, `tests/test_watch.py` | 45 | Watch tests pass, compound-event loss recorded | C1, C11 | P1-4 |
| P1-6 | Operating context contract, benign hold and re-check | `data.py`, `context.py`, `watch.py`, `tests/test_watch.py` | 20 | Benign cases pass | C1, C3, C11 | P1-5 |
| P1-7 | Static HTML report | `report.py`, `cli.py`, `tests/test_report.py` | 45 | Report generated for PUMP-08 | C14 | P1-2 |
| P1-8 | Milestone | - | 15 | C8 table updated, C6 passes | C6, C8 | P1-6, P1-7 |

### P2 (Sat 16:00-20:00)
| # | Task | Files | Min | Done when | Criteria | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| P2-1 | Duty and inlet normalisation, CUSUM or slope on residuals | `residuals.py`, `pipeline.py`, `tests/test_physics.py` | 45 | Train and validation not worse than P1 | C1, C8 | P1-8 |
| P2-2 | Pump-curve and affinity checks by channels, T0 absolute check | `physics.py`, `diagnosis.py`, `tests/test_physics.py` | 45 | Tier cases pass | C1, C12 | P2-1 |
| P2-3 | Snapshot contract, BPFO, 1x and 2x spectra in diagnosis | `spectra.py`, `data.py`, `diagnosis.py`, `tests/test_spectra.py` | 45 | Synthetic tones recovered | C1, C3, C13 | P2-2 |
| P2-4 | Milestone | - | 15 | C8 table updated, C6 passes | C6, C8 | P2-3 |

### P3 (Sat 20:00-23:00)
| # | Task | Files | Min | Done when | Criteria | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| P3-1 | Ablation by channel masking | `ablation.py`, `cli.py`, `pipeline.py` | 45 | Per-tier table written | C15 | P2-4 |
| P3-2 | Confidence levels and hit rates | `confidence.py`, `evaluate.py`, `tests/test_confidence.py` | 30 | Levels carry hit rate and n | C1, C16 | P2-4 |
| P3-3 | Freeze gate, truncation on test assets, official tests once, milestone | - | 25 | Gate exits 0 or the shortfall is reported to the owner, and C19 passes | C1, C6, C9, C17, C19 | P3-1, P3-2 |

### Wrap-up (Sat 23:00-Sun 01:00)
| # | Task | Files | Min | Done when | Criteria | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| W-1 | README, business case from measured early warning | `README.md` | 45 | Setup and all commands reproduced | C17 | P3-3 |
| W-2 | Architecture document with diagram | `ARCHITECTURE.md` | 30 | Matches the final modules | C17 | P3-3 |
| W-3 | Final run and reproducibility check | - | 20 | C6 and C17 pass | C6, C17 | W-1, W-2 |

## Open questions

## Changes after approval
- 2026-11-06: P0-6 now sets the threshold for false-alert episodes in the first 24 h, as the owner decided.
- 2026-11-07, safety submission: decided by the owner. The safety CSV is `apply_guarantees(causal_b1)`. This replaces "the submission always comes from `full`" in Design and the `full` part of P0-5 and P0-6 for the safety CSV.
- 2026-11-07, C9: decided by the owner. The gate decides when an improved pipeline replaces the source of the safety CSV. It passes if the composite is >= `causal_b1` on both train and validation and > on at least one of them. This replaces "beats causal B1 on both train and validation" in C9. The gate does not apply in P0, where `full` is by construction `causal_b1` plus the guarantees. It still never blocks generating a submission.
- 2026-11-07, P0-4 redefined: decided by the owner after measuring on train and validation, see ADR 0001 Amendment 2026-11-07. P0-4 is a filter on `causal_b1` candidates: pass-through plus mandatory guarantees. `full` in P0 is `causal_b1` through this filter. Evidence-family conditions are not built in P0 and are reconsidered in P1, once diagnosis exists. This entry prevails over the policy paragraph in Design, the Out of scope line on reminders, and C7:
  - C7 now reads: given crafted candidate streams, when the filter is applied, then each alert has one type and one class, alerts on one pump are at least `ALERT_SPACING_MIN` = 6 min apart, no alert falls in a minute whose `operating_mode` is `STOPPED` or `LOCKED_OUT`, and an emitted alert is never revised. Official-scorer fixtures cover mixed types, mixed classes, the 5-min boundary, and UNKNOWN followed by a correct diagnosis. Verify is unchanged.
  - A minute with no row has an unknown state and does not count as stopped.
  - The 12 h repeat limit is the one already inside `b1_threshold`. Reminders from `causal_b1` stay in the output until diagnosis exists.
- 2026-11-07, C6: decided by the owner. On every split, including test, `check-submission` prints `PASS rows=<n>` or `FAIL rows=<n> rule=<rule>`. The rule name is a fixed string from our code, and row content or values are never printed. This entry prevails over C6 on the test output. The C6 Verify command writes and checks `build/submission/predictions_test_<YYYYMMDDTHHMMSSZ>_<shorthash>.csv` instead of `build/submission/predictions_test.csv`.
- 2026-11-07, deterministic CLI output: decided by the owner. The official `diagnose` iterates a set, so its output depends on the process hash seed: across 8 seeds one train alert changes `fault_type`, one changes evidence, and scores do not change. `__main__.py` therefore re-executes the process once with `PYTHONHASHSEED=0` when the variable is not `"0"`, setting it before the exec so no loop is possible. A test requires byte-identical CSVs from two CLI processes started with different seeds. `diagnose` is not copied. In P1 our diagnosis replaces the official `diagnose` in `full`, with an explicit ordered channel sequence and no iteration over sets in runtime modules. The P0-5 file list gains `__main__.py`.
