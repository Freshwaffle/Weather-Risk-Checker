from nicegui import ui
import requests
from datetime import datetime
import math

def wind_to_uv(speed_kt, direction_deg):
    rad = math.radians(direction_deg)
    u = -speed_kt * math.sin(rad)
    v = -speed_kt * math.cos(rad)
    return u, v

# New: Approximate SRH (0-3km) - needs storm motion vector; we'll estimate as right-mover (Bunkers method proxy)
def calculate_srh(u_sfc, v_sfc, u_700, v_700, storm_u=0, storm_v=0):  # Simple proxy; storm motion ~0 for now
    return ((u_700 - storm_u) * (v_sfc - storm_v) - (v_700 - storm_v) * (u_sfc - storm_u))  # Units: m2/s2

KMH_TO_KT = 0.539957
MM_TO_IN = 0.0393701

# Default: Baltimore, MD
LAT, LON = 39.29, -76.61

# New: Fetch SPC Day 1 categorical outlook (scrape from site; use browse_page in prod if needed)
def get_spc_outlook():
    try:
        url = "https://www.spc.noaa.gov/products/outlook/day1otlk_cat.kml"  # Or JSON if available
        response = requests.get(url)
        response.raise_for_status()
        data = response.text.lower()  # Simple parse for risk levels
        if "high" in data: return "HIGH"
        elif "mdt" in data or "moderate" in data: return "MDT"
        elif "enh" in data or "enhanced" in data: return "ENH"
        elif "slgt" in data or "slight" in data: return "SLGT"
        elif "mrgl" in data or "marginal" in data: return "MRGL"
        else: return "NONE"
    except:
        return "Unable to fetch SPC outlook"

