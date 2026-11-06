Measured by baselines/run_baselines.py (parameters tuned on the training split only).

Chosen parameters: {"B1_mode_aware_z": {"k": 6, "persist_min": 15}, "B2_cusum": {"kappa": 2.0, "h": 60}, "B3_isolation_forest": {"train_quantile": 0.99, "persist_min": 10}}

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
