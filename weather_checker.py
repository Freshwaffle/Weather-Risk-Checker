# =========================================
# 24-Hour Severe Weather / Tornado Potential Checker
# For operational forecasting (SPC-style)
# Requires: requests, math, datetime, matplotlib, nicegui
# =========================================

from nicegui import ui
import requests
from datetime import datetime
import math
import matplotlib.pyplot as plt
from io import BytesIO
import base64

# ========================
# Conversion Constants
# ========================
KMH_TO_KT = 0.539957
MM_TO_IN = 0.0393701

# ========================
# Default Location
# ========================
LAT, LON = 39.29, -76.61  # Baltimore, MD

# ========================
# Wind to UV Conversion
# ========================
def wind_to_uv(speed_kt, direction_deg):
    rad = math.radians(direction_deg)
    u = -speed_kt * math.sin(rad)
    v = -speed_kt * math.cos(rad)
    return u, v

# ========================
# Fetch and Analyze Data
# ========================
def fetch_and_analyze():
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&hourly=cape,cin,wind_speed_10m,wind_direction_10m,"
        f"wind_speed_700hPa,wind_direction_700hPa,"
        f"wind_speed_500hPa,wind_direction_500hPa,"
        f"wind_speed_300hPa,wind_direction_300hPa,"
        f"precipitation"
        f"&forecast_days=2&timezone=America/New_York"
    )

    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()['hourly']

        alerts = []
        times = data['time'][:24]
        cape_vals = data['cape'][:24]
        precip_vals = data['precipitation'][:24]
        shear_03 = []
        shear_06 = []

        # Hourly Processing
        for i in range(len(times)):
            cape = cape_vals[i] or 0
            precip = (precip_vals[i] or 0) * MM_TO_IN

            # Surface winds
            spd_sfc = (data['wind_speed_10m'][i] or 0) * KMH_TO_KT
            dir_sfc = data['wind_direction_10m'][i]

            # 700 hPa
            spd_700 = (data['wind_speed_700hPa'][i] or 0) * KMH_TO_KT
            dir_700 = data['wind_direction_700hPa'][i]

            # 500 hPa
            spd_500 = (data['wind_speed_500hPa'][i] or 0) * KMH_TO_KT
            dir_500 = data['wind_direction_500hPa'][i]

            # 300 hPa
            spd_300 = (data['wind_speed_300hPa'][i] or 0) * KMH_TO_KT
            dir_300 = data['wind_direction_300hPa'][i]

            # Compute shear
            if None not in (dir_sfc, dir_700):
                u_sfc, v_sfc = wind_to_uv(spd_sfc, dir_sfc)
                u_700, v_700 = wind_to_uv(spd_700, dir_700)
                shear_03_inst = ((u_700 - u_sfc)**2 + (v_700 - v_sfc)**2)**0.5
            else:
                shear_03_inst = 0

            if None not in (dir_sfc, dir_300):
                u_300, v_300 = wind_to_uv(spd_300, dir_300)
                deep_shear_inst = ((u_300 - u_sfc)**2 + (v_300 - v_sfc)**2)**0.5
            else:
                deep_shear_inst = 0

            shear_03.append(shear_03_inst)
            shear_06.append(deep_shear_inst)

            # Hourly flags (SPC-style)
            flags = []
            if cape >= 1500: flags.append(f"High Instability (CAPE {cape:.0f})")
            if shear_03_inst >= 25: flags.append(f"Strong 0–3 km Shear ({shear_03_inst:.0f} kt)")
            if deep_shear_inst >= 35: flags.append(f"Strong Deep-Layer Shear ({deep_shear_inst:.0f} kt)")
            if precip >= 0.75: flags.append(f"Heavy Rain ({precip:.2f} in)")
            if flags: alerts.append(f"{times[i]}: {', '.join(flags)}")

        # 24-Hour Summary
        max_cape = max([c or 0 for c in cape_vals[:24]])
        total_precip = sum([(p or 0) * MM_TO_IN for p in precip_vals[:24]])
        avg_shear_03 = sum(shear_03)/len(shear_03) if shear_03 else 0
        avg_shear_06 = sum(shear_06)/len(shear_06) if shear_06 else 0

        # SPC-style Risk Score
        score = 0
        if max_cape >= 500: score += 1
        if max_cape >= 1500: score += 2
        if max_cape >= 2500: score += 2
        if avg_shear_03 >= 25: score += 1
        if avg_shear_06 >= 40: score += 2
        if total_precip >= 0.75: score += 1
        if total_precip >= 1.5: score += 1

        risk_level = "Low"
        if score >= 3: risk_level = "Marginal"
        if score >= 5: risk_level = "Moderate"
        if score >= 7: risk_level = "High, Severe Potential!"

        # ============================
        # UI Output
        # ============================
        result_container.clear()
        with result_container:
            color = "text-green-500"
            if score >= 3: color = "text-yellow-500"
            if score >= 5: color = "text-orange-500"
            if score >= 7: color = "text-red-600"

            ui.label(f"Risk Level: {risk_level} (Score {score}/8)").classes(f"text-2xl font-bold {color}")
            ui.label(
                f"Next 24h — Max CAPE: {max_cape:.0f} J/kg | "
                f"Avg 0–3 km Shear: {avg_shear_03:.1f} kt | "
                f"Avg 0–6 km Shear: {avg_shear_06:.1f} kt | "
                f"Total Precip: {total_precip:.2f} in"
            ).classes("text-lg mb-4")

            if alerts:
                ui.label(f"{len(alerts)} potentially risky hours detected:").classes("text-xl text-red-600")
                for a in alerts: ui.label(a)
            else:
                ui.label("No Severe Weather Setups Detected").classes("text-green-600")

            # Plot CAPE & Shear
            fig, ax1 = plt.subplots(figsize=(8,4))
            ax1.plot(times, [c or 0 for c in cape_vals[:24]], 'r-', label="CAPE (J/kg)")
            ax1.set_ylabel("CAPE (J/kg)", color='r')
            ax1.tick_params(axis='y', labelcolor='r')
            ax2 = ax1.twinx()
            ax2.plot(times, shear_03, 'b--', label="0-3 km Shear (kt)")
            ax2.plot(times, shear_06, 'g--', label="0-6 km Shear (kt)")
            ax2.set_ylabel("Shear (kt)")
            fig.autofmt_xdate(rotation=45)
            fig.tight_layout()

            buf = BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            img_b64 = base64.b64encode(buf.read()).decode('utf-8')
            ui.html(f'<img src="data:image/png;base64,{img_b64}" />')

    except Exception as e:
        result_container.clear()
        ui.label(f"Error: {e}").classes("text-red-600")

# ========================
# GUI Layout
# ========================
ui.label("24h Severe Weather / Tornado Checker").classes("text-4xl font-bold text-center mt-4")
ui.label("Operational SPC-style analysis").classes("text-center mb-6")

with ui.card().classes("w-96 mx-auto p-6"):
    ui.label("Location (Lat / Lon)")
    lat_input = ui.number(value=LAT, label="Latitude")
    lon_input = ui.number(value=LON, label="Longitude")

    def update_location():
        global LAT, LON
        LAT = lat_input.value
        LON = lon_input.value
        ui.notify(f"Location updated to {LAT}, {LON}")

    ui.button("Update Location", on_click=update_location)

ui.button("CHECK NOW", on_click=fetch_and_analyze).classes("mx-auto mt-6")
result_container = ui.card().classes("w-full max-w-4xl mx-auto mt-8 p-6")

ui.run(title="24h Severe Weather Checker", dark=True)
