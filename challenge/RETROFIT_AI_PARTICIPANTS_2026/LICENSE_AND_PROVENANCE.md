# License and provenance

## Synthetic origin

Every telemetry value, alarm, maintenance record, label, waveform and asset description in this package was produced by the simulator in `src/retrofit_sim/`. The simulator was driven by the configuration in `configs/fleet_public.yaml` and by a private test configuration held by the organizers.

- No data were measured on, exported from, or derived from any vessel, plant, company or person. That includes Elomatic, Business Turku and any shipowner or manufacturer.
- Site and vessel names ("Vessel A", "Plant C", ...) are fictional.
- Product names appear only in `RETROFIT_FEASIBILITY.md`, as examples of commercially available equipment with public prices.
- The dataset contains no personal data and no customer data. Maintenance free text is template-generated.
- The data are educational and benchmark material. They are not certification-grade simulation and must not be used as engineering evidence for a real installation.

The generator, its version, the public seed and the configuration hash are recorded in `data/full/provenance.md` and `data/full/manifest.json`. The train and validation data can be regenerated exactly with `python make_dataset.py --tier full --output <dir>` (tables are written to `<dir>/public/`); `tests/test_01_determinism.py` checks this. Test-split data need the organizers' private configuration.

## Licences

| Component | License |
|---|---|
| Simulator, scorer, baselines, tools, tests (`src/`, `baselines/`, `examples/`, `tests/`, `make_dataset.py`) | MIT License (text below) |
| Synthetic data and documentation (`data/`, `figures/`, `*.md`, `START_HERE.html`) | Creative Commons Attribution 4.0 International (CC BY 4.0). Attribute as "RETROFIT AI 2026 synthetic pump benchmark, Since AI Hackathon 2026" |

Third-party Python dependencies are not redistributed. They are installed from PyPI under their own licenses:

| Package | License |
|---|---|
| NumPy | BSD-3 |
| pandas | BSD-3 |
| PyArrow | Apache-2.0 |
| SciPy | BSD-3 |
| scikit-learn | BSD-3 |
| Matplotlib | Matplotlib license (PSF-based) |
| PyYAML | MIT |
| pytest | MIT |
| paho-mqtt (optional) | EPL-2.0 / EDL-1.0 |

No third-party dataset is included or derived.

**Team submissions and IP:** team work, code and intellectual property are governed by the official Since AI 2026 hackathon terms. This package does not create, transfer or assign any rights to Business Turku, Elomatic, the organizers or anyone else.

MIT license text for the code:

> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions: The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## References used to calibrate the model (retrieved October 2026)

Public sources only. Numbers taken from them are reference values for plausibility, not claims about any specific product or installation. Secondary sources are marked (S).

**Pump hydraulics and marine cooling (P)**

| Ref | Topic | Source |
|---|---|---|
| P1 | Ship cooling system with SW/LT/HT pump duty points (400 m³/h, 25 m, 37 kW), LT set-point 36 °C, pressure ranges | Theotokatos et al., *J. Marine Sci. Technol.* 2016: https://strathprints.strath.ac.uk/56472/1/Theotokatos_etal_JMST_2016_Investigation_of_ship_cooling_system_operation_for_improving.pdf |
| P2 | Strainer and filter pressure drop (clean < 0.03-0.1 bar, backflush or alarm about 0.5 bar) | https://www.filternox.com/en/faq (S); https://www.eng-tips.com/threads/pump-suction-strainers-pressure-drop.489626/latest (S) |
| P3 | Stable, rising head curves; head rise to shut-off | https://www.pumpsandsystems.com/stable-and-unstable-pump-curves (S) |
| P4 | Affinity laws and efficiency correction η2 = 1 - (1 - η1)(N1/N2)^0.1 | Simpson & Marchi, *J. Hydraulic Eng.* 139(12), 2013: https://digital.library.adelaide.edu.au/dspace/bitstream/2440/82965/2/hdl_82965.pdf |
| P5 | NPSH3 definition (3 % head drop), POR/AOR | Hydraulic Institute: https://pumps.org/2022/03/21/reliability-basics-understanding-npsh-por-and-aor |
| P6 | IE3 motor efficiency and power factor at part load; starting current | ABB M3BP IE3 catalog: https://library.e.abb.com/public/8d336b612b2642bc95685a1db4a17ebd/9AKK106128%20EN_03_2014_PP%20IE3%20cast%20iron%20generation%20L,%20280-355.pdf ; 75 hp datasheet https://www.mep.ca/Public/pdf/DATA%20SHEET%20IJC250M-4-47.pdf (S) |
| P7 | Drive (VFD) part-load efficiency | US DOE motor tip sheet via NRCan: https://www.nrcan.gc.ca/energy/products/reference/15385 |
| P8 | Archipelago Sea / Baltic surface temperature and salinity | Laakso et al., *Ocean Science* 14, 617-632 (2018): https://os.copernicus.org/articles/14/617/2018/os-14-617-2018.pdf ; HELCOM SST fact sheet: https://helcom.fi/wp-content/uploads/2020/07/BSEFS-Sea-Surface-Temperature-in-the-Baltic-Sea-2018.pdf |

