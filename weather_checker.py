# weather_checker_spc.py
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import herbie
from nicegui import ui

# ----------------------
# 1. HRRR Data Fetch
# ----------------------
def fetch_hrrr(lat=39.29, lon=-76.61):
    """Fetch HRRR 13 km grib data for location"""
    try:
        hrrr_data = herbie.grib('HRRR:13:0')  # surface + upper levels
        data = hrrr_data.get(lat=lat, lon=lon, variables=[
            'CAPE', 'CIN', 'U700', 'V700', 'U300', 'V300', 'U10', 'V10'
        ])
        return data
    except Exception as e:
        print(f'ERROR fetching HRRR: {e}')
        return None

# ----------------------
# 2. Derived Parameters
# ----------------------
def calculate_shear(data):
    """Compute 0-3 km and 0-6 km shear (kt)"""
    u10, v10 = data['U10'], data['V10']
    u700, v700 = data['U700'], data['V700']
    u300, v300 = data['U300'], data['V300']

    shear03 = np.sqrt((u700-u10)**2 + (v700-v10)**2) * 1.94384  # m/s -> kt
    shear06 = np.sqrt((u300-u10)**2 + (v300-v10)**2) * 1.94384

    return shear03, shear06

def calculate_srh_ehi_stp(data):
    """Simplified proxies for helicity, EHI, STP"""
    cape = data['CAPE']
    shear03, shear06 = calculate_shear(data)
    srh03 = shear03 * 1.2  # simple SRH proxy
    ehi = (cape/1000) * (srh03/100)
    stp = (cape/1000) * (shear03/50) * (srh03/100)
    return srh03, ehi, stp

# ----------------------
# 3. Hourly Risk Evaluation
# ----------------------
def evaluate_risk(data):
    cape = data['CAPE']
    shear03, shear06 = calculate_shear(data)
    srh, ehi, stp = calculate_srh_ehi_stp(data)
    precip = data.get('PRECIP', np.zeros_like(cape))

    risk_level = []
    fail_modes = []

    for i in range(len(cape)):
        score = 0
        fail = []

        if cape[i] >= 1000: score += 2
        elif cape[i] >= 500: fail.append('Marginal CAPE')

        if shear03[i] >= 25: score += 1
        elif shear03[i] >= 20: fail.append('Weak 0-3 km Shear')

        if shear06[i] >= 50: score += 1
        elif shear06[i] >= 40: fail.append('Weak Deep-Layer Shear')

        if srh[i] >= 150: score += 2
        elif srh[i] >= 100: fail.append('Marginal SRH')

        if ehi[i] >= 1: score += 1
        if stp[i] >= 1: score += 1

        # Risk mapping
        if score >= 6: level = 'High'
        elif score >= 4: level = 'Moderate'
        elif score >= 2: level = 'Slight'
        elif score >= 1: level = 'Marginal'
        else: level = 'Low'

        risk_level.append(level)
        fail_modes.append(fail if fail else ['None'])

    df = pd.DataFrame({
        'Time': pd.date_range(datetime.now(), periods=len(cape), freq='H'),
        'CAPE (J/kg)': cape,
        '0-3 km Shear (kt)': shear03,
        '0-6 km Shear (kt)': shear06,
        'SRH 0-3 km (m2/s2)': srh,
        'EHI': ehi,
        'STP': stp,
        'Precip (in)': precip,
        'Risk Level': risk_level,
        'Fail Modes': fail_modes
    })
    return df

# ----------------------
# 4. Web Interface
# ----------------------
def main():
    data = fetch_hrrr()
    if data is None:
        ui.label("Error fetching HRRR data.")
        return

    df = evaluate_risk(data)

    ui.label(f"Severe Weather Forecast for 24h ({datetime.now():%Y-%m-%d %H:%M})")
    ui.table(df.to_dict(orient='records'), columns=[{'name': c, 'label': c} for c in df.columns])

    # Optional: simple CAPE plot
    ui.plot()
    fig = df[['Time', 'CAPE (J/kg)']].set_index('Time').plot(title='CAPE over next 24h')
    ui.label("CAPE Plot")

    ui.run(title="Severe Weather Risk Checker")

# ----------------------
# 5. Run
# ----------------------
if __name__ in {"__main__", "__mp_main__"}:
    main()
