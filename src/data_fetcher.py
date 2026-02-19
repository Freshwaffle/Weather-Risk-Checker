"""
data_fetcher.py — Multi-source NWP data acquisition.

Priority chain:
  1. HRRR  (CONUS, ~3 km, best convective detail, 0-18hr)
  2. NAM-3km (CONUS, 3 km, 0-60hr)
  3. GFS  (global, ~25 km, 0-384hr)
  4. Open-Meteo (global fallback, no install required)

Herbie fetches subsetted GRIB2 data from NOMADS/AWS/GCS archives.
Returns a unified SoundingProfile dataclass for each forecast hour.
"""

from __future__ import annotations
import math
import logging
import requests
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SoundingProfile:
    """
    Unified vertical profile at a single point and time.
    All wind speeds in knots, temps in Celsius, pressure in hPa, heights in m AGL.
    """
    valid_time:  datetime
    source:      str           # "HRRR", "NAM", "GFS", "Open-Meteo"
    lat:         float
    lon:         float

    # Vertical levels (arrays, top→bottom or bottom→top consistent = bottom→top)
    p_hpa:       np.ndarray = field(default_factory=lambda: np.array([]))
    t_c:         np.ndarray = field(default_factory=lambda: np.array([]))
    td_c:        np.ndarray = field(default_factory=lambda: np.array([]))
    heights_m_agl: np.ndarray = field(default_factory=lambda: np.array([]))
    u_kt:        np.ndarray = field(default_factory=lambda: np.array([]))
    v_kt:        np.ndarray = field(default_factory=lambda: np.array([]))

    # Surface / single-level
    t_sfc_c:     float = 0.0
    td_sfc_c:    float = 0.0
    p_sfc_hpa:   float = 1013.25
    z_sfc_m:     float = 0.0

    # Grid data for boundary detection (optional, only from gridded models)
    grid_lats:   Optional[np.ndarray] = None
    grid_lons:   Optional[np.ndarray] = None
    grid_t_sfc:  Optional[np.ndarray] = None
    grid_td_sfc: Optional[np.ndarray] = None
    grid_p_sfc:  Optional[np.ndarray] = None


# ─────────────────────────────────────────────────────────────────────────────
# GEOCODING
# ─────────────────────────────────────────────────────────────────────────────

def geocode(location_str: str) -> Optional[tuple]:
    """Returns (lat, lon, display_name) or None."""
    url = (
        f"https://geocoding-api.open-meteo.com/v1/search"
        f"?name={requests.utils.quote(location_str)}&count=1&language=en&format=json"
    )
    try:
        r = requests.get(url, timeout=8).json()
        if r.get("results"):
            res = r["results"][0]
            name = res.get("name", location_str)
            country = res.get("country", "")
            display = f"{name}, {country}" if country else name
            return res["latitude"], res["longitude"], display
    except Exception as e:
        logger.warning(f"Geocode failed: {e}")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# HERBIE-BASED MODEL FETCHER
# ─────────────────────────────────────────────────────────────────────────────

def _herbie_available() -> bool:
    try:
        import herbie  # noqa
        return True
    except ImportError:
        return False

# Pressure levels to request (matches standard sounding levels)
PRESSURE_LEVELS = [1000, 975, 950, 925, 900, 875, 850, 825, 800,
                   775, 750, 700, 650, 600, 550, 500, 450, 400, 350, 300, 250, 200]