**Condition monitoring and fault signatures (C)**

| Ref | Topic | Source |
|---|---|---|
| C14, C15 | ISO 10816-7 pump vibration zones, alarm and trip | Europump, *Guidelines on Pump Vibration* (2013): https://www.europump.net/files/Publications/Guides/ |
| C21-C22 | Four stages of rolling-bearing failure | https://www.acoem.com/en/blog/do-you-know-the-4-stages-of-bearing-failure/ (S) |
| C24 | Kurtosis and crest-factor behavior | https://sensemore.io/how-is-fault-detection-performed/ (S) |
| C25 | P-F interval lead times | https://reliamag.com/articles/what-is-a-p-f-curve/ (S) |
| C27 | Bearing housing temperature bands | https://machinerylubrication.com/Articles/Print/30608?id=30608 (S) |
| C35-C37 | Bearing geometry (6309/6311/6312) | https://www.nsk.com/engineering/6311-apn.html and related NSK pages |
| C38 | Unbalance and misalignment signatures | https://www.manufacturing.net/home/article/13217368/vibration-due-to-shaft-misalignment (S) |
| C49 | Strainer Δp clean vs dirty | https://www.eng-tips.com/threads/pump-suction-strainers-pressure-drop.489626/latest (S) |
| C60 | Insulation classes | https://myelectrical.com/notes/entryid/122/understanding-electric-motor-insulation-temperature (S) |
| C73 | Pressure transmitter accuracy (±0.25 % span) | https://reotemp.com/products/pressure-transmitters-switches/ta-industrial-pressure-transmitter |
| C81 | Pump MTBF and seal share of failures | https://reliamag.com/guides/pump-reliability-mtbf-statistics/ (S) |
| C97-C98 | Point-adjusted F1 critique; composite F1 | Kim et al., AAAI 2022: https://ar5iv.arxiv.org/html/2109.05257 ; Garg et al. 2021: https://arxiv.org/pdf/2109.11428 |

**Retrofit hardware, OT security, class, business inputs (R)**

LIST prices were seen on the cited pages on 30 Oct 2026.

