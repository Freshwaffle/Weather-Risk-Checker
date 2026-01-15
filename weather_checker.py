from nicegui import ui
import requests
from datetime import datetime
import math

def wind_to_uv(speed_kt, direction_deg):
    rad = math.radians(direction_deg)
    u = -speed_kt * math.sin(rad)
    v = -speed_kt * math.cos(rad)
    return u, v


KMH_TO_KT = 0.539957
MM_TO_IN = 0.0393701

# default location = baltimore, md
LAT, LON = 39.29, -76.61

def fetch_and_analyze():
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&hourly="
        f"cape,"
        f"wind_speed_10m,wind_direction_10m,"
        f"wind_speed_925hPa,wind_direction_925hPa,"
        f"wind_speed_700hPa,wind_direction_700hPa,"
        f"precipitation"
        f"&forecast_days=2"
        f"&timezone=America/New_York"
    )

    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()['hourly']

        alerts = []

        for i in range(len(data['time'])):
            time_str = data['time'][i]
            cape = data['cape'][i] or 0

            # shear between surface and 700 hPa
            spd_sfc = (data['wind_speed_10m'][i] or 0) * KMH_TO_KT
            dir_sfc = data['wind_direction_10m'][i]

            spd_700 = (data['wind_speed_700hPa'][i] or 0) * KMH_TO_KT
            dir_700 = data['wind_direction_700hPa'][i]

            if dir_sfc is None or dir_700 is None:
                shear = 0
            else:
                u_sfc, v_sfc = wind_to_uv(spd_sfc, dir_sfc)
                u_700, v_700 = wind_to_uv(spd_700, dir_700)
                shear = ((u_700 - u_sfc)**2 + (v_700 - v_sfc)**2) ** 0.5

            precip = (data['precipitation'][i] or 0) * MM_TO_IN  # CHANGED

            flags = []
            if cape > 1500:
                flags.append(f"High Instability (CAPE: {cape:.0f} J/kg)")
            if shear >= 25:
                flags.append(f"Strong 0–3 km Shear ({shear:.0f} kt)")
            if precip > 0.75:
                flags.append(f"Heavy Rain Risk ({precip:.2f} in/hr)")

            if len(flags) >= 2:
                alerts.append(f"{time_str}: Potential severe setup! {', '.join(flags)}")

        # 24hr summary
        cape_vals = [c for c in data['cape'][:24] if c is not None]
        max_cape = max(cape_vals) if cape_vals else 0

        total_precip = sum((p or 0) * MM_TO_IN for p in data['precipitation'][:24])

        shears = []
        for i in range(min(24, len(data['time']))):
            if data['wind_direction_10m'][i] is None or data['wind_direction_700hPa'][i] is None:
                continue

            u1, v1 = wind_to_uv(
                data['wind_speed_10m'][i] * KMH_TO_KT,
                data['wind_direction_10m'][i]
            )
            u2, v2 = wind_to_uv(
                data['wind_speed_700hPa'][i] * KMH_TO_KT,
                data['wind_direction_700hPa'][i]
            )
            shears.append(((u2 - u1)**2 + (v2 - v1)**2) ** 0.5)

        avg_shear = sum(shears) / len(shears) if shears else 0

        # risk score
        #-instability
        score = 0
        if max_cape >= 500:
            score += 1
        if max_cape >= 1500:
            score += 2
        if max_cape >= 2500:
            score += 2
        #-shear
        if avg_shear >=20:
            score += 1
        if avg_shear >=30:
            score += 1
        if avg_shear >=40:
            score += 1
        #moisture/forcing
        if total_precip >=1.0:
            score += 1
        if total_precip >=2.0:
            score += 1
        #risk level
        risk_level = "Low"
        if score >=3:
            risk_level = "Marginial"
        if score >=5:
            risk_level = "Moderate"
        if score >=7:
            risk_level = "High, Severe Potential!"
        
        result_container.clear()
        with result_container:
            color = "text-green-500"
            if score >= 3:
                color = "text-yellow-500"
            if score >= 5:
                color = "text-orange-500"
            if score >= 7:
                color = "text-red-600"
            ui.label(f"Risk Level: {risk_level} (Score: {score}/8)").classes(f'text-2xl font-bold {color}')
            ui.label(
                f"Next 24h — Max CAPE: {max_cape:.0f} J/kg | "
                f"Avg 0–3 km Shear: {avg_shear:.1f} kt | "
                f"Total Precip: {total_precip:.1f} in"
            ).classes('text-lg mb-4')

            if alerts:
                ui.label(f"{len(alerts)} high-risk hours detected:").classes('text-xl text-red-600')
                for alert in alerts:
                    ui.label(alert)
            else:
                ui.label("No strong severe ingredients right now. Low risk.").classes('text-green-600')
                confidence = "Low"
                if score >=5:
                    confidence = "Moderate"
                if score >=7:
                    confidence = "High"
                ui.label(f"Forecast Confidence: {confidence}").classes('text-sm text-gray-500 mt-4')

    except requests.exceptions.RequestException as e:
        result_container.clear()
        with result_container:
            ui.label(f"Network/API error: {str(e)}").classes('text-red-600')
        ui.notify("Couldn't reach Open-Meteo. Check internet?", type='negative')

    except Exception as e:
        result_container.clear()
        with result_container:
            ui.label(f"Unexpected error: {str(e)}").classes('text-red-600')
        ui.notify("Something went wrong — try again?", type='negative')
        with result_container:
            ui.label(f"Risk Level: {risk_level} (Score: {score}/8)").classes('text-2xl font-bold')
            ui.label(f"Next 24h — Max CAPE: {max_cape:.0f} J/kg | Avg 0–3 km Shear: {avg_shear:.1f} kt | Total Precip: {total_precip:.1f} in").classes('text-lg mb-4')
            ingredients = []
            if max_cape > 1500:
                ingredients.append("instability")
            if avg_shear >= 25:
                ingredients.append("deep-layer shear")
                if total_precip > 2.0:
                    ingredients.append("forcing / moisture")
        reason = ", ".join(ingredients) if ingredients else "no strong severe ingredients"
        ui.label(f"Drivers: {reason}").classes('italic text-gray-400 mb-2')

# ui layout
ui.label('Severe Weather Ingredients Checker').classes('text-4xl font-bold text-center mt-4')
ui.label('Powered by Open-Meteo • Checks for severe weather ingredients/setups').classes('text-center mb-6')

with ui.card().classes('w-96 mx-auto p-6'):
    ui.label('Location (Lat / Lon)').classes('text-lg')
    lat_input = ui.number(value=LAT, label='Latitude')
    lon_input = ui.number(value=LON, label='Longitude')

    def update_location():
        global LAT, LON
        LAT = lat_input.value
        LON = lon_input.value
        ui.notify(f"Location updated to {LAT}, {LON}")

    ui.button('Update Location', on_click=update_location).props('color=primary')

ui.button('CHECK NOW', on_click=fetch_and_analyze).props('color=secondary size=lg').classes('mx-auto mt-6')

result_container = ui.card().classes('w-full max-w-4xl mx-auto mt-8 p-6')

ui.run(title='MD Severe Weather Checker', dark=True)
