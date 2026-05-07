"""Find Polymarket weather market slugs for all active Kalshi cities.

Methods used (in order):
  A - Gamma API /events?slug=<pattern>  (per-city pattern search)
  B - Mine existing phase-1 parquet data (data/research/polymarket_trades_raw.parquet
      and data/research/polymarket_market_outcomes.parquet)
  C - Mine full Becker-derived market parquets in data/polymarket/markets/
  D - Predexon cross-platform matching (requires auth — skipped if unauthorized)

Output:
  data/polymarket/weather_slugs.json   — event slugs per Kalshi ICAO city code
  data/polymarket/becker/              — weather-only market CSVs from Becker data

IMPORTANT: Polymarket settles on KLGA (LaGuardia) for NYC, not KNYC (Central Park).
Do NOT copy Polymarket bracket prices directly into Kalshi strategy.

Usage:
  uv run python research/data/find_polymarket_weather_slugs.py          # full run
  uv run python research/data/find_polymarket_weather_slugs.py --method B  # parquet only
  uv run python research/data/find_polymarket_weather_slugs.py --live      # add live Gamma lookup
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import pandas as pd
import requests

# ── Config ──────────────────────────────────────────────────────────────────

GAMMA_API = "https://gamma-api.polymarket.com"
PREDEXON_API = "https://api.predexon.com/v2"

OUT_DIR = Path("data/polymarket")
BECKER_DIR = OUT_DIR / "becker"
PARQUET_MARKETS_DIR = OUT_DIR / "markets"
PHASE1_TRADES = Path("data/research/polymarket_trades_raw.parquet")
PHASE1_OUTCOMES = Path("data/research/polymarket_market_outcomes.parquet")

# Kalshi ICAO → Polymarket city name patterns (lowercase, slug-safe)
CITY_CONFIG: dict[str, dict] = {
    "KNYC": {
        "slug_patterns": ["new-york", "nyc"],
        "question_patterns": ["new york", "nyc", "new york city"],
        "note": "Polymarket settles KLGA (LaGuardia), Kalshi settles KNYC (Central Park)",
    },
    "KMDW": {
        "slug_patterns": ["chicago"],
        "question_patterns": ["chicago"],
        "note": "Both settle Midway/O'Hare area",
    },
    "KMIA": {
        "slug_patterns": ["miami"],
        "question_patterns": ["miami"],
        "note": "",
    },
    "KAUS": {
        "slug_patterns": ["austin"],
        "question_patterns": ["austin"],
        "note": "",
    },
    "KLAX": {
        "slug_patterns": ["los-angeles"],
        "question_patterns": ["los angeles"],
        "note": "",
    },
    "KDEN": {
        "slug_patterns": ["denver"],
        "question_patterns": ["denver"],
        "note": "",
    },
    "KPHL": {
        "slug_patterns": ["philadelphia"],
        "question_patterns": ["philadelphia"],
        "note": "KXHIGHPHIL series (not KXHIGHPHL)",
    },
}

# Slug keywords that identify weather-temperature markets
WEATHER_TEMP_RE = re.compile(
    r"(temperature|highest.temp|high.temp|daily.high|weather|highest-temperature|"
    r"lowest-temperature|precipitation)",
    re.IGNORECASE,
)

# Slug keywords for Becker full-market scan
BECKER_TEMP_RE = re.compile(
    r"(temperature|highest.temp|high.temp|daily.high|weather)",
    re.IGNORECASE,
)


# ── Gamma API helpers ────────────────────────────────────────────────────────

def _request_json(url: str, params: dict | None = None, retries: int = 3) -> list | dict:
    session = requests.Session()
    session.headers["User-Agent"] = "kalshi-weather-research/1.0 public-data"
    for attempt in range(retries):
        try:
            resp = session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            if attempt == retries - 1:
                raise
            print(f"  retry {attempt+1}: {exc}")
            time.sleep(1.5 ** attempt)
    return []


def gamma_search_event(event_slug: str) -> dict | None:
    """Fetch a single Gamma event by exact slug."""
    data = _request_json(f"{GAMMA_API}/events", {"slug": event_slug})
    if isinstance(data, list) and data:
        return data[0]
    return None


# ── Method B: mine phase-1 parquets ─────────────────────────────────────────

def mine_phase1_parquets() -> dict[str, list[str]]:
    """Extract event slugs by city from existing phase-1 trade/outcome parquets."""
    result: dict[str, list[str]] = {k: [] for k in CITY_CONFIG}

    slugs: set[str] = set()
    if PHASE1_TRADES.exists():
        trades = pd.read_parquet(PHASE1_TRADES)
        slugs |= set(trades["eventSlug"].dropna().astype(str).unique())
        print(f"  Phase-1 trades: {len(trades):,} rows, {len(slugs):,} unique event slugs")

    if PHASE1_OUTCOMES.exists():
        outcomes = pd.read_parquet(PHASE1_OUTCOMES)
        slugs |= set(outcomes["eventSlug"].dropna().astype(str).unique())
        print(f"  Phase-1 outcomes: {len(outcomes):,} rows → combined {len(slugs):,} event slugs")

    for city_key, cfg in CITY_CONFIG.items():
        city_slugs = sorted(
            s for s in slugs
            if any(p in s for p in cfg["slug_patterns"])
        )
        result[city_key] = city_slugs
        print(f"  {city_key}: {len(city_slugs)} event slugs from phase-1")

    return result


# ── Method C: mine Becker market parquets ───────────────────────────────────

def mine_becker_markets() -> pd.DataFrame:
    """Scan all Becker market parquets and extract weather-temp markets."""
    if not PARQUET_MARKETS_DIR.exists():
        print("  Becker markets dir not found — skip")
        return pd.DataFrame()

    weather_frames: list[pd.DataFrame] = []
    files = sorted(PARQUET_MARKETS_DIR.glob("*.parquet"))
    print(f"  Scanning {len(files)} Becker market parquet files...")

    for f in files:
        df = pd.read_parquet(f)
        mask = df["question"].astype(str).apply(lambda x: bool(BECKER_TEMP_RE.search(x)))
        if mask.any():
            weather_frames.append(df[mask].copy())

    if not weather_frames:
        print("  No weather markets found in Becker parquets")
        return pd.DataFrame()

    combined = pd.concat(weather_frames, ignore_index=True)
    print(f"  Becker weather markets total: {len(combined):,}")

    BECKER_DIR.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(BECKER_DIR / "becker_weather_markets.parquet", index=False)

    # Per-city CSV extracts
    for city_key, cfg in CITY_CONFIG.items():
        patterns = "|".join(cfg["question_patterns"])
        mask = combined["question"].astype(str).str.contains(patterns, case=False, na=False)
        sub = combined[mask].copy()
        if not sub.empty:
            out_path = BECKER_DIR / f"becker_weather_{city_key.lower()}.csv"
            sub.to_csv(out_path, index=False)
            # date range
            min_dt = sub["end_date"].dropna().min()
            max_dt = sub["end_date"].dropna().max()
            print(f"  {city_key}: {len(sub):,} markets, {str(min_dt)[:10]} → {str(max_dt)[:10]}, saved {out_path.name}")

    return combined


# ── Method D: Predexon ────────────────────────────────────────────────────────

def predexon_match(kalshi_ticker: str) -> dict | None:
    """Attempt Predexon cross-platform matching. Returns None if unauthorized."""
    try:
        data = _request_json(f"{PREDEXON_API}/matching-markets", {"kalshi_market_ticker": kalshi_ticker})
        if isinstance(data, dict) and data.get("message") == "Unauthorized":
            return None
        return data
    except Exception:
        return None


# ── Method A: live Gamma slug scan ───────────────────────────────────────────

def gamma_live_scan(days_back: int = 14) -> dict[str, list[str]]:
    """
    Probe Gamma for recent events using known slug patterns.
    Pattern: highest-temperature-in-{city_slug}-on-{month}-{day}-{year}
    Only checks last `days_back` days to avoid hammering the API.
    """
    from datetime import date, timedelta

    result: dict[str, list[str]] = {k: [] for k in CITY_CONFIG}
    today = date.today()

    # city_slug → Kalshi key
    city_slug_map = {
        "nyc": "KNYC",
        "chicago": "KMDW",
        "miami": "KMIA",
        "austin": "KAUS",
        "los-angeles": "KLAX",
        "denver": "KDEN",
        "philadelphia": "KPHL",
    }
    temp_types = ["highest", "lowest"]

    print("  Live Gamma slug scan...")
    for city_slug, city_key in city_slug_map.items():
        found = []
        for delta in range(days_back):
            d = today - timedelta(days=delta)
            month_name = d.strftime("%B").lower()
            day = d.day
            year = d.year
            for temp_type in temp_types:
                slug = f"{temp_type}-temperature-in-{city_slug}-on-{month_name}-{day}-{year}"
                event = gamma_search_event(slug)
                if event:
                    found.append(slug)
                time.sleep(0.12)
        result[city_key] = sorted(set(found))
        print(f"  {city_key}: {len(result[city_key])} live events")

    return result


# ── Merge + write ────────────────────────────────────────────────────────────

def merge_results(*result_dicts: dict[str, list[str]]) -> dict[str, list[str]]:
    """Union all slug lists per city."""
    merged: dict[str, set[str]] = {k: set() for k in CITY_CONFIG}
    for d in result_dicts:
        for k, slugs in d.items():
            merged[k].update(slugs)
    return {k: sorted(v) for k, v in merged.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--method", choices=["A", "B", "C", "all"], default="all",
                        help="Which methods to run (default: all)")
    parser.add_argument("--live", action="store_true",
                        help="Run live Gamma scan (Method A) — makes many API calls")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    BECKER_DIR.mkdir(parents=True, exist_ok=True)

    all_results: list[dict[str, list[str]]] = []

    # Method B — always run unless specifically skipping
    if args.method in ("B", "all"):
        print("\n=== Method B: Mine phase-1 parquets ===")
        b_result = mine_phase1_parquets()
        all_results.append(b_result)

    # Method C — Becker market parquets
    if args.method in ("C", "all"):
        print("\n=== Method C: Mine Becker market parquets ===")
        mine_becker_markets()  # saves per-city CSVs as side-effect

    # Method A — live Gamma scan (opt-in only)
    if args.live or args.method == "A":
        print("\n=== Method A: Live Gamma scan ===")
        a_result = gamma_live_scan(days_back=14)
        all_results.append(a_result)

    # Method D — Predexon (best-effort)
    print("\n=== Method D: Predexon cross-platform check ===")
    sample = "KXHIGHNY-26JAN10-T52"
    pred = predexon_match(sample)
    if pred:
        print(f"  Predexon result for {sample}: {json.dumps(pred)[:200]}")
    else:
        print("  Predexon: Unauthorized — no public access")

    # Merge and save
    if all_results:
        final = merge_results(*all_results)
        out_path = OUT_DIR / "weather_slugs.json"
        out_path.write_text(json.dumps(final, indent=2) + "\n")
        print(f"\n=== Saved: {out_path} ===")
        for city_key, slugs in final.items():
            print(f"  {city_key}: {len(slugs)} event slugs")

    print("\nDone.")


if __name__ == "__main__":
    main()
