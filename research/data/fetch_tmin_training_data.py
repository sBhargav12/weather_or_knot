#!/usr/bin/env python3
"""
Fetch IEM ASOS actual daily minimum temperatures for KXLOWT training.

Outputs (example for KXLOWTNYC):
  data/kxlowtnyc_actual_tmin_extended.csv  — IEM min_tmpf for NYC station

These actuals are used by kxlow_backtest.py as EMOS training targets.
Open-Meteo vintage TMIN forecasts are fetched by the backtest script itself.

Usage:
    uv run python research/data/fetch_tmin_training_data.py                     # KXLOWTNYC
    uv run python research/data/fetch_tmin_training_data.py --city KXLOWTCHI
    uv run python research/data/fetch_tmin_training_data.py --all               # all 7 cities
"""
from __future__ import annotations

import argparse
import io
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data"
IEM_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/daily.py"

DEFAULT_START = date(2024, 1, 1)

# Maps KXLOWT city code → (IEM station, IEM network, output filename)
CITY_MAP: dict[str, tuple[str, str, str]] = {
    "KXLOWTNYC":  ("NYC", "NY_ASOS",  "kxlowtnyc_actual_tmin_extended.csv"),
    "KXLOWTCHI":  ("MDW", "IL_ASOS",  "kxlowtchi_actual_tmin_extended.csv"),
    "KXLOWTMIA":  ("MIA", "FL_ASOS",  "kxlowtmia_actual_tmin_extended.csv"),
    "KXLOWTAUS":  ("AUS", "TX_ASOS",  "kxlowtaus_actual_tmin_extended.csv"),
    "KXLOWTLAX":  ("LAX", "CA_ASOS",  "kxlowtlax_actual_tmin_extended.csv"),
    "KXLOWTDEN":  ("DEN", "CO_ASOS",  "kxlowtden_actual_tmin_extended.csv"),
    "KXLOWTPHIL": ("PHL", "PA_ASOS",  "kxlowtphil_actual_tmin_extended.csv"),
}


def log(msg: str) -> None:
    print(msg, flush=True)


def fetch_iem_tmin(station: str, network: str, start: date, end: date) -> pd.DataFrame:
    params = {
        "station": station, "network": network,
        "year1": start.year, "month1": start.month, "day1": start.day,
        "year2": end.year,   "month2": end.month,   "day2": end.day,
        "vars": "min_tmpf", "what": "download",
    }
    resp = requests.get(IEM_URL, params=params, timeout=60)
    resp.raise_for_status()
    raw = pd.read_csv(io.StringIO(resp.text), comment="#")
    rename = {}
    for col in raw.columns:
        if "min_tmp" in col.lower():
            rename[col] = "min_temp_f"
        if col.lower() == "day":
            rename[col] = "date"
    raw = raw.rename(columns=rename)
    if "min_temp_f" not in raw.columns:
        log(f"  WARNING: IEM returned cols {raw.columns.tolist()}, no min_temp_f")
        return pd.DataFrame(columns=["date", "min_temp_f"])
    df = raw[["date", "min_temp_f"]].copy()
    df["min_temp_f"] = pd.to_numeric(df["min_temp_f"], errors="coerce")
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df.dropna(subset=["date", "min_temp_f"])


def fetch_city(city: str, start: date) -> None:
    if city not in CITY_MAP:
        log(f"Unknown city '{city}'. Valid: {list(CITY_MAP)}")
        return
    station, network, out_filename = CITY_MAP[city]
    out_path = DATA_DIR / out_filename
    end = date.today() - timedelta(days=1)

    if out_path.exists():
        existing = pd.read_csv(out_path)
        log(f"  Loaded {len(existing)} existing rows from {out_path.name}")
    else:
        existing = pd.DataFrame()

    log(f"  [{city}] IEM fetch: {station}/{network}, {start} – {end}")
    try:
        new_df = fetch_iem_tmin(station, network, start, end)
    except Exception as exc:
        log(f"  [{city}] ERROR: {exc}")
        return

    combined = pd.concat([existing, new_df], ignore_index=True) if not existing.empty else new_df.copy()
    combined["date"] = pd.to_datetime(combined["date"]).dt.date
    combined = combined.drop_duplicates(subset=["date"]).sort_values("date")
    combined.to_csv(out_path, index=False)
    log(f"  [{city}] Saved {len(combined)} rows → {out_path.name}  "
        f"(range: {combined['date'].min()} – {combined['date'].max()}, "
        f"min={combined['min_temp_f'].min():.1f}°F max={combined['min_temp_f'].max():.1f}°F)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch IEM TMIN actuals for KXLOWT cities.")
    parser.add_argument("--city", default="KXLOWTNYC", help="City code (e.g. KXLOWTCHI)")
    parser.add_argument("--all", action="store_true", help="Fetch all 7 KXLOWT cities")
    parser.add_argument("--start", default=DEFAULT_START.isoformat(), help="Start date YYYY-MM-DD")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    cities = list(CITY_MAP.keys()) if args.all else [args.city.upper()]

    for city in cities:
        fetch_city(city, start)


if __name__ == "__main__":
    main()
