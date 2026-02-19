"""
met_core.py — Sounding-based meteorological calculations.

All functions operate on numpy arrays representing vertical profiles.
Pressure in hPa, temperature/dewpoint in Celsius, winds in knots (u/v components).
Heights in meters AGL unless noted.

References:
  - Thompson et al. 2003 (SCP)
  - Thompson et al. 2004 (STP)
  - Bunkers et al. 2000 (storm motion)
  - Davies & Johns 1993 (EHI)
  - Craven & Brooks 2004 (Craven-Brooks)
  - SHIP: SPC operational definition
"""

import math
import numpy as np
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

Rd   = 287.04   # J kg-1 K-1  dry air gas constant
Rv   = 461.5    # J kg-1 K-1  water vapor gas constant
Cp   = 1005.7   # J kg-1 K-1  specific heat dry air
Lv   = 2.501e6  # J kg-1      latent heat of vaporization
g    = 9.81     # m s-2       gravitational acceleration
eps  = Rd / Rv  # 0.622
T0   = 273.15   # K


# ─────────────────────────────────────────────────────────────────────────────
# THERMODYNAMIC HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def c_to_k(t_c: float) -> float:
    return t_c + T0

def k_to_c(t_k: float) -> float:
    return t_k - T0

def sat_vapor_pressure(t_c: float) -> float:
    """Bolton (1980) saturation vapor pressure in hPa."""
    return 6.112 * math.exp(17.67 * t_c / (t_c + 243.5))

def mixing_ratio_from_dewpoint(td_c: float, p_hpa: float) -> float:
    """Mixing ratio in kg/kg from dewpoint (C) and pressure (hPa)."""
    e = sat_vapor_pressure(td_c)
    return eps * e / (p_hpa - e)

def virtual_temperature(t_c: float, td_c: float, p_hpa: float) -> float:
    """Virtual temperature in K."""
    w = mixing_ratio_from_dewpoint(td_c, p_hpa)
    return c_to_k(t_c) * (1 + w / eps) / (1 + w)

def theta(t_c: float, p_hpa: float) -> float:
    """Potential temperature in K."""
    return c_to_k(t_c) * (1000.0 / p_hpa) ** (Rd / Cp)

def theta_e(t_c: float, td_c: float, p_hpa: float) -> float:
    """
    Equivalent potential temperature (Bolton 1980) in K.
    Used for moisture-rich layer detection and boundary analysis.
    """
    tk = c_to_k(t_c)
    tdk = c_to_k(td_c)
    w  = mixing_ratio_from_dewpoint(td_c, p_hpa)
    e  = sat_vapor_pressure(td_c)
    # Lifting Condensation Level temperature (Bolton eq. 15)
    t_lcl = 56 + 1.0 / (1.0 / (tdk - 56) + math.log(tk / tdk) / 800.0)
    # θe (Bolton eq. 43)
    return tk * (1000.0 / p_hpa) ** (0.2854 * (1 - 0.28e-3 * w * 1000)) * \
           math.exp((3.376 / t_lcl - 0.00254) * w * 1000 * (1 + 0.81e-3 * w * 1000))


# ─────────────────────────────────────────────────────────────────────────────
# LCL CALCULATION
# ─────────────────────────────────────────────────────────────────────────────

def lcl_height(t_sfc_c: float, td_sfc_c: float) -> float:
    """
    LCL height in meters AGL.
    Bolton (1980): z_LCL ≈ 125 * (T - Td)
    More precise version using theta/mixing ratio conserved ascent.
    """
    return max(0.0, 125.0 * (t_sfc_c - td_sfc_c))

def lcl_temperature(t_sfc_c: float, td_sfc_c: float) -> float:
    """LCL temperature in Celsius (Bolton 1980 eq. 15)."""
    tk = c_to_k(t_sfc_c)
    tdk = c_to_k(td_sfc_c)
    t_lcl_k = 56.0 + 1.0 / (1.0 / (tdk - 56.0) + math.log(tk / tdk) / 800.0)
    return k_to_c(t_lcl_k)


# ─────────────────────────────────────────────────────────────────────────────
# PARCEL THEORY / CAPE-CIN
# ─────────────────────────────────────────────────────────────────────────────

