from nicegui import ui
import requests
import math
from datetime import datetime

# ============================================================
# METEOROLOGICAL CONSTANTS & HELPERS
# ============================================================

def dir_spd_to_uv(direction_deg, speed_kt):
    """Convert meteorological wind (from-direction, speed) to U/V components."""
    rad = math.radians(direction_deg)
    u = -speed_kt * math.sin(rad)
    v = -speed_kt * math.cos(rad)
    return u, v

def vector_magnitude(u, v):
    return math.sqrt(u**2 + v**2)

# ============================================================
# KINEMATIC CALCULATIONS
# ============================================================

def compute_shear(u_bot, v_bot, u_top, v_top):
    """Bulk wind difference (shear) between two levels in kt."""
    return vector_magnitude(u_top - u_bot, v_top - v_bot)

def get_bunkers_motion(u_sfc, v_sfc, u_mid, v_mid, u_top, v_top):
    """
    Bunkers (2000) storm motion via the Internal Dynamics method.
    Uses mean wind of the layer + deviation vector perpendicular to shear.
    Returns (RM_u, RM_v, LM_u, LM_v, mean_u, mean_v).
    Deviation D = 7.5 m/s (~14.6 kt) perpendicular to 0-6 km shear vector.
    """
    D = 14.6  # kt — empirical deviation

    # Mean wind (simple 3-level average as proxy for 0–6 km mean)
    mean_u = (u_sfc + u_mid + u_top) / 3
    mean_v = (v_sfc + v_mid + v_top) / 3

    # Shear vector (0–6 km proxy: surface to upper level)
    sh_u = u_top - u_sfc
    sh_v = v_top - v_sfc
    shear_mag = vector_magnitude(sh_u, sh_v)

    if shear_mag < 1:
        # No meaningful shear; fallback
        return mean_u + 7.5, mean_v - 7.5, mean_u - 7.5, mean_v + 7.5, mean_u, mean_v

    # Unit vector perpendicular to shear (90° clockwise = right-mover)
    perp_u =  sh_v / shear_mag
    perp_v = -sh_u / shear_mag

    rm_u = mean_u + D * perp_u
    rm_v = mean_v + D * perp_v
    lm_u = mean_u - D * perp_u
    lm_v = mean_v - D * perp_v

    return rm_u, rm_v, lm_u, lm_v, mean_u, mean_v

def calculate_srh(u_sfc, v_sfc, u_mid, v_mid, storm_u, storm_v):
    """
    Approximate 0–3 km SRH using two wind levels (surface & 700 hPa ~3 km).
    SRH = integral of (V_wind - V_storm) × dV_wind
    For two-level approximation:
    SRH ≈ (u_sfc - su)(v_mid - sv) - (v_sfc - sv)(u_mid - su)
           + (u_mid - su)(v_sfc - sv) - (v_mid - sv)(u_sfc - su)  [second leg back]
    Simplified to the standard two-layer formula.
    """
    # Relative winds
    ru_sfc = u_sfc - storm_u
    rv_sfc = v_sfc - storm_v
    ru_mid = u_mid - storm_u
    rv_mid = v_mid - storm_v

    # Cross products for each layer segment (signed area)
    srh = (ru_sfc * rv_mid) - (ru_mid * rv_sfc)
    return srh

# ============================================================
# COMPOSITE PARAMETERS
# ============================================================

def supercell_composite(cape, srh, shear_06):
    """
    Supercell Composite Parameter (Thompson et al. 2004 approximation).
    SCP = (MUCAPE/1000) * (SRH/50) * (0-6km shear / 20kt)
    Values > 1 favor supercells; > 4 significant supercell threat.
    """
    if cape < 100 or srh < 0 or shear_06 < 10:
        return 0.0
    scp = (cape / 1000.0) * (max(srh, 0) / 50.0) * (shear_06 / 20.0)
    return round(scp, 2)

def significant_tornado_parameter(cape, srh, shear_06, lcl_proxy_rh):
    """
    Significant Tornado Parameter (simplified).
    STP = (MLCAPE/1500) * (0-1km SRH/150) * (0-6km shear/20kt) * (LCL factor)
    We use 0-3km SRH as a proxy when 0-1km isn't cleanly available.
    LCL factor approximated from RH (high RH → lower LCL → favorable).
    STP >= 1 signals significant tornado potential.
    """
    if cape < 100 or srh <= 0 or shear_06 < 12:
        return 0.0

    lcl_factor = max(0.0, min(1.0, (lcl_proxy_rh - 50) / 30.0))  # 0 at RH<50, 1 at RH>80
    stp = (cape / 1500.0) * (max(srh, 0) / 150.0) * (shear_06 / 20.0) * lcl_factor
    return round(stp, 2)

