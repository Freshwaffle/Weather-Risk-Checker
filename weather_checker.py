from nicegui import ui
import requests
import math
import csv
from datetime import datetime
from io import StringIO

# ===== Constants =====
KMH_TO_KT = 0.539957
MM_TO_IN = 0.0393701
PRESSURE_LEVELS = ['850hPa', '500hPa']  # For low-level ( ~1.5km) and mid-level ( ~6km)

# ===== Helper functions =====
def wind_to_uv(speed_kt, direction_deg):
    rad = math.radians(direction_deg)
    u = -speed_kt * math.sin(rad)
    v = -speed_kt * math.cos(rad)
    return u, v

def vector_diff(u1, v1, u2, v2):
    return math.sqrt((u1 - u2)**2 + (v1 - v2)**2)

def approx_srh(u_sfc, v_sfc, u_mid, v_mid, u_upper, v_upper):
    # Simple 0-3km SRH approximation (assumes storm motion as 75% of mean wind)
    mean_u = (u_sfc + u_mid + u_upper) / 3
    mean_v = (v_sfc + v_mid + v_upper) / 3
    storm_u, storm_v = 0.75 * mean_u, 0.75 * mean_v
    # Helicity ~ integral, but approx as cross product sum
    h1 = (u_sfc - storm_u) * (v_mid - v_sfc) - (v_sfc - storm_v) * (u_mid - u_sfc)
    h2 = (u_mid - storm_u) * (v_upper - v_mid) - (v_mid - storm_v) * (u_upper - u_mid)
    return abs(h1 + h2)  # m2/s2, rough estimate

