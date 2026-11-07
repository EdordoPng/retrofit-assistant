# ADR 0001: MVP direction

Status: Accepted
Date: 2026-11-06

## Context

We are a solo team. Submission closes Sunday 8 Nov 2026, 10:00 Turku time. The demo is a recorded
video with a pitch of about 3 minutes.

The composite score is evidence for only one jury criterion (technical validity, 25 %). The other
75 % is business usefulness, reliability/safety, retrofit feasibility and demo clarity
(BENCHMARK_RULES §4).

Points left on the table by B1, per metric:

| Split | Gap to 100 | Fault type | F1 | Timeliness | Class | Burden |
|---|---|---|---|---|---|---|
| Train (58.2) | 41.8 | 18.2 | 9.8 | 8.4 | 4.6 | 0.6 |
| Validation (78.0) | 22.0 | 13.9 | 3.9 | 2.7 | 1.1 | 0.4 |

Diagnosis is the largest single lever, but on train F1 plus timeliness is worth the same 18 points.
Fault-type recall is also capped by event recall, because only detected events earn it. On train
B1 detects 0.69 of events and names 0.39 of those correctly.

Findings that shape the decision:

- B1 is not causal. Its first-24-h baseline is applied to earlier minutes (`baselines.py:66-67`).
  One of its 16 validation alerts is affected (PUMP-09, 12.8 h). The 78.0 and 58.2 references
  therefore carry a small look-ahead.
- The official package has no causality test.
- There are 35 scored events: 26 train, 9 validation. One validation event moves the composite by
  up to about 8 points.
- Validation is not representative. It has no T0 asset and no CAVITATION, IMPELLER_WEAR, IMBALANCE
  or SENSOR_CALIBRATION_SHIFT event. Those four types are 9 of the 26 train events.
- Flow exists on T2 only (15 of 35 events). T0 carries 5 events, and all 5 list discharge pressure
  as evidence.
- 5 of 35 events are pre-existing (3 BEARING_WEAR, 2 IMPELLER_WEAR). A self-baseline absorbs them.
- B1 can never name 5 of the 35 events (SENSOR_DRIFT, AIR_ENTRAINMENT).
- Type and class credit come only from the detecting alert. A correct later alert earns nothing on
  an already detected event.
- 24 of 35 events have no deadline, so their timeliness reference is detectable + 6 h.
- B2 reaches train recall 0.88 and timeliness 0.81 at 0.94 false alerts per asset-day. Early
  sensitivity is available if false alerts are controlled.

## Decision

Build a causal, tier-adaptive, physics-informed rule system. Adopt Direction A with the amendments
below.

1. **Causal B1 as the core and honest reference.** Rebuild B1 with an expanding baseline from data
   <= t and a warm-up phase that relies on physical and generic limits. Alert times use minute end,
   since a one-minute feature contains data up to that point. All gains are measured against this
   causal B1 on train and validation, and also against the published 78.0 and 58.2.
2. **Truncation test first.** Write our own test alongside the causal core: results for alerts
   before a random cut point must be identical on truncated and full input. Run it on PUMP-01..09
   during development and on test assets only as AGENTS.md allows.
3. **Safety submission.** P0 delivers a valid test CSV by Saturday 12:00. It is regenerated at each
   milestone in `build/submission/`. These runs are submission runs only: the output is checked for
   format and is not inspected, scored or used for any decision.
4. **Better detection.** Normalise by regime, duty and inlet temperature. Run CUSUM or slope
   detectors on those residuals, so that slow faults are caught earlier without B2's false-alert
   rate.
5. **Physics residuals by available channels.** Each check declares the channels it needs and
   switches itself off when they are missing.
   - T2: head vs flow on the pump curve, affinity laws where speed exists.
   - T1: differential pressure against current or power as a flow proxy.
   - T0: discharge pressure against current, including an absolute check against the curve for
     pre-existing wear. Motor efficiency and power factor are treated as uncertain.
6. **Sensor vs machine.** Use cross-signal consistency and step vs ramp tests. Add SENSOR_DRIFT and
   AIR_ENTRAINMENT to the output vocabulary. Do not assume one fault at a time, since a drifting
   transmitter can mask a real fault (BENCHMARK_RULES §1).
