# Retrofit feasibility

This document is a practical frame for the "low-cost retrofit feasibility and transfer" criterion. It covers what can be added to an existing pump, what it roughly costs, how to connect it without touching control or safety systems, and how a pilot could be run.

Prices marked **LIST** are public web-shop or distributor prices seen on 30 Oct 2026. They exclude VAT unless stated, and the currency conversions are indicative. Prices marked **ASSUMPTION** are estimates where no public price exists; replace them with quotes. Nothing here is a vendor recommendation.

## 1. Minimum instrumentation pathways

| Level | What it adds | What it can see (in this benchmark and in practice) | What it cannot see |
|---|---|---|---|
| 0: existing signals only | motor current (MCC/drive), discharge pressure, drive speed/power if a VFD exists | hydraulic changes (restriction, impeller wear, clogging on variable-speed drives), stuck or offset transmitters, communication loss | early bearing damage, imbalance and misalignment (no vibration sensor; see PUMP-05 in the training data) |
| 1: low-cost retrofit | suction pressure transmitter, battery wireless vibration and temperature sensor on the pump bearing housing | clogging and cavitation (suction side), bearing damage from stage 2 (acceleration, crest factor), imbalance and misalignment | short events between sparse (5-min) updates; flow-based efficiency |
| 2: full | wired vibration (IO-Link, 1 s), power meter, flow meter, winding PT100, valve feedback | the pump's operating point and efficiency, early and fast faults, better sensor-versus-machine discrimination | still no direct seal-leak detection (not in this benchmark) |

Rule of thumb for transfer to other rotating machines: start with what the drive or MCC already knows, add one vibration and temperature point per critical bearing, and add process measurements only where they change a decision.

## 2. Illustrative bill of materials (one pump)

| Item | Example | Price | Label |
|---|---|---|---|
| Wired vibration + temperature, IO-Link | ifm VVB001 | EUR 632 incl. VAT (about EUR 530 ex VAT) | LIST [R14] |
| Wired vibration + temperature, Modbus RTU | Banner QM30VT2-QP | NOK 3,772 (about EUR 320) | LIST [R15] |
| Loop-powered 4-20 mA vibration transmitter | Wilcoxon PC420VR-20 | EUR 510 | LIST [R16] |
| Wireless vibration platforms (ABB, SKF, Schaeffler, Emerson, KSB) | per point + gateway + subscription | EUR 300-1,500 per point, gateway EUR 1-3 k | ASSUMPTION [R18, R20] |
| Pressure transmitter, industrial | WIKA A-10 0-10 bar | about EUR 145 | LIST [R24] |
| Pressure transmitter, class-approved (ships) | Danfoss MBS 3100 | about EUR 288 | LIST [R23] |
| PT100 probe | RS PRO class B, 4-wire | EUR 108 | LIST [R26] |
| Energy meter, Modbus | Carlo Gavazzi EM24 / Schneider PM5110 | about EUR 430 / about EUR 630 | LIST [R31, R32] |
| Clamp-on flow, indicative | TUF-2000M class | EUR 200-400 (needs on-site calibration) | LIST, field report [R30] |
| Clamp-on flow, instrument grade | Flexim F721 / SITRANS FS230 | EUR 3-10 k | ASSUMPTION [R28, R29] |
| Edge computer | Revolution Pi Connect 4 / SIMATIC IOT2050 | EUR 497 / EUR 602 | LIST [R36, R34] |
| IO-Link master | ifm AL1350 | EUR 373 | LIST [R39] |
| Protocol gateway (Modbus to MQTT/EtherNet/IP) | Moxa MGate 5105-MB-EIP | EUR 769 | LIST [R38] |

Indicative packages, before cabling, enclosure, installation labor, class or flag approvals and software:

| Option | Contents | Hardware total |
|---|---|---|
| A: wired minimum | 2 x VVB001, AL1350, 2 pressure transmitters, PT100, EM24, RevPi | about EUR 2.8-3.1 k |
| B: Modbus minimum | 2 x QM30VT2, the same instruments, IOT2050 | about EUR 2.1-2.4 k |

Add EUR 0.2-0.4 k (indicative) or EUR 3-10 k (instrument grade) for flow [R28-R30]. These totals are an **ASSUMPTION** built from the LIST prices.

A drive retrofit on a seawater pump is a separate lever (energy, not monitoring). Published cases report US$30 k per vessel per year with payback under 14 months (NORDEN/Danfoss) and more than 60 % pump energy saved (ABB/Tsakos) [R74, R75]. These are vendor-reported figures. Monitoring can share the drive's data and the same edge box.

## 3. Read-only integration architecture

Ship and plant cyber-security rules, and plain good practice, require that the monitoring layer can only listen: it reads data and never sends commands to the machine or its control system.

```
 [ Safety system / SIS ]   own zone, untouched, authoritative trips and interlocks
 [ PLC / drive / MCC ] ── read-only (OPC UA read nodes, Modbus read registers, drive fieldbus mirror)
         │
 [ Retrofit sensors ] ──> [ Edge box in its own zone ]  local buffer + inference, works offline
                                   │  one-way conduit (DMZ or unidirectional gateway)
                                   ▼
                         [ Historian / dashboard / cloud ]  advisory alerts to humans
```

