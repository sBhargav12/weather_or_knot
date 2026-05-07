"""
Download NOAA 1991-2020 Daily Climate Normals for 7 stations.
Output: data/climate_normals/normals_by_city_doy.parquet
"""
import io
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "climate_normals"
OUT_DIR.mkdir(parents=True, exist_ok=True)

NOAA_STATIONS = {
    "KNYC": "USW00094728",
    "KMDW": "USW00014819",
    "KMIA": "USW00012839",
    "KAUS": "USW00013904",
    "KLAX": "USW00023174",
    "KDEN": "USW00003017",
    "KPHL": "USW00013739",
}

# Primary URL pattern
PRIMARY_URL = (
    "https://www.ncei.noaa.gov/data/normals-daily/1991-2020/access/{station_id}.csv"
)

# Fallback: NCEI v1 data service
FALLBACK_URL = (
    "https://www.ncei.noaa.gov/access/services/data/v1"
    "?dataset=normals-daily"
    "&stations={station_id}"
    "&startDate=2010-01-01"
    "&endDate=2010-12-31"
    "&dataTypes=DLY-TMAX-NORMAL,DLY-TMAX-STDDEV,DLY-TMIN-NORMAL,DLY-TMIN-STDDEV"
    "&format=csv"
    "&includeAttributes=false"
)

TARGET_COLS = {
    "DLY-TMAX-NORMAL": "climo_tmax_f",
    "DLY-TMAX-STDDEV": "climo_tmax_std",
    "DLY-TMIN-NORMAL": "climo_tmin_f",
    "DLY-TMIN-STDDEV": "climo_tmin_std",
}


