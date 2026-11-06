# Technical model

This document describes how the synthetic data are generated: the pump and system model, operating context, fault processes, instrumentation, and how labels are derived. It also states the limits of the model. The simulator is a reduced-order, quasi-steady model built from textbook pump relations and published reference values. It is not a validated digital twin, and its outputs are not measurements.

Source code: `src/retrofit_sim/` (`physics.py`, `plant.py`, `context.py`, `faults.py`, `sensors.py`, `labels.py`, `generate.py`). References in square brackets are listed in `LICENSE_AND_PROVENANCE.md`.

## 1. Generation pipeline (per asset, 1 s time step)

```
seeded RNG streams (seed, asset_id)
  -> fault plan (scenario + seeded onset jitter, repairs become locked-out maintenance stops)
  -> operating context (schedule, duty demand, inlet temperature, ambient, suction level, sea state, supply voltage)
  -> latent condition states (bearing wear, strainer clog, restriction, misalignment, unbalance, impeller wear, air)
  -> plant: control -> speed / valve -> operating point (incl. cavitation) -> power -> thermal -> vibration   [true state]
  -> instruments: lag, calibration offset/gain, noise, resolution, range, update interval, dropouts, instrument faults
  -> public tables (telemetry, alarms, maintenance log, context, features, waveform snapshots)
  -> labels from counterfactual runs (fault-only vs healthy) and the true state
```

Every observed change has a physical or instrument cause. Faults change state variables before any signal is computed. Instrument faults change only the stored reading, never the physics.

## 2. Pump family (one coherent model for all assets)

Speed ratio r = n / n_rated. Flow ratio at the current speed q = Q / (r Q_BEP).

| Quantity | Relation | Notes |
|---|---|---|
| Head | H = H_BEP (h0 r^2 - (h0 - 1)(Q/Q_BEP)^2) f_H | h0 = shut-off head / BEP head, 1.18-1.22 (datasheets show 1.13-1.22; API 610 requires a rising curve [P3]). Affinity scaling is built in. |
| Head factor | f_H = (1 - w_imp)(1 - 2.5 alpha_air) f_cav | impeller / wear-ring wear, entrained gas, cavitation |
| Efficiency | eta = eta_r q (2 - q), eta_r = 1 - (1 - eta_BEP) r^-0.1 | parabolic around BEP; Sarbu-Borza speed correction, shown by Simpson and Marchi to be reasonable down to about 70 % speed [P4] |
| Shaft power | P = rho g Q_BEP H_BEP / eta_r * r^3 * h(q) / (2 - q) * (1 + 0.04 w_brg^2 + 0.02 m) | algebraically equal to rho g Q H / eta, finite at shut-off; small friction increase from bearing wear and misalignment |
| NPSH3 | NPSH3 = NPSH3_BEP r^2 (0.55 + 0.45 q^2.6) | rises steeply above BEP flow |

Validity: 0.5 <= r <= 1.0 and 0.3 <= q <= 1.3 are the intended operating range. Outside it (start-up ramps, shut-off) the model stays finite and monotone, but it is not accurate.

Asset ratings span 50-650 m³/h, 24-46 m, 11-75 kW, 2- and 4-pole motors at 400 V/50 Hz (industrial) or 440 V/60 Hz (marine). Each asset passes the check hydraulic power / BEP efficiency < motor rating < 2 x shaft power (`tests/test_02_schema_values.py`). The ship seawater duty points are consistent with published reference vessels, e.g. 400 m³/h at 25 m on 37 kW for a handymax bulk carrier [P1].

## 3. System curve and operating point

H_sys = H_static + K_total Q^2, with K_total = K_pipe * R + K_valve(x) + K_suction(c).

