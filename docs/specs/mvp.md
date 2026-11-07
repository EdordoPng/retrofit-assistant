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
Durations are time-boxes. Each task has at most two implementation rounds. Done before the direction
review: P0-1 to P0-6, P1-1, P1-2, P1-3, P1-7, and P1-7b (report layout). Their rows are in Git at
`eb335a0`.

Order of changes to `pipeline.py`: P1-3b, then the guidance hook in P1-8, then `mask_tier` in P3-1,
then the context hook of P1-6 after P3-1 is merged, then confidence in P3-2. All of them act before
`apply_guarantees`, which keeps only the seven CSV columns and so drops `decided_by`. The final
order is candidates, re-diagnosis, sources, guidance, context, confidence, then guarantees.

| # | Task | Files | Min | Done when | Criteria | Depends on |
| --- | --- | --- | --- | --- | --- | --- |
| P1-3b-1 | SENSOR_STUCK source, dense and wireless, and the internal column `decided_by` | `sources.py`, `diagnosis.py`, `pipeline.py`, `params.py`, `tests/test_sources.py`, `tests/test_diagnosis.py`, `tests/test_causality.py` | 60 | Sources tests and C1 pass, new false alerts per train pump reported, C9 measured against `full` after P1-3 | C1, C10, C20 | P1-3 |
| P1-3b-2 | CAVITATION source from the NPSH margin | same as P1-3b-1 | 60 | As P1-3b-1, rule stated with n = 1 pump; cut if over the time-box | C1, C20 | P1-3b-1 |
| P1-4 | Repair guidance templates | `recommendations.py`, `tests/test_recommendations.py` | 75 | Guidance tests pass; module not yet called by the pipeline | C11 | P1-3 |
| P1-8 | Milestone: guidance hook, CSV columns test, lead time in compare, gate, safety CSV | `pipeline.py` (hook), `evaluate.py`, `consistency.py` (docstring of `coupled_channels` only), `tests/test_evaluate.py`, `tests/test_output.py` | 30 | C1 complete green, CSV columns equal the template, table with lead time, gate result recorded, safety CSV checked | C1, C6, C8, C9 | P1-3b, P1-4 |
| P1-6 | Benign context as evidence | `data.py`, `context.py`, `tests/test_context.py`, `tests/test_boundaries.py`; hook in `pipeline.py` by the supervisor after P3-1 | 30 | Context tests pass, hook merged | C1, C3, C21 | P1-8 |
| P3-1 | Tier ablation with score and lead time | `ablation.py`, `cli.py`, `pipeline.py` (`mask_tier`), `tests/test_ablation.py` | 60 | Table per tier written | C15 | P1-8 |
| P3-2 | Evidence-level confidence | `confidence.py`, `evaluate.py`, `pipeline.py`, `report.py`, `tests/test_confidence.py`, `tests/test_output.py` | 60 | Levels carry train and validation hit rates, type-correct shares and n; "(provisional)" removed from the report | C1, C16 | P3-1, P1-6 |
| P3-4 | Edge measurement | - | 15 | Time and peak RSS recorded | C22 | P3-2 |
| P3-5 | What-if scene, margin only | `build/` output only | 45 | One simulated action shown, never on equipment | - | P3-2 |
| P3-3 | Freeze gate, truncation on test assets, official tests once, milestone | - | 40 | Gate result reported, C19 passes, safety CSV checked | C1, C6, C9, C17, C19 | P3-2 |
| W-1 | README with all commands | `README.md` | 45 | Setup and commands reproduced | C17 | P3-3 |
| W-2 | Technical note with architecture diagram | `docs/technical-note.md` | 105 | Draft before freeze, final after; matches the modules; limits list the fault types named only by official rules and AIR_ENTRAINMENT as not covered | C17, C22 | P3-2 |
| W-3 | Presentation and PDF | `docs/presentation/` | 90 | Draft before freeze, final after | - | W-2 |
| W-4 | Final run and reproducibility check | - | 20 | C6 and C17 pass | C6, C17 | W-1, W-2 |
| W-5 | Narrated video | outside the repo | 90 | Recorded from the report and the commands | - | W-3 |

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
- 2026-11-07, C1 comparison: decided by the owner. `causal_b1` is compared strictly: alerts of the full run with `alert_time <= cut` equal all alerts of the truncated run. `full` is compared after filtering both sides to `alert_time <= cut`. A truncated `full` alert later than the cut is allowed only if deferred by spacing: it maps to a distinct `causal_b1` candidate of the same truncated run, on the same asset, with candidate time `<= cut` and `alert_time == max(candidate_time, previous emission + ALERT_SPACING_MIN)`. The previous emission is the last row emitted by the truncated run on that asset, including rows `<= cut`, and the expected value is computed by walking the candidates in order. This check replicates the spacing rule and changes in the same task as `policy.py`. This entry prevails over C1.
- 2026-11-07, C1 execution: decided by the owner. `tests/test_causality.py` has a fast version, run by default, and a complete version marked `slow`. `pyproject.toml` registers the marker, sets `--strict-markers` and excludes `slow` through `addopts`. The fast version has an exact cut at the `alert_time` of every `causal_b1` alert on PUMP-01..09, with a budget of about 4 minutes. The complete version is mandatory, run in the background, before every commit that touches detection or policy, and at every milestone. The final check in P3-3 runs both versions, and this replaces the C1 final command:
  `RETROFIT_CAUSALITY_ASSETS=PUMP-10,PUMP-11,PUMP-12 python -m pytest -q --tb=line --show-capture=no -p no:warnings tests/test_causality.py`
  `RETROFIT_CAUSALITY_ASSETS=PUMP-10,PUMP-11,PUMP-12 python -m pytest -q --tb=line --show-capture=no -p no:warnings -m slow tests/test_causality.py`