def _moist_lapse_rate(t_k: float, p_hpa: float) -> float:
    """Saturated adiabatic lapse rate (K/m)."""
    ws = mixing_ratio_from_dewpoint(k_to_c(t_k), p_hpa)
    numer = g * (1 + (Lv * ws) / (Rd * t_k))
    denom = Cp + (Lv**2 * ws * eps) / (Rd * t_k**2)
    return numer / denom

def lift_parcel_moist(t0_k: float, p0_hpa: float, p_levels_hpa: np.ndarray) -> np.ndarray:
    """
    Lift a saturated parcel from (t0_k, p0_hpa) to each pressure level.
    Uses simple Euler integration with 10 hPa steps.
    Returns parcel temperature array in K at p_levels_hpa.
    """
    # Interpolate to finer grid for accuracy
    p_fine = np.arange(p0_hpa, p_levels_hpa[-1] - 1, -5.0)
    t_parcel = np.zeros(len(p_fine))
    t_parcel[0] = t0_k

    for i in range(1, len(p_fine)):
        dp = p_fine[i] - p_fine[i - 1]   # negative
        # Convert dp to dz via hydrostatic
        dz = -Rd * t_parcel[i-1] / (g * p_fine[i-1] * 100) * (dp * 100)
        lapse = _moist_lapse_rate(t_parcel[i-1], p_fine[i-1])
        t_parcel[i] = t_parcel[i-1] - lapse * dz

    # Interpolate back to target levels
    result = np.interp(p_levels_hpa, p_fine[::-1], t_parcel[::-1])
    return result

def compute_cape_cin(
    p_hpa: np.ndarray,
    t_c: np.ndarray,
    td_c: np.ndarray,
    p_sfc: Optional[float] = None,
    layer_depth_hpa: float = 100.0
) -> dict:
    """
    Compute MLCAPE, MUCAPE, MLCIN, MUCIN, and parcel temperatures.

    - MLCAPE: Mixed-layer parcel (mean T/Td over lowest 100 hPa)
    - MUCAPE: Most-unstable parcel (max θe in lowest 300 hPa)

    Returns dict with keys: mlcape, mucape, mlcin, mucin, mu_p, ml_lcl_hgt, mu_lcl_hgt
    """
    if p_sfc is None:
        p_sfc = p_hpa[0]

    # ── Mixed-layer parcel ──────────────────────────────────────────────────
    ml_mask = p_hpa >= (p_sfc - layer_depth_hpa)
    t_ml  = float(np.mean(t_c[ml_mask]))
    td_ml = float(np.mean(td_c[ml_mask]))
    p_ml  = float(np.mean(p_hpa[ml_mask]))

    ml_lcl_hgt = lcl_height(t_ml, td_ml)
    ml_lcl_t   = lcl_temperature(t_ml, td_ml)
    ml_lcl_p   = p_ml * (c_to_k(ml_lcl_t) / c_to_k(t_ml)) ** (Cp / Rd)

    # ── Most-unstable parcel ────────────────────────────────────────────────
    mu_mask = p_hpa >= (p_sfc - 300.0)
    theta_e_vals = np.array([
        theta_e(float(t_c[i]), float(td_c[i]), float(p_hpa[i]))
        for i in range(len(p_hpa)) if mu_mask[i]
    ])
    mu_idx_local = int(np.argmax(theta_e_vals))
    mu_idx = np.where(mu_mask)[0][mu_idx_local]
    t_mu   = float(t_c[mu_idx])
    td_mu  = float(td_c[mu_idx])
    p_mu   = float(p_hpa[mu_idx])

    mu_lcl_hgt = lcl_height(t_mu, td_mu)
    mu_lcl_t   = lcl_temperature(t_mu, td_mu)
    mu_lcl_p   = p_mu * (c_to_k(mu_lcl_t) / c_to_k(t_mu)) ** (Cp / Rd)

    def _cape_cin(parcel_t_c, parcel_td_c, parcel_p, parcel_lcl_p, parcel_lcl_t_c):
        """Integrate CAPE and CIN for a given parcel."""
        # Levels above parcel origin, sorted top to bottom → bottom to top
        mask = p_hpa <= parcel_p
        p_above = p_hpa[mask][::-1]   # ascending pressure (bottom→top)
        t_above = t_c[mask][::-1]

        if len(p_above) < 2:
            return 0.0, 0.0

        # Lift dry-adiabatically to LCL, then moist above
        t_parcel_k = np.zeros(len(p_above))
        t_dry = c_to_k(parcel_t_c) * (p_above / parcel_p) ** (Rd / Cp)

        # LCL index
        lcl_mask = p_above <= parcel_lcl_p
        t_parcel_k[~lcl_mask] = t_dry[~lcl_mask]

        if lcl_mask.any():
            lcl_i = int(np.argmax(lcl_mask))
            t_lcl_k = c_to_k(parcel_lcl_t_c)
            moist_temps = lift_parcel_moist(t_lcl_k, parcel_lcl_p, p_above[lcl_mask])
            t_parcel_k[lcl_mask] = moist_temps

        cape = 0.0
        cin  = 0.0
        env_k = c_to_k(t_above)

        for i in range(len(p_above) - 1):
            # Layer mean buoyancy
            b_mean = g * ((t_parcel_k[i] + t_parcel_k[i+1]) / 2 -
                          (env_k[i] + env_k[i+1]) / 2) / ((env_k[i] + env_k[i+1]) / 2)
            # dz via hypsometric
            dz = (Rd * (env_k[i] + env_k[i+1]) / 2) / g * math.log(p_above[i] / p_above[i+1])
            contribution = b_mean * dz
            if contribution > 0:
                cape += contribution
            else:
                # CIN only below LFC
                if cape == 0.0:
                    cin += contribution

        return cape, cin

    mlcape, mlcin = _cape_cin(t_ml, td_ml, p_ml, ml_lcl_p, ml_lcl_t)
    mucape, mucin = _cape_cin(t_mu, td_mu, p_mu, mu_lcl_p, mu_lcl_t)

    return {
        "mlcape": max(0.0, mlcape),
        "mucape": max(0.0, mucape),
        "mlcin":  mlcin,
        "mucin":  mucin,
        "mu_p":   p_mu,
        "ml_lcl_hgt": ml_lcl_hgt,
        "mu_lcl_hgt": mu_lcl_hgt,
        "ml_lcl_t_c": ml_lcl_t,
        "mu_lcl_t_c": mu_lcl_t,
    }


