from nicegui import ui
import herbie
import xarray as xr
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from metpy.calc import cape_cin, storm_relative_helicity, bulk_shear
from metpy.units import units
from datetime import datetime
from io import BytesIO
import base64
import warnings

warnings.filterwarnings('ignore')

# ======================
# Defaults
# ======================
LAT, LON = 39.29, -76.61  # default Baltimore, MD

# ======================
# Utilities
# ======================
def wind_to_uv(speed, direction):
    """Convert wind speed (kt) + direction (deg) to u/v components."""
    rad = np.radians(direction)
    u = -speed * np.sin(rad)
    v = -speed * np.cos(rad)
    return u, v

def grib_download(run_time, model='hrrr'):
    """
    Download HRRR (or fallback RAP/GFS) data at nearest runtime
    for the specified lat/lon point.
    """
    try:
        H = herbie.Herbie(run_time, model=model, product="prs")
        H.download(lat=LAT, lon=LON)
        return H.xarray()
    except Exception as e:
        print(f"{model.upper()} fetch failed ({e}), trying RAP ...")
        try:
            H = herbie.Herbie(run_time, model='rap', product="prs")
            H.download(lat=LAT, lon=LON)
            return H.xarray()
        except Exception as e2:
            print(f"RAP failed ({e2}), trying GFS ...")
            H = herbie.Herbie(run_time, model='gfs', product="prs")
            H.download(lat=LAT, lon=LON)
            return H.xarray()

def plot_series(times, data1, data2=None, labels=None, title=""):
    """Make a base64-encoded PNG for NiceGUI."""
    fig, ax = plt.subplots()
    ax.plot(times, data1, label=labels[0] if labels else None, color='C0')
    if data2 is not None:
        ax.plot(times, data2, label=labels[1] if labels else None, color='C1')
    ax.set_title(title)
    ax.tick_params(axis='x', rotation=45)
    ax.grid(True)
    if labels:
        ax.legend()
    fig.tight_layout()

    buf = BytesIO()
    plt.savefig(buf, format='png')
    plt.close()
    buf.seek(0)
    return base64.b64encode(buf.read()).decode('utf-8')

