# AGENTS.md — retrofit-assistant

Operator-assist layer for the RETROFIT AI 2026 challenge: detect developing machine and
instrument faults on simulated cooling-water pumps, explain evidence, state uncertainty,
recommend human-reviewable actions. Advisory only.

## Layout
- `challenge/RETROFIT_AI_PARTICIPANTS_2026/` — official package. **READ-ONLY.** Never edit,
  move, delete or reformat anything in it. You may import `retrofit_sim` and run its tools.
- `src/retrofit_assistant/` — our code.
- `tests/` — our tests.
- `docs/specs/`, `docs/decisions/` — specs and ADRs.
- `build/` — all generated outputs (gitignored). Never write outputs elsewhere.

Key docs to read before changing detection logic: `challenge/.../BENCHMARK_RULES.md`,
`DATA_DICTIONARY.md`, `TECHNICAL_MODEL.md`.

## Environment
- Python 3.14, venv in `.venv` at repo root: `source .venv/bin/activate`
- Setup from scratch:
  `python -m pip install -r requirements-lock.txt && python -m pip install -e challenge/RETROFIT_AI_PARTICIPANTS_2026 --no-deps`
- Data root: `challenge/RETROFIT_AI_PARTICIPANTS_2026/data/full` (pass as `--data`, never hard-code
  absolute paths). Prefer `features_1min.parquet`; read 1 Hz telemetry only when needed.

## Commands
- Our tests: `python -m pytest -q tests`
- Official package checks (slow, ~1 min): `python -m pytest -q challenge/RETROFIT_AI_PARTICIPANTS_2026/tests`
- Baselines: `python challenge/RETROFIT_AI_PARTICIPANTS_2026/baselines/run_baselines.py --data challenge/RETROFIT_AI_PARTICIPANTS_2026/data/full --out build/baselines`
- Score a validation file:
  `python -m retrofit_sim score --predictions build/<file>.csv --events challenge/RETROFIT_AI_PARTICIPANTS_2026/data/full/events_validation.csv --assets challenge/RETROFIT_AI_PARTICIPANTS_2026/data/full/assets.csv --benign challenge/RETROFIT_AI_PARTICIPANTS_2026/data/full/benign_windows_train_validation.csv --split validation`
- Reference to beat: B1_mode_aware_z = 78.0 (validation), 58.2 (train). Always report train AND validation.

## Hard rules (benchmark integrity)
1. **Test assets PUMP-10, PUMP-11, PUMP-12:** no tuning, no threshold selection, no labeling, no
   inspection for model decisions, no use of `baselines/results/*_test.csv` as a reference. Allowed
   only: submission runs (milestone safety CSVs and the final one) with output checked for format
   validity only (columns, vocabulary, row count), and the causality test. Fit on train
   (PUMP-01..07), select on validation (PUMP-08, 09).
2. **Causality:** an alert at time t may use only data with timestamp <= t plus static `assets.csv`.
   No centered rolling windows, no whole-window normalization, no backward fill, no look-ahead.
   Every change to detection logic must keep the causality test passing.
3. **Runtime inputs** must exist on test assets too: telemetry, features, vibration snapshots,
   operating context, alarms, `assets.csv`, pre-window maintenance only. Never use events, benign
   windows or in-window maintenance (`in_window = True`) as runtime features.
4. **Alert policy:** exactly one `fault_type` and one `event_class` per alert; respect burst
   (5 min) and repeat (one reminder per 12 h) rules in BENCHMARK_RULES §4. Use `UNKNOWN` when the
   type is uncertain.
5. **Advisory only:** no code that writes to devices, PLCs, drives or valves; no control commands.
6. Do not run `make_dataset.py` or stress generation unless explicitly asked.

## Working rules
- Change only the files assigned in the brief. No commit, push, merge or rm without user confirmation.
- No secrets exist in this project; never create `.env` files with real credentials.
- Done means: tests pass, causality test passes, train + validation scores reported vs B1.
