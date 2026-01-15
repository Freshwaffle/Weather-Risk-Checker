import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ---------- CONFIG ----------
LAT = 39.29      # example: Baltimore, MD
LON = -76.61
FORECAST_HOURS = 24

# ---------- FETCH WEATHER ----------
def fetch_weather():
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={LAT}&longitude={LON}&hourly=cape,cin,"
        f"wind_speed_10m,wind_direction_10m,"
        f"wind_speed_700hPa,wind_direction_700hPa,"
        f"wind_speed_500hPa,wind_direction_500hPa,"
        f"wind_speed_300hPa,wind_direction_300hPa,"
        f"precipitation&forecast_days=2&timezone=America/New_York"
    )
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json()["hourly"]

# ---------- CALCULATE SHEAR ----------
def vector_shear(u1, v1, u2, v2):
    """Compute shear magnitude between two levels"""
    du = u2 - u1
    dv = v2 - v1
    return np.sqrt(du**2 + dv**2)

def calc_shear(data):
    shear_03km = []
    shear_06km = []
    for i in range(min(FORECAST_HOURS, len(data["time"]))):
        # Convert wind speed/direction to u/v components
        def uv(ws, wd):
            wd_rad = np.radians(wd)
            u = -ws * np.sin(wd_rad)
            v = -ws * np.cos(wd_rad)
            return u, v
        
        u10, v10 = uv(data["wind_speed_10m"][i], data["wind_direction_10m"][i])
        u700, v700 = uv(data["wind_speed_700hPa"][i], data["wind_direction_700hPa"][i])
        u500, v500 = uv(data["wind_speed_500hPa"][i], data["wind_direction_500hPa"][i])
        u300, v300 = uv(data["wind_speed_300hPa"][i], data["wind_direction_300hPa"][i])

        shear_03km.append(vector_shear(u10, v10, u700, v700))
        shear_06km.append(vector_shear(u10, v10, u300, v300))
    return shear_03km, shear_06km

# ---------- CALCULATE RISK ----------
def calculate_risk(data):
    risk_scores = []
    fail_modes_list = []

    shear_03km, shear_06km = calc_shear(data)

    for i in range(min(FORECAST_HOURS, len(data["time"]))):
        score = 0
        fail_modes = []

        cape = data["cape"][i]
        prec = data["precipitation"][i]

        # CAPE
        if cape >= 1000: score += 2
        if cape >= 2500: score += 2
        if cape < 500: fail_modes.append("Low CAPE")

        # Shear
        s03 = shear_03km[i]
        s06 = shear_06km[i]
        if s03 >= 25: score += 2
        if s06 >= 50: score += 2
        if s03 < 20: fail_modes.append("Weak 0–3 km Shear")
        if s06 < 40: fail_modes.append("Weak Deep-Layer Shear")

        # Precipitation (proxy for moist environment)
        if prec >= 2.0: score += 1

        # Determine Risk Level
        if score <= 2: risk = "Low"
        elif score <= 4: risk = "Marginal"
        elif score <= 6: risk = "Moderate"
        else: risk = "High"

        risk_scores.append({
            "time": data["time"][i],
            "CAPE": cape,
            "Shear 0–3 km": round(s03,1),
            "Shear 0–6 km": round(s06,1),
            "Precip": prec,
            "Score": score,
            "Risk": risk,
            "Fail Modes": ", ".join(fail_modes) if fail_modes else "None"
        })
    return risk_scores

# ---------- MAIN ----------
def main():
    print("Fetching weather data...")
    data = fetch_weather()
    print("Calculating risk...")
    results = calculate_risk(data)
    
    df = pd.DataFrame(results)
    print("\n--- 24-Hour Severe Weather Risk ---")
    print(df.to_string(index=False))

    # Optional: overall max score and risk
    max_score = max([r["Score"] for r in results])
    if max_score <= 2: overall_risk = "Low"
    elif max_score <= 4: overall_risk = "Marginal"
    elif max_score <= 6: overall_risk = "Moderate"
    else: overall_risk = "High"
    
    print(f"\nOverall 24h Risk Level: {overall_risk} (Max Score: {max_score})")

if __name__ in {"__main__", "__mp_main__"}:
    main()
