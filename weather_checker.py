# weather_checker_operational.py
import requests
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

# ---------------------------
# CONFIGURATION
# ---------------------------
LATITUDE = 39.29      # Example: Baltimore, MD
LONGITUDE = -76.61
FORECAST_HOURS = 24
TIMEZONE = "America/New_York"

# ---------------------------
# FETCH DATA (HRRR or Open Meteo)
# ---------------------------
def fetch_weather():
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={LATITUDE}&longitude={LONGITUDE}&"
        f"hourly=cape,cape_surface,cin,surface_temperature,surface_dewpoint,"
        f"wind_speed_10m,wind_direction_10m,"
        f"wind_speed_700hPa,wind_direction_700hPa,"
        f"wind_speed_500hPa,wind_direction_500hPa,"
        f"wind_speed_300hPa,wind_direction_300hPa,"
        f"storm_relative_helicity_0_3km,"
        f"precipitation&forecast_days=2&timezone={TIMEZONE}"
    )
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json()

# ---------------------------
# CALCULATE SHEAR, EHI, STP
# ---------------------------
def calculate_metrics(data):
    hours = data['hourly']['time'][:FORECAST_HOURS]
    cape = np.array(data['hourly']['cape'][:FORECAST_HOURS])
    cin = np.array(data['hourly']['cin'][:FORECAST_HOURS])
    shear_0_3 = np.array(data['hourly']['wind_speed_10m'][:FORECAST_HOURS])
    shear_0_6 = np.array(data['hourly']['wind_speed_500hPa'][:FORECAST_HOURS])
    helicity = np.array(data['hourly'].get('storm_relative_helicity_0_3km', [0]*FORECAST_HOURS))
    precip = np.array(data['hourly']['precipitation'][:FORECAST_HOURS])
    
    # EHI = (CAPE / 1000) * (Helicity / 160)
    ehi = (cape / 1000) * (helicity / 160)
    
    # STP simplified = (CAPE / 1500) * (shear_0_3 / 20) * (helicity / 150)
    stp = (cape / 1500) * (shear_0_3 / 20) * (helicity / 150)
    
    # Risk scoring
    score = []
    for i in range(FORECAST_HOURS):
        s = 0
        if cape[i] > 500: s += 1
        if cape[i] > 1500: s += 1
        if shear_0_3[i] > 20: s += 1
        if shear_0_6[i] > 40: s += 1
        if ehi[i] > 1: s += 2
        if stp[i] > 1: s += 2
        score.append(s)
    
    return pd.DataFrame({
        'Time': hours,
        'CAPE': cape,
        'CIN': cin,
        '0-3km Shear': shear_0_3,
        '0-6km Shear': shear_0_6,
        'Helicity': helicity,
        'EHI': ehi,
        'STP': stp,
        'Score': score,
        'Precip': precip
    })

# ---------------------------
# SUMMARIZE RISK
# ---------------------------
def summarize_risk(df):
    max_cape = df['CAPE'].max()
    avg_shear = df['0-3km Shear'].mean()
    total_precip = df['Precip'].sum()
    
    total_score = df['Score'].max()
    if total_score >= 7: risk_level = "High"
    elif total_score >= 5: risk_level = "Moderate"
    elif total_score >= 3: risk_level = "Marginal"
    else: risk_level = "Low"
    
    print(f"Risk Level: {risk_level} (Score: {total_score}/8)")
    print(f"Next {FORECAST_HOURS}h — Max CAPE: {max_cape:.0f} J/kg | Avg 0–3 km Shear: {avg_shear:.1f} kt | Total Precip: {total_precip:.2f} in")
    
    risky_hours = df[df['Score'] >= 3]
    if not risky_hours.empty:
        print(f"{len(risky_hours)} potentially risky hours detected:")
        for _, row in risky_hours.iterrows():
            parts = []
            if row['0-3km Shear'] > 25: parts.append(f"Strong 0–3 km Shear ({row['0-3km Shear']:.0f} kt)")
            if row['0-6km Shear'] > 50: parts.append(f"Strong Deep-Layer Shear ({row['0-6km Shear']:.0f} kt)")
            if row['EHI'] > 1: parts.append(f"High EHI ({row['EHI']:.2f})")
            if row['STP'] > 1: parts.append(f"High STP ({row['STP']:.2f})")
            print(f"{row['Time']}: {', '.join(parts)}")
    else:
        print("No severe weather setups detected.")

# ---------------------------
# OPTIONAL: PLOTS
# ---------------------------
def plot_metrics(df):
    plt.figure(figsize=(10,5))
    plt.plot(df['Time'], df['CAPE'], label='CAPE (J/kg)')
    plt.plot(df['Time'], df['0-3km Shear'], label='0-3km Shear (kt)')
    plt.plot(df['Time'], df['EHI'], label='EHI')
    plt.plot(df['Time'], df['STP'], label='STP')
    plt.xticks(rotation=45)
    plt.legend()
    plt.tight_layout()
    plt.show()

# ---------------------------
# MAIN
# ---------------------------
def main():
    data = fetch_weather()
    df = calculate_metrics(data)
    summarize_risk(df)
    plot_metrics(df)

if __name__ == "__main__":
    main()