# ===== Fetch and analyze data =====
async def fetch_and_analyze():
    lat = location['lat']
    lon = location['lon']
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        ui.notify("Invalid lat/lon—must be -90 to 90 / -180 to 180", color='red')
        return

    hourly_vars = [
        'cape', 'wind_speed_10m', 'wind_direction_10m', 'precipitation', 'weather_code',
        'dew_point_500hPa', 'temperature_500hPa'
    ]
    for level in PRESSURE_LEVELS:
        hourly_vars.extend([f'wind_speed_{level}', f'wind_direction_{level}'])

    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}&"
        f"hourly={','.join(hourly_vars)}&"
        f"forecast_days=2&timezone=America/New_York"
    )
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()['hourly']
        alerts = []
        hourly_data = []  # For table and CSV
        times = data['time'][:24]  # Next 24h focus

        # Precompute vectors
        u_sfc, v_sfc = [], []
        u_850, v_850 = [], []
        u_500, v_500 = [], []
        bulk_shear = []
        low_shear = []
        srh = []
        cape_vals = []
        mid_dry = []  # Dewpoint depression at 500hPa

        for i in range(24):
            cape = data['cape'][i] or 0
            spd_sfc = (data['wind_speed_10m'][i] or 0) * KMH_TO_KT
            dir_sfc = data['wind_direction_10m'][i] or 0
            spd_850 = (data.get(f'wind_speed_850hPa', [0]*len(times))[i] or 0) * KMH_TO_KT
            dir_850 = data.get(f'wind_direction_850hPa', [0]*len(times))[i] or 0
            spd_500 = (data.get(f'wind_speed_500hPa', [0]*len(times))[i] or 0) * KMH_TO_KT
            dir_500 = data.get(f'wind_direction_500hPa', [0]*len(times))[i] or 0
            precip = (data['precipitation'][i] or 0) * MM_TO_IN
            wcode = data['weather_code'][i] or 0
            td_500 = data.get('dew_point_500hPa', [0]*len(times))[i] or 0
            t_500 = data.get('temperature_500hPa', [0]*len(times))[i] or 0

            u_s, v_s = wind_to_uv(spd_sfc, dir_sfc)
            u_8, v_8 = wind_to_uv(spd_850, dir_850)
            u_5, v_5 = wind_to_uv(spd_500, dir_500)
            u_sfc.append(u_s); v_sfc.append(v_s)
            u_850.append(u_8); v_850.append(v_8)
            u_500.append(u_5); v_500.append(v_5)

            bs = vector_diff(u_s, v_s, u_5, v_5)
            ls = vector_diff(u_s, v_s, u_8, v_8)
            helic = approx_srh(u_s, v_s, u_8, v_8, u_5, v_5)
            dry = t_500 - td_500 if t_500 and td_500 else 0

            bulk_shear.append(bs)
            low_shear.append(ls)
            srh.append(helic)
            mid_dry.append(dry)
            cape_vals.append(cape)

            flags = []
            if cape >= 1500: flags.append(f"High CAPE ({cape:.0f})")
            if bs >= 30: flags.append(f"Strong Bulk Shear ({bs:.0f} kt)")
            if helic >= 150: flags.append(f"Helicity ({helic:.0f} m²/s²)")
            if precip >= 0.75: flags.append(f"Heavy Precip ({precip:.2f} in)")
            if wcode in [95, 96, 99]: flags.append("Thunderstorm/Hail Possible")
            if dry >= 10: flags.append("Dry Mid-Levels")

            if len(flags) >= 2:
                alerts.append(f"{times[i][11:16]}: {', '.join(flags)}")

            hourly_data.append({
                "Time": times[i][11:16],
                "CAPE (J/kg)": cape,
                "Bulk Shear (kt)": bs,
                "Low Shear (kt)": ls,
                "SRH (m²/s²)": helic,
                "Precip (in)": precip,
                "Weather Code": wcode,
                "Flags": "; ".join(flags)
            })

        # ===== 24h Aggregates =====
        max_cape = max(cape_vals)
        avg_bulk_shear = sum(bulk_shear) / 24
        max_srh = max(srh)
        total_precip = sum((data['precipitation'][i] or 0) * MM_TO_IN for i in range(24))
        max_dry = max(mid_dry)

        # ===== SPC-Aligned Risk Scoring (out of 10) =====
        score = 0
        if max_cape >= 500: score += 1
        if max_cape >= 1500: score += 2
        if max_cape >= 2500: score += 2
        if avg_bulk_shear >= 20: score += 1
        if avg_bulk_shear >= 40: score += 1
        if max_srh >= 100: score += 1
        if max_srh >= 300: score += 1
        if total_precip >= 1.0: score += 1

        risk_level = "TSTM (General Thunderstorms)"
        if score >= 2: risk_level = "Marginal (Isolated Severe)"
        if score >= 4: risk_level = "Slight (Scattered Severe)"
        if score >= 6: risk_level = "Enhanced (Numerous Severe)"
        if score >= 8: risk_level = "Moderate (Widespread Severe)"
        if score >= 10: risk_level = "High (Major Outbreak Potential)"

        # ===== Possible/Likely Risks & Fail Modes =====
        likely = []
        if max_cape >= 1500 and avg_bulk_shear >= 30: likely.append("Supercells/Tornadoes")
        if total_precip >= 1.5 and max_cape >= 1000: likely.append("Heavy Rain/Flooding")
        if avg_bulk_shear >= 40: likely.append("Damaging Winds/Derecho")

        fail_modes = []
        if max_cape >= 1500 and avg_bulk_shear < 20: fail_modes.append("High CAPE, Low Shear — Pulse Storms Only")
        if avg_bulk_shear >= 30 and max_cape < 500: fail_modes.append("Strong Shear, Weak Instability — Elevated/Low-Topped Storms")
        if max_dry >= 15: fail_modes.append("Dry Mid-Levels — Downdraft CAPE High, Possible Microbursts but Limited Tornadoes")
        if max_srh < 100 and max_cape >= 1500: fail_modes.append("Low Helicity — Straight-Line Winds More Likely Than Rotation")

        # ===== Display =====
        result_container.clear()
        with result_container:
            color = "text-green-500"
            if score >= 4: color = "text-yellow-500"
            if score >= 6: color = "text-orange-500"
            if score >= 8: color = "text-red-500"
            if score >= 10: color = "text-purple-600"  # High
            ui.label(f"Risk: {risk_level} (Score {score}/10)").classes(f"text-2xl font-bold {color}")
            ui.label(
                f"Max CAPE: {max_cape:.0f} J/kg | Avg Bulk Shear: {avg_bulk_shear:.1f} kt | "
                f"Max SRH: {max_srh:.0f} m²/s² | Total Precip: {total_precip:.2f} in"
            ).classes("text-lg mb-4")

            if likely:
                ui.label("Likely Risks:").classes("text-lg font-semibold text-orange-600")
                for l in likely:
                    ui.label(f"- {l}")
            if fail_modes:
                ui.label("Possible Fail Modes:").classes("text-lg font-semibold text-red-600")
                for f in fail_modes:
                    ui.label(f"- {f}")
            if alerts:
                ui.label(f"{len(alerts)} Risky Hours:").classes("text-xl text-red-600")
                for a in alerts:
                    ui.label(a)
            else:
                ui.label("No Major Setups Detected").classes("text-green-600")

            # Hourly Table
            ui.table(columns=[{'name': col, 'label': col, 'field': col} for col in hourly_data[0]], rows=hourly_data).classes("mt-4")

            # Charts: CAPE and Shear Time Series
            chart_data = {
                'title': {'text': '24h Ingredients'},
                'xAxis': {'categories': [t[11:16] for t in times]},
                'yAxis': [{'title': {'text': 'CAPE (J/kg)'}}, {'title': {'text': 'Shear (kt)'}, 'opposite': True}],
                'series': [
                    {'name': 'CAPE', 'data': cape_vals, 'yAxis': 0},
                    {'name': 'Bulk Shear', 'data': bulk_shear, 'yAxis': 1}
                ]
            }
            ui.highchart(chart_data).classes("mt-4 w-full h-64")

            # CSV Download
            def download_csv():
                if not hourly_data:
                    ui.notify("No data", color='warning')
                    return
                output = StringIO()
                writer = csv.DictWriter(output, fieldnames=hourly_data[0].keys())
                writer.writeheader()
                writer.writerows(hourly_data)
                ui.download(output.getvalue().encode('utf-8'), f"forecast_{datetime.now().strftime('%Y%m%d_%H%M')}.csv", 'text/csv')

            ui.button("Download CSV", on_click=download_csv).classes("mt-4")

    except Exception as e:
        ui.notify(f"Error: {e}", color='red')

# ===== UI Setup =====
location = ui.context.client.shared_data.setdefault('location', {'lat': 39.29, 'lon': -76.61})  # Baltimore default

ui.label("Operational Severe Weather Forecaster").classes("text-4xl font-bold text-center mt-4")
ui.label("Powered by Open-Meteo | Aligned to SPC Criteria").classes("text-center mb-6")

with ui.card().classes("w-96 mx-auto p-6"):
    ui.label("Location (Lat / Lon)")
    lat_input = ui.number(value=location['lat'], label="Latitude")
    lon_input = ui.number(value=location['lon'], label="Longitude")
    async def update_location():
        location['lat'] = lat_input.value
        location['lon'] = lon_input.value
        ui.notify(f"Updated to {location['lat']}, {location['lon']}")
    ui.button("Update Location", on_click=update_location)

ui.button("RUN FORECAST", on_click=fetch_and_analyze).classes("mx-auto mt-6 block")

result_container = ui.column().classes("w-full max-w-4xl mx-auto mt-8 p-6")

ui.run(title="MD Severe Forecaster", dark=True)