# ─────────────────────────────────────────────────────────────────────────────
# WIND PROFILE UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def dir_spd_to_uv(direction_deg: float, speed_kt: float):
    """Meteorological wind → U/V components (kt)."""
    rad = math.radians(direction_deg)
    return -speed_kt * math.sin(rad), -speed_kt * math.cos(rad)

def uv_to_dir_spd(u: float, v: float):
    """U/V → meteorological direction (deg) and speed (kt)."""
    spd = math.sqrt(u**2 + v**2)
    dirn = math.degrees(math.atan2(-u, -v)) % 360
    return dirn, spd

def interpolate_wind_to_height(
    heights_m: np.ndarray,
    u_kt: np.ndarray,
    v_kt: np.ndarray,
    target_m: float
) -> tuple:
    """Linear interpolation of wind to target height AGL."""
    u = float(np.interp(target_m, heights_m, u_kt))
    v = float(np.interp(target_m, heights_m, v_kt))
    return u, v

def pressure_to_height_msl(p_hpa: np.ndarray, t_c: np.ndarray, p_sfc: float, z_sfc: float) -> np.ndarray:
    """
    Convert pressure levels to heights MSL using hypsometric equation.
    p_hpa must be sorted descending (sfc → top).
    """
    heights = np.zeros(len(p_hpa))
    heights[0] = z_sfc
    for i in range(1, len(p_hpa)):
        t_mean_k = (c_to_k(float(t_c[i-1])) + c_to_k(float(t_c[i]))) / 2.0
        dz = (Rd * t_mean_k / g) * math.log(float(p_hpa[i-1]) / float(p_hpa[i]))
        heights[i] = heights[i-1] + dz
    return heights


# ─────────────────────────────────────────────────────────────────────────────
# BUNKERS STORM MOTION (2000) — proper Internal Dynamics method
# ─────────────────────────────────────────────────────────────────────────────