| Ref | Topic | Source |
|---|---|---|
| R14 | ifm VVB001 | https://buerklin.com/en/p/ifm-electronic/motion-sensors/vvb001/82P8793 |
| R15 | Banner QM30VT2 | https://no.farnell.com/en-NO/banner-engineering/qm30vt2-qp/vibration-temperature-sensor-30vdc/dp/4295202 |
| R16 | Wilcoxon PC420VR-20 | https://fi.farnell.com/en-FI/amphenol-wilcoxon/pc420vr-20/loop-powered-sensor-4-20ma-30vdc/dp/4719983 |
| R18, R20 | Wireless platforms (no public price) | ABB service description: https://library.e.abb.com/public/f99565481af446639a4146ec9c9a9f5f/ABB%20Ability%20Smart%20Sensor%20Service%20Description%20_9AKK107419_REV%20D_JULY2021.pdf |
| R23 | Danfoss MBS 3100 (marine) | https://www.mandmcontrols.com/060g1743 |
| R24 | WIKA A-10 | https://uk.rs-online.com/web/p/pressure-sensors/7255948 |
| R26 | PT100 probe | https://ie.rs-online.com/web/p/rtd-sensors/1780978 |
| R28 | Flexim F721 | https://s1-live.emerson.com/documents/automation/product-data-sheet-flexim-fluxus-f721-ultrasonic-flowmeter-en-10912570.pdf |
| R29 | SITRANS FS230 | https://assets.new.siemens.com/siemens/assets/api/uuid:5b00ef70-7bba-4456-ba19-da9fac875e8b/pifl-00109-0819-sitrans-fs230.pdf |
| R30 | TUF-2000M field report | https://www.libe.net/en-flowmeter (S) |
| R31 | Carlo Gavazzi EM24 | https://uk.rs-online.com/web/p/energy-meters/2864873 |
| R32 | Schneider PM5110 | https://store.greenpeg.com/products/digital-energy/metsepm5110-pm5110-meter-modbus-up-to-15th-h-1do-33-alarms/ |
| R34 | SIMATIC IOT2050 | https://ie.farnell.com/siemens/6es7647-0ba00-1ya2/gateway-24vdc-20-digital-i-o/dp/4008389 |
| R36 | Revolution Pi Connect 4 | https://ie.rs-online.com/web/p/industrial-computers/2713625 |
| R38 | Moxa MGate 5105-MB-EIP | https://befr.rs-online.com/web/p/iot-gateways/2552478 |
| R39 | ifm AL1350 | https://befr.rs-online.com/web/p/sensor-connectivity/0191062 |
| R41 | Sparkplug 3.0 = ISO/IEC 20237 | https://newsroom.eclipse.org/node/39754 |
| R43-R44 | IEC 62443 zones, conduits, security levels | https://www.trout.software/blog/iec-62443-zones-and-conduits-explained (S) |
| R45-R46 | NIST SP 800-82 Rev. 3 | https://csrc.nist.gov/pubs/sp/800/82/r3/final |
| R47 | Unidirectional gateways vs data diodes | https://waterfall-security.com/wp-content/uploads/2025/04/Data-Diodes-vs.-Unidirectional-Gateways-Guide.pdf (vendor) |
| R48-R49 | IEC 61511 / SIS independence | https://webstore.iec.ch/publication/24241 ; https://www.processonline.com.au/content/safety/article/integrating-control-and-safety-where-to-draw-the-line-608324800 (S) |
| R51 | IMO MSC.428(98) | https://www.imo.org/en/OurWork/Security/Pages/Cyber-security.aspx |
| R52-R55 | IACS UR E26 / E27 | https://iacs.org.uk/news/iacs-ur-e26-and-e27-press-release ; https://www.pentestpartners.com/security-blog/iacs-ur-e26-and-e27-guidance/ (S) |
| R57-R58 | ABS machinery reliability and condition monitoring guide (2023) | https://ww2.eagle.org/content/dam/eagle/rules-and-guides/current/survey_and_inspection/121-guide-for-surveys-based-on-machinery-reliability-and-maintenance-techniques/MRM_Guide_e-Jan23.pdf |
| R60 | Lloyd's Register machinery survey and condition monitoring | https://www.lr.org/en/insights/articles/210621-new-guidance-notes-simplify-machinery-survey-maintenance-evolution/ |
| R61-R64 | DNV condition-based maintenance, approved service suppliers | https://www.dnv.com/services/offshore-classification/fleet-in-service/condition-based-maintenance/ |
| R74 | NORDEN / Danfoss seawater pump drives (vendor case) | https://danfoss.com/da-dk/service-and-support/case-studies/cf/shipping-company-saves-half-a-million-on-seawater-pumps |
| R75 | ABB / Tsakos seawater pump drives (vendor case) | https://new.abb.com/gr/our-businesses/automation/tsakos-success-story |