# ======================
# Main Handler
# ======================
def fetch_and_analyze():
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)

    ds = grib_download(now)
    profile = ds.sel(time=ds.time[:24])

    times = [str(t.values) for t in profile.time]

    cape_vals, cin_vals = [], []
    shear03_vals, shear06_vals = [], []
    srh01_vals, srh03_vals = [], []
    ehi_vals, stp_vals = [], []
    precip_vals = []
    alerts = []

    for i in range(len(profile.time)):
        px = profile.isel(time=i)

        # Pressure, temperature, dewpoint
        p = px['pressure'] * units.hPa
        t = px['temperature'] * units.degC
        td = px['dewpoint'] * units.degC

        # CAPE/CIN
        mlcape, mlcin = cape_cin(p, t, td)
        cape_vals.append(mlcape.magnitude)
        cin_vals.append(mlcin.magnitude)

        # Vertical winds
        wspd = px['wind_speed'] * units('kt')
        wdir = px['wind_direction'] * units('degree')
        u, v = wind_to_uv(wspd.magnitude, wdir.magnitude)

        # Shear: 0–3 km and 0–6 km
        shear03 = bulk_shear(p, u, v, 0 * units.km, 3 * units.km).magnitude
        shear06 = bulk_shear(p, u, v, 0 * units.km, 6 * units.km).magnitude
        shear03_vals.append(shear03)
        shear06_vals.append(shear06)

        # SRH: 0–1 km & 0–3 km
        srh01 = storm_relative_helicity(p, u, v, 0 * units.km, 1 * units.km).magnitude
        srh03 = storm_relative_helicity(p, u, v, 0 * units.km, 3 * units.km).magnitude
        srh01_vals.append(srh01)
        srh03_vals.append(srh03)

        # Precip
        precip_vals.append(px['precipitation'].values * MM_TO_IN)

        # EHI & STP proxies
        ehi = (mlcape.magnitude * srh03) / 160000 if mlcape.magnitude > 0 else 0
        stp = ((mlcape.magnitude/1500)*(srh03/150)*(shear06/40)*(max(0,30-mlcin.magnitude)/30))
        ehi_vals.append(ehi)
        stp_vals.append(stp)

        # Hourly flags
        flags = []
        if mlcape.magnitude >= 1500: flags.append(f"MLCAPE {mlcape:.0f}")
        if shear03 >= 25: flags.append(f"0–3 km shear {shear03:.0f} kt")
        if shear06 >= 40: flags.append(f"0–6 km shear {shear06:.0f} kt")
        if srh03 >= 150: flags.append(f"SRH0–3 km {srh03:.0f}")
        if px['precipitation'].values*MM_TO_IN >= 0.75:
            flags.append(f"Precip {precip_vals[-1]:.2f} in")
        if flags: alerts.append(f"{times[i]}: {', '.join(flags)}")

    # 24h summary
    max_cape = max(cape_vals)
    total_precip = sum(precip_vals)
    avg_shear03 = np.mean(shear03_vals)
    avg_shear06 = np.mean(shear06_vals)
    max_srh03 = max(srh03_vals)
    avg_ehi = np.mean(ehi_vals)
    avg_stp = np.mean(stp_vals)

    # SPC‑style scoring
    score = 0
    if max_cape >= 500: score += 1
    if max_cape >= 1500: score += 2
    if avg_shear03 >= 25: score += 1
    if avg_shear06 >= 40: score += 2
    if max_srh03 >= 150: score += 2
    if total_precip >= 0.75: score += 1
    if avg_ehi >= 1: score += 1
    if avg_stp >= 0.5: score += 1

    risk_level = "Low"
    if score >= 3: risk_level = "Marginal"
    if score >= 5: risk_level = "Moderate"
    if score >= 7: risk_level = "High"

    result_container.clear()
    with result_container:
        ui.label(f"Risk Level: {risk_level} (Score {score})").classes("text-2xl font-bold")
        ui.label(
            f"24h — Max CAPE: {max_cape:.0f} J/kg | "
            f"Avg 0–3 km shear: {avg_shear03:.1f} kt | "
            f"Avg 0–6 km shear: {avg_shear06:.1f} kt | "
            f"Max SRH0–3 km: {max_srh03:.0f} | "
            f"Total precip: {total_precip:.2f} in"
        )

        for a in alerts: ui.label(a)

        ui.html(plot_series(times, cape_vals, shear03_vals, labels=["CAPE","0–3 km shear"], title="CAPE & Shear"))
        ui.html(plot_series(times, srh01_vals, srh03_vals, labels=["SRH0–1km","SRH0–3km"], title="SRH"))
        ui.html(plot_series(times, ehi_vals, stp_vals, labels=["EHI","STP"], title="EHI & STP"))

# ======================
# UI Setup
# ======================
ui.label("Operational Severe Weather Checker").classes("text-4xl text-center")
with ui.card().classes("w-96 mx-auto p-6"):
    ui.label("Location (lat/lon)")
    lat_input = ui.number(LAT, label="Latitude")
    lon_input = ui.number(LON, label="Longitude")

    def update_loc():
        global LAT, LON
        LAT = lat_input.value
        LON = lon_input.value
        ui.notify(f"Location set to {LAT}, {LON}")

    ui.button("Set Location", on_click=update_loc)

ui.button("RUN ANALYSIS", on_click=fetch_and_analyze).classes("mx-auto mt-6")
result_container = ui.card().classes("w-full max-w-4xl mx-auto mt-8 p-6")

ui.run(title="Operational Severe Weather Checker", dark=True, host='0.0.0.0', port=8080)