- 2026-11-07, C1 output on test assets: decided by the owner. On PUMP-10, PUMP-11 and PUMP-12 the test stops at the first failure and prints the asset and the cut only. A cut derived from an alert prints `cut=alert-derived`, because its timestamp would reveal the alert time. No per-cut test ids or cut counts are printed. On PUMP-01..09 all failures are collected in one message. This entry prevails over C1 and the test-data leakage risk.
- 2026-11-07, P1-1 reduced to the freeze: decided by the owner. Warm-up limits are removed and `causal_b1` is frozen as it stands, with scores 58.451 on train and 78.013 on validation at commit `1fc6da3` (`src/` unchanged since `fc3ce49`). Evidence: 1 false-alert episode in the first 24 h summed over PUMP-01..07, against a threshold of 3. Of 9 scored events whose window starts before t0 + 24 h, 8 are detected and 1 is missed. The pool reaches `MIN_POOL_SAMPLES` at minute 39 and the first z-score appears at minute 60 on all nine assets, while no window of a non-pre-existing event opens before t0 + 6 h. The weak cases are 4 pre-existing events, which are input to P2-2, and two slow early faults, which are input to P2-1. P1-1 is now a golden test in `tests/test_causal_b1.py`: `causal_b1` CLI output on train and validation must match recorded sha256 values, valid with `requirements-lock.txt`, and changes only by decision of the owner. The golden test skips explicitly, with a reason, when the Python minor version or the pandas, numpy or pyarrow versions differ from the lock, and a separate test prevents that skip from firing on the locked environment. Its only file is `tests/test_causal_b1.py`, and C2 is unchanged. This entry prevails over the warm-up sentence in Design and the P1-1 row in Tasks.
- 2026-11-07, diagnosis plan: decided by the owner after the oracle review. `full` is `causal_b1` candidates, then `rediagnose` at fixed times, then `apply_guarantees`. `rediagnose` changes class, type, evidence and action only, never which alerts exist or when, so `b1_threshold` and the `causal_b1` golden output do not change. P1-3 decides sensor versus machine and sensor types in three states. Confirmed: coupled channels are present, fresh and still, which is positive incoherence, and gives SENSOR with a type from step, ramp or variance. Refuted: coupled channels are present, fresh and follow the deviation, so an official SENSOR alert becomes MACHINE / UNKNOWN. Not verifiable: coupled channels are absent, NaN or stale, so the official diagnosis stays, except that a deviation only on accelerometer-derived channels (crest, acceleration, vibration rms) is MACHINE. P1-4 adds machine signatures. Spectra for imbalance and misalignment stay in P2-3. P1-3b adds dedicated `full` alert sources after P1-3, first SENSOR_STUCK, dense and wireless, then CAVITATION, and C9 is measured for it separately. The cavitation threshold comes from physics, using the NPSH margin from `assets.csv` and the simulator model, and is not fitted on PUMP-06. Its false alerts are measured on all train pumps, and reports state it as a rule with one physical context, n = 1 pump. Budgets for C11 are set in P1-5. P1 totals 340 minutes, with P1-7 running in parallel on its own worktree.
- 2026-11-07, C1 with re-diagnosis and new sources: decided by the owner. From P1-3 the `full` comparison matches emitted rows to candidates by asset and time, because `rediagnose` changes other columns. From P1-3b every internal candidate carries a provenance that is not written to the CSV, and spacing applies to the merged candidate stream. In both cases, equality of emitted alerts up to the cut stays exact in every column. This entry prevails over the C1 comparison entry where they differ.
- 2026-11-07, P0 assertions superseded by the diagnosis plan: decided by the owner. `test_compare_end_to_end` no longer requires `GATE FAIL`: the expected exit code and message follow from `gate()` on the composite values in the table, and 58.451 and 78.013 stay fixed for `causal_b1`. `test_run_detector_validation_pump08_and_until` no longer requires `full` to equal `causal_b1`: asset, alert time and confidence stay exactly equal, row counts match, and class and type stay in the vocabulary.
- 2026-11-07, independent witnesses and noise check in P1-3: decided by the owner. The witnesses of a channel are its installed channels in the official `COUPLED` map, and they decide confirmed, refuted or not verifiable. The actuator channels `n` (`motor_speed_rpm`) and `vp` (`valve_position_pct`) are excluded as witnesses of any other channel, because in a closed loop they react to the measurement, and their fresh readings appear in the evidence only as context. `n` and `vp` have no entry in `COUPLED`, so when either is itself the deviating channel it has no witnesses: the state is not verifiable and the noise check cannot pass. `COUPLED_FOLLOW_RATIO` was measured and removed: at 0.25 it made 3 correct train alerts wrong, so the stillness limit stays k / 3. Here k is `B1_K` = 6.0, so k / 3 = 2.0 (`COUPLED_STILL_FRACTION` = 1/3); z is (minute mean - baseline median) / max(`MAD_SCALE` x baseline MAD, the channel floor in `Z_FLOORS`), and zs is (minute std - baseline median of std) / max(`MAD_SCALE` x MAD of std, `ZS_FLOOR_ABS` + `ZS_FLOOR_REL` x |baseline median of std|). `SENSOR_NOISE_SPIKES` no longer depends on the last minute. The noise window holds the minutes with `window_start_utc` in (last - `NOISE_RECENT_MIN`, last], with `NOISE_RECENT_MIN` = 10 and last the newest minute available at re-diagnosis, that is `window_start_utc` + 60 s <= alert time, so the window uses only minutes available at that time. A real observation is a minute with non-NaN `<channel>__mean`, `<channel>__count` > 0, no COMM_LOSS, STALE or BAD_SENSOR_STATUS flag in `quality_any`, and finite z and zs. `<channel>__count` is the number of valid samples in that minute. A candidate channel must be fresh at re-diagnosis, have an update interval of at most 60 s, so longer-interval wireless channels are excluded, and have at least `SHAPE_MIN_OBSERVATIONS` = 3 real observations with `<channel>__count` >= `NOISE_MIN_DENSE_COUNT` = 30 in the window, median zs above k and median |z| below k / 3. It needs at least one witness, and every installed independent witness must be fresh, have at least 3 real observations and have median |zs| below k / 3, with no count limit. Candidates are tried from the highest median zs, and the first that passes gives SENSOR / `SENSOR_NOISE_SPIKES`. If no candidate passes, the noise check changes nothing: the alert stays, and the three-state rule decides its diagnosis. COMMUNICATION_LOSS and SENSOR_STUCK alerts skip both the noise check and the three-state rule and stay unchanged. This entry prevails over the diagnosis plan entry where they differ.
- 2026-11-07, direction review: decided by the owner, see ADR 0001 Amendment 2026-11-07, direction review. The watch state (P1-5), P2-1, P2-2 and P2-3 are cut, and `watch.py`, `residuals.py`, `physics.py` and `spectra.py` leave the Design list. `sources.py`, `recommendations.py`, `context.py`, `confidence.py` and `ablation.py` enter it. The Tasks section is replaced. The cut order is CAVITATION, then P1-6, then the ablation reduced to one T2 pump. P1-4, P3-2, the technical note, the presentation and the test CSV are never cut. An OPC UA or MQTT adapter and a natural-language interface stay out of scope, described only as an integration path.
- 2026-11-07, requirements after the direction review: decided by the owner.
  - R5 now reads: diagnosis separates sensor from machine faults. Our own rules name SENSOR_STUCK, CAVITATION, SENSOR_DRIFT, SENSOR_CALIBRATION_SHIFT, SENSOR_NOISE_SPIKES and UNKNOWN. COMMUNICATION_LOSS, BEARING_WEAR, SUCTION_STRAINER_CLOGGING, DISCHARGE_RESTRICTION, MISALIGNMENT, IMBALANCE and IMPELLER_WEAR are named only by the official B1 rules. AIR_ENTRAINMENT is not covered.
  - R6 now reads: alert sources, guidance and context adapt to the channels each asset has. A check whose channels are missing is disabled with no error and no alert.
  - New R10: the submission includes a technical note, a short presentation with a PDF and a narrated video. Every number in them comes from a recorded command output.