def bunkers_storm_motion(
    heights_m_agl: np.ndarray,
    u_kt: np.ndarray,
    v_kt: np.ndarray,
    top_m: float = 6000.0,
    D_kt: float = 14.6
) -> dict:
    """
    Bunkers et al. (2000) Internal Dynamics method.

    D_kt = 7.5 m/s = 14.6 kt (empirical deviation magnitude)
    Right-mover = mean wind + D perpendicular-right to 0-top shear
    Left-mover  = mean wind - D perpendicular-right to 0-top shear

    Returns dict: rm_u, rm_v, lm_u, lm_v, mean_u, mean_v
    """
    # Mean wind 0–6 km (pressure-weighted approximation via equal-height integration)
    mask = heights_m_agl <= top_m
    if mask.sum() < 2:
        return {"rm_u": 0, "rm_v": 0, "lm_u": 0, "lm_v": 0, "mean_u": 0, "mean_v": 0}

    h_layer = heights_m_agl[mask]
    u_layer = u_kt[mask]
    v_layer = v_kt[mask]

    mean_u = float(np.trapz(u_layer, h_layer) / (h_layer[-1] - h_layer[0]))
    mean_v = float(np.trapz(v_layer, h_layer) / (h_layer[-1] - h_layer[0]))

    # Shear vector: surface to top
    sh_u = float(u_layer[-1] - u_layer[0])
    sh_v = float(v_layer[-1] - v_layer[0])
    shear_mag = math.sqrt(sh_u**2 + sh_v**2)

    if shear_mag < 0.5:
        return {"rm_u": mean_u + 7.5, "rm_v": mean_v - 7.5,
                "lm_u": mean_u - 7.5, "lm_v": mean_v + 7.5,
                "mean_u": mean_u, "mean_v": mean_v}

    # Perpendicular unit vector (90° clockwise = right of shear)
    perp_u =  sh_v / shear_mag
    perp_v = -sh_u / shear_mag

    return {
        "rm_u":   mean_u + D_kt * perp_u,
        "rm_v":   mean_v + D_kt * perp_v,
        "lm_u":   mean_u - D_kt * perp_u,
        "lm_v":   mean_v - D_kt * perp_v,
        "mean_u": mean_u,
        "mean_v": mean_v,
    }


# ─────────────────────────────────────────────────────────────────────────────
# STORM-RELATIVE HELICITY — multi-level integration
# ─────────────────────────────────────────────────────────────────────────────

def compute_srh(
    heights_m_agl: np.ndarray,
    u_kt: np.ndarray,
    v_kt: np.ndarray,
    storm_u: float,
    storm_v: float,
    layer_top_m: float = 3000.0,
    layer_bot_m: float = 0.0
) -> float:
    """
    Multi-level SRH integration (Davies-Jones 1984).

    SRH = -∫ (V_rel × dV_wind) · k̂  [from bottom to top]
        = Σ [(u_rel_i)(v_rel_i+1) - (u_rel_i+1)(v_rel_i)]

    Positive = cyclonic (right-moving supercell favorable).
    """
    mask = (heights_m_agl >= layer_bot_m) & (heights_m_agl <= layer_top_m)
    if mask.sum() < 2:
        return 0.0

    h  = heights_m_agl[mask]
    ru = (u_kt[mask] - storm_u)
    rv = (v_kt[mask] - storm_v)

    srh = 0.0
    for i in range(len(h) - 1):
        srh += ru[i] * rv[i+1] - ru[i+1] * rv[i]

    return float(-srh)   # convention: positive = cyclonic


# ─────────────────────────────────────────────────────────────────────────────
# BULK SHEAR
# ─────────────────────────────────────────────────────────────────────────────

def bulk_shear(
    heights_m_agl: np.ndarray,
    u_kt: np.ndarray,
    v_kt: np.ndarray,
    bottom_m: float,
    top_m: float
) -> float:
    """Bulk wind difference (kt) between two heights."""
    u_bot, v_bot = interpolate_wind_to_height(heights_m_agl, u_kt, v_kt, bottom_m)
    u_top, v_top = interpolate_wind_to_height(heights_m_agl, u_kt, v_kt, top_m)
    return math.sqrt((u_top - u_bot)**2 + (v_top - v_bot)**2)

