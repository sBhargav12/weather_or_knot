"""
Fetch GFS, ECMWF, ICON, and GEM T-max/T-min forecast vintages from
Open-Meteo Historical Forecast API for all 7 cities.

Output: data/openmeteo_forecast_vintages/{city}_forecast_vintages.parquet
        data/openmeteo_forecast_vintages/all_cities_forecast_vintages.parquet

Columns: city, date, model, tmax_f, tmin_f

API response structure (multi-model):
  data["daily"]["time"] = ["2022-01-01", ...]
  data["daily"]["temperature_2m_max_gfs_seamless"] = [45.2, ...]
  data["daily"]["temperature_2m_min_ecmwf_ifs025"] = [32.1, ...]
  etc.
"""

import time
import requests
import pandas as pd
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CITIES = {
    "KNYC": {"lat": 40.7789, "lon": -73.9692, "tz": "America/New_York"},
    "KMDW": {"lat": 41.7860, "lon": -87.7520, "tz": "America/Chicago"},
    "KMIA": {"lat": 25.7959, "lon": -80.2870, "tz": "America/New_York"},
    "KAUS": {"lat": 30.1945, "lon": -97.6699, "tz": "America/Chicago"},
    "KLAX": {"lat": 33.9425, "lon": -118.4081, "tz": "America/Los_Angeles"},
    "KDEN": {"lat": 39.8561, "lon": -104.6737, "tz": "America/Denver"},
    "KPHL": {"lat": 39.8719, "lon": -75.2411, "tz": "America/New_York"},
}

MODELS = ["gfs_seamless", "ecmwf_ifs025", "icon_seamless", "gem_seamless"]

START_DATE = "2022-01-01"
END_DATE = "2026-05-06"

BASE_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"

OUTPUT_DIR = Path("data/openmeteo_forecast_vintages")

# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def fetch_city(city: str, cfg: dict, max_retries: int = 6) -> pd.DataFrame:
    """Fetch all models for one city; return long-format DataFrame."""
    params = {
        "latitude": cfg["lat"],
        "longitude": cfg["lon"],
        "start_date": START_DATE,
        "end_date": END_DATE,
        "models": ",".join(MODELS),
        "daily": "temperature_2m_max,temperature_2m_min",
        "temperature_unit": "fahrenheit",
        "timezone": cfg["tz"],
    }

    wait = 5
    data = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(BASE_URL, params=params, timeout=120)
            if resp.status_code == 429:
                print(f"  429 rate-limit (attempt {attempt}/{max_retries}) — wait {wait}s")
                time.sleep(wait)
                wait = min(wait * 2, 120)
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        except requests.exceptions.RequestException as exc:
            print(f"  Request error (attempt {attempt}/{max_retries}): {exc}")
            if attempt == max_retries:
                raise
            time.sleep(wait)
            wait = min(wait * 2, 120)

    if data is None:
        return pd.DataFrame()

    # Parse response.
    # Multi-model request returns a single dict; model data is in data["daily"]
    # with suffixed column names: temperature_2m_max_gfs_seamless, etc.
    if not isinstance(data, dict) or "daily" not in data:
        print(f"  ERROR: unexpected response for {city}: {list(data.keys()) if isinstance(data, dict) else type(data)}")
        return pd.DataFrame()

    daily = data["daily"]
    dates = daily.get("time", [])

    rows = []
    for model_name in MODELS:
        tmax_key = f"temperature_2m_max_{model_name}"
        tmin_key = f"temperature_2m_min_{model_name}"
        if tmax_key not in daily:
            print(f"  Warning: model '{model_name}' not in response for {city}")
            continue
        tmax = daily[tmax_key]
        tmin = daily.get(tmin_key, [None] * len(dates))
        for d, hi, lo in zip(dates, tmax, tmin):
            rows.append({"city": city, "date": d, "model": model_name,
                         "tmax_f": hi, "tmin_f": lo})

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["tmax_f"] = pd.to_numeric(df["tmax_f"], errors="coerce")
    df["tmin_f"] = pd.to_numeric(df["tmin_f"], errors="coerce")

    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_frames = []

    for city, cfg in CITIES.items():
        print(f"\n{'='*60}")
        print(f"Fetching {city} ({cfg['lat']}, {cfg['lon']}) ...")

        df = fetch_city(city, cfg)

        if df.empty:
            print(f"  ERROR: no data returned for {city}")
            continue

        models_found = sorted(df["model"].unique().tolist())
        models_missing = [m for m in MODELS if m not in models_found]
        date_min = df["date"].min()
        date_max = df["date"].max()
        n_rows = len(df)

        print(f"  Rows      : {n_rows:,}")
        print(f"  Date range: {date_min} -> {date_max}")
        print(f"  Models    : {models_found}")
        if models_missing:
            print(f"  MISSING   : {models_missing}")

        # Check for null tmax coverage per model
        for m in models_found:
            sub = df[df["model"] == m]
            null_pct = sub["tmax_f"].isna().mean() * 100
            if null_pct > 5:
                print(f"  Warning: {m} has {null_pct:.1f}% null tmax_f")
            else:
                print(f"  {m}: {len(sub):,} rows, {null_pct:.1f}% null tmax_f")

        out_path = OUTPUT_DIR / f"{city.lower()}_forecast_vintages.parquet"
        df.to_parquet(out_path, index=False)
        size_kb = out_path.stat().st_size / 1024
        print(f"  Saved     : {out_path} ({size_kb:.1f} KB)")

        all_frames.append(df)

        # Polite pause between cities
        time.sleep(2)

    if all_frames:
        combined = pd.concat(all_frames, ignore_index=True)
        combined_path = OUTPUT_DIR / "all_cities_forecast_vintages.parquet"
        combined.to_parquet(combined_path, index=False)
        size_kb = combined_path.stat().st_size / 1024
        print(f"\n{'='*60}")
        print(f"Combined   : {len(combined):,} rows across {combined['city'].nunique()} cities")
        print(f"Saved      : {combined_path} ({size_kb:.1f} KB)")
    else:
        print("\nNo data fetched — combined file not created.")


if __name__ == "__main__":
    main()
