"""
weather_checker.py — Severe Weather Environment Diagnostics Hub

Model chain: HRRR → NAM-3km → GFS → Open-Meteo
"""

import asyncio
import math
import logging
from datetime import datetime

from nicegui import ui, run

from data_fetcher import fetch_profiles, geocode
from analysis_engine import analyze_profile, EnvironmentAnalysis

logging.basicConfig(level=logging.INFO)

# ─────────────────────────────────────────────────────────────────────────────
# SUPPORT LEVEL COLOR MAPS
# ─────────────────────────────────────────────────────────────────────────────

TEXT_COLOR = {
    "grey":   "text-gray-400",
    "blue":   "text-blue-400",
    "green":  "text-green-400",
    "yellow": "text-yellow-300",
    "orange": "text-orange-400",
    "red":    "text-red-400",
}

BADGE_COLOR = {
    "grey":   "grey-7",
    "blue":   "blue",
    "green":  "green",
    "yellow": "yellow-8",
    "orange": "orange",
    "red":    "red",
}

# ─────────────────────────────────────────────────────────────────────────────
# PARAMETER THRESHOLD TABLE — for inline flag rendering
# ─────────────────────────────────────────────────────────────────────────────

def flag(val, thresholds: list) -> str:
    """
    thresholds: list of (value, label, color_class) tuples in ascending order.
    Returns the label for the highest exceeded threshold.
    """
    label = ""
    for thresh, lbl, _ in thresholds:
        if val >= thresh:
            label = lbl
    return label

def param_color(val, thresholds: list) -> str:
    color = "text-gray-300"
    for thresh, _, cls in thresholds:
        if val >= thresh:
            color = cls
    return color


CAPE_THRESH  = [(500, "", ""), (1000, "⚡", "text-yellow-300"), (2500, "⚡⚡", "text-orange-400"), (4000, "⚡⚡⚡", "text-red-400")]
SHR6_THRESH  = [(20, "", ""), (35, "↑", "text-yellow-300"), (50, "↑↑", "text-orange-400"), (65, "↑↑↑", "text-red-400")]
SRH_THRESH   = [(100, "", ""), (150, "↑", "text-yellow-300"), (300, "↑↑", "text-orange-400"), (500, "↑↑↑", "text-red-400")]
SCP_THRESH   = [(1, "⚠", "text-yellow-300"), (4, "⚠⚠", "text-orange-400"), (8, "⚠⚠⚠", "text-red-400")]
STP_THRESH   = [(0.5, "⚠", "text-yellow-300"), (1, "⚠⚠", "text-orange-400"), (3, "⚠⚠⚠", "text-red-400")]
EHI_THRESH   = [(1, "⚠", "text-yellow-300"), (2, "⚠⚠", "text-orange-400"), (3, "⚠⚠⚠", "text-red-400")]
SHIP_THRESH  = [(0.5, "⚠", "text-yellow-300"), (1, "⚠⚠", "text-orange-400"), (2, "⚠⚠⚠", "text-red-400")]


# ─────────────────────────────────────────────────────────────────────────────
# CARD RENDERING
# ─────────────────────────────────────────────────────────────────────────────

def render_param_row(label: str, value: str, thresholds=None, raw_val: float = None):
    """Render a single parameter row with optional color/flag."""
    color = "text-gray-200"
    flag_str = ""
    if thresholds and raw_val is not None:
        color    = param_color(raw_val, thresholds)
        flag_str = flag(raw_val, thresholds)

    with ui.row().classes("w-full justify-between items-center py-0"):
        ui.label(label).classes("text-xs text-gray-400")
        with ui.row().classes("items-center gap-1"):
            if flag_str:
                ui.label(flag_str).classes("text-xs")
            ui.label(value).classes(f"text-sm font-mono {color}")


def render_section(title: str):
    ui.label(title).classes("text-xs font-bold text-gray-400 uppercase tracking-wider mt-3 mb-1 border-b border-gray-700 pb-1")