def mean_wind(
    heights_m_agl: np.ndarray,
    u_kt: np.ndarray,
    v_kt: np.ndarray,
    bottom_m: float,
    top_m: float
) -> tuple:
    """Layer-mean wind (u, v) in kt via trapezoidal integration."""
    mask = (heights_m_agl >= bottom_m) & (heights_m_agl <= top_m)
    if mask.sum() < 2:
        u_b, v_b = interpolate_wind_to_height(heights_m_agl, u_kt, v_kt, bottom_m)
        u_t, v_t = interpolate_wind_to_height(heights_m_agl, u_kt, v_kt, top_m)
        return (u_b + u_t) / 2, (v_b + v_t) / 2
    h = heights_m_agl[mask]
    depth = h[-1] - h[0]
    if depth < 1:
        return float(u_kt[mask][0]), float(v_kt[mask][0])
    mu = float(np.trapz(u_kt[mask], h) / depth)
    mv = float(np.trapz(v_kt[mask], h) / depth)
    return mu, mv


# ─────────────────────────────────────────────────────────────────────────────
# COMPOSITE PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────

def supercell_composite(mucape: float, eff_srh: float, shear_06_kt: float) -> float:
    """
    SCP (Thompson et al. 2003).
    SCP = (MUCAPE/1000) * (Eff.SRH/50) * (Eff.BWD/20)
    Note: should use effective-layer SRH and shear; 0-3km SRH and 0-6km shear used as proxies.
    """
    if mucape < 100 or eff_srh <= 0 or shear_06_kt < 10:
        return 0.0
    return round((mucape / 1000.0) * (eff_srh / 50.0) * (shear_06_kt / 20.0), 2)

def significant_tornado_parameter(
    mlcape: float,
    ml_lcl_hgt: float,
    srh_01: float,
    shear_06_kt: float,
    mlcin: float
) -> float:
    """
    STP fixed-layer (Thompson et al. 2004).
    STP = (MLCAPE/1500) * (LCL_factor) * (0-1km SRH/150) * (BWD/20) * (CIN_factor)
    LCL factor: 1.0 if LCL < 1000m, linear decrease to 0 at 2000m
    CIN factor: 1.0 if CIN > -50, linear decrease to 0 at -200 J/kg
    """
    if mlcape < 100 or srh_01 <= 0 or shear_06_kt < 12:
        return 0.0

    lcl_factor = max(0.0, min(1.0, (2000.0 - ml_lcl_hgt) / 1000.0))
    cin_factor  = max(0.0, min(1.0, (mlcin + 200.0) / 150.0))   # mlcin is negative
    stp = (mlcape / 1500.0) * lcl_factor * (srh_01 / 150.0) * (shear_06_kt / 20.0) * cin_factor
    return round(stp, 2)

def energy_helicity_index(cape: float, srh: float) -> float:
    """
    EHI (Davies & Johns 1993).
    EHI = (CAPE * SRH) / 160000
    EHI ≥ 1 supports supercells; ≥ 2–2.5 significant tornadoes.
    """
    if cape < 100 or srh <= 0:
        return 0.0
    return round((cape * srh) / 160000.0, 2)

def significant_hail_parameter(
    mucape: float,
    mu_lcl_t_c: float,
    mid_lapse: float,
    precipitable_water: float,
    shear_06_kt: float
) -> float:
    """
    SHIP (SPC operational definition).
    SHIP = (MUCAPE/1000) * (mu_lcl_t / -10) * (lapse_500_700 / 5.5) * (PW / 13.6) * (shear_06 / 27)
    Positive hail indicator; ≥ 1 supports significant hail (≥ 2 inches).
    mu_lcl_t_c: parcel temperature at LCL in C (should be negative = glaciation level proxy)
    mid_lapse: 500-700 hPa lapse rate in C/km
    precipitable_water: mm
    """
    if mucape < 100:
        return 0.0
    # Clamp terms per SPC convention
    lcl_t_term = max(0.0, -mu_lcl_t_c / 10.0)   # positive when LCL is cold
    lapse_term  = max(0.0, mid_lapse / 5.5)
    pw_term     = max(0.0, min(1.5, precipitable_water / 13.6))
    shear_term  = min(1.5, shear_06_kt / 27.0)
    ship = (mucape / 1000.0) * lcl_t_term * lapse_term * pw_term * shear_term
    return round(ship, 2)

