"""
analysis_engine.py — Composite parameter computation and environment scoring.

Consumes a SoundingProfile, computes all relevant parameters,
and returns a structured EnvironmentAnalysis result.
"""

from __future__ import annotations
import math
import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from met_core import (
    compute_cape_cin,
    bunkers_storm_motion,
    compute_srh,
    bulk_shear,
    mean_wind,
    lapse_rate,
    precipitable_water,
    supercell_composite,
    significant_tornado_parameter,
    energy_helicity_index,
    significant_hail_parameter,
    vorticity_generation_parameter,
    craven_brooks,
    theta_e_deficit,
    detect_boundaries,
)
from data_fetcher import SoundingProfile

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# RESULT DATACLASS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EnvironmentAnalysis:
    valid_time:     object   # datetime
    source:         str

    # Instability
    mlcape:         float = 0.0
    mucape:         float = 0.0
    mlcin:          float = 0.0
    mucin:          float = 0.0
    ml_lcl_hgt:     float = 0.0
    mu_lcl_hgt:     float = 0.0
    ml_lcl_t_c:     float = 0.0
    mu_lcl_t_c:     float = 0.0
    li:             float = 0.0

    # Lapse rates
    lapse_700_500:  float = 0.0   # C/km (mid-level, hail indicator)
    lapse_sfc_700:  float = 0.0   # C/km (low-level, boundary layer)

    # Moisture
    pw_mm:          float = 0.0
    rh_sfc:         float = 0.0   # approximate surface RH (%)

    # Kinematics
    shear_01_kt:    float = 0.0
    shear_06_kt:    float = 0.0
    shear_36_kt:    float = 0.0   # 3-6km, discriminates QLCS vs supercell
    srh_01:         float = 0.0
    srh_03:         float = 0.0
    srh_eff:        float = 0.0   # effective-layer SRH (if computable)
    storm_motion_rm: tuple = (0.0, 0.0)  # (u, v) kt right-mover
    storm_speed_kt:  float = 0.0
    storm_dir_deg:   float = 0.0

    # Composite parameters
    scp:            float = 0.0
    stp:            float = 0.0
    ehi_01:         float = 0.0
    ehi_03:         float = 0.0
    ship:           float = 0.0
    vgp:            float = 0.0
    craven:         float = 0.0

    # Boundary detection
    boundary:       dict  = field(default_factory=dict)

    # Scoring
    support_score:  int   = 0     # 0-5
    support_label:  str   = "None"
    support_color:  str   = "grey"
    support_emoji:  str   = "⬛"

    # Mode and reasoning
    convective_mode: str  = "No Convective Threat"
    fail_modes:      list = field(default_factory=list)
    notes:           list = field(default_factory=list)
    warnings:        list = field(default_factory=list)  # parameter flags above operational thresholds


SUPPORT_LEVELS = [
    (0, "None",     "grey",   "⬛"),
    (1, "Marginal", "blue",   "🟦"),
    (2, "Limited",  "green",  "🟩"),
    (3, "Moderate", "yellow", "🟨"),
    (4, "Enhanced", "orange", "🟧"),
    (5, "Extreme",  "red",    "🟥"),
]


