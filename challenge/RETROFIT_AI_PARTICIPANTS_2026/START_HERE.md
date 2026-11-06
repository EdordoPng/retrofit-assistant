# Start here

**RETROFIT AI: Make Existing Machines Intelligent**
Since AI Hackathon 2026 · Turku · 6-8 November 2026 · challenge owner Business Turku · technical sparring partner Elomatic

A browser version of this page with figures is in `START_HERE.html`.

## The challenge in one minute

Ships and factories are full of machines that were installed 10-30 years ago and still work fine, but they cannot tell anyone when they are starting to fail. Operators find out when a fixed alarm limit is crossed, which is often too late to plan the repair.

Your task is to build an **AI assistant for operators**:

1. Read the data that an existing pump already produces, or could produce with a few cheap extra sensors.
2. Notice developing problems early.
3. Explain the evidence.
4. Say how certain it is.
5. Recommend what a human should check.

It must never control the machine.

Everything here is **synthetic**, made by a documented simulator. You can use it freely without access to a real ship or factory.

## What does a cooling-water pump do?

Engines, compressors and production lines produce heat. A cooling-water pump keeps water flowing through heat exchangers that carry this heat away:

- On a ship, one pump pushes seawater through the central cooler and back overboard, and another circulates fresh water inside the ship.
- In a factory, a pump moves water between the cooling tower and the machines.

If the pump delivers too little water, equipment overheats. If the pump breaks without warning, production or the voyage is disrupted. The motor, bearings, impeller and strainer all wear and clog over time.

## What can go wrong (and is in the data)

| Problem | What happens physically | Typical sign in the data |
|---|---|---|
| Bearing wear | rolling bearing slowly gets damaged | high-frequency vibration rises first, later overall vibration and temperature |
| Strainer clogging | debris or mussels block the inlet filter | suction pressure and flow fall. On variable-speed pumps the speed and power rise instead |
| Cavitation | inlet pressure too low, so vapor bubbles collapse | noisy vibration, lost pressure |
| Restriction | valve left partly closed, heat exchanger fouled | discharge pressure up, flow and current down |
| Misalignment / imbalance | shafts not in line, deposits on the impeller | vibration up, especially with speed |
| Impeller wear, air in the water | lower head, erratic flow | pressure lower than expected at the same flow |
| **Sensor problems** | drift, frozen value, offset, noise, data gaps | one signal changes while related signals do not |

Telling a real machine fault from a misbehaving sensor is a big part of the challenge.

## What the data looks like

- **12 pumps, 7 days each, one row per second:** about 7.2 million rows. A smaller 10-second version (`data/starter/`) opens in any tool.
- **Each row holds** a timestamp, the operating mode (running, starting, stopped, locked out) and up to 14 measurements: speed, current, power, pressures, flow, temperatures, vibration and valve position.
- **Three sensor levels.** Legacy pumps (T0) have only a few signals. Retrofitted pumps (T1) add a cheap wireless vibration sensor that reports every 5 minutes. Fully instrumented pumps (T2) have everything. Empty cells mean "not measured on this pump".
- **Alongside the telemetry:**
  - the plant's own alarms;
  - a maintenance log, whose operator notes are sometimes wrong;
  - the operating context: schedule, cooling demand, sea temperature, weather;
  - short raw vibration recordings.
- **Labels:** 7 training pumps and 2 validation pumps come with labeled events. The 3 test pumps are unlabeled; the organizers score your alerts on them.

## What you deliver

1. A working prototype: ingest or replay data → detect → show evidence and uncertainty → recommend an inspection or maintenance action.
2. A file of alerts for the 3 test pumps, in the format of `submission_template/predictions_template.csv`.
3. Code, run instructions, a short demo video or presentation, a comparison against the provided baselines, and honest limitations.

Optional advanced work:
- a "what-if" check in the provided simulation sandbox (e.g. "would cleaning the strainer now restore flow?");
- an edge-device design;
- a plan for transferring the solution to other machines.

## How you are scored

- **Jury criteria:**
  - business usefulness 25 %
  - technical validity and measured performance 25 %
  - reliability and safety 20 %
  - low-cost retrofit feasibility and transfer 20 %
  - working demo and clarity 10 %
- **Measured performance** comes from an automatic scorer. It rewards:
  - catching real problems;
  - catching them early, before a conventional alarm limit would be reached;
  - naming the right cause, including "sensor problem" versus "machine problem".
- **It penalizes** false and repeated alerts. Guessing everything at once does not pay.
- **Reference points:** the plant's existing alarms score 23 / 100 on validation, and the simple mode-aware baseline 78. Details are in `BENCHMARK_RULES.md`.

## Your first 30 minutes

```bash
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python examples/quickstart.py
```

Then open `examples/01_quickstart.ipynb`, or look at `figures/`, and read `README_FIRST.md`.

## Where things are

| You want to... | Open |
|---|---|
| get going | `README_FIRST.md`, `examples/` |
| understand the words | `GLOSSARY.md` |
| know the columns and files | `DATA_DICTIONARY.md` |
| know the rules and scoring | `BENCHMARK_RULES.md` |
| see how the data were made and the model's limits | `TECHNICAL_MODEL.md` |
| argue cost, hardware and safety | `RETROFIT_FEASIBILITY.md` |
| see the official challenge text | `CHALLENGE_BRIEF.md` |
| check license and data origin | `LICENSE_AND_PROVENANCE.md` |

## Ground rules

- **Synthetic data only.** It is not a measurement from any real ship, plant, company or person.
- **Advice only.** No commands to real devices. Your system advises humans and never controls the machine.
- **Hands off the test pumps.** Do not hand-label or tune on them.

Contact: Reetta Vuorinen, Business Turku, reetta.vuorinen@businessturku.fi