7. **Snapshot spectra (T1, T2).** Extend the BPFO check to 1x and 2x lines, so that one pipeline
   also serves MISALIGNMENT and IMBALANCE. BPFO needs no healthy baseline, which suits pre-existing
   bearing wear.
8. **Simplified watch state, after P0.** A detection first enters an internal watch state shown to
   the operator but not submitted. It becomes an alert when diagnosis is confident or the hold
   budget expires.
   - There is one hold budget per fault family, fitted on train:
     - rotating: BEARING_WEAR, MISALIGNMENT, IMBALANCE
     - slow hydraulic: SUCTION_STRAINER_CLOGGING, DISCHARGE_RESTRICTION, IMPELLER_WEAR
     - instrument: SENSOR_DRIFT, SENSOR_CALIBRATION_SHIFT, SENSOR_NOISE_SPIKES
   - CAVITATION, AIR_ENTRAINMENT, SENSOR_STUCK and COMMUNICATION_LOSS alert immediately.
   - Delay costs (delay / span) x 20 / N after the reference time, and nothing before it. A correct
     type earns 25 / N. Across a 100 h span, 5 h of delay pays off if it raises the chance of a
     correct type by more than 4 points.
   - UNKNOWN is used only at hold expiry.
9. **Alert policy.** One fault_type and class per alert, no more than one reminder per 12 h, none
   while stopped or locked out. A condition is re-evaluated after restart, because a reminder after
   a repair is a false alert.
10. **Benign context.** Hold and re-check instead of dropping alerts. Permanent suppression after a
    maintenance restart could hide real misalignment. Runtime context only.
11. **Confidence.** Scoring does not use it, and 35 events cannot support real calibration. Use
    evidence-based levels with observed hit rates on train and validation, and state the sample
    size. Do not claim calibrated probabilities.
12. **Operator report (P1).** A CLI generates one static HTML report per pump, with no server. It
    shows a timeline of key signals, alert markers and a card with evidence, confidence and
    recommended action. It is the interface shown in the recorded demo.
13. **Sensor value ablation.** Re-run T2 assets with channels masked down to T1 and T0, and report
    the score per tier. This links retrofit cost to measured benefit.
14. **Deterministic output.** Evidence and recommendations come from templates tied to the rule
    that fired. Output is advisory only.
15. **Stress data.** Not used for tuning. It may serve only as a generalisation check on Saturday
    evening, and only with the owner's explicit approval at that time.

Fit on PUMP-01..07 and select on PUMP-08..09. A change is kept only if it beats the causal B1 on
both splits and passes the truncation test.

Delivery order (Turku time):

| Priority | Scope | Slot |
|---|---|---|
| Prep | ADR, `/piano mvp`, oracle review | Fri 22:30-00:30 |
| P0 | Causal B1 with warm-up, truncation test, alert policy, submission writer, safety CSV | Sat 07:30-12:00 |
| P1 | Sensor vs machine, new fault types, watch state, static HTML report | Sat 12:00-16:00 |
| P2 | Physics residuals, BPFO/1x/2x spectra | Sat 16:00-20:00 |
| P3 | Ablation, confidence levels | Sat 20:00-23:00 |
| Freeze | Detection logic frozen | Sat 23:00 |
| Wrap-up | README, diagram, final run | Sat 23:00-Sun 01:00 |
| Demo | Video and pitch | Sun 06:00-09:00 |
| Submit | Margin and delivery | Sun 09:00-10:00 |

Sleep is planned for Sat 00:30-07:30 and Sun 01:00-06:00.

Cut order if time runs short: P2 spectra first, then ablation reduced to one T2 pump, then P2
residuals. The light classifier is out of scope unless P0 to P3 finish early.

## Alternatives

- **B. Heavy supervised ML: rejected.** There are 1 to 4 scored events per type, on 7 train pumps.
  It would overfit, explain poorly and transfer badly across tiers.
- **C. LLM copilot: rejected.** No score gain, a hallucination risk, and a dependency that is hard
  to defend in a safety-minded retrofit.
- **D. Light classifier on residual features: deferred.** Accept only if leave-one-asset-out on
  train and the validation score both improve.
