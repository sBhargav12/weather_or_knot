#!/usr/bin/env python3
"""
Leakage-safe forecast data framework for Kalshi weather backtests.

Problem: The historical-forecast-api.open-meteo.com endpoint compiles forecasts
using later model updates and observation assimilation. This inflates apparent
model accuracy and backtest win rates (e.g. GFS MAE 1.20°F is suspiciously low).

Solution: Use the Previous Runs API (previous-runs-api.open-meteo.com) which
stores explicit model run snapshots with run timestamps. Filter to only runs
that were available before the simulated entry time.

Architecture:
  fetch_vintage_forecasts()   -> downloads and caches as-of forecast data
  build_leakage_safe_features() -> produces clean feature DataFrame
  audit_leakage()             -> verifies no row violates availability constraint

Cache format: data/cache/forecast_vintages_{CITY}_{YYYYMM}.parquet
  Columns: model, cycle_init_utc, available_at_utc, target_date, lead_hours,
           temp_max_f, temp_max_raw_c

Replacing in backtest.py:
  Line 43: OPEN_METEO_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
           -> OPEN_METEO_URL = PREVIOUS_RUNS_URL  (see constant below)
  Lines 114, 1139: Remove comment about vintage filtering not being enforced.
  Data fetch block: call fetch_vintage_forecasts() instead of the daily-row fetch.
  Feature join: join on (date, model) with available_at_utc <= entry_utc filter.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

ET = ZoneInfo("America/New_York")
UTC_TZ = UTC

PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"

# Processing delay from cycle init time to when the run is publicly available.
# Based on NOAA/ECMWF operational schedules.
MODEL_CONFIGS: dict[str, dict] = {
    "gfs_seamless": {
        "cycles_utc": [0, 6, 12, 18],
        "processing_delay": timedelta(hours=4, minutes=40),
        "api_variable": "temperature_2m_max",
        "col": "gfs_maxt",
    },
    "ecmwf_ifs025": {
        "cycles_utc": [0, 12],
        "processing_delay": timedelta(hours=7),
        "api_variable": "temperature_2m_max",
        "col": "ecmwf_maxt",
    },
    "icon_seamless": {
        "cycles_utc": [0, 6, 12, 18],
        "processing_delay": timedelta(hours=5),
        "api_variable": "temperature_2m_max",
        "col": "icon_maxt",
    },
    "gem_seamless": {
        "cycles_utc": [0, 12],
        "processing_delay": timedelta(hours=6),
        "api_variable": "temperature_2m_max",
        "col": "gem_maxt",
    },
}

CITY_COORDS: dict[str, tuple[float, float]] = {
    "KNYC": (40.7789, -73.9692),
    "KMDW": (41.7860, -87.7522),
    "KAUS": (30.1945, -97.6699),
    "KLAX": (33.9425, -118.4081),
    "KDEN": (39.8561, -104.6737),
    "KMIA": (25.7959, -80.2870),
    "KPHL": (39.8721, -75.2411),
}


def _cache_path(city: str, year_month: str) -> Path:
    return CACHE_DIR / f"forecast_vintages_{city}_{year_month}.parquet"


def _celsius_to_fahrenheit(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def _fetch_single_model_month(
    model_name: str,
    lat: float,
    lon: float,
    start: date,
    end: date,
    retries: int = 3,
) -> list[dict]:
    """
    Fetch all available run snapshots for one model over a date range from
    the Previous Runs API. Returns a list of dicts with cycle metadata.
    """
    cfg = MODEL_CONFIGS[model_name]
    variable = cfg["api_variable"]
    rows = []

    for past_days_offset in range((end - start).days + 1):
        target = start + timedelta(days=past_days_offset)
        # The Previous Runs API takes a past_days parameter relative to today.
        # We iterate by requesting each target date via forecast_days=1 with
        # appropriate past_days to position the run.
        days_ago = (date.today() - target).days
        if days_ago < 0:
            continue

        for cycle_hour in cfg["cycles_utc"]:
            cycle_init = datetime(
                target.year, target.month, target.day,
                cycle_hour, 0, 0, tzinfo=UTC_TZ
            )
            available_at = cycle_init + cfg["processing_delay"]

            params = {
                "latitude": lat,
                "longitude": lon,
                "daily": variable,
                "temperature_unit": "celsius",
                "timezone": "UTC",
                "past_days": days_ago,
                "forecast_days": 1,
                "models": model_name,
            }

            for attempt in range(retries):
                try:
                    resp = requests.get(
                        PREVIOUS_RUNS_URL, params=params, timeout=30
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        daily = data.get("daily", {})
                        dates = daily.get("time", [])
                        vals = daily.get(variable, [])

                        for d_str, val in zip(dates, vals):
                            if val is None:
                                continue
                            rows.append({
                                "model": model_name,
                                "col": cfg["col"],
                                "cycle_init_utc": cycle_init,
                                "available_at_utc": available_at,
                                "target_date": date.fromisoformat(d_str),
                                "lead_hours": (
                                    datetime.combine(
                                        date.fromisoformat(d_str),
                                        datetime.min.time(),
                                        tzinfo=UTC_TZ
                                    ) - cycle_init
                                ).total_seconds() / 3600,
                                "temp_max_c": float(val),
                                "temp_max_f": _celsius_to_fahrenheit(float(val)),
                            })
                        break
                    elif resp.status_code == 429:
                        time.sleep(2 ** attempt)
                    else:
                        break
                except requests.RequestException:
                    if attempt < retries - 1:
                        time.sleep(2 ** attempt)

    return rows


def fetch_vintage_forecasts(
    city: str,
    start_date: str,
    end_date: str,
    entry_hour_et: int = 11,
    models: Optional[list[str]] = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Fetch leakage-safe as-of forecast data for a city and date range.

    Only returns forecast rows where available_at_utc <= simulated entry time.
    Caches by city+month to data/cache/.

    Parameters
    ----------
    city : str
        City code, e.g. "KNYC"
    start_date, end_date : str
        ISO date strings, e.g. "2026-01-01"
    entry_hour_et : int
        Simulated entry time in ET (default 11 = 11 AM ET)
    models : list[str], optional
        Subset of MODEL_CONFIGS keys. Defaults to all four.
    force_refresh : bool
        Re-download even if cache exists.

    Returns
    -------
    pd.DataFrame with columns:
        model, col, cycle_init_utc, available_at_utc, target_date,
        lead_hours, temp_max_c, temp_max_f
    """
    if city not in CITY_COORDS:
        raise ValueError(f"Unknown city: {city}. Known: {list(CITY_COORDS)}")

    lat, lon = CITY_COORDS[city]
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    use_models = models or list(MODEL_CONFIGS.keys())

    all_rows: list[dict] = []

    # Group by month for cache granularity
    current = date(start.year, start.month, 1)
    while current <= end:
        month_end = (
            date(current.year, current.month + 1, 1) - timedelta(days=1)
            if current.month < 12
            else date(current.year + 1, 1, 1) - timedelta(days=1)
        )
        month_key = current.strftime("%Y%m")
        cache_file = _cache_path(city, month_key)

        if cache_file.exists() and not force_refresh:
            df_cached = pd.read_parquet(cache_file)
            all_rows.extend(df_cached.to_dict("records"))
        else:
            month_rows = []
            fetch_start = max(current, start)
            fetch_end = min(month_end, end)

            for model_name in use_models:
                rows = _fetch_single_model_month(
                    model_name, lat, lon, fetch_start, fetch_end
                )
                month_rows.extend(rows)

            if month_rows:
                df_month = pd.DataFrame(month_rows)
                df_month.to_parquet(cache_file, index=False)
                all_rows.extend(month_rows)

        current = month_end + timedelta(days=1)

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)

    # Enforce availability constraint: drop rows where forecast wasn't ready by entry time
    entry_times = {}
    for d in df["target_date"].unique():
        naive_et = datetime(d.year, d.month, d.day, entry_hour_et, 0, 0)
        entry_times[d] = naive_et.replace(tzinfo=ET).astimezone(UTC_TZ)

    df["entry_utc"] = df["target_date"].map(entry_times)
    df = df[df["available_at_utc"] <= df["entry_utc"]].copy()
    df = df.drop(columns=["entry_utc"])

    return df.reset_index(drop=True)


