from nicegui import ui
import requests
import math

# ===== Constants =====
KMH_TO_KT = 0.539957
MM_TO_IN = 0.0393701

# ===== Default location: Baltimore, MD =====
LAT, LON = 39.29, -76.61

# ===== Utility Functions =====
def wind_to_uv(speed_kt, direction_deg):
    rad = math.radians(direction_deg)
    u = -speed_kt * math.sin(rad)
    v = -speed_kt * math.cos(rad)
    return u, v

def calc_shear(u_lower, v_lower, u_upper, v_upper):
    return math.sqrt((u_upper - u_lower)**2 + (v_upper - v_lower)**2)

# ===== Fetch & Analyze Function =====
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

        # ===== Hourly analysis =====
        for i in range(len(data['time'])):
            time_str = data['time'][i]

            # CAPE & CIN
            cape_sfc = data['cape_surface'][i] or 0
            cape_ml = data['cape'][i] or 0
            cin = data['cin'][i] or 0

            # Surface wind
            spd_sfc = (data['wind_speed_10m'][i] or 0) * KMH_TO_KT
            dir_sfc = data['wind_direction_10m'][i]
            u_sfc, v_sfc = wind_to_uv(spd_sfc, dir_sfc) if dir_sfc is not None else (0,0)

            # Low-level shear (0-3 km)
            spd_700 = (data['wind_speed_700hPa'][i] or 0) * KMH_TO_KT
            dir_700 = data['wind_direction_700hPa'][i]
            u_700, v_700 = wind_to_uv(spd_700, dir_700) if dir_700 is not None else (0,0)
            shear_03_inst = calc_shear(u_sfc, v_sfc, u_700, v_700)

            # Deep-layer shear (0-6 km ~ surface to 500 hPa)
            spd_500 = (data['wind_speed_500hPa'][i] or 0) * KMH_TO_KT
            dir_500 = data['wind_direction_500hPa'][i]
            u_500, v_500 = wind_to_uv(spd_500, dir_500) if dir_500 is not None else (0,0)
            shear_06_inst = calc_shear(u_sfc, v_sfc, u_500, v_500)

            # Upper-level shear (0-8 km ~ surface to 300 hPa)
            spd_300 = (data['wind_speed_300hPa'][i] or 0) * KMH_TO_KT
            dir_300 = data['wind_direction_300hPa'][i]
            u_300, v_300 = wind_to_uv(spd_300, dir_300) if dir_300 is not None else (0,0)
            shear_08_inst = calc_shear(u_sfc, v_sfc, u_300, v_300)

            # Precipitation
            precip = (data['precipitation'][i] or 0) * MM_TO_IN

            # Hourly flags
            flags = []
            if cape_ml >= 1500:
                flags.append(f"High Instability (CAPE {cape_ml:.0f})")
            if shear_03_inst >= 25:
                flags.append(f"Strong 0–3 km Shear ({shear_03_inst:.0f} kt)")
            if shear_06_inst >= 40:
                flags.append(f"Strong 0–6 km Shear ({shear_06_inst:.0f} kt)")
            if shear_08_inst >= 50:
                flags.append(f"Strong 0–8 km Shear ({shear_08_inst:.0f} kt)")
            if precip >= 0.5:
                flags.append(f"Heavy Rain ({precip:.2f} in)")

            if flags:
                alerts.append(f"{time_str}: {', '.join(flags)}")

        # ===== 24-hour summary =====
        max_cape = max([c or 0 for c in data['cape'][:24]]) if data['cape'] else 0
        total_precip = sum((p or 0) * MM_TO_IN for p in data['precipitation'][:24])
        avg_shear_03 = sum([calc_shear(
            wind_to_uv((data['wind_speed_10m'][i] or 0)*KMH_TO_KT, data['wind_direction_10m'][i]),
            wind_to_uv((data['wind_speed_700hPa'][i] or 0)*KMH_TO_KT, data['wind_direction_700hPa'][i])
        ) for i in range(min(24, len(data['time'])))]) / 24
        avg_shear_06 = sum([calc_shear(
            wind_to_uv((data['wind_speed_10m'][i] or 0)*KMH_TO_KT, data['wind_direction_10m'][i]),
            wind_to_uv((data['wind_speed_500hPa'][i] or 0)*KMH_TO_KT, data['wind_direction_500hPa'][i])
        ) for i in range(min(24, len(data['time'])))]) / 24

        # ===== Risk scoring =====
        score = 0
        if max_cape >= 500: score += 1
        if max_cape >= 1500: score += 2
        if avg_shear_03 >= 25: score += 1
        if avg_shear_06 >= 40: score += 1
        if total_precip >= 0.5: score += 1
        if total_precip >= 1.5: score += 1

        risk_level = "Low"
        if score >= 3: risk_level = "Marginal"
        if score >= 5: risk_level = "Enhanced"
        if score >= 7: risk_level = "Moderate"
        if score >= 9: risk_level = "High"

        # ===== UI Output =====
        result_container.clear()
        with result_container:
            color = "text-green-500"
            if score >= 3: color = "text-yellow-500"
            if score >= 5: color = "text-orange-500"
            if score >= 7: color = "text-red-600"
            if score >= 9: color = "text-red-900"

            ui.label(f"Risk Level: {risk_level} (Score {score}/10)").classes(f"text-2xl font-bold {color}")
            ui.label(
                f"Next 24h — Max CAPE: {max_cape:.0f} J/kg | "
                f"Avg 0–3 km Shear: {avg_shear_03:.1f} kt | "
                f"Avg 0–6 km Shear: {avg_shear_06:.1f} kt | "
                f"Total Precip: {total_precip:.2f} in"
            ).classes("text-lg mb-4")

            if alerts:
                ui.label(f"{len(alerts)} potentially risky hours detected:").classes("text-xl text-red-600")
                for a in alerts:
                    ui.label(a)
            else:
                ui.label("No severe weather setups detected.").classes("text-green-600")

    except Exception as e:
        result_container.clear()
        ui.label(f"Error: {e}").classes("text-red-600")

# ===== UI =====
ui.label("Professional Severe Weather Checker").classes("text-4xl font-bold text-center mt-4")
ui.label("Operational-grade severe setup detection").classes("text-center mb-6")

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

ui.button("RUN ANALYSIS", on_click=fetch_and_analyze).classes("mx-auto mt-6")
result_container = ui.card().classes("w-full max-w-4xl mx-auto mt-8 p-6")

ui.run(title="Operational Severe Weather Checker", dark=True)
