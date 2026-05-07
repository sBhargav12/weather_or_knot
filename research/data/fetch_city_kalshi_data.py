#!/usr/bin/env python3
"""
Fetch Kalshi historical markets + price candlesticks for a given city.

Outputs (example for KMIA):
  data/kxhighmia_markets.csv   — settled markets with target_date, brackets, settlement
  data/kxhighmia_prices.csv    — yes price at open / 9AM / 11AM / 1PM / 3PM

Usage:
    uv run python research/data/fetch_city_kalshi_data.py --city KMIA
    uv run python research/data/fetch_city_kalshi_data.py --city KAUS
    uv run python research/data/fetch_city_kalshi_data.py --city KLAX
    uv run python research/data/fetch_city_kalshi_data.py --city KDEN
    uv run python research/data/fetch_city_kalshi_data.py --city KPHL

Incremental: already-fetched tickers are skipped for prices.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import UTC, date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config

DATA_DIR = ROOT / "data"
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
START_DATE = date(2024, 10, 1)
PRICE_SINCE_DATE = date(2026, 1, 1)  # only fetch candlesticks for eval window; saves ~70% of API calls

ENTRY_TIMES = {
    "open": None,
    "9AM":  dtime(9, 0),
    "11AM": dtime(11, 0),
    "1PM":  dtime(13, 0),
    "3PM":  dtime(15, 0),
}


def log(msg: str) -> None:
    print(msg, flush=True)


def request_json(url: str, params: dict) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json,text/plain,*/*",
    }
    for attempt in range(4):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError:
            raise  # 4xx errors are not retried — 404 is expected for low-volume markets
        except Exception as exc:
            time.sleep(1.5 * (attempt + 1))
            if attempt == 3:
                raise RuntimeError(f"request failed after 4 attempts: {exc}") from exc
    raise RuntimeError("exhausted retries")


def bracket_type(lo: Any, hi: Any) -> str:
    try:
        lo_f, hi_f = float(lo), float(hi)
    except (TypeError, ValueError):
        return "central"
    if lo_f <= 0:
        return "lower_tail"
    if hi_f >= 120:
        return "upper_tail"
    return "central"


def parse_target_date(ticker: str, series_ticker: str) -> Optional[str]:
    # Modern format: {series_ticker}-{YY}{MON}{DD}-...  (works for KXHIGH* and KXLOWT*)
    patterns = [rf"^{re.escape(series_ticker)}-(\d{{2}})([A-Z]{{3}})(\d{{2}})"]
    # Legacy KXHIGH support: some old tickers omit the "KX" prefix
    if series_ticker.startswith("KXHIGH"):
        suffix = series_ticker.replace("KXHIGH", "")
        patterns.append(rf"^(?:KX)?HIGH{re.escape(suffix)}-(\d{{2}})([A-Z]{{3}})(\d{{2}})")
    for pattern in patterns:
        m = re.match(pattern, ticker)
        if m:
            yy, mon, dd = m.groups()
            try:
                return pd.to_datetime(f"20{yy}-{mon}-{dd}", format="%Y-%b-%d").strftime("%Y-%m-%d")
            except Exception:
                return None
    return None


def candle_time(candle: dict) -> Optional[datetime]:
    for key in ("start_period_ts", "end_period_ts", "period_start_ts", "time", "ts", "timestamp"):
        value = candle.get(key)
        if value is None:
            continue
        try:
            if isinstance(value, (int, float)) or str(value).isdigit():
                raw = float(value)
                if raw > 10_000_000_000:
                    raw /= 1000
                return datetime.fromtimestamp(raw, tz=UTC)
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
        except Exception:
            continue
    return None


def candle_yes_price(candle: dict) -> Optional[float]:
    nested = candle.get("yes") if isinstance(candle.get("yes"), dict) else {}
    price_nested = candle.get("price") if isinstance(candle.get("price"), dict) else {}
    for key in ("open_dollars", "open", "price_dollars", "price", "close_dollars", "close"):
        if key in price_nested:
            val = price_nested[key]
        elif key in nested:
            val = nested[key]
        else:
            val = candle.get(key)
        if val is None:
            continue
        try:
            f = float(val)
            if f > 1.0:
                f /= 100.0
            if 0.01 <= f <= 0.99:
                return f
        except (TypeError, ValueError):
            pass
    for key in ("yes_open_dollars", "yes_open", "yes_price_dollars", "yes_price",
                "yes_close_dollars", "yes_close"):
        val = candle.get(key)
        if val is None:
            continue
        try:
            f = float(val)
            if f > 1.0:
                f /= 100.0
            if 0.01 <= f <= 0.99:
                return f
        except (TypeError, ValueError):
            pass
    return None


def iso_to_ts(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


def pick_price(candles: list[tuple[datetime, float]], target_local: Optional[datetime]) -> Optional[float]:
    if not candles:
        return None
    candles = sorted(candles, key=lambda x: x[0])
    if target_local is None:
        return candles[0][1]
    target_utc = target_local.astimezone(UTC)
    eligible = [(ts, p) for ts, p in candles if ts <= target_utc]
    if eligible:
        return eligible[-1][1]
    return min(candles, key=lambda x: abs((x[0] - target_utc).total_seconds()))[1]


def fetch_markets(series_ticker: str) -> pd.DataFrame:
    log(f"Fetching settled {series_ticker} markets from Kalshi...")
    rows: list[dict] = []
    for endpoint in ("/markets", "/historical/markets"):
        cursor = None
        endpoint_rows = 0
        while True:
            params: dict[str, Any] = {"series_ticker": series_ticker, "status": "settled", "limit": 100}
            if cursor:
                params["cursor"] = cursor
            data = request_json(f"{KALSHI_BASE}{endpoint}", params)
            markets = data.get("markets", [])
            rows.extend(markets)
            endpoint_rows += len(markets)
            cursor = data.get("cursor")
            if not cursor or not markets:
                break
        log(f"  {endpoint}: {endpoint_rows} markets")

    out_rows = []
    for market in rows:
        lo = market.get("floor_strike")
        hi = market.get("cap_strike")
        btype = bracket_type(lo, hi)
        target_date = parse_target_date(str(market.get("ticker", "")), series_ticker)
        if not target_date:
            continue
        if target_date < START_DATE.isoformat():
            continue
        out_rows.append({
            "ticker": market.get("ticker"),
            "target_date": target_date,
            "settlement_value": (market.get("result") or market.get("settlement_value")
                                 or market.get("expiration_value")),
            "open_time": market.get("open_time"),
            "close_time": market.get("close_time"),
            "floor_strike": lo,
            "cap_strike": hi,
            "bracket_type": btype,
            "raw_settlement_temp": market.get("expiration_value"),
        })

    df = pd.DataFrame(out_rows).dropna(subset=["ticker", "target_date"])
    df["floor_strike"] = pd.to_numeric(df["floor_strike"], errors="coerce")
    df["cap_strike"] = pd.to_numeric(df["cap_strike"], errors="coerce")
    df = df.drop_duplicates(subset=["ticker"], keep="first").sort_values(["target_date", "ticker"])
    return df


def fetch_prices(markets: pd.DataFrame, series_ticker: str, city_tz: ZoneInfo,
                 existing_tickers: set[str], prices_csv: Path,
                 existing_prices: pd.DataFrame) -> pd.DataFrame:
    # Restrict to eval window — training labels come from actuals CSV, not prices
    eval_markets = markets[pd.to_datetime(markets["target_date"]).dt.date >= PRICE_SINCE_DATE]
    tickers = [t for t in eval_markets["ticker"].dropna().unique() if t not in existing_tickers]
    log(f"Fetching candlesticks for {len(tickers)} tickers since {PRICE_SINCE_DATE} (skipping {len(existing_tickers)} cached)...")
    rows = []
    failures: list[str] = []

    for i, ticker in enumerate(tickers, start=1):
        market = eval_markets.loc[eval_markets["ticker"] == ticker].iloc[0]
        start_ts = iso_to_ts(market.get("open_time"))
        end_ts = iso_to_ts(market.get("close_time"))
        if start_ts is None or end_ts is None:
            target_date = str(market["target_date"])
            target_start = datetime.fromisoformat(f"{target_date}T00:00:00").replace(tzinfo=city_tz)
            start_ts = int((target_start - timedelta(days=1, hours=2)).timestamp())
            end_ts = int((target_start + timedelta(days=1)).timestamp())

        params: dict[str, Any] = {
            "start_ts": start_ts,
            "end_ts": end_ts,
            "period_interval": 60,
            "include_latest_before_start": "true",
        }
        # Try live endpoint first (has 2026 data), fall back to historical for older markets.
        # Neither endpoint retries on 404 — it's expected for low-volume brackets.
        raw_candles = []
        hist_params = {k: v for k, v in params.items() if k != "include_latest_before_start"}
        try:
            data = request_json(
                f"{KALSHI_BASE}/series/{series_ticker}/markets/{ticker}/candlesticks", params)
            raw_candles = data.get("candlesticks", data.get("candles", []))
        except requests.exceptions.HTTPError:
            try:
                data = request_json(
                    f"{KALSHI_BASE}/historical/markets/{ticker}/candlesticks", hist_params)
                raw_candles = data.get("candlesticks", data.get("candles", []))
            except Exception as hist_exc:
                failures.append(f"{ticker}: {hist_exc}")
        except Exception as exc:
            failures.append(f"{ticker}: {exc}")

        candles: list[tuple[datetime, float]] = []
        for candle in raw_candles:
            ts = candle_time(candle)
            price = candle_yes_price(candle)
            if ts is not None and price is not None:
                candles.append((ts, price))

        target_date = str(market["target_date"])
        target_day = datetime.fromisoformat(f"{target_date}T00:00:00").replace(tzinfo=city_tz)
        row: dict[str, Any] = {"ticker": ticker, "target_date": target_date,
                                "price_source": "kalshi_candlesticks"}
        for label, clock in ENTRY_TIMES.items():
            target_local = None if clock is None else target_day.replace(hour=clock.hour, minute=clock.minute)
            row[f"yes_price_{label}"] = pick_price(candles, target_local)
        rows.append(row)

        if i % 50 == 0:
            log(f"  fetched {i}/{len(tickers)} tickers")
            # incremental save every 50 tickers
            checkpoint = pd.concat([existing_prices, pd.DataFrame(rows)], ignore_index=True)
            checkpoint = checkpoint.drop_duplicates(subset=["ticker"], keep="last")
            checkpoint.to_csv(prices_csv, index=False)
        time.sleep(0.05)

    if failures:
        log(f"Failures: {len(failures)}. First 5: {failures[:5]}")

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Kalshi market+price data for a city.")
    parser.add_argument("--city", required=True, help="Station code, e.g. KMIA, KAUS, KLAX, KDEN, KPHL")
    args = parser.parse_args()

    city = args.city.upper()
    if city not in config.CITIES:
        print(f"Unknown city '{city}'. Valid: {list(config.CITIES.keys())}", file=sys.stderr)
        sys.exit(2)

    city_cfg = config.CITIES[city]
    series_ticker = city_cfg["series_ticker"]
    city_tz = ZoneInfo(city_cfg["timezone"])
    series_lower = series_ticker.lower()
    markets_csv = DATA_DIR / f"{series_lower}_markets.csv"
    prices_csv = DATA_DIR / f"{series_lower}_prices.csv"

    log(f"=== {city} ({series_ticker}) ===")

    # --- Markets ---
    if markets_csv.exists():
        existing = pd.read_csv(markets_csv)
        log(f"Loaded {len(existing)} existing markets from {markets_csv.name}")
        markets = fetch_markets(series_ticker)
        combined = pd.concat([existing, markets], ignore_index=True)
        combined = combined.drop_duplicates(subset=["ticker"], keep="last").sort_values(["target_date", "ticker"])
        combined.to_csv(markets_csv, index=False)
        log(f"Saved {len(combined)} total markets → {markets_csv.name}")
        markets = combined
    else:
        markets = fetch_markets(series_ticker)
        markets.to_csv(markets_csv, index=False)
        log(f"Saved {len(markets)} markets → {markets_csv.name}")

    # --- Prices (incremental) ---
    existing_tickers: set[str] = set()
    existing_prices = pd.DataFrame()
    if prices_csv.exists():
        existing_prices = pd.read_csv(prices_csv)
        # Only skip tickers that already have at least one real price; re-fetch NaN rows
        price_cols = [c for c in existing_prices.columns if c.startswith("yes_price_")]
        if price_cols:
            has_price = existing_prices[price_cols].notna().any(axis=1)
            existing_tickers = set(existing_prices.loc[has_price, "ticker"].dropna())
        else:
            existing_tickers = set(existing_prices["ticker"].dropna())
        log(f"Loaded {len(existing_prices)} existing price rows from {prices_csv.name} "
            f"({len(existing_tickers)} with prices, "
            f"{len(existing_prices) - len(existing_tickers)} NaN rows to re-fetch)")

    new_prices = fetch_prices(markets, series_ticker, city_tz, existing_tickers,
                              prices_csv, existing_prices)

    if not new_prices.empty:
        all_prices = pd.concat([existing_prices, new_prices], ignore_index=True)
        all_prices = all_prices.drop_duplicates(subset=["ticker"], keep="last")
        all_prices.to_csv(prices_csv, index=False)
        log(f"Saved {len(all_prices)} total price rows → {prices_csv.name}")
    else:
        log("No new price rows fetched.")

    log(f"\nDone. Markets: {markets_csv}  Prices: {prices_csv}")


if __name__ == "__main__":
    main()
