# Severe Weather Environment Diagnostics Hub

An ingredient-based severe weather environment analysis and pattern-recognition tool built with NiceGUI and powered by Open-Meteo forecast data.

This application evaluates the **environmental support for organized severe convection** by analyzing instability, kinematics, moisture, and forcing proxies. Rather than issuing forecasts, it provides **diagnostic guidance**, highlights **likely convective outcomes**, and identifies **common failure modes** that may prevent severe weather despite favorable parameters.

The tool is designed to aid situational awareness and reasoning during severe weather setups, with emphasis on transparency and physical consistency.

> This is not an official forecast product. Always consult SPC and NWS guidance for operational decisions.

---

## Key Capabilities

- **24–48 hour environmental analysis** using Open-Meteo forecast data
- Ingredient-based diagnostics, including:
  - Instability (maximum CAPE, average Lifted Index)
  - Low-level and deep-layer shear (approximate 0–1 km, 0–3 km, and deep-layer proxies)
  - Storm-relative rotation potential (proxy, with clear limitations)
  - Moisture and precipitation signals
- **Strict instability gating** to avoid false positives in high-shear / low-CAPE or cold-season regimes
- **Environmental support classification** (Minimal → Extreme), describing how supportive the atmosphere is for severe convection
- **Likely convective outcome guidance**, based on ingredient combinations rather than deterministic thresholds
- **Failure mode identification**, explaining why storms may remain weak or fail to initiate
- Clean, grouped summary designed for rapid situational awareness

---

## Intended Use & Philosophy

This tool is intended as a **diagnostic aid**, not a forecast generator. It mirrors how human forecasters reason through severe weather setups by:

- Emphasizing **ingredients over indices**
- Separating **environmental support from storm realization**
- Explicitly communicating **uncertainty and conditionality**

Outputs describe what the **environment may support**, not what storms will do.

---

## Live Demo

Try the live demo here:  
https://huggingface.co/spaces/Freshwaffle23426/Weather-Risk-Checker

---

## Gallery

![DEMO](https://imgur.com/a/D7HJ9xa)

---

## Data Source

Forecast data is provided by **Open-Meteo**, which aggregates multiple numerical weather prediction models. Parameter availability and vertical resolution are limited; all kinematic and composite quantities are therefore **approximations** and treated accordingly.

---

## Limitations

- Vertical levels are pressure-based proxies and may not correspond exactly to fixed-height layers
- Storm-relative rotation metrics are simplified and not equivalent to operational SRH calculations
- No convective initiation, forcing strength, or storm-scale evolution is explicitly modeled
- Not suitable for operational warning or decision-making

---

## License

MIT License