def fetch_and_analyze():
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&hourly="
        f"cape,lifted_index,"  # Added LI for better instability proxy
        f"wind_speed_10m,wind_direction_10m,"
        f"wind_speed_925hPa,wind_direction_925hPa,"  # ~1km
        f"wind_speed_700hPa,wind_direction_700hPa,"  # ~3km
        f"wind_speed_300hPa,wind_direction_300hPa,"  # Deep
        f"precipitation,relative_humidity_2m"  # Added RH for moisture/fail modes
        f"&forecast_days=2"
        f"&timezone=America/New_York"
    )

    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()['hourly']

        alerts = []
        srh_vals = []  # New: Track SRH

        # ===== HOURLY FLAGS (A: Ingredients) =====
        for i in range(len(data['time'])):
            dt = datetime.fromisoformat(data['time'][i])
            local_time = dt.strftime("%a %I:%M %p")  # Friendly time

            cape = data['cape'][i] or 0
            li = data['lifted_index'][i] or 0  # New: LI < -4 = unstable
            rh = data['relative_humidity_2m'][i] or 0  # For moisture

            spd_sfc = (data['wind_speed_10m'][i] or 0) * KMH_TO_KT
            dir_sfc = data['wind_direction_10m'][i]

            spd_925 = (data['wind_speed_925hPa'][i] or 0) * KMH_TO_KT  # ~1km
            dir_925 = data['wind_direction_925hPa'][i]

            spd_700 = (data['wind_speed_700hPa'][i] or 0) * KMH_TO_KT
            dir_700 = data['wind_direction_700hPa'][i]

            spd_300 = (data['wind_speed_300hPa'][i] or 0) * KMH_TO_KT
            dir_300 = data['wind_direction_300hPa'][i]

            # Shear calcs
            shear_03_inst = 0
            shear_01_inst = 0  # New: 0-1km shear
            deep_shear_inst = 0
            srh_inst = 0
            if all(x is not None for x in [dir_sfc, dir_925, dir_700, dir_300]):
                u_sfc, v_sfc = wind_to_uv(spd_sfc, dir_sfc)
                u_925, v_925 = wind_to_uv(spd_925, dir_925)
                u_700, v_700 = wind_to_uv(spd_700, dir_700)
                u_300, v_300 = wind_to_uv(spd_300, dir_300)

                shear_01_inst = math.sqrt((u_925 - u_sfc)**2 + (v_925 - v_sfc)**2)
                shear_03_inst = math.sqrt((u_700 - u_sfc)**2 + (v_700 - v_sfc)**2)
                deep_shear_inst = math.sqrt((u_300 - u_sfc)**2 + (v_300 - v_sfc)**2)
                srh_inst = calculate_srh(u_sfc, v_sfc, u_700, v_700)  # Proxy SRH
                srh_vals.append(srh_inst)

            precip = (data['precipitation'][i] or 0) * MM_TO_IN

            flags = []
            if cape >= 1000: flags.append(f"Mod Instability (CAPE {cape:.0f})")
            if cape >= 2000: flags.append(f"High Instability (CAPE {cape:.0f})")
            if li <= -4: flags.append(f"Unstable (LI {li:.1f})")
            if shear_01_inst >= 15: flags.append(f"Strong 0-1km Shear ({shear_01_inst:.0f} kt)")
            if shear_03_inst >= 30: flags.append(f"Strong 0-3km Shear ({shear_03_inst:.0f} kt)")
            if deep_shear_inst >= 40: flags.append(f"Strong Deep Shear ({deep_shear_inst:.0f} kt)")
            if srh_inst >= 150: flags.append(f"High SRH ({srh_inst:.0f} m²/s²)")
            if precip >= 0.5: flags.append(f"Mod Rain ({precip:.2f} in)")
            if precip >= 1.0: flags.append(f"Heavy Rain ({precip:.2f} in)")
            if rh < 50: flags.append(f"Dry Low-Level ({rh}% RH)")

            if len(flags) >= 2 and cape >= 500:  # Filter for actual severe potential
                alerts.append(f"{local_time}: {', '.join(flags)}")

        # ===== 24H SUMMARY (A & B: Ingredients + Outcomes) =====
        cape_vals = [c for c in data['cape'][:24] if c is not None]
        max_cape = max(cape_vals) if cape_vals else 0
        avg_li = sum([l for l in data['lifted_index'][:24] if l is not None]) / 24 or 0
        total_precip = sum((p or 0) * MM_TO_IN for p in data['precipitation'][:24])
        avg_rh = sum([r for r in data['relative_humidity_2m'][:24] if r is not None]) / 24 or 0

        shear_01, shear_03, deep_shear = [], [], []
        avg_srh = sum(srh_vals[:24]) / len(srh_vals[:24]) if srh_vals else 0
        srh_display =f"{avg_srh:.0f} m²/s²"
        for i in range(24):
            if all(data.get(k)[i] is not None for k in ['wind_direction_10m', 'wind_direction_925hPa', 'wind_direction_700hPa', 'wind_direction_300hPa']):
                u_sfc, v_sfc = wind_to_uv(data['wind_speed_10m'][i] * KMH_TO_KT, data['wind_direction_10m'][i])
                u_925, v_925 = wind_to_uv(data['wind_speed_925hPa'][i] * KMH_TO_KT, data['wind_direction_925hPa'][i])
                u_700, v_700 = wind_to_uv(data['wind_speed_700hPa'][i] * KMH_TO_KT, data['wind_direction_700hPa'][i])
                u_300, v_300 = wind_to_uv(data['wind_speed_300hPa'][i] * KMH_TO_KT, data['wind_direction_300hPa'][i])

                shear_01.append(math.sqrt((u_925 - u_sfc)**2 + (v_925 - v_sfc)**2))
                shear_03.append(math.sqrt((u_700 - u_sfc)**2 + (v_700 - v_sfc)**2))
                deep_shear.append(math.sqrt((u_300 - u_sfc)**2 + (v_300 - v_sfc)**2))

        avg_shear_01 = sum(shear_01) / len(shear_01) if shear_01 else 0
        avg_shear_03 = sum(shear_03) / len(shear_03) if shear_03 else 0
        avg_deep_shear = sum(deep_shear) / len(deep_shear) if deep_shear else 0

        # Calculate composites (proxies; full calcs need more data)
        scp = (max_cape / 1000) * (avg_deep_shear / 50) * (avg_srh / 50) if avg_srh > 0 else 0  # Supercell Composite
        stp = (max_cape / 1500) * (avg_shear_01 / 20) * (avg_srh / 150) * (2000 - 1000) / 1500  # Sig Tornado Param (LCL proxy 1000m)

        # ===== RISK SCORE & SPC ALIGN =====
        score = 0

        instability_ok = (max_cape >= 500) and (avg_li <= 2)

        if instability_ok:
            if max_cape >= 500: score += 1
            if max_cape >= 1500: score += 2
            if max_cape >= 3000: score += 2

            if avg_shear_03 >= 25: score += 1
            if avg_deep_shear >= 35: score += 1
            if avg_deep_shear >= 45: score += 2

            if avg_srh >= 100: score += 1
            if avg_srh >= 250: score += 2

            if scp >= 3: score += 2
            if stp >= 1: score += 2

            if total_precip >= 0.5: score += 1
            if total_precip >= 1.5: score += 1
        else:
            score = 0  # No risk if instability lacking
        # Map score to risk level
        risk_level = "NONE"
        if score >= 2: risk_level = "MRGL"
        if score >= 5: risk_level = "SLGT"
        if score >= 8: risk_level = "ENH"
        if score >= 11: risk_level = "MDT"
        if score >= 14: risk_level = "HIGH"

        spc_current = get_spc_outlook()

        #  Fail modes & likely outcome
        fail_modes = []
        if max_cape < 500: fail_modes.append("Lack of instability - watch for warming/moistening")
        if avg_rh < 50: fail_modes.append("Dry air intrusion - could evaporate precip/storms")
        if avg_li > 0: fail_modes.append("Capping inversion - monitor for erosion via lift")
        if avg_deep_shear < 30 and max_cape > 1000: fail_modes.append("Weak shear - storms may pulse/not organize")
        if total_precip > 2 and max_cape < 1000: fail_modes.append("Heavy rain but no severe - flash flood watch")

        likely_outcome = "No severe weather expected."
        if risk_level == "MRGL": likely_outcome = "Isolated storms possible; mainly wind/hail."
        if risk_level == "SLGT": likely_outcome = "Scattered severe storms; wind/hail primary, low tornado risk."
        if risk_level == "ENH": likely_outcome = "Numerous severe storms; hail/wind, some tornadoes possible."
        if risk_level == "MDT": likely_outcome = "Widespread severe; large hail, strong tornadoes likely."
        if risk_level == "HIGH": likely_outcome = "Major outbreak; violent tornadoes, extreme hail/wind."

        if scp > 5: likely_outcome += " Supercell mode favored."
        if stp > 2: likely_outcome += " Significant tornado potential."
        if not instability_ok:
            likely_outcome = "Severe weather unlikely due to insufficient instability."

        # ===== UI OUTPUT =====
        result_container.clear()
        with result_container:
            ui.label(f"Analysis Refreshed: {datetime.now().strftime('%Y-%m-%d %I:%M %p UTC')}").classes("text-sm text-gray-500 mb-2")
            color = "text-green-500" if risk_level == "NONE" else "text-yellow-500"
            if risk_level in ["SLGT", "ENH"]: color = "text-orange-500"
            if risk_level in ["MDT", "HIGH"]: color = "text-red-600"

            ui.label(f"Risk Level: {risk_level} (Score {score})").classes(f"text-2xl font-bold {color}")
            ui.label(f"SPC Current Day 1: {spc_current}").classes("text-lg text-blue-500")
            ui.label(
                f"**Next 24h Summary**"
            ).classes("text-lg font-bold mt-2")
            
            ui.label(
                f"Instability: Max CAPE {max_cape:.0f} J/kg | Avg LI {avg_li:.1f}"
            ).classes("text-base")

            ui.label(
                f"Low-Level Shear: 0-1km {avg_shear_01:.0f} kt | 0-3km {avg_shear_03:.0f} kt"
            ).classes("text-base")

            ui.label(
                f"Deep Shear & Vorticity: 0-6km {avg_deep_shear:.1f} kt | Avg SRH {srh_display}"
            ).classes("text-base")

            ui.label(
                f"Threats & Moisture: SCP {scp:.1f} | STP {stp:.1f} | Precip {total_precip:.1f} in | Avg RH {avg_rh:.0f}%"
            ).classes("text-base")

            ui.label("").classes("mb-4 border-b border-gray-600")

            ui.label("Most Likely Outcome:").classes("text-xl font-bold")
            ui.label(likely_outcome).classes("text-md")

            if fail_modes:
                ui.label("Possible Fail Modes:").classes("text-xl font-bold text-yellow-600")
                for fm in fail_modes:
                    ui.label(f"- {fm}")

            if alerts:
                ui.label(f"{len(alerts)} higher-risk hours:").classes("text-xl text-red-600")
                for a in alerts:
                    ui.label(a)
            else:
                ui.label("No strong severe ingredients detected.").classes("text-green-600")

    except Exception as e:
        result_container.clear()
        ui.label(f"Error: {e}").classes("text-red-600")

# ===== UI =====
ui.label("Severe Weather Forecast Hub").classes("text-4xl font-bold text-center mt-4")  # Updated title
ui.label("Powered by Open-Meteo & SPC").classes("text-center mb-6")

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

ui.button("ANALYZE NOW", on_click=fetch_and_analyze).classes("mx-auto mt-6")
result_container = ui.card().classes("w-full max-w-4xl mx-auto mt-8 p-6")

ui.run(
    host='0.0.0.0',          
    port=7860,               
    dark=True,
    reload=False,            
    title="MD Severe Weather Hub",
)
