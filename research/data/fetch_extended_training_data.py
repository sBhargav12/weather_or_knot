#!/usr/bin/env python3
"""
Fetch extended EMOS training data for a city (default: NYC/KNYC).

Outputs (city = KNYC):
  data/open_meteo_historical_extended.csv  — model forecasts, all dates
  data/knyc_actual_temps_extended.csv      — IEM actual daily highs, all dates

Outputs (city = KMDW):
  data/open_meteo_kmdw_historical_extended.csv
  data/kmdw_actual_temps_extended.csv

Run once; subsequent runs skip already-fetched dates (incremental).
"""
from __future__ import annotations

import argparse
import io
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config

DATA_DIR = ROOT / "data"
MARKETS_DIR = DATA_DIR / "kalshi" / "markets"

OPEN_METEO_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
IEM_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/daily.py"

# Defaults — overridden in main() by --city
CITY_CODE: str = "KNYC"
SERIES_TICKER: str = "KXHIGHNY"
LAT: float = 40.7789
LON: float = -73.9692
CITY_TZ_STR: str = "America/New_York"
IEM_STATION: str = "NYC"
IEM_NETWORK: str = "NY_ASOS"
OUT_MODELS: Path = DATA_DIR / "open_meteo_historical_extended.csv"
OUT_ACTUALS: Path = DATA_DIR / "knyc_actual_temps_extended.csv"

IEM_STATION_MAP: dict[str, tuple[str, str]] = {
    "KNYC": ("NYC", "NY_ASOS"),
    "KPHL": ("PHL", "PA_ASOS"),
    "KMDW": ("MDW", "IL_ASOS"),
    "KMIA": ("MIA", "FL_ASOS"),
    "KAUS": ("AUS", "TX_ASOS"),
    "KDEN": ("DEN", "CO_ASOS"),
    "KLAX": ("LAX", "CA_ASOS"),
    "KLAS": ("LAS", "NV_ASOS"),
}

# Recency threshold: dates on or after this are real operational forecasts
REAL_FORECAST_CUTOFF = "2024-10-01"


def log(msg: str) -> None:
    print(msg, flush=True)


def parse_target_date(ticker: str, city_suffix: str) -> date | None:
    m = re.match(rf"^(?:KX)?HIGH{re.escape(city_suffix)}-(\d{{2}})([A-Z]{{3}})(\d{{2}})", ticker)
    if not m:
        return None
    yy, mon, dd = m.groups()
    try:
        return pd.to_datetime(f"20{yy}-{mon}-{dd}", format="%Y-%b-%d").date()
    except Exception:
        return None


def collect_target_dates() -> list[date]:
    import glob
    # Derive the legacy ticker suffix from SERIES_TICKER (e.g. KXHIGHNY -> NY, KXHIGHCHI -> CHI)
    city_suffix = SERIES_TICKER.replace("KXHIGH", "")
    # Source 1: Becker market parquet files (Aug 2021–Nov 2025)
    files = sorted(glob.glob(str(MARKETS_DIR / "*.parquet")))
    rows = []
    for f in files:
        df = pd.read_parquet(f)
        mask = df["ticker"].str.match(rf"^(?:KX)?HIGH{city_suffix}-", na=False)
        rows.append(df[mask][["ticker"]])
    if rows:
        all_tickers = pd.concat(rows, ignore_index=True)["ticker"]
        dates = {parse_target_date(t, city_suffix) for t in all_tickers}
    else:
        dates = set()
    dates.discard(None)

    # Source 2: city-specific markets CSV (live API data, extends through Apr 2026+)
    markets_csv = DATA_DIR / f"{SERIES_TICKER.lower()}_markets.csv"
    if markets_csv.exists():
        mdf = pd.read_csv(markets_csv)
        for d in pd.to_datetime(mdf["target_date"], errors="coerce").dropna():
            dates.add(d.date())

    return sorted(dates)


