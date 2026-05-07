#!/usr/bin/env python3
"""
Fetch IEM ASOS hourly temperature data for KNYC covering the same window
as the 1m Kalshi candle dataset (Oct 2024 – May 2026).

Output: data/research/knyc_intraday_asos.csv
Columns: date (ET date), hour_et (0-23), tmpf (°F), dt_utc
"""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "research" / "knyc_intraday_asos.csv"

IEM_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"


def fetch_asos(year1: int, month1: int, year2: int, month2: int) -> pd.DataFrame:
    params = {
        "station": "KNYC",
        "data": "tmpf",
        "year1": year1,
        "month1": month1,
        "day1": 1,
        "year2": year2,
        "month2": month2,
        "day2": 30,
        "tz": "UTC",
        "format": "comma",
        "latlon": "no",
        "missing": "M",
        "trace": "T",
        "direct": "no",
        "report_type": 3,  # hourly
    }
    r = requests.get(IEM_URL, params=params, timeout=60)
    r.raise_for_status()
    text = r.text
    # Strip comment lines starting with #
    lines = [line for line in text.splitlines() if not line.startswith("#")]
    df = pd.read_csv(StringIO("\n".join(lines)), na_values=["M", "T"])
    return df


def main() -> None:
    print("Fetching IEM ASOS hourly data for KNYC (Oct 2024 – May 2026)…")

    # Fetch in two chunks to avoid timeout
    chunks = [
        fetch_asos(2024, 10, 2025, 6),
        fetch_asos(2025, 7, 2026, 5),
    ]
    raw = pd.concat(chunks, ignore_index=True)
    raw = raw.dropna(subset=["tmpf"])
    raw = raw[raw["tmpf"] != "M"]

    # Parse timestamps (UTC)
    raw["dt_utc"] = pd.to_datetime(raw["valid"], utc=True)
    raw["tmpf"] = pd.to_numeric(raw["tmpf"], errors="coerce")
    raw = raw.dropna(subset=["tmpf"])

    # Convert to ET
    raw["dt_et"] = raw["dt_utc"].dt.tz_convert("America/New_York")
    raw["date"] = raw["dt_et"].dt.date.astype(str)
    raw["hour_et"] = raw["dt_et"].dt.hour
    raw["minute_et"] = raw["dt_et"].dt.minute

    # Keep only daytime hours (8 AM – 8 PM ET) relevant for daily max
    raw = raw[(raw["hour_et"] >= 8) & (raw["hour_et"] <= 20)]

    out = raw[["date", "hour_et", "minute_et", "tmpf", "dt_utc"]].copy()
    out = out.sort_values(["date", "dt_utc"]).reset_index(drop=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    print(f"Saved {len(out):,} rows → {OUT}")
    print(f"Date range: {out['date'].min()} → {out['date'].max()}")
    print(f"Sample:\n{out.head(6).to_string()}")


if __name__ == "__main__":
    main()