- **E. Tune B1 thresholds only: rejected.** It cannot fix causality, pre-existing faults or the two
  fault types B1 cannot name.

## Consequences

- We can state that the system is causal, with a test to prove it, which supports the reliability
  criterion.
- The causal B1 may score below the published 78.0 and 58.2. We report both references.
- A valid submission exists from Saturday 12:00, whatever happens to later phases.
- The rule set will be larger than B1's and needs a clear priority order.
- Pre-existing faults gain a route to detection, but mainly through assumptions on T0.
- Each tier will show its own measured limits, and T0 will visibly name fewer faults. This is an
  honest retrofit story.
- The operator sees an early watch state that benchmark timing does not reward.
- Rules read directly as evidence in the HTML report, and `what_if` can illustrate options as
  simulation only.

## Risks

- **Overfitting to the simulator.** Our residuals share the generator's equations, so benchmark
  gains overstate field performance (TECHNICAL_MODEL §12). State this in the pitch.
- **Small validation set.** Differences of a few points are noise. Require agreement on train and
  validation.
- **Unseen combinations on test.** Rules tuned to single faults may fail on compound or masked
  faults. UNKNOWN is the fallback.
- **Hold policy.** It can cost timeliness, or miss machine faults repaired soon after onset.
  Validate per fault family.
- **Immediate alerts.** CAVITATION and AIR_ENTRAINMENT alert without a hold, so a first wrong type
  cannot be corrected for credit. This is accepted because the episodes are short.
- **T0 absolute checks.** Uncertain efficiency, power factor and suction head may create false
  alerts. Disable them if train precision falls.
- **Air vs cavitation.** Separation relies on context, and sea state exists on vessels only.
  Expect confusion.
- **T1 snapshots.** Real wireless hardware may not deliver them. Present that as an assumption.
- **Demo tooling.** `replay` may fail with naive `--start`/`--end` values or under paho 2.x, and it
  produces no alerts. The HTML report does not depend on it.
- **Business case.** The FEASIBILITY figures treat event recall as "caught early". Recompute with
  our early-warning rate.
- **Time.** The schedule leaves little margin. The cut order above is binding.

## Open questions

1. Are the score targets simply "beat the causal B1 on both splits", or do we set per-metric
   targets once B1's per-event train errors are measured?
2. Which train or validation incidents make the clearest demo story across T0, T1 and T2?
3. Is `rpm_at_capture` usable on direct-on-line assets for spectral analysis?
4. How do unobservable events interact with matching? The code keeps them in, and the effect has
   not been measured.

## Amendment 2026-11-06

Accepted by the owner after the oracle review of the draft spec. Where this section differs from
the text above, this section prevails. Details are in `docs/specs/mvp.md` and
`docs/decisions/0002-stack.md`.

Deviations from the Decision section:

| Decision | Amended to |
| --- | --- |
| 1, causal B1 | Alert time is at least `window_start_utc` + 60 s. One estimator: baseline statistics are recomputed hourly on the available prefix and applied to the following hour, with an explicit regime fallback and minimum sample count. The pool stops growing at t0 + 24 h, which keeps results equal to published B1 from then on. |
| 1, warm-up | Warm-up limits move from P0 to P1. `causal_b1` is frozen after they land, not at the end of P0. |
| 2, truncation test | Cuts include deterministic points just before and after minute boundaries, as well as random points. Every intermediate is recomputed from scratch on truncated input. |
| 3, safety submission | The first safety CSV precedes the truncation test and is regenerated once that test is green. It comes from a minimal `full` pipeline, causal core plus policy. `causal_b1` without policy stays the comparison reference. |
| 3, format check | Validation is strict: columns, vocabulary, finite confidence in [0, 1], UTC, exclusive window end, malformed files and a header-only file. On test, only the format outcome is reported. |
| 9, alert policy | A condition is a pump plus an evidence-channel family, with one alert per condition. There are no reminders in the submission. Alerts on one pump are at least 6 min apart, and an emitted alert is never revised. A stop or lockout clears pending evidence, and evaluation restarts fresh. |
| New | Every input has an availability rule and joins are backward as-of only, with no backward fill, future interpolation or nearest join. P0 uses only `features_1min` and `assets.csv`. Context, snapshots and alarms enter in P1 and P2 under their own contracts. Alarms use `raised_utc` only. |
| New | P0-1 includes a smoke gate. The official tests run separately, once, at the freeze. |
| Stack | setuptools is pinned in `requirements-lock.txt`. Both packages install with `--no-build-isolation --no-deps`. |