- **K_pipe**: piping and heat-exchanger resistance on the discharge side, sized so the design point lies on the curve. R >= 1 is the restriction multiplier (fouled heat exchanger, valve left partly closed).
- **K_valve(x)**: an equal-percentage valve with rangeability 50, so K ∝ 50^(2(1 - x)) at position x.
- **K_suction(c)** = K_s0 (1 + s((1 + c)^2 - 1)). The suction loss is about 0.5-0.9 m at design flow, and s is the strainer share of that loss. A clog level c = 3 multiplies the strainer loss by 16. That is roughly the 0.1 to 0.5-1.5 bar range between a clean strainer and a backflush or alarm trigger [P2, C49].
- **H_static**: 3 m overboard lift for the ship seawater (SW) circuit, 0 m for the closed low-temperature (LT) fresh-water loop (pressurized to 120 kPa), 7 m for the cooling tower, and 8 m for the process transfer.

**Cavitation.** NPSHa = (p_tot - p_v) / (rho g), where p_tot = p_atm + p_loop + rho g (z_s + roll - K_suction Q^2) is the total head at the pump inlet. The suction gauge reads the static pressure p_tot - rho v^2 / 2, with the suction line sized for 2.5 m/s at BEP flow. The vapor pressure p_v comes from the Antoine equation. Rolling of the vessel adds a suction-head oscillation of 0.25 * Hs m at the roll period. The margin sigma = NPSHa / NPSH3 sets a head factor f_cav = 1 - 0.03 exp(-6(sigma - 1)), clipped at 0.55. This gives a 3 % head drop at sigma = 1 (the NPSH3 definition [P5]), negligible loss above about 1.3, and breakdown below 1.

Because f_cav depends on Q, the operating point is the fixed point Q* = g(Q*). Here g(Q) is the pump/system intersection evaluated with f_cav(Q). g is non-increasing, so the fixed point is found by bisection. The suction gauge pressure never falls below vapor pressure. This is a simplified one-dimensional NPSH approximation; it is not computational fluid dynamics (CFD) and does not model the onset of recirculation.

## 4. Control strategies (one per asset; listed in `assets.csv`)

| Control | Profile | Logic |
|---|---|---|
| `VFD_TEMPERATURE` | ship SW cooling | Required flow = demand * (T_set - T_design) / (T_set - T_sea), with T_set = 36 °C [P1] and T_design = 25 °C (Baltic-trade design, an assumption). It is clipped to 40-115 % of design flow. Speed is the inverse of the operating point, limited to the drive minimum (0.5-0.6) and with a 25 s lag. In cold water the pump sits at minimum speed. |
| `VFD_PRESSURE` | cooling-tower circulation | Constant header differential pressure. Consumer valves open with demand, and speed is solved for the set-point head. |
| `FLOW_VALVE` | process transfer | Fixed speed. The control valve tracks the batch flow set-point (6 s lag) and saturates fully open when the system can no longer deliver the flow. |
| `FIXED_SPEED` | LT fresh-water loop, legacy CW pumps | Direct-on-line (DOL). Flow is set by the system curve. |

Start-up ramps the speed up (DOL: a few seconds to speed, current inrush about 6.5-7 x rated [P6]; drive: ramped, current about 1.1 x). On a stop command the contactor (or drive output) opens at the start of `STOPPING`: motor current and power drop to zero and the pump coasts down with a 4-8 s time constant. Start-up and load-change transients are deliberately present and labeled as benign windows. Every asset also has at least one routine planned lockout (inspection, lubrication; 0.75-4 h) unrelated to faults, and repair stops vary in length, so a lockout alone does not reveal a repair.

## 5. Motor and drive

- **Losses.** L = L_rated (0.35 + 0.65 lambda^2), where lambda = P_shaft / P_rated and L_rated = P_rated (1/eta_rated - 1). This keeps efficiency nearly flat from 50 to 100 % load, as in IE3 catalog data [P6].
- **Power factor.** pf = pf_rated (1 - e^(-lambda/0.3)) / (1 - e^(-1/0.3)). This gives about 0.72 at half load against 0.75 in catalog data [P6]. Line current I = P_in / (sqrt(3) V pf), so a lightly loaded motor still draws magnetising current.
- **Drive efficiency.** 0.88 / 0.93 / 0.96 / 0.97 at 12.5 / 25 / 50 / 100 % load (US DOE table [P7]).
- **Slip.** Rated slip 1.2-2.5 %, proportional to load. Supply-voltage sags (benign) briefly raise current and winding temperature.