def render_analysis_card(a: EnvironmentAnalysis):
    dt_str = a.valid_time.strftime("%-I %p %a") if hasattr(a.valid_time, 'strftime') else str(a.valid_time)
    tc = TEXT_COLOR.get(a.support_color, "text-white")
    bc = BADGE_COLOR.get(a.support_color, "grey")

    with ui.card().classes("w-full bg-gray-900 border border-gray-700"):
        with ui.expansion() as exp:
            with exp.add_slot("header"):
                with ui.row().classes("w-full items-center gap-3 py-1"):
                    ui.label(a.support_emoji).classes("text-2xl")
                    with ui.column().classes("gap-0 flex-1"):
                        ui.label(dt_str).classes("text-xs text-gray-500")
                        ui.label(a.convective_mode).classes(f"font-bold text-base {tc}")
                        ui.label(f"MLCAPE {a.mlcape:.0f}  ·  SCP {a.scp:.1f}  ·  STP {a.stp:.2f}  ·  SHR6 {a.shear_06_kt:.0f}kt").classes("text-xs text-gray-400")
                    ui.badge(a.support_label, color=bc).props("rounded")

            # ── Expanded detail ──────────────────────────────────────────
            with ui.column().classes("w-full gap-0 px-2 pb-3"):

                # Instability
                render_section("🌡  Instability")
                with ui.grid(columns=2).classes("w-full gap-x-8"):
                    render_param_row("MLCAPE",      f"{a.mlcape:.0f} J/kg",    CAPE_THRESH, a.mlcape)
                    render_param_row("MUCAPE",      f"{a.mucape:.0f} J/kg",    CAPE_THRESH, a.mucape)
                    render_param_row("MLCIN",       f"{a.mlcin:.0f} J/kg")
                    render_param_row("Lifted Index", f"{a.li:.1f} K")
                    render_param_row("ML LCL",      f"{a.ml_lcl_hgt:.0f} m")
                    render_param_row("MU LCL",      f"{a.mu_lcl_hgt:.0f} m")

                # Lapse Rates / Moisture
                render_section("🌧  Thermo / Moisture")
                with ui.grid(columns=2).classes("w-full gap-x-8"):
                    render_param_row("700–500 Lapse",  f"{a.lapse_700_500:.1f} C/km")
                    render_param_row("Sfc–700 Lapse",  f"{a.lapse_sfc_700:.1f} C/km")
                    render_param_row("Precip. Water",   f"{a.pw_mm:.0f} mm")
                    render_param_row("Sfc RH",          f"{a.rh_sfc:.0f}%")

                # Kinematics
                render_section("💨  Kinematics")
                with ui.grid(columns=2).classes("w-full gap-x-8"):
                    render_param_row("0–1km Shear",  f"{a.shear_01_kt:.0f} kt")
                    render_param_row("0–6km Shear",  f"{a.shear_06_kt:.0f} kt",  SHR6_THRESH, a.shear_06_kt)
                    render_param_row("3–6km Shear",  f"{a.shear_36_kt:.0f} kt")
                    render_param_row("0–1km SRH",    f"{a.srh_01:.0f} m²/s²",   SRH_THRESH, max(a.srh_01, 0))
                    render_param_row("0–3km SRH",    f"{a.srh_03:.0f} m²/s²",   SRH_THRESH, max(a.srh_03, 0))
                    render_param_row("Eff. SRH",     f"{a.srh_eff:.0f} m²/s²")
                    render_param_row("Storm Motion", f"{a.storm_dir_deg:.0f}° @ {a.storm_speed_kt:.0f} kt")
                    render_param_row("",             "")

                # Composite Parameters
                render_section("📊  Composite Parameters")
                with ui.grid(columns=2).classes("w-full gap-x-8"):
                    render_param_row("SCP",         f"{a.scp:.2f}",            SCP_THRESH, a.scp)
                    render_param_row("STP (fixed)",  f"{a.stp:.2f}",            STP_THRESH, a.stp)
                    render_param_row("EHI (0-1km)", f"{a.ehi_01:.2f}",         EHI_THRESH, a.ehi_01)
                    render_param_row("EHI (0-3km)", f"{a.ehi_03:.2f}",         EHI_THRESH, a.ehi_03)
                    render_param_row("SHIP",        f"{a.ship:.2f}",           SHIP_THRESH, a.ship)
                    render_param_row("VGP",         f"{a.vgp:.3f}")
                    render_param_row("Craven-Brooks", f"{a.craven:,.0f} J/kg·m/s")
                    render_param_row("", "")

                # Boundary
                if a.boundary.get("boundary_detected") or a.boundary.get("max_gradient_k_per_100km", 0) > 0:
                    render_section("🗺  Mesoscale Boundaries")
                    btype = a.boundary.get("boundary_type", "None")
                    grad  = a.boundary.get("max_gradient_k_per_100km", 0.0)
                    detected = a.boundary.get("boundary_detected", False)
                    bcolor = "text-orange-400" if detected else "text-gray-300"
                    ui.label(f"{'⚠ ' if detected else ''}{btype}  ·  θe gradient {grad:.1f} K/100km").classes(f"text-sm {bcolor}")
                    for bn in a.boundary.get("notes", []):
                        ui.label(f"ℹ {bn}").classes("text-xs text-blue-300 mt-1")

                # Warnings
                if a.warnings:
                    render_section("🚨  Operational Flags")
                    for w in a.warnings:
                        ui.label(f"• {w}").classes("text-sm text-red-400")

                # Fail modes
                if a.fail_modes:
                    render_section("⚠  Possible Fail Modes")
                    for fm in a.fail_modes:
                        ui.label(f"• {fm}").classes("text-sm text-orange-300")

                # Notes
                if a.notes:
                    render_section("ℹ  Analyst Notes")
                    for n in a.notes:
                        ui.label(f"• {n}").classes("text-sm text-blue-300")

                # Source
                ui.label(f"Source: {a.source}").classes("text-xs text-gray-600 mt-3")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN UI
