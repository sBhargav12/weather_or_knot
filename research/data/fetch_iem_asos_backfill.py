"""
Fetch full hourly ASOS observations for 7 cities, June 2021 – May 2026.
Output: data/asos_hourly/{city}_asos_hourly.parquet + all_cities_asos_hourly.parquet
"""
import io
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "asos_hourly"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# IEM uses 3-letter FAA codes (no K-prefix), except NYC Central Park = "NYC"
# report_type=3 = ASOS hourly summary (has actual tmpf values)
# report_type=1 = raw 5-min METARs (tmpf is 'M'/missing for most observations)
STATIONS = {
    "KNYC": "NYC",   # NYC Central Park — IEM special ID
    "KMDW": "MDW",   # Chicago Midway
    "KMIA": "MIA",   # Miami
    "KAUS": "AUS",   # Austin
    "KLAX": "LAX",   # Los Angeles
    "KDEN": "DEN",   # Denver
    "KPHL": "PHL",   # Philadelphia
}

BASE_URL = (
    "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
    "?station={station}"
    "&data=tmpf"
    "&year1=2021&month1=6&day1=1"
    "&year2=2026&month2=5&day2=7"
    "&tz=UTC"
    "&format=comma"
    "&latlon=no"
    "&missing=M"
    "&trace=T"
    "&direct=no"
    "&report_type=3"
)


def fetch_station(station: str) -> pd.DataFrame:
    url = BASE_URL.format(station=station)
    print(f"  Fetching {station} ...", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    # IEM prepends comment lines with '#'; skip them
    lines = [ln for ln in raw.splitlines() if not ln.startswith("#")]
    if not lines:
        raise ValueError(f"No data returned for {station}")

    df = pd.read_csv(io.StringIO("\n".join(lines)), low_memory=False)
    return df


def process(station: str, df: pd.DataFrame) -> pd.DataFrame:
    # Normalise column names
    df.columns = [c.strip().lower() for c in df.columns]

    # Keep only needed columns (station, valid, tmpf)
    needed = ["station", "valid", "tmpf"]
    missing_cols = [c for c in needed if c not in df.columns]
    if missing_cols:
        raise ValueError(f"{station}: missing columns {missing_cols}. Got: {list(df.columns)}")

    df = df[needed].copy()

    # Parse timestamp
    df["valid"] = pd.to_datetime(df["valid"], utc=True, errors="coerce")
    df = df.dropna(subset=["valid"])

    # Coerce tmpf: drop 'M' (missing) and 'T' (trace – not applicable to temp)
    df["tmpf"] = pd.to_numeric(df["tmpf"], errors="coerce")
    df = df.dropna(subset=["tmpf"])

    if df.empty:
        raise ValueError(f"{station}: no valid tmpf rows after parsing")

    df = df.sort_values("valid").reset_index(drop=True)

    # Compute running_max_f = cumulative daily max up to each hour
    df["date"] = df["valid"].dt.date
    df["running_max_f"] = (
        df.groupby("date")["tmpf"].transform("cummax")
    )

    return df


def gap_report(df: pd.DataFrame, station: str):
    """Print any gaps > 3 hours in the time series."""
    df_sorted = df.sort_values("valid")
    deltas = df_sorted["valid"].diff().dropna()
    big_gaps = deltas[deltas > pd.Timedelta(hours=3)]
    if big_gaps.empty:
        print(f"    {station}: no gaps > 3h")
    else:
        print(f"    {station}: {len(big_gaps)} gap(s) > 3h")
        for idx in big_gaps.index[:5]:
            prev = df_sorted.loc[idx - 1, "valid"] if idx - 1 in df_sorted.index else "?"
            curr = df_sorted.loc[idx, "valid"]
            gap = big_gaps.loc[idx]
            print(f"      {prev} → {curr}  ({gap})")


def main():
    all_dfs = []

    for city, station in STATIONS.items():
        try:
            raw = fetch_station(station)
            df = process(station, raw)
            gap_report(df, station)

            out = OUT_DIR / f"{city}_asos_hourly.parquet"
            df.to_parquet(out, index=False)

            date_min = df["valid"].min().strftime("%Y-%m-%d")
            date_max = df["valid"].max().strftime("%Y-%m-%d")
            print(
                f"  {city}: {len(df):,} rows  {date_min} → {date_max}  → {out.name}"
            )
            all_dfs.append(df)

        except Exception as exc:
            print(f"  ERROR {city}: {exc}", file=sys.stderr)

        time.sleep(3)  # be polite to IEM — avoid 429

    if all_dfs:
        combined = pd.concat(all_dfs, ignore_index=True)
        comb_out = OUT_DIR / "all_cities_asos_hourly.parquet"
        combined.to_parquet(comb_out, index=False)
        print(f"\nCombined: {len(combined):,} rows → {comb_out}")
    else:
        print("No data fetched — combined file not written.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