# ─────────────────────────────────────────────────────────────────────────────
# CORE ANALYSIS FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def analyze_profile(profile: SoundingProfile) -> EnvironmentAnalysis:
    """Full analysis of a SoundingProfile. Returns EnvironmentAnalysis."""
    result = EnvironmentAnalysis(
        valid_time=profile.valid_time,
        source=profile.source,
    )

    p  = profile.p_hpa
    t  = profile.t_c
    td = profile.td_c
    h  = profile.heights_m_agl
    u  = profile.u_kt
    v  = profile.v_kt

    if len(p) < 4:
        result.fail_modes.append("Insufficient vertical levels in profile.")
        return result

    # ── INSTABILITY ────────────────────────────────────────────────────────
    try:
        cape_result = compute_cape_cin(p, t, td, p_sfc=profile.p_sfc_hpa)
        result.mlcape    = cape_result["mlcape"]
        result.mucape    = cape_result["mucape"]
        result.mlcin     = cape_result["mlcin"]
        result.mucin     = cape_result["mucin"]
        result.ml_lcl_hgt = cape_result["ml_lcl_hgt"]
        result.mu_lcl_hgt = cape_result["mu_lcl_hgt"]
        result.ml_lcl_t_c = cape_result["ml_lcl_t_c"]
        result.mu_lcl_t_c = cape_result["mu_lcl_t_c"]
    except Exception as e:
        logger.warning(f"CAPE calculation failed: {e}")
        result.notes.append(f"CAPE calculation incomplete ({e}).")

    # Lifted Index proxy: T_500_env - T_500_parcel (negative = unstable)
    try:
        t_500 = float(np.interp(500.0, p[::-1], t[::-1]))
        # Parcel lifted from surface dry-adiabatically to LCL, then moist to 500
        from met_core import c_to_k, k_to_c, Rd, Cp
        t_parcel_lcl = result.ml_lcl_t_c
        p_lcl = profile.p_sfc_hpa * (c_to_k(t_parcel_lcl) / c_to_k(profile.t_sfc_c)) ** (Cp / Rd)
        if p_lcl > 500:
            from met_core import lift_parcel_moist
            t500_parcel_k = float(lift_parcel_moist(c_to_k(t_parcel_lcl), p_lcl, np.array([500.0]))[0])
            result.li = round(t_500 - k_to_c(t500_parcel_k), 1)
    except Exception:
        result.li = round(-result.mlcape / 500.0, 1)   # rough proxy

    # ── LAPSE RATES ───────────────────────────────────────────────────────
    try:
        result.lapse_700_500 = lapse_rate(h, t, 3000, 5500)   # ~700-500 hPa
        result.lapse_sfc_700 = lapse_rate(h, t, 0, 3000)
    except Exception as e:
        logger.debug(f"Lapse rate error: {e}")

    # ── MOISTURE ──────────────────────────────────────────────────────────
    try:
        result.pw_mm = precipitable_water(p, td)
    except Exception:
        pass

    # Surface RH approximation
    try:
        from met_core import sat_vapor_pressure
        e_sfc  = sat_vapor_pressure(profile.td_sfc_c)
        es_sfc = sat_vapor_pressure(profile.t_sfc_c)
        result.rh_sfc = round(min(100.0, e_sfc / es_sfc * 100.0), 1)
    except Exception:
        result.rh_sfc = 60.0

    # ── KINEMATICS ────────────────────────────────────────────────────────
    try:
        # Bulk shear layers
        result.shear_01_kt = bulk_shear(h, u, v, 0, 1000)
        result.shear_06_kt = bulk_shear(h, u, v, 0, 6000)
        result.shear_36_kt = bulk_shear(h, u, v, 3000, 6000)

        # Bunkers storm motion
        bunk = bunkers_storm_motion(h, u, v)
        result.storm_motion_rm = (bunk["rm_u"], bunk["rm_v"])
        from met_core import uv_to_dir_spd
        result.storm_dir_deg, result.storm_speed_kt = uv_to_dir_spd(bunk["rm_u"], bunk["rm_v"])

        # SRH layers
        result.srh_01 = compute_srh(h, u, v, bunk["rm_u"], bunk["rm_v"], layer_top_m=1000)
        result.srh_03 = compute_srh(h, u, v, bunk["rm_u"], bunk["rm_v"], layer_top_m=3000)

        # Effective-layer SRH (simplified: use ML parcel inflow ~0-LCL as bottom)
        # A proper implementation requires effective_inflow_layer(), which is slow;
        # Use 0-3km SRH but gate on MLCAPE > 100 and MLCIN > -250
        if result.mlcape >= 100 and result.mlcin >= -250:
            result.srh_eff = result.srh_03
        else:
            result.srh_eff = 0.0

    except Exception as e:
        logger.warning(f"Kinematics error: {e}")
        result.notes.append(f"Kinematic calculations incomplete ({e}).")

    # ── COMPOSITE PARAMETERS ──────────────────────────────────────────────
    try:
        result.scp = supercell_composite(result.mucape, result.srh_eff, result.shear_06_kt)
        result.stp = significant_tornado_parameter(
            result.mlcape, result.ml_lcl_hgt, result.srh_01, result.shear_06_kt, result.mlcin
        )
        result.ehi_01 = energy_helicity_index(result.mlcape, result.srh_01)
        result.ehi_03 = energy_helicity_index(result.mlcape, result.srh_03)
        result.ship = significant_hail_parameter(
            result.mucape, result.mu_lcl_t_c, result.lapse_700_500,
            result.pw_mm, result.shear_06_kt
        )
        result.vgp = vorticity_generation_parameter(result.srh_01, result.shear_01_kt)
        result.craven = craven_brooks(result.mlcape, result.shear_06_kt)
    except Exception as e:
        logger.warning(f"Composite parameter error: {e}")

    # ── BOUNDARY DETECTION ─────────────────────────────────────────────────
    if profile.grid_lats is not None:
        try:
            result.boundary = detect_boundaries(
                profile.grid_lats, profile.grid_lons,
                profile.grid_t_sfc, profile.grid_td_sfc, profile.grid_p_sfc,
                profile.lat, profile.lon,
            )
        except Exception as e:
            logger.debug(f"Boundary detection failed: {e}")
    else:
        result.boundary = {"boundary_detected": False, "boundary_type": "None",
                           "max_gradient_k_per_100km": 0.0,
                           "notes": ["Grid data unavailable (point-source model); boundary detection skipped."]}

    # ── SCORING & REASONING ───────────────────────────────────────────────
    _score_and_reason(result)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# SCORING & CONVECTIVE MODE REASONING