# ============================================================
# ENVIRONMENT ANALYSIS ENGINE
# ============================================================

SUPPORT_LEVELS = [
    (0,   "None",     "grey",    "⬛"),
    (1,   "Marginal", "blue",    "🟦"),
    (2,   "Limited",  "green",   "🟩"),
    (3,   "Moderate", "yellow",  "🟨"),
    (4,   "Enhanced", "orange",  "🟧"),
    (5,   "Extreme",  "red",     "🟥"),
]

def score_environment(cape, cin, shear_01, shear_06, srh, rh, li, scp, stp):
    """Returns (score 0-5, label, color, emoji, mode, fail_modes, notes)."""
    fail_modes = []
    notes = []

    # --- Instability gating ---
    if cape < 100 or li > 2:
        return 0, "None", "grey", "⬛", "No Convective Threat", ["Insufficient instability (CAPE < 100 J/kg or LI > 2)."], []

    # --- CIN gate ---
    if cin < -150:
        fail_modes.append("Extreme capping (CIN < -150 J/kg) — storms very unlikely to fire without strong forcing.")
    elif cin < -75:
        fail_modes.append("Moderate cap (CIN < -75 J/kg) — initiation requires robust surface-based forcing.")

    # --- Moisture ---
    if rh < 45:
        fail_modes.append("Very dry boundary layer (RH < 45%) — strong entrainment will erode updrafts.")
    elif rh < 60:
        notes.append("Marginal moisture (RH 45–60%) — some dilution of updrafts expected.")

    # --- Convective mode ---
    if shear_06 >= 40 and cape >= 500:
        mode = "Supercellular"
        if stp >= 1.0:
            mode = "Tornadic Supercells"
        elif stp >= 0.5:
            mode = "Supercells / Tor. Possible"
    elif shear_06 >= 25 and cape >= 500:
        mode = "Organized Multicells / QLCS"
        if shear_01 >= 20 and srh >= 150:
            mode = "QLCS / Embedded Supercells"
    elif shear_06 >= 15 and cape >= 300:
        mode = "Multicell Clusters"
        if cape < 1000:
            fail_modes.append("Limited CAPE may restrict updraft intensity and hail size.")
    else:
        mode = "Pulse / Single Cell"
        if shear_06 < 15:
            fail_modes.append("Weak deep-layer shear — storms will be short-lived and outflow dominant.")

    # --- Outflow dominance check ---
    if cape > 2500 and shear_06 < 20:
        fail_modes.append("High CAPE + weak shear → outflow dominant storms that collapse quickly.")

    # --- Score ---
    score = 0
    if cape > 500: score += 1
    if cape > 1500: score += 1
    if shear_06 > 30: score += 1
    if scp > 2 or stp > 0.5: score += 1
    if srh > 200 and stp > 1: score += 1
    score = min(score, 5)

    _, label, color, emoji = SUPPORT_LEVELS[score]
    return score, label, color, emoji, mode, fail_modes, notes

# ============================================================
# DATA FETCHING
# ============================================================

def geocode(location_str):
    """Geocode a location string using Open-Meteo's geocoding API."""
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={requests.utils.quote(location_str)}&count=1&language=en&format=json"
    try:
        r = requests.get(url, timeout=8).json()
        if r.get('results'):
            res = r['results'][0]
            return res['latitude'], res['longitude'], res.get('name', location_str), res.get('country', '')
    except Exception:
        pass
    return None

def fetch_weather(lat, lon):
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        f"&hourly=cape,lifted_index,convective_inhibition,relative_humidity_2m,"
        f"wind_speed_10m,wind_direction_10m,"
        f"wind_speed_850hPa,wind_direction_850hPa,"
        f"wind_speed_700hPa,wind_direction_700hPa,"
        f"wind_speed_500hPa,wind_direction_500hPa"
        f"&wind_speed_unit=kn&timezone=auto&forecast_days=2"
    )
    try:
        r = requests.get(url, timeout=12).json()
        return r.get('hourly'), r.get('timezone_abbreviation', 'UTC')
    except Exception as e:
        return None, str(e)

# ============================================================
# UI
# ============================================================