## 6. Thermal model

- **Fluid.** Pump losses heat the liquid, which matters at low flow: dT = (P_shaft - P_hyd) 0.9 / (rho c_p Q), with a 60 s lag.
- **Bearing housing.** Steady state 0.6 T_ambient + 0.4 T_fluid + k_b r^1.3 (0.75 + 0.25 lambda) + 40 (w - 0.4)^1.6 (0.4 + 0.6 r) + 6 m r, followed by a first-order lag (tau 1100-1500 s). Healthy values are 35-55 °C, or about 65 °C on the hot process pump. These are well below the 82 °C caution band [C27] and the 85 °C alarm used here.
- **Winding.** T_ambient + k_w (0.25 + 0.75 lambda^2) / V_pu^2, with tau 1500-2400 s, and below class-F limits [C60].

## 7. Vibration

The overall velocity RMS (10-1000 Hz) is the root-sum-square of these components:

| Component | Model |
|---|---|
| Structural | v_s (0.4 + 0.6 r^1.5) |
| Unbalance (1x) | (v_u0 + 4 u) r^2, so force rises with speed squared [C38] |
| Misalignment (1x/2x) | 4.5 m (0.5 + 0.5 lambda) r |
| Hydraulic, off-BEP | v_h r^2 abs(q - 1)^1.5, tripled below q = 0.5 (recirculation) |
| Cavitation / air | v_c I_cav r^2 + 3 alpha r, with I_cav = clip((1.25 - sigma) / 0.45, 0, 1) |
| Bearing defect | 14 (w - 0.4)^1.5 (0.3 + 0.7 r), visible in velocity only in late stages [C21, C22] |

Process variability is a log-normal Ornstein-Uhlenbeck factor of about 4 % (tau 3 min). A short spike occurs when the start-up passes through resonance. The acceleration RMS adds a high-frequency bearing term 2.2 (w - 0.12)^1.3 r, which appears early (stage 2), and a cavitation term. The crest factor rises from about 3.2 to about 6 during early, localized bearing damage, then falls back towards 3.5 as damage spreads [C24].

Healthy levels are 0.7-2.5 mm/s, in zone A/B of ISO 10816-7. Alarm and trip limits follow ISO 10816-7 as quoted by Europump [C14, C15]:

| Category | Alarm | Trip |
|---|---|---|
| Category I (ship cooling, critical duty, <= 200 kW) | 5.0 mm/s | 8.3 mm/s |
| Category II (industrial, <= 200 kW) | 6.4 mm/s | 10.6 mm/s |

**Waveform snapshots** (`vibration_snapshots.parquet`, every 4 h on assets with a vibration sensor) are 1 s acceleration records at 10.24 kHz. They are synthesized from the same components:

- 1x, 2x and 3x running-speed lines and vane-pass lines;
- for bearing damage, an outer-race impulse train at BPFO that excites a 2.8 kHz housing resonance;
- band-limited cavitation noise;
- a sensor noise floor.

The BPFO and BPFI orders in `assets.csv` are computed from the bearing geometry of NSK 6309/6311/6312 bearings [C35-C37]. The pitch diameter is assumed to be (bore + OD) / 2.

## 8. Operating context

| Profile | Schedule and environment |
|---|---|
| Ship SW / LT (fictional RoPax) | Night/day liner: 10.5 h at sea (demand about 0.88), 0.6 h manoeuvring (about 0.62), 1.4 h in port (about 0.38), with seeded variation. Duty/standby changeovers stop the pump for 6-30 h. One storm passage (Hs up to about 4 m) gives roll-induced suction oscillation. Monthly Archipelago Sea surface temperature [P8]: 1.5, 0.5, 0.5, 2.5, 7, 13, 17.5, 18, 14, 10, 6, 3 °C, with route variation. Engine-room air about 36 °C. Brackish water at 6 PSU, density about 1004 kg/m³ [P8]. |
| Industrial cooling-tower water | Two shifts (06-22), reduced night and weekend demand. Basin temperature from a monthly wet-bulb proxy + approach + diurnal swing. One production stop of 2-14 h with probability 0.5. |
| Process transfer | Batches of 1-4 h, idle gaps of 0.2-1.5 h, flow set-points of 60-100 % of design, mid-batch set-point changes. Process water at 62-66 °C, so vapor pressure makes cavitation more likely. |

