# operational_severe_checker.py

from nicegui import ui
import herbie
import xarray as xr
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from metpy.calc import cape_cin, bulk_shear, storm_relative_helicity
from metpy.units import units
from datetime import datetime
from io import BytesIO
import base64
import warnings

warnings.filterwarnings("ignore")

# --------------------------------------------
# Global defaults
# --------------------------------------------
LAT, LON = 39.29, -76.61  # Default to Baltimore, MD
H = None  # Herbie instance

# --------------------------------------------
# Helper functions
# --------------------------------------------

def download_model_data(run_time, model='hrrr', product='prs'):
    """
    Uses Herbie to download HRRR/RAP/GFS data for the given time.
    Falls back as needed.
    """
    global H
    try:
        H = herbie.Herbie(run_time, model=model, product=product)
        H.download(lat=LAT, lon=LON)
        return H.xarray()
    except Exception as e:
        print("Primary model fetch failed, trying fallback:", e)
        # Try RAP
        try:
            H = herbie.Herbie(run_time, model='rap', product=product)
            H.download(lat=LAT, lon=LON)
            return H.xarray()
        except Exception as e2:
            print("Fallback failed, using GFS:", e2)
            H = herbie.Herbie(run_time, model='gfs', product=product)
            H.download(lat=LAT, lon=LON)
            return H.xarray()

def compute_parcel_params(ds):
    """
    Computes MLCAPE & MLCIN from the dataset ds.
    ds must contain pressure (isobaric), temperature and dewpoint fields.
    """
    p = ds['pressure'] * units.hPa
    t = ds['temperature'] * units.degC
    td = ds['dewpoint'] * units.degC

    try:
        mlcape, mlcin = cape_cin(p, t, td, parcel_profile=None)
        return mlcape.magnitude, mlcin.magnitude
    except Exception as e:
        print("Error computing MLCAPE/CIN:", e)
        return 0, 0

def compute_srh_shear(ds):
    """
    Computes SRH and bulk shear (0-3 km, 0-6 km).
    Uses MetPy functions.
    """
    wspd = ds['wind_speed'] * units('kt')
    wdir = ds['wind_direction'] * units('degree')
    u, v = wind_to_uv(wspd.magnitude, wdir.magnitude)
    try:
        # 0–1 km & 0–3 km SRH
        srh_01 = storm_relative_helicity(ds['pressure'], u, v, depth=1000 * units.meter)
        srh_03 = storm_relative_helicity(ds['pressure'], u, v, depth=3000 * units.meter)

        # bulk shear 0–3 km & 0–6 km
        shear_03 = bulk_shear(ds['pressure'], u, v, 0 * units.km, 3 * units.km)
        shear_06 = bulk_shear(ds['pressure'], u, v, 0 * units.km, 6 * units.km)

        return srh_01, srh_03, shear_03.magnitude, shear_06.magnitude
    except Exception as e:
        print("Error computing SRH/Shear:", e)
        return 0, 0, 0, 0

def wind_to_uv(speed_kt, direction_deg):
    rad = np.deg2rad(direction_deg)
    u = -speed_kt * np.sin(rad)
    v = -speed_kt * np.cos(rad)
    return u, v

def plot_to_html(x, y1, y2, labels, title):
    """
    Helper to create a matplotlib plot and return HTML <img> tag.
    """
    fig, ax = plt.subplots()
    ax.plot(x, y1, label=labels[0], color='red')
    ax.set_title(title)
    ax.set_xticklabels(x, rotation=45)
    ax2 = ax.twinx()
    ax2.plot(x, y2, label=labels[1], color='blue')
    fig.tight_layout()

    buf = BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)
    return f'<img src="data:image/png;base64,{img_b64}" />'

