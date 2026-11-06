# Provenance of this data build

| Item | Value |
|---|---|
| Content | Synthetic data from the RETROFIT AI 2026 pump simulator (no measured data) |
| Tier | full |
| Generator | retrofit_sim 1.0.0 (`src/retrofit_sim/`) |
| Public fleet configuration | `configs/fleet_public.yaml`, SHA-256 3963529068778cd84a9c515ddf03e6bfc40c8f5908e438753ea45230b42f161d |
| Public seed (train + validation) | 20261106 |
| Test split | generated from a private configuration and seed held by the organizers |
| Build date (UTC) | 2026-10-30 |
| Build environment | Python 3.13.17, numpy 2.5.3, pandas 3.0.5, pyarrow 26.0.0, scipy 1.18.1, scikit-learn 1.9.1 |
| Regenerate | `python make_dataset.py --tier full --output <dir>` reproduces the train/validation tables of this build |