def fetch_open_meteo_range(start: date, end: date) -> pd.DataFrame:
    """Fetch one contiguous date range from Open-Meteo historical forecast API."""
    params = {
        "latitude": LAT,
        "longitude": LON,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": "temperature_2m_max",
        "models": ["gfs_seamless", "ecmwf_ifs025", "ukmo_seamless", "ncep_nbm_conus"],
        "timezone": CITY_TZ_STR,
        "temperature_unit": "fahrenheit",
    }
    resp = requests.get(OPEN_METEO_URL, params=params, timeout=60)
    resp.raise_for_status()
    daily = resp.json().get("daily", {})

    df = pd.DataFrame({"date": daily.get("time", [])})
    col_map = {
        "gfs_maxt": ["temperature_2m_max_gfs_seamless"],
        "ecmwf_maxt": ["temperature_2m_max_ecmwf_ifs025"],
        "ukmo_maxt": ["temperature_2m_max_ukmo_seamless"],
        "nbm_maxt": ["temperature_2m_max_ncep_nbm_conus"],
    }
    for out_col, keys in col_map.items():
        for key in keys:
            if key in daily:
                df[out_col] = daily[key]
                break
        else:
            df[out_col] = np.nan

    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def fetch_iem_range(start: date, end: date) -> pd.DataFrame:
    params = {
        "station": IEM_STATION,
        "network": IEM_NETWORK,
        "year1": start.year, "month1": start.month, "day1": start.day,
        "year2": end.year, "month2": end.month, "day2": end.day,
        "vars": "max_tmpf",
        "what": "download",
    }
    resp = requests.get(IEM_URL, params=params, timeout=60)
    resp.raise_for_status()
    raw = pd.read_csv(io.StringIO(resp.text), comment="#")
    # IEM returns column named max_tmpf; rename to max_temp_f for consistency
    rename = {}
    for col in raw.columns:
        if "max_tmp" in col.lower():
            rename[col] = "max_temp_f"
        if col.lower() == "day":
            rename[col] = "date"
    raw = raw.rename(columns=rename)
    if "max_temp_f" not in raw.columns:
        log(f"  WARNING: IEM returned cols {raw.columns.tolist()}, no max_temp_f")
        return pd.DataFrame(columns=["date", "max_temp_f"])
    df = raw[["date", "max_temp_f"]].copy()
    df["max_temp_f"] = pd.to_numeric(df["max_temp_f"], errors="coerce")
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df.dropna(subset=["date", "max_temp_f"])


def load_existing(path: Path, date_col: str) -> set[date]:
    if not path.exists():
        return set()
    df = pd.read_csv(path)
    return set(pd.to_datetime(df[date_col]).dt.date)


def fill_consensus(df: pd.DataFrame) -> pd.DataFrame:
    """Fill NaN individual models with row-level consensus of available models."""
    model_cols = ["gfs_maxt", "ecmwf_maxt", "ukmo_maxt", "nbm_maxt"]
    df = df.copy()
    row_mean = df[model_cols].mean(axis=1)
    for col in model_cols:
        df[col] = df[col].fillna(row_mean)
    return df


