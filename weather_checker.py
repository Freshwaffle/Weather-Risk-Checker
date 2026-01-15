# weather_checker.py
import herbie
import numpy as np
import pandas as pd
from metpy.calc import cape_cin, bulk_shear, storm_relative_helicity
from metpy.units import units
from datetime import datetime, timedelta

def fetch_hrrr(lat=39.29, lon=-76.61, forecast_hours=24):
    """
    Fetch HRRR data for the next 24 hours.
    """
    # Load HRRR via Herbie
    hrrr = herbie.grib('HRRR:13:0')  # 13 km HRRR, surface+upper levels
    data = hrrr.subset(lat=lat, lon=lon, levels=['surface', '700', '500', '300'])
    return data

def calculate_severe_params(data):
    """
    Compute severe weather parameters: CAPE, CIN, shear, SRH, EHI, STP, total precip.
    """
    results = []
    for i in range(len(data['time'])):
        # Surface conditions
        temp = data['surface_temperature'][i] * units.kelvin
        dew = data['surface_dewpoint'][i] * units.kelvin

        # Compute CAPE/CIN
        try:
            sfc_pressure = 1000 * units.hPa  # approximate surface
            cape, cin = cape_cin(sfc_pressure, temp, dew)
        except:
            cape, cin = 0, 0

        # Shear
        u_lower = data['wind_u_0_3km'][i] * units.meter / units.second
        v_lower = data['wind_v_0_3km'][i] * units.meter / units.second
        u_upper = data['wind_u_0_6km'][i] * units.meter / units.second
        v_upper = data['wind_v_0_6km'][i] * units.meter / units.second
        shear_0_3km, shear_0_6km = bulk_shear([u_lower, u_upper], [v_lower, v_upper])

        # Storm-relative helicity
        srh_0_3km = storm_relative_helicity(u_lower, v_lower, u_upper, v_upper)

        # EHI (simplified)
        ehi = (cape / 1000) * (srh_0_3km / 100)

        # STP (simplified proxy)
        stp = ehi * (shear_0_3km.magnitude / 20)

        # Precip
        precip = data['precipitation'][i]

        results.append({
            'time': data['time'][i],
            'CAPE': cape.magnitude,
            'CIN': cin.magnitude,
            '0-3 km Shear': shear_0_3km.magnitude,
            '0-6 km Shear': shear_0_6km.magnitude,
            'SRH 0-3 km': srh_0_3km,
            'EHI': ehi,
            'STP': stp,
            'Precip (in)': precip
        })

    return pd.DataFrame(results)

def score_risk(df):
    """
    Score risk level based on thresholds. Adjust thresholds as needed.
    """
    score = 0
    if df['CAPE'].max() > 500: score += 2
    if df['CAPE'].max() > 1500: score += 2
    if df['0-3 km Shear'].max() > 20: score += 2
    if df['0-6 km Shear'].max() > 40: score += 2
    if df['Precip (in)'].sum() > 0.5: score += 1
    if df['EHI'].max() > 1: score += 2
    if df['STP'].max() > 1: score += 2

    if score >= 7:
        risk = "High"
    elif score >= 5:
        risk = "Moderate"
    elif score >= 3:
        risk = "Marginal"
    else:
        risk = "Low"

    return risk, score

def main():
    print("Fetching HRRR data...")
    data = fetch_hrrr()
    print("Calculating severe weather parameters...")
    df = calculate_severe_params(data)
    risk_level, score = score_risk(df)

    print(f"\nRisk Level: {risk_level} (Score: {score}/12)")
    print("Next 24h Forecast:")
    print(df[['time', 'CAPE', '0-3 km Shear', '0-6 km Shear', 'EHI', 'STP', 'Precip (in)']])

if __name__ in {"__main__", "__mp_main__"}:
    main()