All profiles carry slow demand fluctuation (4 %, tau 30 min), supply-voltage noise and seeded voltage sags.

## 9. Fault processes (latent state, `faults.py`)

| Fault | Latent variable and growth | Main physical effect |
|---|---|---|
| `BEARING_WEAR` | w = w_b + s (exp(k tau) - 1), where s makes w reach 0.95 at t_fail. Accelerating growth, reset by bearing replacement | accel, crest factor (stage 2) -> velocity, temperature (stage 3-4); slight friction power |
| `SUCTION_STRAINER_CLOGGING` | clog c rises linearly to c_max, reset by cleaning | suction loss ∝ (1 + c)^2 Q^2: lower suction pressure, lower flow, or more speed or valve opening on controlled loops; cavitation when NPSHa falls |
| `CAVITATION` | emergent, not injected: sigma < 1.15 for >= 5 min while running | head drop, broadband acceleration, vibration, pressure loss |
| `DISCHARGE_RESTRICTION` | R = 1 + extra (1 - exp(-k tau)); fast (valve) or slow (heat-exchanger fouling) | higher discharge pressure (fixed speed), lower flow and power |
| `MISALIGNMENT` | step m after re-installation, optional growth | 1x/2x vibration, bearing and winding temperature, small power increase |
| `IMBALANCE` | unbalance u ramps (fouled impeller) | 1x vibration ∝ speed^2, no acceleration signature |
| `IMPELLER_WEAR` | head loss w_imp, slow | lower head and pressure at the same flow; visible only against the pump curve |
| `AIR_ENTRAINMENT` | gas fraction alpha (sea-chest aeration in heavy weather, vortexing at low basin level) | head loss, erratic broadband vibration |
| Instrument faults | drift (ramp), calibration shift (step), stuck (frozen value), noise/spikes, communication loss (gateway rows missing, or channel NaN with the `COMM_LOSS` quality bit) | reading only |

Compound incidents in the data include:

- strainer clogging -> cavitation;
- bearing replacement -> post-maintenance misalignment;
- planned seal or motor work -> misalignment;
- restriction repair -> transmitter calibration offset;
- low basin level -> air entrainment;
- a drifting suction transmitter that masks a clogging strainer (test split only).

## 10. Instrumentation tiers (`sensors.py`)

| Tier | Channels | Typical source |
|---|---|---|
| T0_LEGACY | motor current, discharge pressure, fluid temperature, ambient (+ drive speed/power if a VFD exists) | MCC / PLC 4-20 mA |
| T1_RETROFIT | T0 + suction pressure + battery wireless vibration (velocity, acceleration, crest) and bearing temperature, **one value per 300 s** | low-cost retrofit |
| T2_FULL | T1 at 1 s (IO-Link vibration), + flow meter, power meter, winding PT100, valve feedback | well-instrumented |

Each channel has:

- a range;
- noise (pressure about 0.25 % of span [C73], current 0.4 % of a 0-2 x rated range, flow 0.5 % of BEP + 1 % of reading);
- a unit calibration offset and gain;
- resolution;
- a first-order transmitter lag;
- an update interval;
- random single-sample drops (0.15 %).

Readings outside the transmitter range saturate and are flagged (noise clipped just below zero is not). While the pump is stopped, current, speed and power read about 0. The quality bitmask is `COMM_LOSS` 1, `OUT_OF_RANGE` 2, `STALE` 4, `BAD_SENSOR_STATUS` 8, `STARTUP_INHIBIT` 16. Bit 1 marks a single instrument that stopped reporting; during gateway outages whole rows are absent instead, which is the case for all communication-loss events in this release. Bits 4 and 8 are defined for compatibility but are not set in this release.