- 2026-11-07, criteria after the direction review: decided by the owner. C12 and C13 are removed.
  - C8 now also reports, for `full` and `causal_b1` on train and validation, `median_lead_time_h` and `early_warning_rate` from the official scorer. It reports the declared B1 median lead to deadline from `baselines/results/baseline_metrics.md`: 55.8 h on train and 8.3 h on validation. Verify is unchanged.
  - C10 now reads: given synthetic minute frames, when re-diagnosis runs, then the confirmed, refuted and not verifiable states follow the diagnosis plan. A persistent step gives SENSOR_CALIBRATION_SHIFT, a ramp gives SENSOR_DRIFT, persistent isolated variance gives SENSOR_NOISE_SPIKES, and an ambiguous shape keeps an official SENSOR type. AIR_ENTRAINMENT is not required. Verify is unchanged.
  - C11 is replaced (R5, R2): given every `fault_type` and `event_class` of the vocabulary and every value of `decided_by`, when guidance runs, then `recommended_action` names what to inspect, what to do and what to rule out, from a deterministic template. A SENSOR alert says to verify the instrument before opening the pump. An UNKNOWN alert on a process variable never says only "Inspect pump." No action writes to a device. Verify: `python -m pytest -q tests/test_recommendations.py`
  - C15 now reads: given T2 assets with channels masked to T1 and T0, when ablation runs, then a table reports composite score and median lead time per tier, on PUMP-02, PUMP-04, PUMP-07 and PUMP-09. It may be reduced to one T2 pump under the cut order. Verify is unchanged.
  - C16 now reads: given train and validation alerts, when confidence levels are built, then each level comes from the evidence rule in `decided_by`. A hit is an alert inside the window of a scored event. Each level reports its hit rate, the share of alerts with the correct `fault_type` and the sample size, on train and on validation separately. The runtime confidence of a level is its train hit rate, looked up from a table in code. Validation is a check only and never changes the table. No test data is used, and reports and documents never call it a probability. Verify is unchanged.
  - New C20 (R5, R6): given synthetic minute frames, when the sources run, then SENSOR_STUCK is found on dense channels and on 300 s wireless channels, counting real updates and not minutes, and normal quantisation is not stuck. CAVITATION compares NPSH available, computed from measured suction pressure and the vapour pressure at fluid temperature, with the nameplate `npsh3_at_bep_m`. This matches the simulator's model; on real equipment the margin needs site verification. There is no cavitation alert on T0 and one alert per episode. Alerts up to t do not change when rows after t change. Verify: `python -m pytest -q tests/test_sources.py`
  - New C21 (R2, R6): given operating context, when context runs, then benign context available by the alert time appears in the evidence. It never holds, suppresses or delays an alert. `operating_context.csv` is read only through `data.py`, with its availability rule. Verify: `python -m pytest -q tests/test_context.py && python -m pytest -q tests/test_boundaries.py -k runtime_inputs`
  - New C22 (R10): given one train pump and one validation pump, when `predict` runs in a fresh process, then wall time and peak RSS are recorded in the technical note with the command used. No test asset is used for this measurement.