Changes to the delivery order:

| Task | Scope | Min |
| --- | --- | --- |
| P0-1 | Scaffold, pinned setuptools, smoke gate | 25 |
| P0-2 | Loader with availability contract | 30 |
| P0-3 | Hourly `causal_b1` | 45 |
| P0-4 | Minimal policy and scorer fixtures | 35 |
| P0-5 | Writer, validator, first safety CSV | 25 |
| P0-6 | Truncation test, regenerated safety CSV | 45 |
| Margin | Unassigned | 65 |

P0 keeps its 270-minute slot. Warm-up limits and `compare` automation move to P1. The reserve cut
that moved warm-up to P1 only on overrun no longer applies.

Consequences:
- P1 now totals 265 minutes in a 240-minute slot. It relies on unused P0 margin, and the existing
  cut order applies otherwise.
- One alert per condition can cost a second detection on compound events that share a channel
  family. This is measured on train in P1.

## Amendment 2026-11-07

Accepted by the owner. Where this section differs from the text above, this section prevails.

"No reminders through per-family conditions" (Amendment 2026-11-06, row 9) was measured and rejected
for P0. The gate: keep a variant only if it loses no detection and does not raise false plus
excess-repeat episodes against `causal_b1`, on train and on validation.

All runs use the official scorer on causal z-scores. Reference `causal_b1`: 58.45 and 78.01.

| Variant | Train score | Validation score | Detected (of 26, 9) | False + excess (train, validation) | Gate |
| --- | --- | --- | --- | --- | --- |
| (a) `causal_b1` candidates, guarantees only | 58.45 | 78.01 | 18, 8 | 7, 1 | Pass |
| (b) (a) plus same `fault_type` suppressed on a pump for 12 h | 58.45 | 78.01 | 18, 8 | 7, 1 | Pass, identical to (a) |
| (c) `causal_b1` candidates, per-family conditions, `CONDITION_CLEAR_MIN` = 15 | 56.74 | 72.39 | 17, 7 | 5, 1 | Fail, loses detections |
| Spec policy, persistence per family, same clear time | 49.23 | 65.47 | 17, 7 | 19, 5 | Fail, prototype before this gate |

Decision: keep (a). It equals `causal_b1` row for row on both splits, because no candidate falls in
a stopped minute or within 6 min of another on those splits. (b) adds nothing, since `b1_threshold`
already applies a 12 h refractory per fault type. The guarantees still protect the test split.

Consequences:
- Per-family conditions are reconsidered in P1, once diagnosis exists.
- Reminders from `causal_b1` stay in the output until then.
- The safety CSV is `apply_guarantees(causal_b1)` until an improved pipeline passes the C9 gate: score
  >= `causal_b1` on both splits and > on at least one. The gate does not apply in P0.

## Amendment 2026-11-07, warm-up

Accepted by the owner. Decision 1 has no warm-up phase: `causal_b1` has no physical or generic limits and is frozen as it stands, because first-day measurements gave 1 false-alert episode, 8 of 9 early events detected, and absolute checks stay in P2-2.

## Amendment 2026-11-07, direction review

Accepted by the owner after an oracle review (read only) and a reading of the official challenge
text. Where this section differs from the text above, this section prevails.

Reason: the official text puts actionable alerts and guidance for the person who works on the
machine at the centre (criterion A, 25 %). It asks for measured detection quality and warning lead
time against a simple baseline (B, 25 %). It asks for false alarms, missing sensors, uncertainty
and safe human review (C, 20 %), and for plausible retrofit cost, edge or on-site operation and
adaptation to another machine class (D, 20 %). The remaining plan spent too much on the detector
and too little on this evidence. The composite score is evidence for B only.

Cut, and kept in the technical note as a roadmap:
- Decision 8, watch state (P1-5, C11). A preliminary train measurement with the current diagnosis
  gave losses at every hold tried: holds of 1, 3, 6 and 12 h cost 2.7 to 7.5 composite points
  against 59.797, and lost 1 to 3 detections.