# ─────────────────────────────────────────────────────────────────────────────

ui.dark_mode().enable()
ui.add_head_html('<style>body { background: #0f172a; }</style>')

# ── Header ───────────────────────────────────────────────────────────────────
with ui.row().classes("w-full justify-center items-center pt-8 pb-1 gap-3"):
    ui.icon("thunderstorm", size="2.5rem").classes("text-yellow-400")
    ui.label("Severe Weather Environment Diagnostics").classes("text-3xl font-bold text-white")

ui.label(
    "Ingredient-based convective analysis · HRRR / NAM / GFS / Open-Meteo · Not an official forecast"
).classes("w-full text-center text-xs text-gray-500 pb-6")

# ── Controls ─────────────────────────────────────────────────────────────────
with ui.card().classes("w-full max-w-3xl mx-auto mb-2 bg-gray-900 border border-gray-700"):
    with ui.row().classes("w-full items-end gap-3"):
        location_input = ui.input(
            label="Location",
            placeholder='City name  or  lat, lon  (e.g. "Norman, OK" or "35.22, -97.44")'
        ).classes("flex-1 text-white")
        analyze_btn = ui.button("Analyze", icon="search").props("elevated color=yellow")

    with ui.row().classes("w-full items-center gap-6 pt-2 flex-wrap"):
        hours_select = ui.select(
            label="Forecast window",
            options={"24": "24 hours", "48": "48 hours"},
            value="48"
        ).classes("w-36")

        min_score_select = ui.select(
            label="Min. support level",
            options={"0": "Show all", "1": "Marginal+", "2": "Limited+", "3": "Moderate+"},
            value="1"
        ).classes("w-40")

        show_notes_toggle = ui.switch("Show analyst notes", value=True)

status_bar = ui.label("").classes("w-full max-w-3xl mx-auto text-xs text-gray-400 px-1 mb-1")

