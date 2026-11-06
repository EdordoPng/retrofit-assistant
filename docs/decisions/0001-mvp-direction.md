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