def vorticity_generation_parameter(
    srh_01: float,
    shear_01_kt: float
) -> float:
    """
    VGP (Rasmussen & Blanchard 1998 / Markowski et al.).
    VGP = sqrt(SREH * BWD_01) / 1000
    Higher values → enhanced low-level vorticity generation, favorable for tornadogenesis.
    VGP ≥ 0.2 supports tornadoes.
    """
    if srh_01 <= 0 or shear_01_kt <= 0:
        return 0.0
    return round(math.sqrt(max(0, srh_01) * shear_01_kt) / 1000.0, 3)

def craven_brooks(mlcape: float, shear_06_kt: float) -> float:
    """
    Craven-Brooks (2004) Significant Severe Threshold.
    CB = MLCAPE * BWD_06 / 1e6  (J/kg * m/s product)
    Convert shear from kt to m/s: 1 kt = 0.514 m/s
    Threshold > 20,000 J/kg·m/s (or in normalized form > 0.02) supports sig. severe.
    """
    shear_ms = shear_06_kt * 0.514
    cb = mlcape * shear_ms
    return round(cb, 0)  # in J/kg·m/s, threshold ~20000


# ─────────────────────────────────────────────────────────────────────────────
# LAPSE RATES & MOISTURE
# ─────────────────────────────────────────────────────────────────────────────

def lapse_rate(
    heights_m: np.ndarray,
    t_c: np.ndarray,
    bot_m: float,
    top_m: float
) -> float:
    """
    Temperature lapse rate (C/km) between two heights.
    Positive = unstable (temperature decreasing with height).
    """
    t_bot = float(np.interp(bot_m, heights_m, t_c))
    t_top = float(np.interp(top_m, heights_m, t_c))
    depth_km = (top_m - bot_m) / 1000.0
    if depth_km < 0.1:
        return 0.0
    return round((t_bot - t_top) / depth_km, 2)

def precipitable_water(p_hpa: np.ndarray, td_c: np.ndarray) -> float:
    """
    Precipitable water in mm (integrate water vapor through column).
    """
    pw = 0.0
    for i in range(len(p_hpa) - 1):
        w1 = mixing_ratio_from_dewpoint(float(td_c[i]),   float(p_hpa[i]))
        w2 = mixing_ratio_from_dewpoint(float(td_c[i+1]), float(p_hpa[i+1]))
        dp = abs(float(p_hpa[i]) - float(p_hpa[i+1])) * 100  # Pa
        pw += (w1 + w2) / 2 * dp / g
    return round(pw * 1000, 1)   # kg/m² = mm


# ─────────────────────────────────────────────────────────────────────────────
# EFFECTIVE INFLOW LAYER
# ─────────────────────────────────────────────────────────────────────────────

def effective_inflow_layer(
    p_hpa: np.ndarray,
    t_c: np.ndarray,
    td_c: np.ndarray,
    heights_m_agl: np.ndarray,
    cape_threshold: float = 100.0,
    cin_threshold: float = -250.0
) -> tuple:
    """
    Find effective inflow layer bottom and top heights (m AGL).
    Effective layer = contiguous layer from surface where CAPE > 100 and CIN > -250.
    Returns (eff_bot_m, eff_top_m) or (None, None) if not found.
    """
    eff_bot = None
    eff_top = None

    for i in range(len(p_hpa)):
        try:
            result = compute_cape_cin(
                p_hpa[i:], t_c[i:], td_c[i:],
                p_sfc=float(p_hpa[i]), layer_depth_hpa=50.0
            )
            cape_i = result['mlcape']
            cin_i  = result['mlcin']
        except Exception:
            continue

        if cape_i >= cape_threshold and cin_i >= cin_threshold:
            if eff_bot is None:
                eff_bot = float(heights_m_agl[i])
            eff_top = float(heights_m_agl[i])
        else:
            if eff_bot is not None:
                break  # First contiguous layer complete

    return eff_bot, eff_top


# ─────────────────────────────────────────────────────────────────────────────
# MESOSCALE BOUNDARY DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def theta_e_deficit(t_sfc_c: float, td_sfc_c: float, p_sfc: float,
                    t_500_c: float, td_500_c: float = None) -> float:
    """
    θe deficit: difference between surface and 500 hPa θe.
    Larger values = more unstable column.
    """
    if td_500_c is None:
        td_500_c = t_500_c - 30.0  # rough mid-level dewpoint depression
    te_sfc = theta_e(t_sfc_c, td_sfc_c, p_sfc)
    te_500 = theta_e(t_500_c, td_500_c, 500.0)
    return round(te_sfc - te_500, 1)