# ── Legend ────────────────────────────────────────────────────────────────────
with ui.card().classes("w-full max-w-3xl mx-auto mb-4 bg-gray-900 border border-gray-700 p-3"):
    ui.label("Support Scale").classes("text-xs font-semibold text-gray-500 mb-2")
    with ui.row().classes("gap-4 flex-wrap items-center"):
        for _, lbl, _, emoji in [
            (0,"None","grey","⬛"), (1,"Marginal","blue","🟦"),
            (2,"Limited","green","🟩"), (3,"Moderate","yellow","🟨"),
            (4,"Enhanced","orange","🟧"), (5,"Extreme","red","🟥"),
        ]:
            ui.label(f"{emoji} {lbl}").classes("text-xs text-gray-300")
    ui.label("").classes("mb-1")
    ui.label("Composite thresholds: SCP ≥ 1 supercell · SCP ≥ 4 significant · STP ≥ 1 tornado · SHIP ≥ 1 sig. hail · EHI(01) ≥ 1 tornado · Craven > 20,000 sig. severe").classes(
        "text-xs text-gray-600"
    )

results_col = ui.column().classes("w-full max-w-3xl mx-auto p-1 gap-3 pb-16")


# ─────────────────────────────────────────────────────────────────────────────
# ANALYSIS LOGIC
# ─────────────────────────────────────────────────────────────────────────────

async def run_analysis():
    raw = location_input.value.strip()
    if not raw:
        status_bar.set_text("⚠ Enter a location.")
        return

    results_col.clear()
    analyze_btn.props("loading")
    status_bar.set_text("Starting analysis…")
    await asyncio.sleep(0.05)

    lat, lon, display_name = None, None, raw

    # Parse raw lat,lon
    try:
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) == 2:
            lat_try = float(parts[0])
            lon_try = float(parts[1])
            if -90 <= lat_try <= 90 and -180 <= lon_try <= 180:
                lat, lon = lat_try, lon_try
                display_name = f"{lat:.3f}, {lon:.3f}"
    except ValueError:
        pass

    if lat is None:
        status_bar.set_text("Geocoding…")
        await asyncio.sleep(0.05)
        geo = geocode(raw)
        if geo is None:
            status_bar.set_text("❌ Could not find location. Try 'lat, lon' format.")
            analyze_btn.props(remove="loading")
            return
        lat, lon, display_name = geo

    n_hours = int(hours_select.value)
    min_score = int(min_score_select.value)

    def _progress(msg):
        status_bar.set_text(msg)

    # Fetch profiles in thread pool (network I/O)
    status_bar.set_text(f"Fetching model data for {display_name}…")
    await asyncio.sleep(0.05)

    profiles, source = await run.io_bound(
        fetch_profiles, lat, lon, n_hours, _progress
    )

    if not profiles:
        status_bar.set_text("❌ Could not fetch forecast data.")
        analyze_btn.props(remove="loading")
        return

    status_bar.set_text(f"Analyzing {len(profiles)} profiles from {source}…")
    await asyncio.sleep(0.05)

    # Analyze each profile
    analyses = []
    for prof in profiles:
        a = await run.cpu_bound(analyze_profile, prof)
        analyses.append(a)

    # Filter and render
    shown = 0
    with results_col:
        ui.label(f"Environmental Analysis: {display_name}").classes("text-xl font-bold text-white mt-2")
        ui.label(f"Model: {source}  ·  {len(analyses)} steps  ·  {n_hours}h window").classes("text-xs text-gray-500 mb-2")

        for a in analyses:
            if a.support_score < min_score:
                continue
            if not show_notes_toggle.value:
                a.notes = []
            render_analysis_card(a)
            shown += 1
            await asyncio.sleep(0.01)  # keep UI responsive

        if shown == 0:
            with ui.card().classes("w-full text-center p-8 bg-gray-900 border border-gray-700"):
                ui.label("No time steps meet the selected support threshold.").classes("text-gray-400")
                ui.label("Lower the 'Min. support level' filter to see all hours.").classes("text-xs text-gray-500 mt-1")

    status_bar.set_text(f"✓ Complete — {shown} of {len(analyses)} hours displayed  ·  Source: {source}")
    analyze_btn.props(remove="loading")


analyze_btn.on_click(run_analysis)
location_input.on("keydown.enter", run_analysis)

ui.run(title="Severe Wx Diagnostics", dark=True, port=8080)
