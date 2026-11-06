Measured by baselines/run_baselines.py (parameters tuned on the training split only).

Chosen parameters: {"B1_mode_aware_z": {"k": 8, "persist_min": 5}, "B2_cusum": {"kappa": 2.0, "h": 120}, "B3_isolation_forest": {"train_quantile": 0.99, "persist_min": 10}}

| Baseline | Split | Composite | Event F1 | Recall | Precision | False + excess alerts / asset-day | Timeliness | Fault-type recall | Class recall | Median lead to deadline (h) |
|---|---|---|---|---|---|---|---|---|---|---|
| B0_scada_alarms | train | 33.2 | 0.39 | 0.33 | 0.46 | 0.25 | 0.31 | 0.06 | 0.33 | -0.0 |
| B0_scada_alarms | validation | 37.8 | 0.40 | 0.25 | 1.00 | 0.00 | 0.25 | 0.25 | 0.25 | - |
| B1_mode_aware_z | train | 61.8 | 0.74 | 0.72 | 0.76 | 0.14 | 0.60 | 0.33 | 0.61 | 14.0 |
| B1_mode_aware_z | validation | 60.8 | 0.67 | 0.50 | 1.00 | 0.00 | 0.50 | 0.50 | 0.50 | 12.0 |
| B2_cusum | train | 56.5 | 0.58 | 0.78 | 0.47 | 0.57 | 0.74 | 0.28 | 0.72 | 10.0 |
| B2_cusum | validation | 51.7 | 0.50 | 0.75 | 0.38 | 0.71 | 0.70 | 0.25 | 0.75 | 27.7 |
| B3_isolation_forest | train | 46.9 | 0.56 | 0.39 | 1.00 | 0.00 | 0.32 | 0.28 | 0.39 | 97.8 |
| B3_isolation_forest | validation | 50.6 | 0.67 | 0.50 | 1.00 | 0.00 | 0.30 | 0.25 | 0.50 | - |