- **No write path.** The monitoring layer cannot write to the PLC, drive, valves or safety system. Existing alarms and trips stay authoritative. This follows IEC 62443 zone/conduit practice [R43, R44], NIST SP 800-82r3 (DMZ, unidirectional gateways) [R45-R47] and IEC 61511 independence of safety layers [R48, R49].
- **Ships.** On vessels contracted from 1 July 2024, IACS UR E26/E27 apply [R52-R55]. A cloud-connected box is a connection to an untrusted network: keep it outside the E26 zones or make it one-way, and record it in the asset inventory and the management-of-change process [R52-R55]. IMO MSC.428(98) puts cyber risk into the safety management system [R51].
- **Edge and offline.** Detection should run on the edge box with local buffering (hours to days) and work without connectivity at sea. The replay tool (`python -m retrofit_sim replay`) emits the same MQTT-style messages a gateway would. Sparkplug 3.0 (ISO/IEC 20237) is one option for an OT topic namespace [R41].
- **Class credit** for condition-based maintenance needs an approved planned maintenance scheme, baselines, limits and actions, and often an approved service supplier [R57-R64]. A hackathon prototype is advisory and earns no class credit by itself.

## 4. Pilot validation path (realistic sequence)

1. **Read-only data first.** Connect to existing signals (historian export or read-only OPC UA/Modbus) for 4-8 weeks. Establish per-regime baselines. No alerts go to operators yet.
2. **Shadow mode.** Alerts are logged and compared afterwards with operator logs, alarms and work orders. Measure precision, lead time and nuisance rate per asset-week against what operators actually decided.
3. **Add one retrofit point** where shadow mode shows blind spots, for example wireless vibration on a critical pump without redundancy.
4. **Advisory pilot.** Alerts go to a named role with an evidence view and a feedback button. Agree beforehand on actions and on how a false alert is closed.
5. **Review.** Decide on scale-up from measured value (avoided stops and repairs, minus nuisance), not from model accuracy alone. An independent engineering and regulatory review is needed before any operational use.

## 5. Worked business example (illustrative, synthetic)

The script `examples/business_case.py` links benchmark metrics to money. Its inputs are the measured baseline recall and false-alert rate, plus stated assumptions; change them to test your own solution.

All inputs are assumptions or benchmark measurements on synthetic data. This is a worked example of the business logic, not a realized or expected saving for any real site.

### Inputs

| Input | Value | Unit | Basis |
|---|---|---|---|
| Developing faults per year | 0.6 | 1/yr | assumption: developing faults that would otherwise end in an unplanned stop (bearing, clogging/cavitation, restriction) for one duty pump |
| Share caught early (recall) | 0.889 | - | measured: B1 baseline validation event recall (replace with your own) |
| False + excess alerts per pump-day | 0.071 | 1/asset-day | measured: B1 baseline validation false + excess-repeat alerts per asset-day |
| Unplanned stop duration | 10 | h | assumption: detection by failure, diagnosis, parts, repair |
| Planned stop duration | 3 | h | assumption: same work prepared and done in a planned window |
| Downtime cost | 1500 | EUR/h | assumption: production loss of a mid-size process line with no redundant pump |
| Repair cost, unplanned | 9000 | EUR | assumption within a typical EUR 3-15 k small/medium pump overhaul range (itself an estimate) |
| Repair cost, planned | 4000 | EUR | assumption: damage limited when caught early (e.g. bearing only, no shaft/seal damage) |
| Cost of checking one false alert | 120 | EUR | assumption: ~1.5 h of technician/operator time to check a false alert |
| Installed cost (hardware + installation) | 4500 | EUR | BOM option B ~EUR 2.1-2.4 k (built from list prices, RETROFIT_FEASIBILITY.md section 2) + cabling, enclosure, installation ~EUR 2 k (assumption) |
| Operating cost | 700 | EUR/yr | assumption: connectivity, software maintenance, battery/sensor replacements |

### Result (base case)

- Faults caught early per year: 0.53
- Avoided downtime and repair cost: EUR 8,268 per year
- False-alert handling cost: EUR 3,110 per year
- Net annual effect after operating cost: EUR 4,458
- Simple payback on EUR 4,500 installed cost: 1.0 years

### Sensitivity (one input changed at a time)

| Input | Low | High | Net EUR/yr at low | Net EUR/yr at high | Payback at low | Payback at high |
|---|---|---|---|---|---|---|
| Developing faults per year | 0.2 | 1.2 | -1,054 | 12,726 | never | 0.4 yr |
| Share caught early (recall) | 0.4 | 0.95 | -90 | 5,025 | never | 0.9 yr |
| False + excess alerts per pump-day | 0 | 0.5 | 7,568 | -14,332 | 0.6 yr | never |
| Downtime cost | 0 | 5000 | -1,143 | 17,526 | never | 0.3 yr |
| Repair cost, unplanned | 5000 | 15000 | 2,324 | 7,658 | 1.9 yr | 0.6 yr |
| Installed cost (hardware + installation) | 2500 | 12000 | 4,458 | 4,458 | 0.6 yr | 2.7 yr |

### Break-even and redundancy

- Break-even: with these assumptions, a 5-year payback needs a downtime cost of about EUR 547 per hour.
- Redundant duty/standby pump (e.g. a ship seawater pump with a healthy standby, downtime cost about 0) and 0.3 events per year: net effect EUR -2,476 per year, so payback never. Here the case rests on repair-cost avoidance, energy (drive retrofits are a separate, documented lever) and crew time, not on downtime.
- Each false alert per asset-day costs about EUR 43,800 per year in checks alone and erodes operator trust; the benchmark weights alert burden for this reason.


## 6. When additional instrumentation is not cost-effective

- **Redundant pumps** with an automatic standby and low repair cost, where downtime cost is near zero. Use existing current and pressure plus a periodic handheld route.
- **Low-value or spare-on-shelf pumps** that can be swapped in minutes.
- **High false-alert rates.** Each daily false alert costs operator time and trust, so a noisy system is worse than none. The benchmark penalizes alert burden for this reason.
- **Expensive certification** for the location, for example hazardous areas or class-approved installation on a ship, when it exceeds the plausible avoided cost.
- **No organizational owner** to act on alerts. Monitoring without a maintenance decision process produces data, not value.
