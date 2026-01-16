from nicegui import ui
import requests
from datetime import datetime
import math

# =====================
# Constants & Utilities
# =====================

KMH_TO_KT = 0.539957
MM_TO_IN = 0.0393701

def wind_to_uv(speed_kt, direction_deg):
    rad = math.radians(direction_deg)
    u = -speed_kt * math.sin(rad)
    v = -speed_kt * math.cos(rad)
    return u, v

# =====================
# Default Location
# =====================

LAT, LON = 39.29, -76.61  # Baltimore

# =====================
# Data Fetch
# =====================

def fetch_open_meteo(lat, lon):
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&hourly="
        "cape,lifted_index,relative_humidity_2m,"
        "wind_speed_10m,wind_direction_10m,"
        "wind_speed_925hPa,wind_direction_925hPa,"
        "wind_speed_700hPa,wind_direction_700hPa,"
        "wind_speed_300hPa,wind_direction_300hPa,"
        "precipitation"
        "&forecast_days=2"
        "&timezone=America/New_York"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()["hourly"]

# =====================
# Analysis Core
# =====================

def analyze(hourly):
    shear01, shear03, shear06 = [], [], []
    alerts = []

    for i in range(24):
        try:
            cape = hourly["cape"][i] or 0
            li = hourly["lifted_index"][i] or 9
            rh = hourly["relative_humidity_2m"][i] or 0

            spd_sfc = (hourly["wind_speed_10m"][i] or 0) * KMH_TO_KT
            spd_925 = (hourly["wind_speed_925hPa"][i] or 0) * KMH_TO_KT
            spd_700 = (hourly["wind_speed_700hPa"][i] or 0) * KMH_TO_KT
            spd_300 = (hourly["wind_speed_300hPa"][i] or 0) * KMH_TO_KT

            dir_sfc = hourly["wind_direction_10m"][i]
            dir_925 = hourly["wind_direction_925hPa"][i]
            dir_700 = hourly["wind_direction_700hPa"][i]
            dir_300 = hourly["wind_direction_300hPa"][i]

            if None in [dir_sfc, dir_925, dir_700, dir_300]:
                continue

            u_sfc, v_sfc = wind_to_uv(spd_sfc, dir_sfc)
            u_925, v_925 = wind_to_uv(spd_925, dir_925)
            u_700, v_700 = wind_to_uv(spd_700, dir_700)
            u_300, v_300 = wind_to_uv(spd_300, dir_300)

            s01 = math.hypot(u_925 - u_sfc, v_925 - v_sfc)
            s03 = math.hypot(u_700 - u_sfc, v_700 - v_sfc)
            s06 = math.hypot(u_300 - u_sfc, v_300 - v_sfc)

            shear01.append(s01)
            shear03.append(s03)
            shear06.append(s06)

            if cape >= 500 and (s06 >= 35 or s03 >= 25):
                alerts.append(
                    f"{hourly['time'][i][11:16]} | CAPE {cape:.0f} | 0–6km {s06:.0f} kt"
                )

        except:
            continue

    max_cape = max([c for c in hourly["cape"][:24] if c] or [0])
    min_li = min([l for l in hourly["lifted_index"][:24] if l is not None] or [9])
    avg_rh = sum([r for r in hourly["relative_humidity_2m"][:24] if r is not None]) / 24
    total_qpf = sum((p or 0) * MM_TO_IN for p in hourly["precipitation"][:24])

    avg_s01 = sum(shear01) / len(shear01) if shear01 else 0
    avg_s03 = sum(shear03) / len(shear03) if shear03 else 0
    avg_s06 = sum(shear06) / len(shear06) if shear06 else 0

    # =====================
    # Instability Gate
    # =====================

    instability_ok = max_cape >= 500 and min_li <= -2

    # =====================
    # Convective Mode
    # =====================

    mode = "None"
    if instability_ok:
        if avg_s06 >= 45 and avg_s01 >= 15:
            mode = "Discrete Supercells"
        elif avg_s03 >= 30:
            mode = "Organized Linear / QLCS"
        elif avg_s06 >= 30:
            mode = "Multicellular Clusters"
        else:
            mode = "Pulse / Disorganized"

    # =====================
    # Risk Level
    # =====================

    risk = "NONE"
    if instability_ok:
        if max_cape >= 2000 and avg_s06 >= 50:
            risk = "MDT"
        elif max_cape >= 1500 and avg_s06 >= 40:
            risk = "ENH"
        elif max_cape >= 800 and avg_s06 >= 30:
            risk = "SLGT"
        else:
            risk = "MRGL"

    # =====================
    # Fail Modes
    # =====================

    fail_modes = []
    if max_cape < 500:
        fail_modes.append("Insufficient instability")
    if avg_rh < 45:
        fail_modes.append("Dry low-level air")
    if min_li > 0:
        fail_modes.append("Strong cap")
    if avg_s06 < 25 and max_cape > 1000:
        fail_modes.append("Weak shear → poor organization")
    if total_qpf > 2 and max_cape < 800:
        fail_modes.append("Rain-dominant system")

    return {
        "risk": risk,
        "mode": mode,
        "max_cape": max_cape,
        "min_li": min_li,
        "shear01": avg_s01,
        "shear03": avg_s03,
        "shear06": avg_s06,
        "rh": avg_rh,
        "qpf": total_qpf,
        "alerts": alerts,
        "fail_modes": fail_modes,
    }

# =====================
# UI
# =====================

ui.label("Severe Weather Forecast Hub").classes("text-4xl font-bold text-center mt-4")
ui.label("Ingredients-based mesoscale guidance (experimental)").classes("text-center mb-6")

with ui.card().classes("w-96 mx-auto p-6"):
    lat_input = ui.number(label="Latitude", value=LAT)
    lon_input = ui.number(label="Longitude", value=LON)

    def update_location():
        global LAT, LON
        LAT, LON = lat_input.value, lon_input.value
        ui.notify("Location updated")

    ui.button("Update Location", on_click=update_location)

result_container = ui.card().classes("w-full max-w-4xl mx-auto mt-8 p-6")

def run_analysis():
    result_container.clear()
    try:
        data = fetch_open_meteo(LAT, LON)
        r = analyze(data)

        with result_container:
            ui.label(f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}").classes("text-sm")
            ui.label(f"Risk Level: {r['risk']}").classes("text-2xl font-bold")
            ui.label(f"Dominant Mode: {r['mode']}").classes("text-lg")

            ui.separator()

            ui.label(f"Max CAPE: {r['max_cape']:.0f} J/kg | Min LI: {r['min_li']:.1f}")
            ui.label(f"Shear (kt): 0–1km {r['shear01']:.0f} | 0–3km {r['shear03']:.0f} | 0–6km {r['shear06']:.0f}")
            ui.label(f"Moisture: RH {r['rh']:.0f}% | QPF {r['qpf']:.1f}\"")

            if r["fail_modes"]:
                ui.label("Fail Modes:").classes("text-yellow-500 font-bold")
                for f in r["fail_modes"]:
                    ui.label(f"- {f}")

            if r["alerts"]:
                ui.label("Higher-risk hours:").classes("text-red-500 font-bold")
                for a in r["alerts"]:
                    ui.label(a)

    except Exception as e:
        ui.label(str(e)).classes("text-red-600")

ui.button("ANALYZE", on_click=run_analysis).classes("mx-auto mt-6")

ui.run(host="0.0.0.0", port=7860, dark=True)