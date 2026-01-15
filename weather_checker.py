from nicegui import ui
import requests
import math
from datetime import datetime

# --- Utility Functions ---

KMH_TO_KT = 0.539957
MM_TO_IN = 0.0393701

def wind_to_uv(speed_kt, direction_deg):
    """Convert wind speed (kt) and direction (deg) to u,v components."""
    rad = math.radians(direction_deg)
    u = -speed_kt * math.sin(rad)
    v = -speed_kt * math.cos(rad)
    return u, v

def calc_shear(u_lower, v_lower, u_upper, v_upper):
    """Vector shear magnitude between two wind levels."""
    return ((u_upper - u_lower)**2 + (v_upper - v_lower)**2) ** 0.5

def calc_lcl(temp_c, dew_c):
    """Approximate LCL in meters using surface temp and dewpoint."""
    return 125 * (temp_c - dew_c)

def calc_ehi(cape, srh):
    """Approximate Energy Helicity Index (EHI)"""
    if cape > 0 and srh > 0:
        return (cape / 1600.0) * (srh / 100.0)
    return 0

# --- Default Location ---
LAT, LON = 39.29, -76.61  # Baltimore, MD

# --- Result Container ---
result_container = ui.card().classes("w-full max-w-4xl mx-auto mt-8 p-6")

# --- Fetch & Analyze Function ---
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
        f"&forecast_days=2"
        f"&timezone=America/New_York"
    )

    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()['hourly']

        alerts = []

        shear_03_list = []
        shear_06_list = []
        ehi_list = []

        # --- Hourly Analysis ---
        for i in range(len(data['time'])):
            time_str = data['time'][i]
            temp_sfc = data['surface_temperature'][i] or 0
            dew_sfc = data['surface_dewpoint'][i] or 0
            cape = data['cape'][i] or 0
            cin = data['cin'][i] or 0
            precip = (data['precipitation'][i] or 0) * MM_TO_IN

            # --- Winds ---
            spd_sfc = (data['wind_speed_10m'][i] or 0) * KMH_TO_KT
            dir_sfc = data['wind_direction_10m'][i]

            spd_700 = (data['wind_speed_700hPa'][i] or 0) * KMH_TO_KT
            dir_700 = data['wind_direction_700hPa'][i]

            spd_500 = (data['wind_speed_500hPa'][i] or 0) * KMH_TO_KT
            dir_500 = data['wind_direction_500hPa'][i]

            spd_300 = (data['wind_speed_300hPa'][i] or 0) * KMH_TO_KT
            dir_300 = data['wind_direction_300hPa'][i]

            u_sfc, v_sfc = wind_to_uv(spd_sfc, dir_sfc)
            u_700, v_700 = wind_to_uv(spd_700, dir_700)
            u_500, v_500 = wind_to_uv(spd_500, dir_500)
            u_300, v_300 = wind_to_uv(spd_300, dir_300)

            shear_03 = calc_shear(u_sfc, v_sfc, u_700, v_700)
            shear_06 = calc_shear(u_sfc, v_sfc, u_300, v_300)

            shear_03_list.append(shear_03)
            shear_06_list.append(shear_06)

            # --- LCL & SRH ---
            lcl = calc_lcl(temp_sfc, dew_sfc)
            srh_01 = shear_03 * (1000.0 / max(lcl, 100))  # crude low-level SRH approx

            # --- EHI ---
            ehi = calc_ehi(cape, srh_01)
            ehi_list.append(ehi)

            # --- Flags ---
            flags = []
            if cape >= 1500:
                flags.append(f"High Instability (CAPE {cape:.0f})")
            if shear_03 >= 25:
                flags.append(f"Strong 0–3 km Shear ({shear_03:.0f} kt)")
            if shear_06 >= 35:
                flags.append(f"Strong Deep-Layer Shear ({shear_06:.0f} kt)")
            if ehi >= 1:
                flags.append(f"Tornado Potential (EHI {ehi:.2f})")
            if precip >= 0.75:
                flags.append(f"Heavy Rain ({precip:.2f} in)")

            if flags:
                alerts.append(f"{time_str}: {', '.join(flags)}")

        # --- 24h Summary ---
        max_cape = max([c for c in data['cape'][:24] if c is not None] or [0])
        total_precip = sum((p or 0) * MM_TO_IN for p in data['precipitation'][:24])
        avg_shear_03 = sum(shear_03_list[:24]) / len(shear_03_list[:24])
        avg_shear_06 = sum(shear_06_list[:24]) / len(shear_06_list[:24])
        max_ehi = max(ehi_list[:24])

        # --- Risk Scoring ---
        score = 0
        if max_cape >= 500: score += 1
        if max_cape >= 1500: score += 2
        if avg_shear_06 >= 30: score += 1
        if avg_shear_06 >= 40: score += 2
        if max_ehi >= 1: score += 2
        if total_precip >= 0.75: score += 1
        if total_precip >= 1.5: score += 1

        risk_level = "Low"
        if score >= 3: risk_level = "Marginal"
        if score >= 5: risk_level = "Slight / Enhanced"
        if score >= 7: risk_level = "Moderate+ / High Tornado Potential"

        # --- UI Output ---
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
                f"Total Precip: {total_precip:.2f} in | "
                f"Max EHI: {max_ehi:.2f}"
            ).classes("text-lg mb-4")

            if alerts:
                ui.label(f"{len(alerts)} potentially risky hours detected:").classes("text-xl text-red-600")
                for a in alerts:
                    ui.label(a)
            else:
                ui.label("No significant severe weather setups detected.").classes("text-green-600")

    except Exception as e:
        result_container.clear()
        ui.label(f"Error: {e}").classes("text-red-600")

# --- UI ---
ui.label("Severe Weather & Tornado Ingredients Checker").classes("text-4xl font-bold text-center mt-4")
ui.label("Powered by Open-Meteo").classes("text-center mb-6")

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

ui.run(title="Severe Weather Checker", dark=True)
