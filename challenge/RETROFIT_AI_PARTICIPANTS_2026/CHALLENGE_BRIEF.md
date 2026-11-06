# Challenge brief: Since AI Hackathon 2026, Turku, 6-8 November 2026

This brief follows the eight official Since AI 2026 challenge fields. Business Turku is the challenge owner. Elomatic is an invited technical sparring partner. It is not necessarily a paid challenge sponsor, and it is not the source of the synthetic data.

## 1. Title

**RETROFIT AI — Make Existing Machines Intelligent**

## 2. Problem

Existing ship and industrial machines already produce useful signals, but they rarely have an intelligence layer that turns those signals into early, explainable warnings. The use case is an **existing ship/industrial motor-driven cooling-water pump**. The goal is to use existing or low-cost industrial sensor data to:

- detect developing issues;
- explain the contributing evidence;
- recommend human-approved interventions;
- optionally test changes in a **digital sandbox only**.

The aim is to do this without large capital investment, by retrofitting intelligence onto machines that are already in service.

## 3. Guiding question

How can existing or low-cost sensor data from an existing motor-driven cooling-water pump be turned into an operator-assist layer that detects developing issues early, explains its evidence and uncertainty, and recommends human-approved interventions, without any hardware writes or production control?

## 4. Recommended AI approaches

- **Minimum working demo:** ingest or replay telemetry → detect and triage abnormality → show evidence and uncertainty → recommend maintenance or inspection.
- **Advanced:** model the what-if impact of an intervention in the digital sandbox, run bounded edge inference, and provide a transferable interface to other rotating machines.
- Context-aware anomaly detection (operating mode, speed, duty, season), physics-informed residuals, change-point detection, separating sensor faults from machine faults, and calibrated uncertainty are all relevant. No hardware writes or production control are in scope.

## 5. Dataset

An organizer-supplied **synthetic** dataset, generated for this challenge. It is not measured data from Elomatic, any vessel or any plant. It contains:

- 12 simulated pumps (ship seawater and fresh-water cooling, industrial cooling-tower circulation, hot process-water transfer);
- 7 days per pump at 1 Hz, about 7.2 million telemetry rows, in Parquet;
- a 10-s CSV starter subset;
- three instrumentation tiers: legacy, low-cost retrofit and fully instrumented;
- SCADA-style alarms, a maintenance log with imperfect operator notes, operating context, 1-min feature windows and vibration waveform snapshots;
- train and validation labels. Test labels are held by the organizers.

There is also a sandbox what-if tool and a read-only replay adapter. See `README_FIRST.md`, `DATA_DICTIONARY.md` and `TECHNICAL_MODEL.md`.

## 6. Evaluation criteria

| Criterion | Weight |
|---|---|
| Business usefulness | 25 % |
| Technical validity and measured performance | 25 % |
| Reliability / safety | 20 % |
| Low-cost retrofit feasibility and transfer | 20 % |
| Working demo and clarity | 10 % |

The measured-performance part uses the event-based scorer described in `BENCHMARK_RULES.md`.

## 7. Submission

- a working prototype;
- a code repository and run instructions;
- a short demo video or presentation;
- a measured baseline comparison;
- honest limitations.

For the measured comparison, include a test-set prediction file in the format of `submission_template/predictions_template.csv` (see `BENCHMARK_RULES.md`). Submission and IP terms follow the official Since AI 2026 rules.

## 8. Contact

Reetta Vuorinen, Business Turku, reetta.vuorinen@businessturku.fi

Elomatic technical participant names and onsite roles are subject to confirmation.