Controllers use their own (separate) transmitters, so an instrument fault on the monitoring channel does not change the control action.

## 11. Labels (`labels.py`, `generate.py`)

- **Onset.** Physical onset of the latent process, clipped to the window start for pre-existing conditions.
- **Detectable.** For each machine fault the simulator is re-run twice with identical random streams: once with only that fault and once healthy. The first time the 10-min mean difference on any instrumented channel exceeds 3 x its noise is the detectable time. Sparse channels count fewer samples. Vibration and current also need a change above 2 % of the healthy value. A channel does not count while an instrument fault or a data gap affects it, so a drifting transmitter can mask a real fault. Instrument faults: a drift becomes detectable when it exceeds 3 x the noise of a 10-min mean, a calibration step when it exceeds the same threshold (5 min after the step; smaller steps are unobservable), a stuck reading once it has lasted longer than the channel's normal constant runs (p99.9, at least 10 min), and noise or spikes after 5 min. If this never happens with the asset's instruments, the event is `observable = False` and is not scored. This is how "the physics does not support detection here" is represented.
- **Cavitation episodes.** An episode is labeled when the NPSH margin stays below 1.15 for at least 5 min while running (episodes less than 30 min apart are merged). Evidence channels are the instrumented signals whose episode mean departs from the healthy system by more than 3 x the noise of a 10-min mean; an episode with no such channel is unobservable. Its action deadline is the first time the margin stays below 1.1 for 60 s.
- **Action deadline.** The first sustained time a conventional limit is reached while the fault is active and materially contributes (>= 25 % of the deviation). It is computed on the true plant state; the displayed reading can differ by the sensor's calibration error, so a deadline can occur without a plant alarm:
  - vibration-type faults: vibration above the ISO 10816-7 alarm, or bearing temperature above 85 °C;
  - hydraulic faults: cooling flow more than 10 % below the healthy system at the same duty, flow below 95 % of the controller's requirement, or NPSH margin below 1.1.
- **Severity.** Based on peak vibration (zone B upper / trip), flow loss (8 % / 20 %), minimum NPSH margin, or impeller head loss.
- **Benign windows.** Start-up, shutdown, load change, set-point change, standby changeover, planned stop, maintenance restart, heavy weather and voltage sag.

Operator-facing records are deliberately imperfect:

- SCADA alarms use fixed limits, on-delays, deadbands, start-up inhibit and realistic acknowledgement delays (longer at night).
- Maintenance records carry free-text observations that are sometimes a wrong suspicion, with a `diagnosis_confidence` field.

## 12. Limitations

The following are not modeled:

- **Not in the fault set:** mechanical seal leakage (the most common real pump failure [C81]), rotor dynamics and critical speeds, water hammer, electrical rotor or stator faults, motor current signature analysis (MCSA) sidebands.
- **Control simplifications:** controllers react to changes in hydraulic resistance (clogging, restriction) but do not compensate head lost to entrained air or cavitation, which a real closed loop partly would.
- **System simplifications:** parallel pump staging and duty/standby hydraulic interaction (each asset is one pump in its own loop), and explicit heat-exchanger thermal dynamics. Temperature control acts through the required-flow relation.
- **Simplified approximations:** cavitation is a one-dimensional NPSH approximation; impeller wear acts only through a head factor; vibration is a component model, not a finite-element or rotordynamic model.
- **Parameter uncertainty:** fault growth rates are compressed into a 7-day window. Real bearing and fouling processes usually take weeks to months [C25].
- **Assumed inputs:** seawater temperature is a climatological profile with noise, not observations. Prices, costs and some ratings are assumptions (`RETROFIT_FEASIBILITY.md`).

Results obtained on these data show that a method works on a physically coherent synthetic benchmark. They are not evidence of field performance.
