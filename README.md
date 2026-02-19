# ⛈ Severe Weather Environment Diagnostics Hub

An ingredient-based severe weather environment analysis tool built with **NiceGUI**, powered by a **HRRR → NAM-3km → GFS → Open-Meteo** model fallback chain. Enter any city name or lat/lon and get a full diagnostic breakdown of convective potential across the next 24–48 hours.

> **Not an official forecast product.** Always consult [SPC](https://www.spc.noaa.gov/) and [NWS](https://www.weather.gov/) for operational decisions.

---

## 🔴 Live Demo

**[Try it on Hugging Face Spaces →](https://huggingface.co/spaces/Freshwaffle23426/Weather-Risk-Checker)**

---

## What It Does

Rather than issuing a simple yes/no severe weather forecast, this tool reasons through an atmospheric setup the way a human forecaster would — evaluating instability, kinematics, moisture, and composite parameters together — then explains *why* storms might succeed or fail.

Each analyzed time step returns:

- **Convective mode** — Pulse, Multicell, QLCS, Supercellular, or Tornadic Supercells
- **Environmental support level** — scored tier from None → Extreme
- **Full composite parameter suite** — SCP, STP, EHI, SHIP, VGP, Craven-Brooks
- **Mesoscale boundary detection** — θe gradient analysis on the model grid
- **Fail mode identification** — explicit reasoning on why storms may not materialize

---

## 🗂 Project Structure

```
Weather-Risk-Checker/
├── src/
│   ├── met_core.py          # Pure meteorology — CAPE/CIN, SRH, Bunkers, composites
│   ├── data_fetcher.py      # Model chain: HRRR → NAM → GFS → Open-Meteo
│   ├── analysis_engine.py   # Scoring, convective mode, fail mode reasoning
│   └── weather_checker.py   # NiceGUI app (entry point)
├── tests/
│   ├── fixtures/
│   │   └── sample_profile.json
│   ├── test_met_core.py
│   └── test_analysis.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## 📊 Parameters Analyzed

### Instability
| Parameter | Description |
|-----------|-------------|
| MLCAPE | Mixed-layer CAPE — primary instability measure (J/kg) |
| MUCAPE | Most-unstable CAPE — elevated convection signal (J/kg) |
| MLCIN | Mixed-layer convective inhibition / cap strength (J/kg) |
| LI | Lifted Index (K) |
| ML LCL | Mixed-layer lifting condensation level height (m AGL) |

### Kinematics
| Parameter | Description |
|-----------|-------------|
| 0–1 km Shear | Low-level bulk wind difference (kt) |
| 0–6 km Shear | Deep-layer bulk wind difference — primary supercell discriminator (kt) |
| 3–6 km Shear | Mid-level shear — QLCS vs supercell discrimination (kt) |
| 0–1 km SRH | Storm-relative helicity, low-level (m²/s²) |
| 0–3 km SRH | Storm-relative helicity, full layer (m²/s²) |
| Storm Motion | Bunkers right-mover (direction/speed) |

### Composite Parameters
| Parameter | Threshold | Meaning |
|-----------|-----------|---------|
| **SCP** | > 1 supercell; > 4 significant | Supercell Composite — MUCAPE × SRH × shear |
| **STP** | ≥ 1 tornado potential | Significant Tornado Parameter — MLCAPE × LCL × SRH(01) × shear × CIN |
| **EHI** | ≥ 1 tornado-supporting | Energy-Helicity Index — CAPE × SRH / 160,000 |
| **SHIP** | ≥ 1 significant hail | Significant Hail Parameter — hail growth layer composite |
| **VGP** | ≥ 0.2 favorable | Vorticity Generation Parameter — low-level vorticity production |
| **Craven-Brooks** | > 20,000 J/kg·m/s | Significant severe weather threshold |

---

## 🌪 Support Level Scale

| Level | Meaning |
|-------|---------|
| ⬛ None | No convective threat |
| 🟦 Marginal | Isolated pulse storms possible |
| 🟩 Limited | Multicell activity, marginal organization |
| 🟨 Moderate | Organized convection likely |
| 🟧 Enhanced | Supercells possible, large hail / severe wind risk |
| 🟥 Extreme | Tornadic supercell environment |

---

## ⚙️ Meteorological Methods

### CAPE/CIN Integration
Full parcel theory implementation using dry-adiabatic lift to the LCL, then saturated moist-adiabatic ascent above. MLCAPE uses the mean mixed-layer parcel (lowest 100 hPa); MUCAPE uses the most-unstable parcel (max θe in lowest 300 hPa). LCL height computed via Bolton (1980).

### Storm Motion — Bunkers Internal Dynamics (2000)
Mean wind of the 0–6 km layer plus a 7.5 m/s deviation vector perpendicular to the 0–6 km shear vector. Produces physically consistent right- and left-mover solutions that rotate with the hodograph.

### Storm-Relative Helicity
Multi-level integration via Davies-Jones (1984):
```
SRH = -Σ [(u_rel_i)(v_rel_i+1) - (u_rel_i+1)(v_rel_i)]
```
Referenced to the Bunkers right-mover. Computed separately for 0–1 km and 0–3 km layers.

### Mesoscale Boundary Detection
θe gradient analysis on the model grid surrounding the target point. Gradients exceeding ~3 K/100 km flag a likely mesoscale boundary, with characterization of warm sector vs. cold/dry side based on relative θe at the point.

---

## 🚀 Running Locally

```bash
git clone https://github.com/Freshwaffle/Weather-Risk-Checker
cd Weather-Risk-Checker
pip install -r requirements.txt
python src/weather_checker.py
```

Open `http://localhost:8080`.

> **Note:** HRRR and NAM data requires [Herbie](https://herbie.readthedocs.io/) and `eccodes`. Without these installed, the tool automatically falls back to Open-Meteo — no configuration needed.

---

## 🐳 Docker

```bash
docker compose up --build
```

The Docker image includes `eccodes` and all dependencies for the full HRRR/NAM/GFS model chain.

---

## 📡 Data Sources

| Source | Coverage | Resolution | Max Forecast |
|--------|----------|------------|--------------|
| HRRR | CONUS | ~3 km | 18 hr |
| NAM-3km | CONUS | 3 km | 60 hr |
| GFS | Global | ~25 km | 120 hr |
| Open-Meteo | Global | ~11 km | 48 hr (fallback) |

---

## ⚠️ Limitations

- HRRR and NAM coverage is CONUS-only; international locations use GFS or Open-Meteo
- SRH is computed from available pressure levels — more levels = more accurate
- No convective initiation timing, forcing mechanism strength, or storm-scale evolution modeled
- Not suitable for operational warning or emergency management decisions

---

## License

[MIT](LICENSE)