# ─────────────────────────────────────────────────────────────────────────────

def _score_and_reason(r: EnvironmentAnalysis):
    """Mutates r in place to set support_score, mode, fail_modes, notes, warnings."""

    fail_modes = []
    notes      = []
    warnings   = []

    # ── Instability gating ────────────────────────────────────────────────
    if r.mlcape < 100 and r.mucape < 200:
        r.convective_mode = "No Convective Threat"
        r.fail_modes = ["Insufficient instability (MLCAPE < 100 J/kg)."]
        r.support_score, r.support_label, r.support_color, r.support_emoji = SUPPORT_LEVELS[0]
        return

    # ── CIN gating ────────────────────────────────────────────────────────
    if r.mlcin < -200:
        fail_modes.append(f"Extreme cap (CIN = {r.mlcin:.0f} J/kg) — initiation very unlikely without synoptic-scale forcing or mesoscale boundaries.")
    elif r.mlcin < -75:
        fail_modes.append(f"Moderate cap (CIN = {r.mlcin:.0f} J/kg) — inhibits initiation; requires surface heating or boundary lifting.")
    elif r.mlcin < -25:
        notes.append(f"Weak cap (CIN = {r.mlcin:.0f} J/kg) — modest inhibition, may help focus/organize storms.")

    # ── LCL height (tornado proxy) ────────────────────────────────────────
    if r.ml_lcl_hgt > 2000:
        fail_modes.append(f"High LCL ({r.ml_lcl_hgt:.0f} m) — unfavorable for tornadoes; sub-cloud evaporation will weaken surface circulation.")
    elif r.ml_lcl_hgt > 1500:
        notes.append(f"Elevated LCL ({r.ml_lcl_hgt:.0f} m) — marginal for tornadoes; better conditions below ~1000 m.")
    elif r.ml_lcl_hgt < 800:
        notes.append(f"Very low LCL ({r.ml_lcl_hgt:.0f} m) — highly favorable for tornado potential if kinematics support.")

    # ── Lapse rates ───────────────────────────────────────────────────────
    if r.lapse_700_500 >= 7.0:
        warnings.append(f"Very steep 700-500 hPa lapse rate ({r.lapse_700_500:.1f} C/km) — significant hail potential with any organized updraft.")
    elif r.lapse_700_500 >= 6.5:
        notes.append(f"Steep mid-level lapse rate ({r.lapse_700_500:.1f} C/km) — favorable for hail growth.")

    if r.lapse_sfc_700 < 5.0 and r.mlcape > 500:
        fail_modes.append(f"Weak low-level lapse rate ({r.lapse_sfc_700:.1f} C/km) — reduced buoyancy in sub-cloud layer.")

    # ── Moisture ──────────────────────────────────────────────────────────
    if r.rh_sfc < 40:
        fail_modes.append(f"Very dry boundary layer (RH ≈ {r.rh_sfc:.0f}%) — intense entrainment will erode updrafts.")
    elif r.rh_sfc < 55:
        notes.append(f"Marginal boundary-layer moisture (RH ≈ {r.rh_sfc:.0f}%) — some updraft dilution expected.")

    if r.pw_mm > 40:
        notes.append(f"Very high precipitable water ({r.pw_mm:.0f} mm) — heavy rainfall / flash flood threat with any convection.")

    # ── Shear ─────────────────────────────────────────────────────────────
    if r.shear_06_kt < 15 and r.mlcape > 1500:
        fail_modes.append(f"Weak deep-layer shear ({r.shear_06_kt:.0f} kt) — storms will be outflow dominant and short-lived despite high CAPE.")

    # ── Convective mode determination ─────────────────────────────────────
    if r.shear_06_kt >= 40 and r.mlcape >= 500:
        if r.stp >= 2.0:
            mode = "Significant Tornadic Supercells"
            warnings.append(f"STP = {r.stp:.2f} ≥ 2 — significant (EF2+) tornado environment.")
        elif r.stp >= 1.0:
            mode = "Tornadic Supercells"
            warnings.append(f"STP = {r.stp:.2f} ≥ 1 — tornado potential present.")
        elif r.stp >= 0.5:
            mode = "Supercells / Tornado Possible"
            notes.append(f"STP = {r.stp:.2f} — marginal tornado potential; watch for surface boundaries enhancing rotation.")
        elif r.scp >= 4.0:
            mode = "Significant Supercell Environment"
            warnings.append(f"SCP = {r.scp:.2f} ≥ 4 — significant supercell threat.")
        else:
            mode = "Supercellular"

        if r.ship >= 1.0:
            warnings.append(f"SHIP = {r.ship:.2f} ≥ 1 — significant hail (≥ 2 in.) possible.")

    elif r.shear_06_kt >= 30 and r.mlcape >= 500:
        if r.shear_36_kt >= 20 and r.srh_03 >= 100:
            mode = "QLCS / Embedded Supercells"
            notes.append("3-6km shear and mid-level SRH support embedded rotating updrafts within linear segments.")
        else:
            mode = "Organized Multicells / QLCS"

    elif r.shear_06_kt >= 20 and r.mlcape >= 300:
        mode = "Multicell Clusters"
        if r.mlcape < 1000:
            notes.append("Limited CAPE may restrict updraft depth and hail size.")
        if r.craven > 20000:
            warnings.append(f"Craven-Brooks = {r.craven:.0f} J/kg·m/s > 20,000 — significant severe weather threshold.")

    else:
        mode = "Pulse / Single Cell"
        fail_modes.append(f"Weak deep-layer shear ({r.shear_06_kt:.0f} kt) — storms isolated and disorganized.")

    # Outflow dominance
    if r.mlcape > 2500 and r.shear_06_kt < 25:
        fail_modes.append("Very high CAPE + weak shear → dominant outflow; storms will collapse before sustained hazards develop.")

    # ── EHI flags ─────────────────────────────────────────────────────────
    if r.ehi_01 >= 2.5:
        warnings.append(f"EHI(0-1km) = {r.ehi_01:.2f} ≥ 2.5 — significant tornado environment (Davies & Johns 1993).")
    elif r.ehi_01 >= 1.0:
        notes.append(f"EHI(0-1km) = {r.ehi_01:.2f} ≥ 1.0 — tornado-supporting environment.")

    if r.vgp >= 0.2:
        notes.append(f"VGP = {r.vgp:.3f} ≥ 0.2 — low-level vorticity generation favorable.")

    # ── Boundary influence ─────────────────────────────────────────────────
    if r.boundary.get("boundary_detected"):
        notes.append(
            f"Mesoscale boundary nearby ({r.boundary['boundary_type']}, "
            f"θe gradient = {r.boundary['max_gradient_k_per_100km']:.1f} K/100km) — "
            f"significantly increases tornado/supercell initiation risk."
        )
        for bn in r.boundary.get("notes", []):
            notes.append(bn)

    # ── Scoring ───────────────────────────────────────────────────────────
    score = 0
    if r.mlcape > 500:   score += 1
    if r.mlcape > 1500:  score += 1
    if r.shear_06_kt > 30: score += 1
    if r.scp > 2 or r.stp > 0.5: score += 1
    if r.srh_01 > 200 and r.stp >= 1.0: score += 1
    score = min(score, 5)

    r.support_score, r.support_label, r.support_color, r.support_emoji = SUPPORT_LEVELS[score]
    r.convective_mode = mode
    r.fail_modes = fail_modes
    r.notes      = notes
    r.warnings   = warnings