- Decision 4, duty and inlet normalisation with CUSUM or slope on residuals (P2-1).
- Decision 5, pump-curve, affinity and T0 absolute checks (P2-2).
- Decision 7, snapshot spectra for BPFO, 1x and 2x (P2-3).

Kept, with these changes:
- P1-3b adds dedicated alert sources, SENSOR_STUCK first and CAVITATION second, each with a
  60-minute time-box. The cavitation rule compares NPSH available, computed from measured suction
  pressure and the vapour pressure at fluid temperature (standard hydraulics), with the nameplate
  `npsh3_at_bep_m` in `assets.csv`. It is never fitted on PUMP-06. This matches the simulator's
  model; on real equipment the margin needs site verification. Its false alerts are measured on
  every train pump. It is stated as a rule with one physical context, n = 1 pump. It is cut
  without discussion if it exceeds its time-box.
- The rule that decided each alert travels in an internal column, `decided_by`. It is never kept
  in DataFrame attributes and never written to the CSV.
- P1-4 becomes repair guidance by type and class. Each alert carries readable evidence, what to
  inspect, what to do and what to rule out before intervening. For SENSOR alerts, verify the
  instrument before opening the pump. Templates are deterministic and tied to the rule in
  `decided_by`. They replace generic actions on process variables, such as UNKNOWN on
  `fluid_temp_c` with "Inspect pump.". P1-4 adds no new diagnostic signature.
- Decision 10 is reduced (P1-6): benign operating context is shown as evidence on the alert card,
  with no hold and no suppression.
- Decision 13 moves earlier (P3-1): the tier ablation reports composite score and lead time, on
  every T2 pump if time allows.
- Decision 11 (P3-2): confidence is an evidence level. Its runtime value is the level's hit rate on
  train, looked up from a table in code. Validation is reported separately as a check and never
  changes the table. It is never presented as a calibrated probability. It replaces the confidence
  after re-diagnosis, so it changes the contract "rediagnose changes class, type, evidence and
  action only" and the confidence assertion in `tests/test_output.py`.

Fault types named after the cuts:
- By our own rules: SENSOR_STUCK and CAVITATION (P1-3b sources), SENSOR_DRIFT and
  SENSOR_CALIBRATION_SHIFT (re-diagnosis shape), SENSOR_NOISE_SPIKES (re-diagnosis noise check),
  and UNKNOWN (refuted, accelerometer-only or ambiguous cases).
- Only by the official B1 rules: COMMUNICATION_LOSS, BEARING_WEAR, SUCTION_STRAINER_CLOGGING,
  DISCHARGE_RESTRICTION, MISALIGNMENT, IMBALANCE and IMPELLER_WEAR. SENSOR_STUCK and CAVITATION
  can also come from the official rules.
- Not covered: AIR_ENTRAINMENT. No rule names it.

New deliverables required by the official text:
- A short presentation, also as PDF.
- A technical note covering retrofit costs, deployment assumptions, safety and limits, including
  the fault types above. It also covers transfer to another class of rotating machine, as a table
  of component, transfers or must be reconfigured, and limit. It includes an edge measurement of
  `predict` wall time and peak memory per pump on this PC.
- A short narrated demo video.

Only if there is margin: one what-if scene in the simulator, with an operating action tried in
simulation only, never on equipment. Out: an OPC UA or MQTT adapter and a natural-language
interface. They are described only as an integration path.

Cut order, which replaces the one above: CAVITATION first, then P1-6, then the ablation reduced to
one T2 pump. Never cut: P1-4, P3-2, the technical note, the presentation and the test CSV.

Claims to avoid in all material: "+7.3 from diagnosis" (part of it is the scorer's matching),
"accuracy", "calibrated probabilities", "works on any machine", "failures prevented".

Consequences:
- The detector stays `causal_b1` candidates plus re-diagnosis plus two dedicated sources. Slow
  faults and pre-existing wear keep the limits measured on train, and the note reports them.
- IMBALANCE and MISALIGNMENT are still named only by the official rules, since spectra are cut.
- Effort moves to guidance, measured uncertainty, tier value and the written case for retrofit.
