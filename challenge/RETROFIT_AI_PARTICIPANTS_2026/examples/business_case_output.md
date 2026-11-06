# Illustrative business case: one retrofitted duty pump (synthetic scenario)

All inputs are assumptions or benchmark measurements on synthetic data. This is a worked example of the business logic, not a realized or expected saving for any real site.

## Inputs

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

## Result (base case)

- Faults caught early per year: 0.53
- Avoided downtime and repair cost: EUR 8,268 per year
- False-alert handling cost: EUR 3,110 per year
- Net annual effect after operating cost: EUR 4,458
- Simple payback on EUR 4,500 installed cost: 1.0 years

## Sensitivity (one input changed at a time)

| Input | Low | High | Net EUR/yr at low | Net EUR/yr at high | Payback at low | Payback at high |
|---|---|---|---|---|---|---|
| Developing faults per year | 0.2 | 1.2 | -1,054 | 12,726 | never | 0.4 yr |
| Share caught early (recall) | 0.4 | 0.95 | -90 | 5,025 | never | 0.9 yr |
| False + excess alerts per pump-day | 0 | 0.5 | 7,568 | -14,332 | 0.6 yr | never |
| Downtime cost | 0 | 5000 | -1,143 | 17,526 | never | 0.3 yr |
| Repair cost, unplanned | 5000 | 15000 | 2,324 | 7,658 | 1.9 yr | 0.6 yr |
| Installed cost (hardware + installation) | 2500 | 12000 | 4,458 | 4,458 | 0.6 yr | 2.7 yr |

## Break-even and redundancy

- Break-even: with these assumptions, a 5-year payback needs a downtime cost of about EUR 547 per hour.
- Redundant duty/standby pump (e.g. a ship seawater pump with a healthy standby, downtime cost about 0) and 0.3 events per year: net effect EUR -2,476 per year, so payback never. Here the case rests on repair-cost avoidance, energy (drive retrofits are a separate, documented lever) and crew time, not on downtime.
- Each false alert per asset-day costs about EUR 43,800 per year in checks alone and erodes operator trust; the benchmark weights alert burden for this reason.