def _fetch_herbie(lat: float, lon: float, model: str, fxx: int) -> Optional[SoundingProfile]:
    """
    Fetch a vertical profile from HRRR, NAM, or GFS using Herbie.
    fxx = forecast hour offset from most recent run.
    """
    try:
        from herbie import Herbie
        import cfgrib
        import xarray as xr

        model_map = {
            "HRRR": {"model": "hrrr", "product": "prs"},
            "NAM":  {"model": "nam",  "product": "conusnest"},
            "GFS":  {"model": "gfs",  "product": "pgrb2.0p25"},
        }
        cfg = model_map[model]

        H = Herbie(
            "latest",
            model=cfg["model"],
            product=cfg["product"],
            fxx=fxx,
            verbose=False,
        )

        # Request temperature, dewpoint, and winds on isobaric levels
        # + surface fields
        ds_t   = H.xarray(":TMP:(?:{}(?= mb))".format("|".join(str(p) for p in PRESSURE_LEVELS)))
        ds_rh  = H.xarray(":RH:(?:{}(?= mb))".format("|".join(str(p) for p in PRESSURE_LEVELS)))
        ds_u   = H.xarray(":UGRD:(?:{}(?= mb))".format("|".join(str(p) for p in PRESSURE_LEVELS)))
        ds_v   = H.xarray(":VGRD:(?:{}(?= mb))".format("|".join(str(p) for p in PRESSURE_LEVELS)))
        ds_hgt = H.xarray(":HGT:(?:{}(?= mb))".format("|".join(str(p) for p in PRESSURE_LEVELS)))
        ds_sfc = H.xarray(":(TMP|DPT|PRES):2 m above")

        def nearest(ds, lat, lon):
            return ds.sel(latitude=lat, longitude=lon, method="nearest")

        # Extract point profiles
        p_arr   = np.array(PRESSURE_LEVELS, dtype=float)
        t_arr   = np.array([float(nearest(ds_t,  lat, lon)["t"].sel(isobaricInhPa=p).values) - 273.15
                            for p in PRESSURE_LEVELS])
        rh_arr  = np.array([float(nearest(ds_rh, lat, lon)["r"].sel(isobaricInhPa=p).values)
                            for p in PRESSURE_LEVELS])
        u_arr   = np.array([float(nearest(ds_u,  lat, lon)["u"].sel(isobaricInhPa=p).values) * 1.94384
                            for p in PRESSURE_LEVELS])  # m/s → kt
        v_arr   = np.array([float(nearest(ds_v,  lat, lon)["v"].sel(isobaricInhPa=p).values) * 1.94384
                            for p in PRESSURE_LEVELS])
        z_arr   = np.array([float(nearest(ds_hgt, lat, lon)["gh"].sel(isobaricInhPa=p).values)
                            for p in PRESSURE_LEVELS])  # m MSL

        # Dewpoint from RH and T: Td = T - (100 - RH)/5 (Magnus approximation)
        td_arr  = t_arr - (100.0 - rh_arr) / 5.0

        # Surface
        sfc_pt = nearest(ds_sfc, lat, lon)
        t_sfc  = float(sfc_pt["t2m"].values)  - 273.15
        td_sfc = float(sfc_pt["d2m"].values)  - 273.15
        p_sfc  = float(sfc_pt["sp"].values)   / 100.0  # Pa → hPa

        # Heights AGL
        z_sfc  = float(z_arr[0]) - (float(z_arr[0]) - 0)  # approximate: first level ≈ surface
        h_agl  = z_arr - z_arr[0]  # AGL relative to lowest model level
        h_agl  = np.maximum(h_agl, 0.0)

        # Sort bottom → top
        sort_idx = np.argsort(p_arr)[::-1]  # descending p = ascending altitude
        p_sorted  = p_arr[sort_idx]
        t_sorted  = t_arr[sort_idx]
        td_sorted = td_arr[sort_idx]
        u_sorted  = u_arr[sort_idx]
        v_sorted  = v_arr[sort_idx]
        h_sorted  = h_agl[sort_idx]

        # Grid data for boundary detection (coarse subset around point)
        grid_data = {}
        try:
            lat_slice = slice(lat - 3, lat + 3)
            lon_slice = slice(lon - 3, lon + 3)
            g_t  = ds_sfc["t2m"].sel(latitude=lat_slice, longitude=lon_slice).values - 273.15
            g_td = ds_sfc["d2m"].sel(latitude=lat_slice, longitude=lon_slice).values - 273.15
            g_p  = ds_sfc["sp"].sel(latitude=lat_slice, longitude=lon_slice).values / 100.0
            g_la = ds_sfc.latitude.sel(latitude=lat_slice).values
            g_lo = ds_sfc.longitude.sel(longitude=lon_slice).values
            g_lons, g_lats = np.meshgrid(g_lo, g_la)
            grid_data = dict(grid_lats=g_lats, grid_lons=g_lons,
                             grid_t_sfc=g_t, grid_td_sfc=g_td, grid_p_sfc=g_p)
        except Exception:
            pass

        return SoundingProfile(
            valid_time=H.valid_time,
            source=model,
            lat=lat, lon=lon,
            p_hpa=p_sorted, t_c=t_sorted, td_c=td_sorted,
            heights_m_agl=h_sorted, u_kt=u_sorted, v_kt=v_sorted,
            t_sfc_c=t_sfc, td_sfc_c=td_sfc, p_sfc_hpa=p_sfc,
            **grid_data,
        )

    except Exception as e:
        logger.warning(f"{model} fetch failed (fxx={fxx}): {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# OPEN-METEO FALLBACK
# ─────────────────────────────────────────────────────────────────────────────

# Open-Meteo pressure levels available
OM_LEVELS = [1000, 975, 950, 925, 900, 875, 850, 800, 750, 700,
             650, 600, 550, 500, 450, 400, 350, 300, 250, 200]

def _fetch_open_meteo(lat: float, lon: float, forecast_hours: int = 48) -> Optional[list[SoundingProfile]]:
    """
    Fetch multi-hour profiles from Open-Meteo.
    Returns list of SoundingProfile (one per hour).
    """
    level_str = ",".join(str(l) for l in OM_LEVELS)
    t_vars  = ",".join(f"temperature_{l}hPa"   for l in OM_LEVELS)
    rh_vars = ",".join(f"relative_humidity_{l}hPa" for l in OM_LEVELS)
    u_vars  = ",".join(f"windspeed_{l}hPa"     for l in OM_LEVELS)
    d_vars  = ",".join(f"winddirection_{l}hPa" for l in OM_LEVELS)
    z_vars  = ",".join(f"geopotential_height_{l}hPa" for l in OM_LEVELS)

    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&hourly={t_vars},{rh_vars},{u_vars},{d_vars},{z_vars},"
        f"temperature_2m,dewpoint_2m,surface_pressure,"
        f"cape,convective_inhibition,lifted_index"
        f"&wind_speed_unit=kn&timezone=auto&forecast_days={max(1, forecast_hours // 24 + 1)}"
    )

    try:
        r = requests.get(url, timeout=15).json()
    except Exception as e:
        logger.error(f"Open-Meteo fetch failed: {e}")
        return None

    hourly = r.get("hourly", {})
    times  = hourly.get("time", [])
    tz_abbr = r.get("timezone_abbreviation", "UTC")
    profiles = []

    for i, t_str in enumerate(times[:forecast_hours]):
        try:
            valid_time = datetime.fromisoformat(t_str).replace(tzinfo=timezone.utc)

            p_arr  = np.array(OM_LEVELS[::-1], dtype=float)   # sort asc altitude = desc pressure
            t_arr  = np.array([hourly.get(f"temperature_{p}hPa",  [None]*len(times))[i] or 0.0
                               for p in OM_LEVELS[::-1]])
            rh_arr = np.array([hourly.get(f"relative_humidity_{p}hPa", [None]*len(times))[i] or 50.0
                               for p in OM_LEVELS[::-1]])
            u_raw  = np.array([hourly.get(f"windspeed_{p}hPa",    [None]*len(times))[i] or 0.0
                               for p in OM_LEVELS[::-1]])
            d_raw  = np.array([hourly.get(f"winddirection_{p}hPa", [None]*len(times))[i] or 0.0
                               for p in OM_LEVELS[::-1]])
            z_arr  = np.array([hourly.get(f"geopotential_height_{p}hPa", [None]*len(times))[i] or 0.0
                               for p in OM_LEVELS[::-1]])

            # Dewpoint from RH
            td_arr = t_arr - (100.0 - rh_arr) / 5.0

            # U/V from speed + direction
            u_arr = np.array([-float(u_raw[j]) * math.sin(math.radians(float(d_raw[j])))
                              for j in range(len(u_raw))])
            v_arr = np.array([-float(u_raw[j]) * math.cos(math.radians(float(d_raw[j])))
                              for j in range(len(u_raw))])

            # Heights AGL
            z_sfc = float(z_arr[0]) if z_arr[0] > 0 else 0.0
            h_agl = np.maximum(z_arr - z_sfc, 0.0)

            # Surface
            t_sfc  = hourly.get("temperature_2m",  [0.0]*len(times))[i] or 0.0
            td_sfc = hourly.get("dewpoint_2m",      [0.0]*len(times))[i] or 0.0
            p_sfc  = hourly.get("surface_pressure", [1013.0]*len(times))[i] or 1013.0

            profiles.append(SoundingProfile(
                valid_time=valid_time,
                source="Open-Meteo",
                lat=lat, lon=lon,
                p_hpa=p_arr, t_c=t_arr, td_c=td_arr,
                heights_m_agl=h_agl, u_kt=u_arr, v_kt=v_arr,
                t_sfc_c=float(t_sfc), td_sfc_c=float(td_sfc), p_sfc_hpa=float(p_sfc),
            ))
        except Exception as e:
            logger.debug(f"Hour {i} profile build failed: {e}")
            continue

    return profiles if profiles else None


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC INTERFACE — MODEL FALLBACK CHAIN
# ─────────────────────────────────────────────────────────────────────────────