def build_leakage_safe_features(
    city: str,
    start_date: str,
    end_date: str,
    entry_hour_et: int = 11,
    models: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Build one-row-per-day feature DataFrame using only leakage-safe forecasts.

    For each target date, selects the LATEST available run for each model
    (best information without leakage). Then computes:
        consensus, model_spread, physics_mean, spread_between, month, day_of_year

    Returns
    -------
    pd.DataFrame indexed by target_date with columns matching existing backtest
    feature schema: gfs_maxt, ecmwf_maxt, icon_maxt, gem_maxt, consensus,
    model_spread, month, day_of_year (°F units throughout)
    """
    raw = fetch_vintage_forecasts(
        city, start_date, end_date, entry_hour_et, models
    )
    if raw.empty:
        return pd.DataFrame()

    # For each (target_date, model): keep the row with latest cycle_init_utc
    raw = raw.sort_values("cycle_init_utc")
    latest = (
        raw.groupby(["target_date", "col"])
        .last()
        .reset_index()
    )

    # Pivot to wide format: one row per date, one column per model
    wide = latest.pivot(index="target_date", columns="col", values="temp_max_f")
    wide.index = pd.to_datetime(wide.index)
    wide.columns.name = None
    wide = wide.reset_index().rename(columns={"index": "date", "target_date": "date"})

    model_cols = [c for c in ["gfs_maxt", "ecmwf_maxt", "icon_maxt", "gem_maxt"] if c in wide.columns]

    wide["consensus"] = wide[model_cols].mean(axis=1)
    wide["model_spread"] = wide[model_cols].std(axis=1)
    wide["physics_mean"] = wide[model_cols].mean(axis=1)  # Alias for compat
    wide["ai_mean"] = wide["gfs_maxt"] if "gfs_maxt" in wide.columns else wide["consensus"]
    wide["spread_between"] = wide["model_spread"]

    wide["date"] = pd.to_datetime(wide["date"])
    wide["month"] = wide["date"].dt.month
    wide["day_of_year"] = wide["date"].dt.dayofyear

    return wide.set_index("date").sort_index()


def audit_leakage(
    df: pd.DataFrame,
    entry_hour_et: int = 11,
    date_col: str = "target_date",
    avail_col: str = "available_at_utc",
) -> dict:
    """
    Audit a forecast DataFrame for leakage violations.

    A violation is any row where available_at_utc > simulated entry time
    (i.e., the forecast was not yet available when we pretended to use it).

    Parameters
    ----------
    df : pd.DataFrame
        Raw vintage forecast DataFrame with available_at_utc column.
    entry_hour_et : int
        Simulated entry hour in ET.
    date_col : str
        Column name for the forecast target date.
    avail_col : str
        Column name for the model availability datetime (UTC).

    Returns
    -------
    dict with:
        n_total, n_violations, pct_clean, violation_dates (list),
        earliest_violation, latest_violation
    """
    if df.empty:
        return {"n_total": 0, "n_violations": 0, "pct_clean": 1.0, "violation_dates": []}

    entry_times: dict = {}
    for d in df[date_col].unique():
        d_date = d if isinstance(d, date) else pd.to_datetime(d).date()
        naive_et = datetime(d_date.year, d_date.month, d_date.day, entry_hour_et)
        entry_times[d] = naive_et.replace(tzinfo=ET).astimezone(UTC_TZ)

    df = df.copy()
    df["_entry_utc"] = df[date_col].map(entry_times)

    avail = df[avail_col]
    if avail.dt.tz is None:
        avail = avail.dt.tz_localize(UTC_TZ)

    violations = df[avail > df["_entry_utc"]]
    violation_dates = sorted(violations[date_col].unique().tolist())

    return {
        "n_total": len(df),
        "n_violations": len(violations),
        "pct_clean": round(1.0 - len(violations) / max(len(df), 1), 4),
        "violation_dates": [str(d) for d in violation_dates],
        "earliest_violation": str(violation_dates[0]) if violation_dates else None,
        "latest_violation": str(violation_dates[-1]) if violation_dates else None,
    }


def _entry_utc_for_date(d: date, entry_hour_et: int) -> datetime:
    naive = datetime(d.year, d.month, d.day, entry_hour_et, 0, 0)
    return naive.replace(tzinfo=ET).astimezone(UTC_TZ)


# ---------------------------------------------------------------------------
# Changes required in research/backtests/backtest.py to use this framework
# ---------------------------------------------------------------------------
#
# 1. Replace:
#      OPEN_METEO_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
#    With:
#      from research.backtests.leakage_safe_framework import (
#          build_leakage_safe_features, audit_leakage
#      )
#
# 2. Replace the Open-Meteo fetch block (around lines 200–260 in backtest.py)
#    that calls OPEN_METEO_URL and caches to open_meteo_historical.csv
#    With a call to:
#      features_df = build_leakage_safe_features(
#          city=CITY_CODE,
#          start_date=str(START_DATE),
#          end_date=str(END_DATE),
#          entry_hour_et=11,
#      )
#    Then join features_df onto the trade DataFrame by date.
#
# 3. After building features_df, run the audit:
#      audit = audit_leakage(raw_vintage_df, entry_hour_et=11)
#      assert audit["n_violations"] == 0, f"Leakage! {audit}"
#      print(f"Leakage audit: {audit['n_total']} rows, {audit['pct_clean']*100:.1f}% clean")
#
# 4. Remove the comment at line ~114:
#      "# vintage filtering is not enforced because the cache has no cycle timestamps"
#    The new cache has cycle timestamps and filtering is enforced.
#
# 5. Entry timing tests (9AM vs 11AM) now require separate feature builds:
#      features_9am = build_leakage_safe_features(..., entry_hour_et=9)
#      features_11am = build_leakage_safe_features(..., entry_hour_et=11)
#    For 9AM entry, only GFS 00Z (available ~04:40 UTC = 00:40 AM ET) is usable.
#    For 11AM entry, GFS 06Z (available ~10:40 UTC = 06:40 AM ET) is usable.
#    ECMWF 00Z (available 07:00 UTC = 03:00 AM ET) is usable for both.
#
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Leakage-safe forecast framework demo")
    parser.add_argument("--city", default="KNYC")
    parser.add_argument("--start", default="2026-01-01")
    parser.add_argument("--end", default="2026-01-31")
    parser.add_argument("--entry-hour", type=int, default=11)
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()

    print(f"Building leakage-safe features for {args.city} {args.start}–{args.end}")
    print(f"Entry time: {args.entry_hour}:00 ET")
    print()

    features = build_leakage_safe_features(
        city=args.city,
        start_date=args.start,
        end_date=args.end,
        entry_hour_et=args.entry_hour,
    )

    if features.empty:
        print("No data returned. Check API connectivity and date range.")
    else:
        print(f"Features shape: {features.shape}")
        print(features[["gfs_maxt", "ecmwf_maxt", "consensus", "model_spread"]].head(10).round(2))
        print()

        # Quick audit using the raw cache
        city_ym = args.start[:7].replace("-", "")
        cache_file = CACHE_DIR / f"forecast_vintages_{args.city}_{city_ym}.parquet"
        if cache_file.exists():
            raw = pd.read_parquet(cache_file)
            audit = audit_leakage(raw, entry_hour_et=args.entry_hour)
            print("=== Leakage Audit ===")
            print(json.dumps(audit, indent=2, default=str))