# --------------------------------------------
# Main fetch/analyze function
# --------------------------------------------
def fetch_and_analyze():
    # Determine current UTC and model run
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)

    # Fetch HRRR/RAP/GFS data
    ds = download_model_data(now)

    # Extract vertical profiles for next 24h
    profile = ds.sel(time=ds.time[:24])

    # Compute parameters
    cape_vals, cin_vals = [], []
    srh_01_vals, srh_03_vals = [], []
    shear_03_vals, shear_06_vals = [], []
    precip_vals = []

    alerts = []
    times = []

    for i in range(len(profile.time)):
        tstr = str(profile.time.values[i])
        times.append(tstr)

        # Mixed Layer CAPE & CIN
        mlcape, mlcin = compute_parcel_params(profile.isel(time=i))
        cape_vals.append(mlcape)
        cin_vals.append(mlcin)

        # SRH and shear
        srh01, srh03, sh03, sh06 = compute_srh_shear(profile.isel(time=i))
        srh_01_vals.append(srh01)
        srh_03_vals.append(srh03)
        shear_03_vals.append(sh03)
        shear_06_vals.append(sh06)

        # Precip
        p = profile['precipitation'].isel(time=i).values * MM_TO_IN
        precip_vals.append(p)

        # Hourly SPC flags
        flags = []
        if mlcape >= 1500: flags.append(f"MLCAPE {mlcape:.0f}")
        if sh03 >= 25: flags.append(f"0–3 km Shear {sh03:.0f} kt")
        if sh06 >= 40: flags.append(f"0–6 km Shear {sh06:.0f} kt")
        if srh03 >= 150: flags.append(f"SRH 0–3 km {srh03:.0f}")
        if p >= 0.75: flags.append(f"Precip {p:.2f} in")

        if flags:
            alerts.append(f"{tstr}: {', '.join(flags)}")

    # 24-hour summary metrics
    max_cape = max(cape_vals)
    total_precip = sum(precip_vals)
    avg_shear_03 = np.mean(shear_03_vals)
    avg_shear_06 = np.mean(shear_06_vals)
    max_srh03 = max(srh_03_vals)

    # SPC risk scoring
    score = 0
    if max_cape >= 500: score += 1
    if max_cape >= 1500: score += 2
    if avg_shear_03 >= 25: score += 1
    if avg_shear_06 >= 40: score += 2
    if max_srh03 >= 150: score += 2
    if total_precip >= 0.75: score += 1

    risk_level = "Low"
    if score >= 3: risk_level = "Marginal"
    if score >= 5: risk_level = "Moderate"
    if score >= 7: risk_level = "High"

    # ===== Update UI =====
    result_container.clear()
    with result_container:
        # Header
        color = "text-green-500"
        if score >= 3: color = "text-yellow-500"
        if score >= 5: color = "text-orange-500"
        if score >= 7: color = "text-red-600"
        ui.label(f"Risk Level: {risk_level} (Score {score})").classes(f"text-2xl font-bold {color}")

        # Summary
        ui.label(
            f"24h — Max MLCAPE: {max_cape:.0f} J/kg | "
            f"Avg 0–3 km Shear: {avg_shear_03:.1f} kt | "
            f"Avg 0–6 km Shear: {avg_shear_06:.1f} kt | "
            f"Max SRH0–3km: {max_srh03:.0f} m²/s² | "
            f"Total Precip: {total_precip:.2f} in"
        ).classes("text-lg mb-4")

        # Alerts
        if alerts:
            ui.label(f"{len(alerts)} high‑risk hours:").classes("text-xl text-red-600")
            for a in alerts: ui.label(a)
        else:
            ui.label("No high‑risk hours detected").classes("text-green-600")

        # Plots
        cape_plot = plot_to_html(times, cape_vals, shear_03_vals, ["MLCAPE","0–3 km Shear"], "MLCAPE & Shear")
        srh_plot = plot_to_html(times, srh_01_vals, srh_03_vals, ["SRH0–1km","SRH0–3km"], "SRH Over 24h")
        ui.html(cape_plot)
        ui.html(srh_plot)

# --------------------------------------------
# NiceGUI Layout
# --------------------------------------------
ui.label("Operational Severe/Tornado Potential Checker").classes("text-4xl font-bold text-center mt-4")
ui.label("Powered by HRRR/RAP/GFS + SPC indices").classes("text-center mb-6")

with ui.card().classes("w-96 mx-auto p-6"):
    ui.label("Location (Latitude/Longitude)")
    lat_input = ui.number(value=LAT, label="Latitude")
    lon_input = ui.number(value=LON, label="Longitude")

    def update_location():
        global LAT, LON
        LAT = lat_input.value
        LON = lon_input.value
        ui.notify(f"Location updated to {LAT}, {LON}")

    ui.button("Update Location", on_click=update_location)

ui.button("RUN ANALYSIS", on_click=fetch_and_analyze).classes("mx-auto mt-6")
result_container = ui.card().classes("w-full max-w-4xl mx-auto mt-8 p-6")

ui.run(title="24h Operational Severe Weather Checker", dark=True)
