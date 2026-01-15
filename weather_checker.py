from nicegui import ui
import requests
import math

# ----------------------
# Helper Functions
# ----------------------
def wind_to_uv(speed_kt, direction_deg):
    """Convert wind speed (kt) and direction (deg) to u/v components."""
    rad = math.radians(direction_deg)
    u = -speed_kt * math.sin(rad)
    v = -speed_kt * math.cos(rad)
    return u, v

KMH_TO_KT = 0.539957
MM_TO_IN = 0.0393701

# ----------------------
# Default Location
# ----------------------
LAT, LON = 39.29, -76.61  # Baltimore, MD

# ----------------------
# Main Analysis Function
# ----------------------
def fetch_and_analyze():
    global LAT, LON

    # ECMWF endpoint (supports CAPE, CIN, upper-level winds)
    url = (
        f"https://api.open-meteo.com/v1/ecmwf?"
        f"latitude={LAT}&longitude={LON}"
        f"&hourly="
        f"cape,convective_inhibition,temperature_2m,dew_point_2m,"
        f"wind_speed_10m,wind_direction_10m,"
        f"wind_speed_1000hPa,wind_direction_1000hPa,"
        f"wind_speed_850hPa,wind_direction_850hPa,"
        f"wind_speed_700hPa,wind_direction_700hPa,"
        f"wind_speed_500hPa,wind_direction_500hPa,"
        f"wind_speed_300hPa,wind_direction_300hPa,"
        f"precipitation,relative_humidity_2m"
        f"&forecast_days=2&timezone=America/New_York"
    )

    try:
        resp = requests.get(url)
        resp.raise_for_status()
        data = resp.json()['hourly']

        alerts = []
        shear_03_list, shear_06_list = [], []

        for i in range(len(data['time'])):
            # Time
            t = data['time'][i]

            # CAPE
            cape = data['cape'][i] or 0

            # Winds
            wsfc = (data['wind_speed_10m'][i] or 0) * KMH_TO_KT
            dsfc = data['wind_direction_10m'][i] or 0

            w700 = (data['wind_speed_700hPa'][i] or 0) * KMH_TO_KT
            d700 = data['wind_direction_700hPa'][i] or 0

            w300 = (data['wind_speed_300hPa'][i] or 0) * KMH_TO_KT
            d300 = data['wind_direction_300hPa'][i] or 0

            # Shear calculation
            u_sfc, v_sfc = wind_to_uv(wsfc, dsfc)
            u_700, v_700 = wind_to_uv(w700, d700)
            u_300, v_300 = wind_to_uv(w300, d300)

            shear_03 = ((u_700 - u_sfc)**2 + (v_700 - v_sfc)**2)**0.5
            shear_06 = ((u_300 - u_sfc)**2 + (v_300 - v_sfc)**2)**0.5

            shear_03_list.append(shear_03)
            shear_06_list.append(shear_06)

            # Precip
            precip = (data['precipitation'][i] or 0) * MM_TO_IN

            # Alert flags
            flags = []
            if cape >= 1500: flags.append(f"High CAPE ({cape:.0f} J/kg)")
            if shear_03 >= 25: flags.append(f"Strong 0–3 km Shear ({shear_03:.0f} kt)")
            if shear_06 >= 35: flags.append(f"Strong Deep-Layer Shear ({shear_06:.0f} kt)")
            if precip >= 0.75: flags.append(f"Heavy Precip ({precip:.2f} in)")

            if len(flags) >= 2:
                alerts.append(f"{t}: {', '.join(flags)}")

        # 24h Summary
        max_cape = max([c for c in data['cape'][:24] if c is not None] or [0])
        total_precip = sum([(p or 0)*MM_TO_IN for p in data['precipitation'][:24]])
        avg_shear_03 = sum(shear_03_list[:24])/len(shear_03_list[:24])
        avg_shear_06 = sum(shear_06_list[:24])/len(shear_06_list[:24])

        # Scoring System
        score = 0
        if max_cape >= 500: score += 1
        if max_cape >= 1500: score += 2
        if max_cape >= 2500: score += 2
        if avg_shear_06 >= 30: score += 1
        if avg_shear_06 >= 40: score += 2
        if avg_shear_06 >= 50: score += 1
        if total_precip >= 0.75: score += 1
        if total_precip >= 1.5: score += 1

        # Risk Level
        risk_level = "Low"
        if score >= 3: risk_level = "Marginal"
        if score >= 5: risk_level = "Moderate"
        if score >= 7: risk_level = "High, Severe Potential!"

        # UI Output
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
                ui.label("No strong severe weather setups detected.").classes("text-green-600")

    except requests.exceptions.RequestException as e:
        result_container.clear()
        ui.label(f"Network/API error: {e}").classes("text-red-600")
        ui.notify("Couldn't reach ECMWF Open-Meteo API.", type="negative")
    except Exception as e:
        result_container.clear()
        ui.label(f"Unexpected error: {e}").classes("text-red-600")
        ui.notify("Something went wrong in analysis.", type="negative")

# ----------------------
# NiceGUI UI Layout
# ----------------------
ui.label("Severe Weather & Tornado Setup Checker").classes("text-4xl font-bold text-center mt-4")
ui.label("Powered by Open-Meteo ECMWF").classes("text-center mb-6")

with ui.card().classes("w-96 mx-auto p-6"):
    ui.label("Location (Lat / Lon)").classes("text-lg")
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

# Run GUI
ui.run(title="Operational Severe Weather Checker", dark=True)