def main() -> None:
    global CITY_CODE, SERIES_TICKER, LAT, LON, CITY_TZ_STR
    global IEM_STATION, IEM_NETWORK, OUT_MODELS, OUT_ACTUALS

    parser = argparse.ArgumentParser(description="Fetch extended EMOS training data for a city.")
    parser.add_argument("--city", default="KNYC", help="Station code from config.CITIES (e.g. KNYC, KMDW).")
    args = parser.parse_args()

    if args.city not in config.CITIES:
        print(f"Unknown city '{args.city}'. Valid: {list(config.CITIES.keys())}", file=sys.stderr)
        sys.exit(2)

    city_cfg = config.CITIES[args.city]
    CITY_CODE = args.city
    SERIES_TICKER = city_cfg["series_ticker"]
    LAT = city_cfg["lat"]
    LON = city_cfg["lon"]
    CITY_TZ_STR = city_cfg["timezone"]
    IEM_STATION, IEM_NETWORK = IEM_STATION_MAP.get(args.city, (args.city.lstrip("K"), "ASOS"))

    city_lower = args.city.lower()
    series_lower = SERIES_TICKER.lower()
    if args.city == "KNYC":
        OUT_MODELS = DATA_DIR / "open_meteo_historical_extended.csv"
        OUT_ACTUALS = DATA_DIR / "knyc_actual_temps_extended.csv"
    else:
        OUT_MODELS = DATA_DIR / f"open_meteo_{city_lower}_historical_extended.csv"
        OUT_ACTUALS = DATA_DIR / f"{city_lower}_actual_temps_extended.csv"

    log(f"=== fetch_extended_training_data  city={CITY_CODE}  series={SERIES_TICKER} ===")

    target_dates = collect_target_dates()
    log(f"Unique {SERIES_TICKER} target dates: {len(target_dates)}  "
        f"({target_dates[0]} – {target_dates[-1]})")

    existing_models = load_existing(OUT_MODELS, "date")
    existing_actuals = load_existing(OUT_ACTUALS, "date")

    new_model_dates = [d for d in target_dates if d not in existing_models]
    new_actual_dates = [d for d in target_dates if d not in existing_actuals]
    log(f"New model dates to fetch:  {len(new_model_dates)}")
    log(f"New actual dates to fetch: {len(new_actual_dates)}")

    # --- Open-Meteo: fetch in 365-day batches to stay within API limits ---
    new_model_rows: list[pd.DataFrame] = []
    if new_model_dates:
        batch_start = new_model_dates[0]
        batch_end = new_model_dates[-1]
        cur = batch_start
        while cur <= batch_end:
            chunk_end = min(cur + timedelta(days=364), batch_end)
            log(f"  Open-Meteo fetch: {cur} – {chunk_end}")
            try:
                chunk = fetch_open_meteo_range(cur, chunk_end)
                new_model_rows.append(chunk)
                time.sleep(0.5)
            except Exception as e:
                log(f"  WARNING: Open-Meteo failed for {cur}–{chunk_end}: {e}")
            cur = chunk_end + timedelta(days=1)

    # --- IEM actuals: single request for full new range ---
    new_actual_rows: list[pd.DataFrame] = []
    if new_actual_dates:
        log(f"  IEM fetch: {new_actual_dates[0]} – {new_actual_dates[-1]}")
        try:
            new_actual_rows.append(fetch_iem_range(new_actual_dates[0], new_actual_dates[-1]))
        except Exception as e:
            log(f"  WARNING: IEM fetch failed: {e}")

    # --- Merge with existing and save ---
    def merge_and_save(existing_path: Path, new_rows: list[pd.DataFrame],
                       date_col: str, value_cols: list[str]) -> pd.DataFrame:
        parts: list[pd.DataFrame] = []
        if existing_path.exists():
            parts.append(pd.read_csv(existing_path))
        for r in new_rows:
            parts.append(r[[date_col] + value_cols])
        if not parts:
            return pd.DataFrame(columns=[date_col] + value_cols)
        combined = pd.concat(parts, ignore_index=True)
        combined[date_col] = pd.to_datetime(combined[date_col]).dt.date
        combined = combined.drop_duplicates(subset=[date_col]).sort_values(date_col)
        combined.to_csv(existing_path, index=False)
        log(f"  Saved {len(combined)} rows → {existing_path.name}")
        return combined

    models_df = merge_and_save(
        OUT_MODELS, new_model_rows, "date",
        ["gfs_maxt", "ecmwf_maxt", "ukmo_maxt", "nbm_maxt"],
    )
    actuals_df = merge_and_save(
        OUT_ACTUALS, new_actual_rows, "date", ["max_temp_f"],
    )

    # --- Summary ---
    models_df = fill_consensus(models_df)
    joined = models_df.merge(actuals_df, on="date", how="inner")
    real = joined[joined["date"].astype(str) >= REAL_FORECAST_CUTOFF]
    hindcast = joined[joined["date"].astype(str) < REAL_FORECAST_CUTOFF]
    log(f"\nTraining-ready rows (models + actuals joined): {len(joined)}")
    log(f"  Real forecast period (≥{REAL_FORECAST_CUTOFF}): {len(real)}")
    log(f"  Hindcast period (ERA5-based):                  {len(hindcast)}")
    log(f"  GFS coverage:   {models_df['gfs_maxt'].notna().sum()}/{len(models_df)}")
    log(f"  ECMWF coverage: {models_df['ecmwf_maxt'].notna().sum()}/{len(models_df)}")
    log(f"  UKMO coverage:  {models_df['ukmo_maxt'].notna().sum()}/{len(models_df)}")
    log(f"  NBM coverage:   {models_df['nbm_maxt'].notna().sum()}/{len(models_df)}")


if __name__ == "__main__":
    main()
