# ⛈ Severe Weather Environment Diagnostics Hub 
-NOTE: THIS WAS MADE WITH THE HELP OF AI, AS I AM STILL LEARNING TO CODE.
An ingredient-based severe weather environment analysis tool built with **NiceGUI** and powered by **Open-Meteo** forecast data. Enter any city name or lat/lon coordinates and get a diagnostic breakdown of convective potential across the next 24–48 hours.

> **This is not an official forecast product.** Always consult [SPC](https://www.spc.noaa.gov/) and [NWS](https://www.weather.gov/) guidance for operational decisions.

---

## 🔴 Live Demo

**[Try it on Hugging Face Spaces →](https://huggingface.co/spaces/Freshwaffle23426/Weather-Risk-Checker)**

---

## What It Does

Rather than issuing a simple "yes/no" severe weather forecast, this tool reasons through an atmospheric setup the way a human forecaster would — evaluating instability, kinematics, moisture, and composite parameters together — and then explains *why* storms might succeed or fail.

Each analyzed time step returns:

- **Convective mode** — Pulse, Multicell, QLCS, Supercellular, or Tornadic Supercells
- **Environmental support level** — a scored tier from None to Extreme
- **Composite parameters** — SCP and STP with operational thresholds flagged
- **Fail mode identification** — explicit reasoning on why storms may not materialize

---

## 📊 Parameters Analyzed

### Instability
| Parameter | Description |
|-----------|-------------|
| CAPE | Convective Available Potential Energy (J/kg) |
| CIN | Convective Inhibition / cap strength (J/kg) |
| LI | Lifted Index (K) |
| RH | 2m Relative Humidity — moisture proxy |

### Kinematics
| Parameter | Description |
|-----------|-------------|
| 0–6 km Shear | Deep-layer bulk wind difference (surface → 500 hPa), primary supercell discriminator |
| 0–1 km Shear | Low-level shear proxy (surface → 850 hPa), influences tornado potential |
| 0–3 km SRH | Storm-Relative Helicity referenced to Bunkers right-mover motion |

### Composite Parameters
| Parameter | Threshold | Meaning |
|-----------|-----------|---------|
| **SCP** (Supercell Composite) | > 1 favorable; > 4 significant | Combines CAPE, SRH, and deep shear |
| **STP** (Significant Tornado Parameter) | ≥ 1 signals sig. tornado potential | Adds LCL proxy via boundary layer RH |

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

### Storm Motion — Bunkers Internal Dynamics (2000)
Storm motion is estimated using the proper Internal Dynamics method: the mean wind vector of the 0–6 km layer plus a **7.5 m/s deviation vector perpendicular to the 0–6 km shear vector**. This correctly produces right- and left-mover solutions that rotate with the hodograph, unlike flat U/V offset approximations.

### Storm-Relative Helicity
SRH is computed as the cross product of storm-relative wind vectors at the surface and 700 hPa (≈ 3 km), referenced to the Bunkers right-mover:

```
SRH ≈ (ru_sfc × rv_mid) - (ru_mid × rv_sfc)
```

where `ru`, `rv` are winds relative to storm motion.

### Wind Level Assignments
| Model Level | Approximate Height | Use |
|-------------|-------------------|-----|
| 10m | Surface | Low-level base |
| 850 hPa | ~1.5 km | 0–1 km shear proxy |
| 700 hPa | ~3 km | SRH layer top, Bunkers mid-level |
| 500 hPa | ~5.5 km | Deep-layer shear top |

---

## 🚀 Running Locally

**Requirements:** Python 3.10+

```bash
git clone https://github.com/Freshwaffle/Weather-Risk-Checker
cd Weather-Risk-Checker
pip install -r requirements.txt
python weather_checker.py
```

Then open `http://localhost:8080` in your browser.

---

## 🐳 Docker

```bash
docker build -t weather-risk-checker .
docker run -p 8080:8080 weather-risk-checker
```

---

## Data Source

Forecast data is provided by **[Open-Meteo](https://open-meteo.com/)**, a free and open-source weather API aggregating multiple NWP models. Geocoding also uses Open-Meteo's free geocoding endpoint — no API key required.

---

## ⚠️ Limitations

- Vertical levels are pressure-based proxies and do not correspond exactly to fixed AGL heights
- SRH is a two-level approximation; operational calculations integrate across many more levels
- No convective initiation, forcing mechanism strength, or storm-scale evolution is modeled
- STP uses boundary layer RH as an LCL proxy, which is a simplification
- Not suitable for operational warning or emergency management decisions

---

## License

[MIT](LICENSE)
