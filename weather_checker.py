# weather_checker.py
import herbie
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
from nicegui import ui
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
import io
import base64

# ----------------------------
# CONFIG
# ----------------------------
LATITUDE = 39.29
LONGITUDE = -76.61
TIMEZONE = 'America/New_York'
FORECAST_HOURS = 24  # operational 24h
MODEL = 'hrrr'

# ----------------------------
# UTILITY FUNCTIONS
# ----------------------------

def fetch_weather():
    """Fetch HRRR data via Herbie."""
    try:
        hrrr = herbie.HRRR()
        data = hrrr.grib(
            variables=['cape', 'cin', 'wind', 'srh'], 
            levels=['surface','0-3km','0-6km','500hPa','300hPa'],
            latitude=LATITUDE,
            longitude=LONGITUDE,
            forecast_hours=FORECAST_HOURS
        )
        return data
    except Exception as e:
        print(f"ERROR fetching weather: {e}")
        return None

def calculate_shear(wind_low, wind_high):
    """Compute vector difference (kts)"""
    return np.sqrt((wind_high[:,0]-wind_low[:,0])**2 + (wind_high[:,1]-wind_low[:,1])**2)

def compute_ehi(cape, srh):
    """Energy Helicity Index"""
    # simple scaling
    return (cape/1000.0)*(srh/100.0)

def compute_stp(cape, shear, srh, lcl, conv_depth):
    """Significant Tornado Parameter"""
    # approximate formula for operational scoring
    return (cape/1500)*(shear/20)*(srh/100)*(2000/lcl)*(conv_depth/10000)

def spc_risk_score(cape, shear, ehi, stp):
    score = 0
    if cape > 1500: score += 2
    if shear > 25: score += 2
    if ehi > 1: score += 2
    if stp > 1: score += 2

    if score >= 7: return "High"
    if score >= 5: return "Moderate"
    if score >= 3: return "Marginal"
    return "Low"

def plot_skewt(data):
    fig, ax = plt.subplots(figsize=(6,6))
    ax.plot(data['temperature'], data['pressure'], 'r')
    ax.plot(data['dewpoint'], data['pressure'], 'g')
    ax.set_ylim(1050,100)
    ax.set_xlim(-40,60)
    ax.set_xlabel('Temperature [°C]')
    ax.set_ylabel('Pressure [hPa]')
    canvas = FigureCanvas(fig)
    buf = io.BytesIO()
    canvas.print_png(buf)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

# ----------------------------
# MAIN FUNCTION
# ----------------------------

def main():
    data = fetch_weather()
    if data is None:
        ui.label("Error fetching weather data.")
        return

    table = []
    for i in range(FORECAST_HOURS):
        cape = data['cape'][i]
        shear_03 = data['shear_0_3km'][i]
        shear_06 = data['shear_0_6km'][i]
        srh = data['srh_0_3km'][i]
        ehi = compute_ehi(cape, srh)
        stp = compute_stp(cape, shear_03, srh, lcl=1000, conv_depth=12000)

        risk = spc_risk_score(cape, shear_03, ehi, stp)
        table.append({
            'Time': (datetime.now(pytz.timezone(TIMEZONE)) + timedelta(hours=i)).strftime('%Y-%m-%d %H:%M'),
            'CAPE': cape,
            '0-3 km Shear': shear_03,
            '0-6 km Shear': shear_06,
            'SRH': srh,
            'EHI': round(ehi,2),
            'STP': round(stp,2),
            'Risk': risk
        })

    df = pd.DataFrame(table)

    ui.label("### 24h Severe Weather Forecast")
    ui.table(df.to_dict('records'), columns=list(df.columns))

    # optional plot
    skewt_img = plot_skewt({'temperature': data['temperature'], 'pressure': data['pressure']})
    ui.image(f"data:image/png;base64,{skewt_img}")

    ui.run()

# ----------------------------
# ENTRY POINT
# ----------------------------

if __name__ in {"__main__", "__mp_main__"}:
    main()