def detect_boundaries(
    grid_lat: np.ndarray,
    grid_lon: np.ndarray,
    grid_t_sfc: np.ndarray,
    grid_td_sfc: np.ndarray,
    grid_p_sfc: np.ndarray,
    target_lat: float,
    target_lon: float,
    radius_deg: float = 2.0,
    gradient_threshold: float = 3.0
) -> dict:
    """
    Detect mesoscale boundaries near a point using θe gradients on a grid.

    A boundary is identified when the θe gradient exceeds threshold (K/deg-lat)
    in the surrounding grid boxes. Returns info on likely boundary type and proximity.

    grid_* arrays are 2D [lat, lon].
    gradient_threshold: K per degree lat (~111 km), ~3K/100km is a meaningful boundary.
    """
    result = {
        "boundary_detected": False,
        "boundary_type": "None",
        "max_gradient_k_per_100km": 0.0,
        "notes": []
    }

    # Mask to radius
    lat_mask = np.abs(grid_lat - target_lat) <= radius_deg
    lon_mask = np.abs(grid_lon - target_lon) <= radius_deg

    if not (lat_mask.any() and lon_mask.any()):
        return result

    try:
        # Compute θe on grid
        theta_e_grid = np.zeros_like(grid_t_sfc)
        for i in range(grid_t_sfc.shape[0]):
            for j in range(grid_t_sfc.shape[1]):
                try:
                    theta_e_grid[i, j] = theta_e(
                        float(grid_t_sfc[i, j]),
                        float(grid_td_sfc[i, j]),
                        float(grid_p_sfc[i, j])
                    )
                except Exception:
                    theta_e_grid[i, j] = np.nan

        # Gradient magnitude (simple finite difference)
        dy = np.gradient(theta_e_grid, axis=0)  # K per grid-step latitude
        dx = np.gradient(theta_e_grid, axis=1)
        grad_mag = np.sqrt(dy**2 + dx**2)  # K per grid step

        # Convert to K/100km (rough: 1 deg lat ≈ 111 km)
        lat_spacing_deg = float(np.abs(np.diff(grid_lat[:, 0]).mean())) if grid_lat.shape[0] > 1 else 1.0
        km_per_step = lat_spacing_deg * 111.0
        grad_k_per_100km = grad_mag / km_per_step * 100.0

        # Find max gradient near target
        i_target = np.argmin(np.abs(grid_lat[:, 0] - target_lat))
        j_target = np.argmin(np.abs(grid_lon[0, :] - target_lon))

        i_min = max(0, i_target - int(radius_deg / lat_spacing_deg))
        i_max = min(grid_lat.shape[0], i_target + int(radius_deg / lat_spacing_deg) + 1)
        j_min = max(0, j_target - int(radius_deg / lat_spacing_deg))
        j_max = min(grid_lon.shape[1], j_target + int(radius_deg / lat_spacing_deg) + 1)

        local_grad = grad_k_per_100km[i_min:i_max, j_min:j_max]
        max_grad = float(np.nanmax(local_grad)) if local_grad.size > 0 else 0.0
        result["max_gradient_k_per_100km"] = round(max_grad, 1)

        if max_grad >= gradient_threshold:
            result["boundary_detected"] = True

            # Characterize boundary type from θe magnitude and wind shear proxy
            te_target = float(theta_e_grid[i_target, j_target])
            te_mean   = float(np.nanmean(theta_e_grid[i_min:i_max, j_min:j_max]))

            if te_target > te_mean + 2:
                btype = "Warm Sector / Moisture Axis"
                result["notes"].append("High θe air at point — location is in warm sector ahead of boundary.")
            elif te_target < te_mean - 2:
                btype = "Cold/Dry Side of Boundary"
                result["notes"].append("Low θe at point — location may be behind a boundary; initiation risk reduced.")
            else:
                btype = "Near Mesoscale Boundary"
                result["notes"].append(f"θe gradient of {max_grad:.1f} K/100km nearby — boundary likely within ~{radius_deg * 111:.0f} km.")

            result["boundary_type"] = btype

    except Exception as e:
        result["notes"].append(f"Boundary analysis incomplete: {e}")

    return result
