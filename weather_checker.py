from nicegui import ui
import requests
from datetime import datetime, timedelta
import math
import matplotlib.pyplot as plt
import io
import base64

# -------------------------------
# Utility functions
# -------------------------------
def wind_to_uv(speed_kt, direction_deg):
    rad = math.radians(direction_deg)
    u = -speed_kt * math.sin(rad)
    v = -speed_kt * math.cos(rad)
    return u, v

KMH_TO_KT = 0.539957
MM_TO_IN = 0.0393701

LAT, LON = 39.29, -76.61  # default: Baltimore, MD

def plot_to_html(times, *series, labels=None, title=""):
    plt.figure(figsize=(10,4))
    for i, data in enumerate(series):
        plt.plot(times, data, label=labels[i] if labels else None)
    plt.xticks(rotation=45)
    plt.grid(True)
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close()
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode('utf-8')
    return f'<img src="data:image/png;base64,{encoded}"/>'

# -------------------------------
# Fetch & Analyze Function
# -------------------------------
def fetch_and_analyze():
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&hourly="
        f"cape,cape_surface,cin,surface_temperature,surface_dewpoint,"
        f"wind_speed_10m,wind_direction_10m,"
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

        times = [datetime.fromisoformat(t) for t in data['time'][:24]]
        cape_vals, cin_vals, precip_vals = [], [], []
        shear_03_vals, shear_06_vals = [], []
        ehi_vals, stp_vals = [], []

        alerts = []

        for i in range(min(24, len(times))):
            cape = data['cape'][i] or 0
            cin = data['cin'][i] or 0
            precip = (data['precipitation'][i] or 0) * MM_TO_IN

            # Winds
            spd_sfc = (data['wind_speed_10m'][i] or 0) * KMH_TO_KT
            dir_sfc = data['wind_direction_10m'][i] or 0

            spd_700 = (data['wind_speed_700hPa'][i] or 0) * KMH_TO_KT
            dir_700 = data['wind_direction_700hPa'][i] or 0

            spd_500 = (data['wind_speed_500hPa'][i] or 0) * KMH_TO_KT
            dir_500 = data['wind_direction_500hPa'][i] or 0

            spd_300 = (data['wind_speed_300hPa'][i] or 0) * KMH_TO_KT
            dir_300 = data['wind_direction_300hPa'][i] or 0

            u_sfc, v_sfc = wind_to_uv(spd_sfc, dir_sfc)
            u_700, v_700 = wind_to_uv(spd_700, dir_700)
            u_500, v_500 = wind_to_uv(spd_500, dir_500)
            u_300, v_300 = wind_to_uv(spd_300, dir_300)

            shear_03 = ((u_700 - u_sfc)**2 + (v_700 - v_sfc)**2) ** 0.5
            shear_06 = ((u_300 - u_sfc)**2 + (v_300 - v_sfc)**2) ** 0.5

            # Approx 0–3 km SRH (simplified proxy)
            srh03 = abs(u_700 - u_sfc) * abs(v_700 - v_sfc)

            # EHI & STP
            ehi = (cape * srh03) / 160000 if cape > 0 else 0
            stp = ((cape/1500)*(srh03/150)*(shear_06/40)*(max(0,30-cin)/30))
            ehi_vals.append(ehi)
            stp_vals.append(stp)

            # Store values
            cape_vals.append(cape)
            cin_vals.append(cin)
            precip_vals.append(precip)
            shear_03_vals.append(shear_03)
            shear_06_vals.append(shear_06)

            # Alerts
            hour_alerts = []
            if cape >= 1500: hour_alerts.append(f"High Instability (CAPE {cape:.0f})")
            if shear_03 >= 25: hour_alerts.append(f"Strong 0–3 km Shear ({shear_03:.0f} kt)")
            if shear_06 >= 35: hour_alerts.append(f"Strong Deep-Layer Shear ({shear_06:.0f} kt)")
            if precip >= 0.75: hour_alerts.append(f"Heavy Rain ({precip:.2f} in)")
            if hour_alerts: alerts.append(f"{times[i].isoformat()}: {', '.join(hour_alerts)}")

        # 24h summary
        max_cape = max(cape_vals)
        total_precip = sum(precip_vals)
        avg_shear_03 = sum(shear_03_vals)/len(shear_03_vals)
        avg_shear_06 = sum(shear_06_vals)/len(shear_06_vals)
        avg_ehi = sum(ehi_vals)/len(ehi_vals)
        avg_stp = sum(stp_vals)/len(stp_vals)

        # Risk score (simplified)
        score = 0
        if max_cape >= 500: score += 1
        if max_cape >= 1500: score += 2
        if max_cape >= 2500: score += 2
        if avg_shear_03 >= 25: score += 1
        if avg_shear_06 >= 40: score += 2
        if total_precip >= 0.75: score += 1
        if avg_ehi >= 1: score += 1
        if avg_stp >= 0.5: score += 1

        risk_level = "Low"
        if score >= 3: risk_level = "Marginal"
        if score >= 5: risk_level = "Moderate"
        if score >= 7: risk_level = "High, Severe Potential!"

        # -------------------------------
        # UI Display
        # -------------------------------
        result_container.clear()
        color = "text-green-500"
        if score >= 3: color = "text-yellow-500"
        if score >= 5: color = "text-orange-500"
        if score >= 7: color = "text-red-600"

        with result_container:
            ui.label(f"Risk Level: {risk_level} (Score {score}/8)").classes(f"text-2xl font-bold {color}")
            ui.label(
                f"Next 24h — Max CAPE: {max_cape:.0f} J/kg | "
                f"Avg 0–3 km Shear: {avg_shear_03:.1f} kt | "
                f"Avg 0–6 km Shear: {avg_shear_06:.1f} kt | "
                f"Total Precip: {total_precip:.2f} in | "
                f"Avg EHI: {avg_ehi:.2f} | Avg STP: {avg_stp:.2f}"
            ).classes("text-lg mb-4")

            if alerts:
                ui.label(f"{len(alerts)} potentially risky hours detected:").classes("text-xl text-red-600")
                for a in alerts:
                    ui.label(a)
            else:
                ui.label("No severe weather setups detected.").classes("text-green-600")

            # Plots
            ui.html(plot_to_html(times, shear_03_vals, shear_06_vals, labels=["0–3 km Shear","0–6 km Shear"], title="Shear over 24h"))
            ui.html(plot_to_html(times, ehi_vals, stp_vals, labels=["EHI","STP"], title="EHI & STP over 24h"))

    except Exception as e:
        result_container.clear()
        ui.label(f"Error: {e}").classes("text-red-600")

# -------------------------------
# UI Layout
# -------------------------------
ui.label("Operational Severe Weather Checker").classes("text-4xl font-bold text-center mt-4")
ui.label("Powered by Open-Meteo | Includes EHI & STP").classes("text-center mb-6")

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

# -------------------------------
# Run public web service
# -------------------------------
ui.run(title="Operational Severe Weather Checker", dark=True, host='0.0.0.0', port=8080)