ui.dark_mode().enable()

# Header
with ui.row().classes('w-full justify-center items-center pt-6 pb-2 gap-2'):
    ui.icon('thunderstorm', size='2rem').classes('text-yellow-400')
    ui.label('Severe Weather Environment Diagnostics').classes('text-3xl font-bold text-white')

ui.label('Ingredient-based convective analysis · Not an official forecast product').classes(
    'w-full text-center text-sm text-gray-400 pb-4'
)

# Search bar
with ui.card().classes('w-full max-w-2xl mx-auto mb-4'):
    with ui.row().classes('w-full items-end gap-3'):
        location_input = ui.input(
            label='Location (city name or "lat, lon")',
            placeholder='e.g. Oklahoma City or 35.47, -97.52'
        ).classes('flex-1')
        analyze_btn = ui.button('Analyze', icon='search').props('elevated color=yellow')

    with ui.row().classes('w-full items-center gap-6 pt-2'):
        hours_select = ui.select(
            label='Forecast window',
            options={'24': 'Next 24 hours', '48': 'Next 48 hours'},
            value='24'
        ).classes('w-48')
        ui.label('').classes('flex-1')  # spacer
        show_all_toggle = ui.switch('Show low-threat hours', value=False)

status_label = ui.label('').classes('w-full max-w-2xl mx-auto text-sm text-gray-400 px-2')
results_col = ui.column().classes('w-full max-w-2xl mx-auto p-2 gap-2')

# ============================================================
# LEGEND
# ============================================================
with ui.card().classes('w-full max-w-2xl mx-auto mb-6 p-3'):
    ui.label('Support Level Legend').classes('text-xs font-semibold text-gray-400 mb-1')
    with ui.row().classes('gap-3 flex-wrap'):
        for _, label, color, emoji in SUPPORT_LEVELS:
            ui.label(f"{emoji} {label}").classes('text-xs')

# ============================================================
# ANALYSIS RUN
# ============================================================