- 2026-11-07, provenance and confidence contract: decided by the owner. The rule that decided each alert is the internal column `decided_by`, never DataFrame attributes. `rediagnose` sets it for `causal_b1` candidates, and the sources set it for their own. `apply_guarantees` keeps only the seven CSV columns, so `decided_by` never reaches the writer, and a test requires the CSV columns to equal `submission_template/predictions_template.csv`. From P3-2 the pipeline assigns `confidence` after re-diagnosis, so `rediagnose` still changes only class, type, evidence, action and `decided_by`, while `confidence` is set by `confidence.py`. `test_run_detector_validation_pump08_and_until` then keeps exact equality on `asset_id` and `alert_time_utc` only, with confidence finite in [0, 1]. This entry prevails over the diagnosis plan entry and the C1 with re-diagnosis and new sources entry where they differ.
- 2026-11-07, two independent witnesses to confirm a sensor fault: decided by the owner after an in-memory measurement on `main` `34dbb2d`. For an alert on `pd` or `q`, `ps` is not a witness, because a drifting suction transmitter can mask a real suction loss (BENCHMARK_RULES §1). The state is confirmed only if at least two installed witnesses are fresh, finite and below k / 3 (`MIN_STILL_WITNESSES` = 2, a design choice that was not measured). Otherwise, if no witness follows the deviation, the state is not verifiable and the official diagnosis stays. Refuted is unchanged. The measurement left train and validation scores unchanged, with 3 train candidates back to the official diagnosis. In a synthetic T1 valve-pump case, with `pd` ramping to z = -8 over 3 h, `ps` still and `i` at z = -1.5, the alert now stays MACHINE / SUCTION_STRAINER_CLOGGING instead of SENSOR / SENSOR_DRIFT. On T0 and on T1 without a drive, a discharge-pressure deviation can therefore no longer be confirmed as a sensor fault: it is refuted when a witness follows it, otherwise the official diagnosis stays. This entry prevails over the independent witnesses and noise check in P1-3 entry where they differ.
- 2026-11-07, P2-3 reinstated in reduced form: decided by the owner after an in-memory train measurement whose criteria were fixed before the snapshots were opened. This entry prevails over the direction review entry for P2-3 and C13. `vibration_snapshots.parquet` enters the availability contract from `timestamp_utc` + 1 s, read only through `load_snapshots` in `data.py` with the same `until` cut as the features. In `rediagnose`, an alert that is still MACHINE and not protected may change type from the latest snapshot of the same asset available at the alert time and no older than 8 h (two 4 h snapshot cycles). Protected alerts are those whose official type is COMMUNICATION_LOSS or SENSOR_STUCK; alerts from the dedicated sources are not re-diagnosed. If the latest eligible snapshot has no valid `rpm_at_capture`, no older snapshot is used and the type does not change. BEARING_WEAR is assigned when the envelope of the 2000-3600 Hz band (Hilbert modulus) shows a peak at BPFO or BPFI times running speed (orders from `assets.csv`, ±3 %) at least 6 times the median of the envelope in [0.5, 1.5] of that frequency. Otherwise MISALIGNMENT is assigned when, after a LOCKED_OUT available before the alert, the median 2x line of steady-minute snapshots is at least 2 times the median before the lockout. There is no IMBALANCE rule. Class, alert time and alert count do not change, and `decided_by` is `rediagnose_spectrum`. The measurement gave train 74.042 to 76.663 and validation 83.314 to 86.092. On validation the gain comes from a single event. On train, 2 of the 3 gained types come from the rules, and 1 comes from the scorer's matching. When bearing wear and imbalance overlap on one pump, the BEARING_WEAR precedence overwrites IMBALANCE alerts that were correct.
- 2026-11-07, C13 after P2-3: decided by the owner. C13 now reads: given synthetic snapshots with known envelope tones at BPFO or BPFI on a 2.8 kHz carrier, a doubled 2x line after a lockout and a known `rpm_at_capture`, when spectra run, then BEARING_WEAR and MISALIGNMENT are returned as above, a snapshot after the alert time or older than 8 h is ignored, another asset's snapshot is ignored, and a SENSOR or protected alert is not changed. Verify: `python -m pytest -q tests/test_spectra.py`
- 2026-11-07, P3-1 tier ablation: decided by the owner. `run_detector(..., mask_tier)` with `mask_tier` in {T1, T0} applies only to T2 assets and masks the input before baseline, sources, re-diagnosis and spectra. It removes the channels that the tier lacks from the features and from the runtime metadata: `channels_available` loses them and `instrumentation_tier` becomes `T1_RETROFIT` or `T0_LEGACY`. T1 removes `flow_m3_h`, `motor_winding_temp_c` and `valve_position_pct`. T0 also removes `suction_pressure_kpa`, the vibration channels, `bearing_temp_c` and the snapshots. Without a drive, `motor_speed_rpm` and `motor_power_kw` are removed as well (TECHNICAL_MODEL §10). The simulated T1 is optimistic, because the wireless cadence is not emulated and vibration stays dense. Masked scores are pessimistic, because the event `observable` flags come from the real T2 instrumentation. Pumps that are really T1 (PUMP-01, PUMP-06) and T0 (PUMP-03, PUMP-05) on train are shown as a reference only, because their events differ and they are not comparable. Without a mask the output is byte-identical. `predict --mask-tier` is refused on the test split. C15 is verified by `python -m retrofit_assistant ablate --data $D --out build/scores/ablation.md`.