def _fetch_url(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_primary(raw: str, city: str, station_id: str) -> pd.DataFrame:
    """Parse the full normals CSV (wide format with many columns).

    NOAA normals-daily CSVs have explicit 'month' and 'day' columns (string "01").
    They also have a 'DATE' column in MM-DD format ("01-01") which is NOT a full
    date — do NOT attempt pd.to_datetime() on it.
    """
    df = pd.read_csv(io.StringIO(raw), low_memory=False)
    df.columns = [c.strip() for c in df.columns]

    # Priority: use explicit month/day columns if present (NOAA normals format)
    has_month = any(c.lower() == "month" for c in df.columns)
    has_day = any(c.lower() == "day" for c in df.columns)

    if has_month and has_day:
        # Rename to lowercase if needed
        col_rename = {}
        for c in df.columns:
            if c.lower() == "month" and c != "month":
                col_rename[c] = "month"
            if c.lower() == "day" and c != "day":
                col_rename[c] = "day"
        if col_rename:
            df = df.rename(columns=col_rename)
    else:
        # Fall back: try to parse DATE column as full ISO date
        date_col = next((c for c in df.columns if c.upper() == "DATE"), None)
        if date_col:
            # Try full date parse (YYYY-MM-DD)
            df["_date"] = pd.to_datetime(df[date_col], format="%Y-%m-%d", errors="coerce")
            good = df["_date"].notna()
            if good.sum() > 0:
                df = df[good].copy()
                df["month"] = df["_date"].dt.month
                df["day"] = df["_date"].dt.day
            else:
                # Try MM-DD format (split on "-")
                parts = df[date_col].str.split("-", expand=True)
                if parts.shape[1] >= 2:
                    df["month"] = pd.to_numeric(parts[0], errors="coerce")
                    df["day"] = pd.to_numeric(parts[1], errors="coerce")
                else:
                    raise ValueError(f"{city}: cannot parse DATE column: {df[date_col].head(3).tolist()}")
        else:
            raise ValueError(f"{city}: cannot determine month/day from columns: {list(df.columns)[:20]}")

    # Collect target columns (case-insensitive search)
    col_map = {}
    for src, dst in TARGET_COLS.items():
        # exact match first
        if src in df.columns:
            col_map[src] = dst
        else:
            # case-insensitive
            match = next((c for c in df.columns if c.upper() == src.upper()), None)
            if match:
                col_map[match] = dst

    if len(col_map) < 4:
        found = list(col_map.keys())
        raise ValueError(
            f"{city}: only found {len(col_map)}/4 target columns. Found: {found}. "
            f"Available: {list(df.columns)[:30]}"
        )

    out = df[["month", "day"] + list(col_map.keys())].copy()
    out = out.rename(columns=col_map)

    for dst in TARGET_COLS.values():
        out[dst] = pd.to_numeric(out[dst], errors="coerce")

    out = out.dropna(subset=["month", "day"])
    out["month"] = out["month"].astype(int)
    out["day"] = out["day"].astype(int)
    out["city"] = city
    out = out[["city", "month", "day"] + list(TARGET_COLS.values())]
    return out.sort_values(["month", "day"]).reset_index(drop=True)


def _parse_fallback(raw: str, city: str) -> pd.DataFrame:
    """Parse the v1 API response (wide format with MM-DD DATE column).

    DATE format is "01-01" (MM-DD). Values are in tenths of °F (e.g. 389 = 38.9°F)
    when returned from the raw API, but the primary CSV already has °F floats.
    The v1 API returns tenths — divide by 10.
    """
    df = pd.read_csv(io.StringIO(raw), low_memory=False)
    df.columns = [c.strip() for c in df.columns]

    # Wide format: STATION, DATE (MM-DD), DLY-TMAX-NORMAL, ...
    date_col = next((c for c in df.columns if c.upper() == "DATE"), None)
    if date_col is None:
        raise ValueError(f"{city}: fallback CSV has no DATE column. Cols: {list(df.columns)}")

    parts = df[date_col].str.strip('"').str.split("-", expand=True)
    df["month"] = pd.to_numeric(parts[0], errors="coerce")
    df["day"] = pd.to_numeric(parts[1], errors="coerce")
    df = df.dropna(subset=["month", "day"])

    col_map = {}
    for src, dst in TARGET_COLS.items():
        match = next((c for c in df.columns if c.strip('"') == src), None)
        if match:
            col_map[match] = dst

    if len(col_map) < 4:
        raise ValueError(f"{city}: fallback only found {len(col_map)}/4 cols: {list(col_map.keys())}")

    out = df[["month", "day"] + list(col_map.keys())].copy()
    out = out.rename(columns=col_map)

    for dst in TARGET_COLS.values():
        out[dst] = pd.to_numeric(out[dst], errors="coerce")
        # v1 API returns tenths of °F — convert to °F
        out[dst] = out[dst] / 10.0

    out = out.dropna(subset=["month", "day"])
    out["month"] = out["month"].astype(int)
    out["day"] = out["day"].astype(int)
    out["city"] = city
    out = out[["city", "month", "day"] + list(TARGET_COLS.values())]
    return out.sort_values(["month", "day"]).reset_index(drop=True)


def fetch_city(city: str, station_id: str) -> pd.DataFrame:
    url = PRIMARY_URL.format(station_id=station_id)
    print(f"  {city} ({station_id}): trying primary URL ...", flush=True)
    try:
        raw = _fetch_url(url)
        df = _parse_primary(raw, city, station_id)
        print(f"    primary OK: {len(df)} rows")
        return df
    except Exception as e1:
        print(f"    primary failed: {e1}")

    url2 = FALLBACK_URL.format(station_id=station_id)
    print(f"    trying fallback URL ...", flush=True)
    try:
        raw2 = _fetch_url(url2)
        df = _parse_fallback(raw2, city)
        print(f"    fallback OK: {len(df)} rows")
        return df
    except Exception as e2:
        print(f"    fallback failed: {e2}")
        raise RuntimeError(f"{city}: both URLs failed. Primary: {e1}  Fallback: {e2}")


def check_missing_days(df: pd.DataFrame, city: str):
    """Warn if any month/day combos are missing (expected 365 or 366)."""
    expected = set()
    for m in range(1, 13):
        days_in_month = pd.Timestamp(2020, m, 1).days_in_month
        for d in range(1, days_in_month + 1):
            expected.add((m, d))
    actual = set(zip(df["month"], df["day"]))
    missing = expected - actual
    if missing:
        print(f"    {city}: {len(missing)} missing day(s): {sorted(missing)[:5]} ...")
    else:
        print(f"    {city}: all {len(df)} days present")


def main():
    all_dfs = []

    for city, station_id in NOAA_STATIONS.items():
        try:
            df = fetch_city(city, station_id)
            check_missing_days(df, city)
            all_dfs.append(df)
        except Exception as exc:
            print(f"  ERROR {city}: {exc}", file=sys.stderr)
        time.sleep(0.5)

    if not all_dfs:
        print("No normals data fetched.", file=sys.stderr)
        sys.exit(1)

    combined = pd.concat(all_dfs, ignore_index=True)
    out = OUT_DIR / "normals_by_city_doy.parquet"
    combined.to_parquet(out, index=False)
    print(f"\nSaved: {len(combined)} rows across {combined['city'].nunique()} cities → {out}")
    print(combined.groupby("city").size().to_string())


if __name__ == "__main__":
    main()
