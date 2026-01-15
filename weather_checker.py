from nicegui import ui
import requests
import math

# ===== UTILITY FUNCTIONS =====
def wind_to_uv(speed_kt, direction_deg):
    """Convert wind speed (kt) and direction (deg) to u/v components."""
    rad = math.radians(direction_deg)
    u = -speed_kt * math.sin(rad)
    v = -speed_kt * math.cos(rad)
    return u, v

def calculate_shear(u_upper, v_upper, u_lower, v_lower):
    """Vector difference between two wind layers."""
    return ((u_upper - u_lower)**2 + (v_upper - v_lower)**2) ** 0.5

KMH_TO_KT = 0.539957
MM_TO_IN = 0.0393701

# ===== DEFAULT LOCATION =====
LAT, LON = 39.29, -76.61  # Baltimore, MD

# ===== MAIN FUNCTION =====
def fetch_and_analyze():
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&hourly="
        f"cape,cape_surface,cin,surface_temperature,surface_dewpoint,"
        f"wind_speed_10m,wind_direction_10m,"
        f"wind_speed_700hPa,wind_direction_700hPa,"
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

        # ===== HOURLY ANALYSIS =====
        for i in range(len(data['time'])):
            time_str = data['time'][i]

            cape = data['cape'][i] or 0
            spd_sfc = (data['wind_speed_10m'][i] or 0) * KMH_TO_KT
            dir_sfc = data['wind_direction_10m'][i] or 0
            spd_700 = (data['wind_speed_700hPa'][i] or 0) * KMH_TO_KT
            dir_700 = data['wind_direction_700hPa'][i] or 0
            spd_300 = (data['wind_speed_300hPa'][i] or 0) * KMH_TO_KT
            dir_300 = data['wind_direction_300hPa'][i] or 0
            precip = (data['precipitation'][i] or 0) * MM_TO_IN

            # 0–3 km shear
            u_sfc, v_sfc = wind_to_uv(spd_sfc, dir_sfc)
            u_700, v_700 = wind_to_uv(spd_700, dir_700)
            shear_03_inst = calculate_shear(u_700, v_700, u_sfc, v_sfc)

            # 0–6 km (deep layer) shear
            u_300, v_300 = wind_to_uv(spd_300, dir_300)
            deep_shear_inst = calculate_shear(u_300, v_300, u_sfc, v_sfc)

            flags = []
            if cape >= 1500:
                flags.append(f"High Instability (CAPE {cape:.0f})")
            if shear_03_inst >= 25:
                flags.append(f"Strong 0–3 km Shear ({shear_03_inst:.0f} kt)")
            if deep_shear_inst >= 35:
                flags.append(f"Strong Deep-Layer Shear ({deep_shear_inst:.0f} kt)")
            if precip >= 0.75:
                flags.append(f"Heavy Rain ({precip:.2f} in)")

            if len(flags) >= 2:
                alerts.append(f"{time_str}: {', '.join(flags)}")

        # ===== 24-HOUR SUMMARY =====
        cape_vals = [c for c in data['cape'][:24] if c is not None]
        max_cape = max(cape_vals) if cape_vals else 0
        total_precip = sum((p or 0) * MM_TO_IN for p in data['precipitation'][:24])

        shear_03 = [
            calculate_shear(
                *wind_to_uv((data['wind_speed_700hPa'][i] or 0) * KMH_TO_KT, data['wind_direction_700hPa'][i] or 0),
                *wind_to_uv((data['wind_speed_10m'][i] or 0) * KMH_TO_KT, data['wind_direction_10m'][i] or 0)
            ) for i in range(min(24, len(data['time'])))
        ] or [0]

        shear_06 = [
            calculate_shear(
                *wind_to_uv((data['wind_speed_300hPa'][i] or 0) * KMH_TO_KT, data['wind_direction_300hPa'][i] or 0),
                *wind_to_uv((data['wind_speed_10m'][i] or 0) * KMH_TO_KT, data['wind_direction_10m'][i] or 0)
            ) for i in range(min(24, len(data['time'])))
        ] or [0]

        avg_shear_03 = sum(shear_03) / len(shear_03)
        avg_deep_shear = sum(shear_06) / len(shear_06)

        # ===== RISK SCORING =====
        score = 0
        if max_cape >= 500: score += 1
        if max_cape >= 1500: score += 2
        if max_cape >= 2500: score += 2
        if avg_deep_shear >= 30: score += 1
        if avg_deep_shear >= 40: score += 2
        if avg_deep_shear >= 50: score += 1
        if total_precip >= 0.75: score += 1
        if total_precip >= 1.5: score += 1

        risk_level = "Low"
        if score >= 3: risk_level = "Marginal"
        if score >= 5: risk_level = "Moderate"
        if score >= 7: risk_level = "High, Severe Potential!"

        # ===== UI OUTPUT =====
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
                f"Avg 0–6 km Shear: {avg_deep_shear:.1f} kt | "
                f"Total Precip: {total_precip:.2f} in"
            ).classes("text-lg mb-4")

            if alerts:
                ui.label(f"{len(alerts)} potentially risky hours detected:").classes("text-xl text-red-600")
                for a in alerts:
                    ui.label(a)
            else:
                ui.label("No severe weather setups detected.").classes("text-green-600")

    except requests.exceptions.RequestException as e:
        result_container.clear()
        ui.label(f"Network/API error: {e}").classes("text-red-600")
        ui.notify("Couldn't reach Open-Meteo. Check your internet?", type="negative")

    except Exception as e:
        result_container.clear()
        ui.label(f"Unexpected error: {e}").classes("text-red-600")
        ui.notify("Something went wrong — try again?", type="negative")

# ===== UI LAYOUT =====
ui.label("Severe Weather Ingredients Checker").classes("text-4xl font-bold text-center mt-4")
ui.label("Powered by Open-Meteo").classes("text-center mb-6")

with ui.card().classes("w-96 mx-auto p-6"):
    ui.label("Location (Lat / Lon)").classes("text-lg")
    lat_input = ui.number(value=LAT, label="Latitude")
    lon_input = ui.number(value=LON, label="Longitude")

    def update_location():
        global LAT, LON
        LAT = lat_input.value
        LON = lon_input.value
        ui.notify(f"Location updated to {LAT}, {LON}")

    ui.button("Update Location", on_click=update_location).props("color=primary")

ui.button("CHECK NOW", on_click=fetch_and_analyze).classes("mx-auto mt-6")
result_container = ui.card().classes("w-full max-w-4xl mx-auto mt-8 p-6")

# ===== RUN SERVER =====
ui.run(title="MD Severe Weather Checker", dark=True)
