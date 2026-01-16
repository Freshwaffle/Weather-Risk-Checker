# Weather Risk Calculator

A personal severe weather ingredients checker and risk estimator for Maryland (and beyond), built with NiceGUI and powered by Open-Meteo data.

This tool analyzes forecast data to identify key severe thunderstorm ingredients (CAPE, shear, SRH, precipitation) and estimates risk levels aligned with SPC categories (NONE → HIGH). It includes fail modes and likely outcomes to explain why severe weather might **not** happen, even with strong shear.

Designed for educational and personal use by an aspiring meteorologist. Not an official forecast, always check SPC/NWS for real decisions.

## Gallery
![DEMO](https://i.imgur.com/h3qtbYy.png)
## Features
- Real-time 24–48 hour forecast analysis from Open-Meteo
- Calculates:
  - Instability (max CAPE, avg LI)
  - Low-level & deep shear (0-1km, 0-3km, 0-6km proxy)
  - SRH (with sign explanation for cyclonic/anticyclonic)
  - Composites (SCP, STP)
- Strict instability gate, no false alarms in winter/high-shear-only setups
- SPC-style risk levels (NONE, MRGL, SLGT, ENH, MDT, HIGH)
- Fail modes & most likely outcome narrative
- Clean, grouped summary display

## Live Demo
Try it here:  
[https://huggingface.co/spaces/Freshwaffle23426/Weather_Risk_Checker](https://huggingface.co/spaces/Freshwaffle23426/Weather-Risk-Checker)


## How to Run Locally
1. Clone the repo:
   ```bash
   git clone https://github.com/Freshwaffle/Weather-Risk-Checker.git
   cd Weather-Risk-Checker