def fetch_profiles(
    lat: float,
    lon: float,
    forecast_hours: int = 48,
    progress_cb=None
) -> tuple[list[SoundingProfile], str]:
    """
    Fetch sounding profiles using the fallback chain:
      HRRR → NAM-3km → GFS → Open-Meteo

    Returns (profiles, source_used).
    progress_cb: optional callable(str) for status updates.
    """
    def _progress(msg):
        if progress_cb:
            progress_cb(msg)
        logger.info(msg)

    if _herbie_available():
        # Determine which models are viable for the requested hour range
        # HRRR: max 18hr (some runs to 48hr), NAM: 60hr, GFS: 384hr

        for model, max_fxx in [("HRRR", 18), ("NAM", 60), ("GFS", 120)]:
            _progress(f"Trying {model}…")
            profiles = []
            failed = False

            for fxx in range(0, min(forecast_hours, max_fxx) + 1, 3):
                prof = _fetch_herbie(lat, lon, model, fxx)
                if prof is None:
                    failed = True
                    break
                profiles.append(prof)

            if not failed and profiles:
                _progress(f"✓ Using {model} ({len(profiles)} forecast steps)")
                return profiles, model

            _progress(f"{model} unavailable, trying next…")

    # Final fallback: Open-Meteo
    _progress("Falling back to Open-Meteo…")
    profiles = _fetch_open_meteo(lat, lon, forecast_hours)
    if profiles:
        _progress(f"✓ Using Open-Meteo ({len(profiles)} hours)")
        return profiles, "Open-Meteo"

    return [], "None"