def run_analysis():
    raw = location_input.value.strip()
    if not raw:
        status_label.set_text('⚠ Please enter a location.')
        return

    results_col.clear()
    analyze_btn.props('loading')
    status_label.set_text('Fetching data…')

    lat, lon, display_name = None, None, raw

    # Try parsing as "lat, lon"
    try:
        parts = [p.strip() for p in raw.split(',')]
        if len(parts) == 2:
            lat = float(parts[0])
            lon = float(parts[1])
            display_name = f"{lat:.3f}, {lon:.3f}"
    except ValueError:
        pass

    # Otherwise geocode
    if lat is None:
        status_label.set_text('Geocoding location…')
        result = geocode(raw)
        if result is None:
            status_label.set_text('❌ Could not geocode location. Try "lat, lon" format.')
            analyze_btn.props(remove='loading')
            return
        lat, lon, name, country = result
        display_name = f"{name}, {country}" if country else name

    status_label.set_text(f'Fetching forecast for {display_name}…')
    data, tz = fetch_weather(lat, lon)

    if data is None:
        status_label.set_text(f'❌ API error: {tz}')
        analyze_btn.props(remove='loading')
        return

    n_hours = int(hours_select.value)
    show_all = show_all_toggle.value
    displayed = 0

    with results_col:
        ui.label(f"Environmental Analysis: {display_name}").classes('text-xl font-bold text-white mt-2')
        ui.label(f"Timezone: {tz} · {n_hours}-hour window").classes('text-xs text-gray-400 mb-2')

        for i in range(min(n_hours, len(data['time']))):
            cape = data['cape'][i] or 0
            cin  = data['convective_inhibition'][i] or 0
            li   = data['lifted_index'][i] or 0
            rh   = data['relative_humidity_2m'][i] or 0

            # Surface winds
            u_sfc, v_sfc = dir_spd_to_uv(
                data['wind_direction_10m'][i] or 0,
                data['wind_speed_10m'][i] or 0
            )
            # 850 hPa (~1.5 km) — useful for low-level shear
            u_850, v_850 = dir_spd_to_uv(
                data['wind_direction_850hPa'][i] or 0,
                data['wind_speed_850hPa'][i] or 0
            )
            # 700 hPa (~3 km) — mid-level, used for SRH layer top
            u_700, v_700 = dir_spd_to_uv(
                data['wind_direction_700hPa'][i] or 0,
                data['wind_speed_700hPa'][i] or 0
            )
            # 500 hPa (~5.5 km) — used for deep-layer shear
            u_500, v_500 = dir_spd_to_uv(
                data['wind_direction_500hPa'][i] or 0,
                data['wind_speed_500hPa'][i] or 0
            )

            # Shear
            shear_06 = compute_shear(u_sfc, v_sfc, u_500, v_500)
            shear_01 = compute_shear(u_sfc, v_sfc, u_850, v_850) * 0.5  # rough 0-1km proxy from 0-1.5km

            # Bunkers storm motion (right-mover)
            rm_u, rm_v, _, _, _, _ = get_bunkers_motion(u_sfc, v_sfc, u_700, v_700, u_500, v_500)

            # SRH (0–3 km layer, surface to 700 hPa)
            srh = calculate_srh(u_sfc, v_sfc, u_700, v_700, rm_u, rm_v)

            # Composite params
            scp = supercell_composite(cape, srh, shear_06)
            stp = significant_tornado_parameter(cape, srh, shear_06, rh)

            score, label, color, emoji, mode, fail_modes, notes = score_environment(
                cape, cin, shear_01, shear_06, srh, rh, li, scp, stp
            )

            # Filter low-threat hours unless show_all is on
            if score < 2 and not show_all:
                continue

            dt_obj = datetime.fromisoformat(data['time'][i])
            dt_str = dt_obj.strftime("%a %-I %p")

            color_map = {
                'grey': 'text-gray-400', 'blue': 'text-blue-400',
                'green': 'text-green-400', 'yellow': 'text-yellow-300',
                'orange': 'text-orange-400', 'red': 'text-red-400'
            }
            text_color = color_map.get(color, 'text-white')

            displayed += 1
            with ui.card().classes('w-full'):
                with ui.expansion() as exp:
                    with exp.add_slot('header'):
                        with ui.row().classes('w-full items-center gap-3'):
                            ui.label(emoji).classes('text-xl')
                            with ui.column().classes('gap-0'):
                                ui.label(dt_str).classes('text-xs text-gray-400')
                                ui.label(mode).classes(f'font-semibold {text_color}')
                            ui.label('').classes('flex-1')
                            ui.badge(label, color=color if color != 'grey' else 'grey').props('rounded')

                    # Expanded content
                    with ui.grid(columns=2).classes('w-full gap-x-6 gap-y-1 text-sm mt-2'):
                        # Instability
                        ui.label('🌡 Instability').classes('font-semibold col-span-2 text-gray-300 mt-1')
                        ui.label(f"CAPE: {cape:.0f} J/kg")
                        ui.label(f"LI: {li:.1f} K")
                        ui.label(f"CIN: {cin:.0f} J/kg")
                        ui.label(f"RH: {rh:.0f}%")

                        # Kinematics
                        ui.label('💨 Kinematics').classes('font-semibold col-span-2 text-gray-300 mt-2')
                        ui.label(f"0–6km Shear: {shear_06:.1f} kt")
                        ui.label(f"0–1km Shear (proxy): {shear_01:.1f} kt")
                        ui.label(f"0–3km SRH: {srh:.0f} m²/s²")
                        ui.label('')

                        # Composites
                        ui.label('📊 Composite Params').classes('font-semibold col-span-2 text-gray-300 mt-2')
                        ui.label(f"SCP: {scp:.2f}  {'⚠' if scp > 4 else ''}")
                        ui.label(f"STP: {stp:.2f}  {'⚠' if stp >= 1 else ''}")

                    if fail_modes:
                        ui.separator().classes('my-2')
                        ui.label('⚠ Possible Fail Modes').classes('text-orange-400 font-semibold text-sm')
                        for fm in fail_modes:
                            ui.label(f"• {fm}").classes('text-orange-300 text-xs')

                    if notes:
                        for n in notes:
                            ui.label(f"ℹ {n}").classes('text-blue-300 text-xs mt-1')

        if displayed == 0:
            with ui.card().classes('w-full text-center p-6'):
                ui.label('No significant severe weather support found in this window.').classes('text-gray-400')
                ui.label('Toggle "Show low-threat hours" to view all time steps.').classes('text-xs text-gray-500 mt-1')

    status_label.set_text(f'✓ Analysis complete — {displayed} time step(s) shown.')
    analyze_btn.props(remove='loading')

analyze_btn.on_click(run_analysis)
location_input.on('keydown.enter', run_analysis)

ui.run(title='Severe Wx Diagnostics', dark=True)
