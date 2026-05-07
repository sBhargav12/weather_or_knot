#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
from scipy.stats import gumbel_r


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from execution.fill_model import simulate_fill, stress_test_fills
from models.distributional_temp import DistributionalTempModel

DATA_DIR = ROOT / "data"
MARKETS_CSV = DATA_DIR / "kxhighny_markets.csv"
PRICES_CSV = DATA_DIR / "kxhighny_prices.csv"
ACTUALS_CSV = DATA_DIR / "knyc_actual_temps.csv"
OPEN_METEO_CSV = DATA_DIR / "open_meteo_historical.csv"
RESULTS_CSV = DATA_DIR / "backtest_results.csv"
SUMMARY_JSON = DATA_DIR / "backtest_summary.json"

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
IEM_DAILY_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/daily.py"
OPEN_METEO_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"

NY_TZ = ZoneInfo("America/New_York")

# City-specific config — overridden at startup by --city arg
CITY_CODE: str = "KNYC"
SERIES_TICKER: str = "KXHIGHNY"
CITY_TZ: ZoneInfo = NY_TZ
CITY_LAT: float = 40.7789
CITY_LON: float = -73.9692
IEM_STATION: str = "NYC"
IEM_NETWORK: str = "NY_ASOS"

IEM_STATION_MAP: dict[str, tuple[str, str]] = {
    "KNYC": ("NYC", "NY_ASOS"),
    "KPHL": ("PHL", "PA_ASOS"),
    "KMDW": ("MDW", "IL_ASOS"),
    "KMIA": ("MIA", "FL_ASOS"),
    "KAUS": ("AUS", "TX_ASOS"),
    "KDEN": ("DEN", "CO_ASOS"),
    "KLAX": ("LAX", "CA_ASOS"),
}
START_DATE = date(2024, 10, 1)
END_DATE = date(2026, 4, 25)
DEFAULT_CORE_GAP_PP = float(config.MIN_GAP_PP)
DEFAULT_ENTRY_TIMING = "9AM"
THRESHOLD_BAKEOFF_GAPS = [20, 25, 30]
TAIL_NO_PROB_MAX = 0.30
TAIL_NO_YES_PRICE_MIN = 0.55
DEEP_TAIL_NO_PROB_MAX = 0.02
DEEP_TAIL_NO_YES_PRICE_MIN = 0.05

VERSION_BOUNDARIES = {
    "2024-12-17": ("regime_hgefs", "HGEFS_operational"),
    "2025-02-25": ("regime_aifs", "ECMWF_AIFS_single_live"),
    "2025-05-27": ("regime_nbm_v43", "NBM_v4.3_upgrade"),
    "2025-07-01": ("regime_aifs_ens", "ECMWF_AIFS_ENS_live"),
    "2026-04-15": ("regime_nbm_v50", "NBM_v5.0_upgrade"),
}

REGIME_PERIODS = [
    ("pre_HGEFS", START_DATE.isoformat(), "2024-12-16"),
    ("HGEFS_to_AIFS", "2024-12-17", "2025-02-24"),
    ("AIFS_to_NBM_v43", "2025-02-25", "2025-05-26"),
    ("NBM_v43_to_AIFS_ENS", "2025-05-27", "2025-06-30"),
    ("AIFS_ENS_to_NBM_v50", "2025-07-01", "2026-04-14"),
    ("NBM_v50_on", "2026-04-15", END_DATE.isoformat()),
]

MODEL_COLUMNS = {
    "gfs": "gfs_maxt",
    "ecmwf": "ecmwf_maxt",
    "ukmo": "ukmo_maxt",
    "nbm": "nbm_maxt",
}

FIXED_ENSEMBLE_WEIGHTS = {
    "ecmwf": 0.35,
    "gfs": 0.25,
    "ukmo": 0.20,
    "nbm": 0.20,
}

ENTRY_TIMES = {
    "open": None,
    "9AM": dtime(9, 0),
    "11AM": dtime(11, 0),
    "1PM": dtime(13, 0),
    "3PM": dtime(15, 0),
}

VINTAGE_FILTER_NOTE = (
    "Open-Meteo historical cache has daily values without cycle_init_utc; "
    "true forecast-vintage filtering cannot drop rows yet."
)


def log(message: str) -> None:
    print(message, flush=True)


def request_json(url: str, params: Optional[dict] = None, timeout: int = 30) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json,text/plain,*/*",
    }
    for attempt in range(4):
        response = requests.get(url, params=params, headers=headers, timeout=timeout)
        if response.status_code in (429, 500, 502, 503, 504) and attempt < 3:
            time.sleep(1.5 * (attempt + 1))
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError("unreachable")


def request_text(url: str, params: Optional[dict] = None, timeout: int = 60) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    response = requests.get(url, params=params, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.text


def parse_target_date_from_ticker(ticker: str) -> Optional[str]:
    # KXHIGHNY-26APR25-T70 -> 2026-04-25
    try:
        token = ticker.split("-")[1]
        year = 2000 + int(token[:2])
        month = {
            "JAN": 1,
            "FEB": 2,
            "MAR": 3,
            "APR": 4,
            "MAY": 5,
            "JUN": 6,
            "JUL": 7,
            "AUG": 8,
            "SEP": 9,
            "OCT": 10,
            "NOV": 11,
            "DEC": 12,
        }[token[2:5].upper()]
        day = int(token[5:])
        return date(year, month, day).isoformat()
    except Exception:
        return None


def as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def price_to_float(value: Any) -> Optional[float]:
    value_f = as_float(value)
    if value_f is None:
        return None
    # Kalshi older fields are cents; *_dollars fields are already 0-1.
    return value_f / 100.0 if value_f > 1.0 else value_f


def bracket_type(floor_strike: Any, cap_strike: Any) -> str:
    if pd.isna(floor_strike) or floor_strike is None:
        return "wing_low"
    if pd.isna(cap_strike) or cap_strike is None:
        return "wing_high"
    return "central"


def bracket_label(row: pd.Series) -> str:
    lo = row.get("floor_strike")
    hi = row.get("cap_strike")
    btype = row.get("bracket_type")
    if btype == "wing_low":
        return f"<={hi:g}F"
    if btype == "wing_high":
        return f">{lo:g}F"
    return f"{lo:g}-{hi:g}F"


def resolved_yes(actual_temp: float, lo: Optional[float], hi: Optional[float], btype: str) -> bool:
    if btype == "wing_low":
        return hi is not None and actual_temp <= hi
    if btype == "wing_high":
        return lo is not None and actual_temp > lo
    return lo is not None and hi is not None and lo <= actual_temp <= hi


def kalshi_result_yes(value: Any) -> Optional[bool]:
    if value is None or pd.isna(value):
        return None
    normalized = str(value).strip().lower()
    if normalized in {"yes", "1", "true"}:
        return True
    if normalized in {"no", "0", "false"}:
        return False
    return None


def gumbel_prob(lo: Optional[float], hi: Optional[float], btype: str, consensus: float) -> float:
    mu = consensus - 0.45
    beta = 0.742
    if btype == "wing_low":
        if hi is None:
            return np.nan
        prob = gumbel_r.cdf(hi - 0.5, mu, beta)
    elif btype == "wing_high":
        if lo is None:
            return np.nan
        prob = 1.0 - gumbel_r.cdf(lo + 0.5, mu, beta)
    else:
        if lo is None or hi is None:
            return np.nan
        prob = gumbel_r.cdf(hi + 0.5, mu, beta) - gumbel_r.cdf(lo - 0.5, mu, beta)
    return float(min(max(prob, 0.0), 1.0))


def kalshi_fee(price: float) -> float:
    return math.ceil(0.07 * price * (1.0 - price) * 100.0) / 100.0


def sharpe(values: Iterable[float]) -> float:
    arr = np.array(list(values), dtype=float)
    if len(arr) < 2:
        return 0.0
    std = float(np.std(arr, ddof=1))
    return 0.0 if std == 0 else float(np.mean(arr) / std)


def max_drawdown(values: Iterable[float]) -> float:
    equity = np.cumsum(np.array(list(values), dtype=float))
    if len(equity) == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    return float(np.min(equity - peak))


def summarize_trades(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "net_pnl": 0.0,
            "gross_pnl": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "avg_return": 0.0,
        }
    return {
        "trades": int(len(df)),
        "win_rate": float(df["win"].mean()),
        "net_pnl": float(df["net"].sum()),
        "gross_pnl": float(df["gross"].sum()),
        "sharpe": sharpe(df["net"]),
        "max_drawdown": max_drawdown(df["net"]),
        "avg_return": float((df["net"] / df["entry_price"].replace(0, np.nan)).mean()),
    }


def add_regime_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Add binary model-version regime flags to a DataFrame with date-like rows."""
    out = df.copy()
    date_col = "date" if "date" in out.columns else "target_date"
    if date_col not in out.columns:
        return out
    dates = out[date_col].astype(str)
    for cutoff, (column, _label) in VERSION_BOUNDARIES.items():
        out[column] = (dates >= cutoff).astype(int)
    return out


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(float(value) for value in weights.values() if np.isfinite(value))
    if total <= 0:
        return dict(FIXED_ENSEMBLE_WEIGHTS)
    return {key: float(value) / total for key, value in weights.items()}


def fetch_kalshi_markets() -> pd.DataFrame:
    log(f"Fetching settled {SERIES_TICKER} markets from Kalshi...")
    rows: list[dict] = []
    for endpoint in ("/markets", "/historical/markets"):
        cursor = None
        endpoint_rows = 0
        while True:
            params = {"series_ticker": SERIES_TICKER, "status": "settled", "limit": 100}
            if cursor:
                params["cursor"] = cursor
            data = request_json(f"{KALSHI_BASE}{endpoint}", params=params)
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
        out_rows.append(
            {
                "ticker": market.get("ticker"),
                "target_date": parse_target_date_from_ticker(str(market.get("ticker", ""))),
                "settlement_value": market.get("result") or market.get("settlement_value") or market.get("expiration_value"),
                "open_time": market.get("open_time"),
                "close_time": market.get("close_time"),
                "floor_strike": lo,
                "cap_strike": hi,
                "bracket_type": btype,
                "raw_settlement_temp": market.get("expiration_value"),
            }
        )
    df = pd.DataFrame(out_rows).dropna(subset=["ticker", "target_date"])
    df["floor_strike"] = pd.to_numeric(df["floor_strike"], errors="coerce")
    df["cap_strike"] = pd.to_numeric(df["cap_strike"], errors="coerce")
    df = df[(df["target_date"] >= START_DATE.isoformat()) & (df["target_date"] <= END_DATE.isoformat())]
    df = df.drop_duplicates(subset=["ticker"], keep="first").sort_values(["target_date", "ticker"])
    df.to_csv(MARKETS_CSV, index=False)
    log(f"Saved {len(df)} markets to {MARKETS_CSV}")
    return df


def candle_time(candle: dict) -> Optional[datetime]:
    candidates = [
        candle.get("start_period_ts"),
        candle.get("end_period_ts"),
        candle.get("period_start_ts"),
        candle.get("time"),
        candle.get("ts"),
        candle.get("timestamp"),
    ]
    for value in candidates:
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
            value = price_nested.get(key)
        elif key in nested:
            value = nested.get(key)
        else:
            value = candle.get(key)
        price = price_to_float(value)
        if price is not None:
            return price
    for key in ("yes_open_dollars", "yes_open", "yes_price_dollars", "yes_price", "yes_close_dollars", "yes_close"):
        price = price_to_float(candle.get(key))
        if price is not None:
            return price
    return None


def iso_to_ts(value: Any) -> Optional[int]:
    if value is None or pd.isna(value):
        return None
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


def pick_price(candles: list[tuple[datetime, float]], target_local: Optional[datetime]) -> Optional[float]:
    if not candles:
        return None
    candles = sorted(candles, key=lambda item: item[0])
    if target_local is None:
        return candles[0][1]
    target_utc = target_local.astimezone(UTC)
    eligible = [(ts, price) for ts, price in candles if ts <= target_utc]
    if eligible:
        return eligible[-1][1]
    return min(candles, key=lambda item: abs((item[0] - target_utc).total_seconds()))[1]


def target_price_times(markets: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, market in markets.iterrows():
        target_date = str(market["target_date"])
        target_day = datetime.fromisoformat(f"{target_date}T00:00:00").replace(tzinfo=CITY_TZ)
        rows.append(
            {
                "ticker": market["ticker"],
                "target_date": target_date,
                "open_time": datetime.fromisoformat(str(market["open_time"]).replace("Z", "+00:00")),
                "t9": target_day.replace(hour=9, minute=0).astimezone(UTC),
                "t11": target_day.replace(hour=11, minute=0).astimezone(UTC),
                "t13": target_day.replace(hour=13, minute=0).astimezone(UTC),
                "t15": target_day.replace(hour=15, minute=0).astimezone(UTC),
            }
        )
    return pd.DataFrame(rows)


def fetch_kalshi_prices_from_api(markets: pd.DataFrame) -> pd.DataFrame:
    log("Fetching hourly Kalshi candlesticks from API...")
    rows = []
    tickers = markets["ticker"].dropna().unique().tolist()
    failures: list[str] = []
    for i, ticker in enumerate(tickers, start=1):
        market = markets.loc[markets["ticker"] == ticker].iloc[0]
        start_ts = iso_to_ts(market.get("open_time"))
        end_ts = iso_to_ts(market.get("close_time"))
        if start_ts is None or end_ts is None:
            target_date = str(market["target_date"])
            target_start = datetime.fromisoformat(f"{target_date}T00:00:00").replace(tzinfo=CITY_TZ)
            start_ts = int((target_start - timedelta(days=1, hours=2)).timestamp())
            end_ts = int((target_start + timedelta(days=1)).timestamp())
        params = {
            "start_ts": start_ts,
            "end_ts": end_ts,
            "period_interval": 60,
            "include_latest_before_start": "true",
        }
        raw_candles = []
        try:
            data = request_json(
                f"{KALSHI_BASE}/series/{SERIES_TICKER}/markets/{ticker}/candlesticks",
                params,
            )
            raw_candles = data.get("candlesticks", data.get("candles", []))
        except Exception as exc:
            try:
                data = request_json(
                    f"{KALSHI_BASE}/historical/markets/{ticker}/candlesticks",
                    {k: v for k, v in params.items() if k != "include_latest_before_start"},
                )
                raw_candles = data.get("candlesticks", data.get("candles", []))
            except Exception as hist_exc:
                failures.append(f"{ticker}: live={exc}; historical={hist_exc}")
        candles = []
        for candle in raw_candles:
            ts = candle_time(candle)
            price = candle_yes_price(candle)
            if ts is not None and price is not None:
                candles.append((ts, price))

        target_date = str(market["target_date"])
        target_day = datetime.fromisoformat(f"{target_date}T00:00:00").replace(tzinfo=CITY_TZ)
        row = {"ticker": ticker, "target_date": target_date, "price_source": "kalshi_candlesticks"}
        for label, clock in ENTRY_TIMES.items():
            target_local = None if clock is None else target_day.replace(hour=clock.hour, minute=clock.minute)
            row[f"yes_price_{label}"] = pick_price(candles, target_local)
        rows.append(row)
        if i % 50 == 0:
            log(f"  fetched {i}/{len(tickers)} tickers")
        time.sleep(0.05)
    df = pd.DataFrame(rows)
    df.to_csv(PRICES_CSV, index=False)
    log(f"Saved {len(df)} price rows to {PRICES_CSV}")
    usable = int(df[[col for col in df.columns if col.startswith("yes_price_")]].notna().any(axis=1).sum())
    log(f"Price rows with at least one usable candle: {usable}/{len(df)}")
    if failures:
        log(f"Candlestick failures: {len(failures)} tickers. First 5:")
        for item in failures[:5]:
            log(f"  {item}")
    return df


def fetch_kalshi_prices(markets: pd.DataFrame) -> pd.DataFrame:
    price_cols = ["yes_price_open", "yes_price_9AM", "yes_price_11AM", "yes_price_1PM", "yes_price_3PM"]
    prices = fetch_kalshi_prices_from_api(markets)
    prices.to_csv(PRICES_CSV, index=False)
    usable = int(prices[price_cols].notna().any(axis=1).sum())
    log(f"Saved {len(prices)} price rows to {PRICES_CSV}")
    log(f"Price rows with at least one usable price: {usable}/{len(prices)}")
    return prices


def fetch_iem_actuals() -> pd.DataFrame:
    log(f"Fetching {CITY_CODE} daily max temperatures from IEM...")
    params = {
        "station": IEM_STATION,
        "network": IEM_NETWORK,
        "year1": START_DATE.year,
        "month1": START_DATE.month,
        "day1": START_DATE.day,
        "year2": END_DATE.year,
        "month2": END_DATE.month,
        "day2": END_DATE.day,
        # IEM's daily endpoint uses "vars" or checked boolean params.  A singular
        # "var" silently returns only station/day, so keep this plural.
        "vars": "max_tmpf",
        "what": "download",
    }
    text = request_text(IEM_DAILY_URL, params=params)
    raw = pd.read_csv(io.StringIO(text), comment="#")
    if "max_temp_f" not in raw.columns:
        raise RuntimeError(f"IEM daily response did not include max_temp_f. Columns: {list(raw.columns)}")
    df = raw.rename(columns={"day": "date"})[["date", "max_temp_f"]].copy()
    df["max_temp_f"] = pd.to_numeric(df["max_temp_f"], errors="coerce")
    df = df.dropna(subset=["date", "max_temp_f"])
    df.to_csv(ACTUALS_CSV, index=False)
    log(f"Saved {len(df)} actual temperature rows to {ACTUALS_CSV}")
    return df


def fetch_open_meteo() -> pd.DataFrame:
    log("Fetching historical Open-Meteo model forecasts...")
    params = {
        "latitude": CITY_LAT,
        "longitude": CITY_LON,
        "start_date": START_DATE.isoformat(),
        "end_date": (END_DATE - timedelta(days=1)).isoformat(),
        "daily": "temperature_2m_max",
        # Open-Meteo expects repeated models=params, not a comma-separated string.
        "models": ["gfs_seamless", "ecmwf_ifs025", "ukmo_seamless", "ncep_nbm_conus"],
        "timezone": str(CITY_TZ),
        "temperature_unit": "fahrenheit",
    }
    data = request_json(OPEN_METEO_URL, params=params, timeout=60)
    daily = data.get("daily", {})
    df = pd.DataFrame({"date": daily.get("time", [])})

    def find_column(options: list[str]) -> Optional[list]:
        for key in options:
            if key in daily:
                return daily[key]
        return None

    mapping = {
        "gfs_maxt": ["temperature_2m_max_gfs_seamless", "temperature_2m_max"],
        "ecmwf_maxt": ["temperature_2m_max_ecmwf_ifs025", "temperature_2m_max_ecmwf"],
        "ukmo_maxt": ["temperature_2m_max_ukmo_seamless", "temperature_2m_max_ukmetoffice_seamless"],
        "nbm_maxt": ["temperature_2m_max_ncep_nbm_conus", "temperature_2m_max_nbm_conus"],
    }
    for out_col, options in mapping.items():
        values = find_column(options)
        df[out_col] = values if values is not None else np.nan
    df.to_csv(OPEN_METEO_CSV, index=False)
    log(f"Saved {len(df)} Open-Meteo rows to {OPEN_METEO_CSV}")
    return df


def load_or_fetch(refresh: bool) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    DATA_DIR.mkdir(exist_ok=True)
    def cached(path: Path, required_cols: list[str]) -> Optional[pd.DataFrame]:
        if not path.exists():
            return None
        try:
            df = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            return None
        if df.empty or any(col not in df.columns for col in required_cols):
            return None
        return df

    markets = fetch_kalshi_markets() if refresh else cached(MARKETS_CSV, ["ticker", "target_date"])
    if markets is None:
        markets = fetch_kalshi_markets()
    prices = fetch_kalshi_prices(markets) if refresh else cached(PRICES_CSV, ["ticker", "target_date", "yes_price_11AM"])
    if prices is None:
        prices = fetch_kalshi_prices(markets)
    elif set(prices["ticker"].dropna()) != set(markets["ticker"].dropna()):
        prices = fetch_kalshi_prices(markets)
    actuals = fetch_iem_actuals() if refresh else cached(ACTUALS_CSV, ["date", "max_temp_f"])
    if actuals is None:
        actuals = fetch_iem_actuals()
    models = fetch_open_meteo() if refresh else cached(OPEN_METEO_CSV, ["date", "gfs_maxt", "ecmwf_maxt", "ukmo_maxt", "nbm_maxt"])
    if models is None:
        models = fetch_open_meteo()
    return markets, prices, actuals, models


@dataclass
class BacktestConfig:
    gap_threshold: float = DEFAULT_CORE_GAP_PP
    entry_timing: str = DEFAULT_ENTRY_TIMING
    ensemble_weights: Optional[dict[str, float]] = None
    label: str = "fixed_weights"
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class BacktestEngine:
    def __init__(self, markets: pd.DataFrame, prices: pd.DataFrame, actuals: pd.DataFrame, models: pd.DataFrame):
        self.markets = markets.copy()
        self.prices = prices.copy()
        self.actuals = actuals.copy()
        self.models = models.copy()
        self.dataset = self._build_dataset()

    def _build_dataset(self) -> pd.DataFrame:
        markets = self.markets.copy()
        markets["target_date"] = markets["target_date"].astype(str)
        markets["floor_strike"] = pd.to_numeric(markets["floor_strike"], errors="coerce")
        markets["cap_strike"] = pd.to_numeric(markets["cap_strike"], errors="coerce")
        markets["bracket_type"] = markets.apply(lambda row: bracket_type(row["floor_strike"], row["cap_strike"]), axis=1)
        markets["bracket"] = markets.apply(bracket_label, axis=1)
        markets["kalshi_result_yes"] = markets["settlement_value"].apply(kalshi_result_yes)
        markets["raw_settlement_temp"] = pd.to_numeric(markets.get("raw_settlement_temp"), errors="coerce")
        settlement_by_date = (
            markets.dropna(subset=["raw_settlement_temp"])
            .groupby("target_date")["raw_settlement_temp"]
            .first()
            .rename("kalshi_settlement_temp")
        )
        markets = markets.merge(settlement_by_date, on="target_date", how="left")

        prices = self.prices.copy()
        prices["target_date"] = prices["target_date"].astype(str)
        actuals = self.actuals.rename(columns={"date": "target_date"}).copy()
        actuals["target_date"] = actuals["target_date"].astype(str)
        models = self.models.rename(columns={"date": "target_date"}).copy()
        models["target_date"] = models["target_date"].astype(str)
        for col in MODEL_COLUMNS.values():
            models[col] = pd.to_numeric(models.get(col), errors="coerce")

        df = markets.merge(prices, on=["ticker", "target_date"], how="left")
        df = df.merge(actuals[["target_date", "max_temp_f"]], on="target_date", how="left")
        df = df.merge(models[["target_date", *MODEL_COLUMNS.values()]], on="target_date", how="left")
        df["max_temp_f"] = pd.to_numeric(df["max_temp_f"], errors="coerce")
        df["kalshi_settlement_temp"] = pd.to_numeric(df.get("kalshi_settlement_temp"), errors="coerce")
        return df

    def model_stats(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> pd.DataFrame:
        day_df = self.dataset.drop_duplicates("target_date").dropna(subset=["kalshi_settlement_temp"])
        if start_date:
            day_df = day_df[day_df["target_date"] >= start_date]
        if end_date:
            day_df = day_df[day_df["target_date"] <= end_date]
        rows = []
        for name, col in MODEL_COLUMNS.items():
            valid = day_df.dropna(subset=[col])
            if valid.empty:
                continue
            err = valid[col] - valid["kalshi_settlement_temp"]
            rows.append({"model": name, "mae": float(err.abs().mean()), "bias": float(err.mean())})
        return pd.DataFrame(rows)

    def run(self, cfg: BacktestConfig) -> pd.DataFrame:
        rows = []
        entry_col = f"yes_price_{cfg.entry_timing}"
        weights = normalize_weights(cfg.ensemble_weights or FIXED_ENSEMBLE_WEIGHTS)
        required = [
            entry_col,
            "kalshi_result_yes",
            "gfs_maxt",
            "ecmwf_maxt",
            "ukmo_maxt",
            "nbm_maxt",
        ]
        df = self.dataset.dropna(subset=required).copy()
        if cfg.start_date:
            df = df[df["target_date"] >= cfg.start_date]
        if cfg.end_date:
            df = df[df["target_date"] <= cfg.end_date]
        dist_model = DistributionalTempModel()
        for _, day_group in df.groupby("target_date", sort=True):
            first = day_group.iloc[0]
            gfs = float(first["gfs_maxt"])
            ecmwf = float(first["ecmwf_maxt"])
            ukmo = float(first["ukmo_maxt"])
            nbm = float(first["nbm_maxt"])
            physics_models = np.array([gfs, ecmwf], dtype=float)
            ai_models = np.array([ukmo, nbm], dtype=float)
            physics_mean = float(np.mean(physics_models))
            physics_spread = float(np.std(physics_models))
            ai_mean = float(np.mean(ai_models))
            ai_spread = float(np.std(ai_models))
            consensus = (
                weights["ecmwf"] * ecmwf
                + weights["gfs"] * gfs
                + weights["ukmo"] * ukmo
                + weights["nbm"] * nbm
            )
            brackets = [
                {
                    "ticker": row["ticker"],
                    "lo_f": None if pd.isna(row["floor_strike"]) else float(row["floor_strike"]),
                    "hi_f": None if pd.isna(row["cap_strike"]) else float(row["cap_strike"]),
                    "bracket_type": row["bracket_type"],
                }
                for _, row in day_group.iterrows()
            ]
            coherent_probs = dist_model.bracket_probabilities(consensus, brackets)
            prob_mass = sum(coherent_probs.values())
            assert abs(prob_mass - 1.0) < 0.001, f"Bracket probs sum to {prob_mass}, not 1.0"

            for _, row in day_group.iterrows():
                lo = None if pd.isna(row["floor_strike"]) else float(row["floor_strike"])
                hi = None if pd.isna(row["cap_strike"]) else float(row["cap_strike"])
                btype = str(row["bracket_type"])
                p_yes = float(coherent_probs.get(row["ticker"], np.nan))
                if not np.isfinite(p_yes):
                    continue
                market_price = float(row[entry_col])
                gap_pp = (p_yes - market_price) * 100.0
                gap_abs = abs(gap_pp)
                gate1 = physics_spread < 3.0 and ai_spread < 3.0 and abs(physics_mean - ai_mean) < 2.5
                gate2 = gap_abs > cfg.gap_threshold and not (35.0 <= gap_abs <= 40.0)
                gate3 = 0.25 <= market_price <= 0.75
                actual_temp = float(row["max_temp_f"]) if not pd.isna(row.get("max_temp_f")) else np.nan
                kalshi_settlement_temp = (
                    float(row["kalshi_settlement_temp"]) if not pd.isna(row.get("kalshi_settlement_temp")) else np.nan
                )
                bracket_yes = bool(row["kalshi_result_yes"])
                reconstructed_yes = (
                    resolved_yes(actual_temp, lo, hi, btype) if np.isfinite(actual_temp) else None
                )
                settlement_mismatch = (
                    reconstructed_yes is not None
                    and bool(reconstructed_yes) != bracket_yes
                )

                if gate1 and gate2 and gate3:
                    direction = "YES" if gap_pp > 0 else "NO"
                    entry_price = market_price if direction == "YES" else 1.0 - market_price
                    confidence = self._confidence_score(
                        gap_abs,
                        entry_price,
                        physics_spread,
                        ai_spread,
                        abs(physics_mean - ai_mean),
                        btype,
                    )
                    self._append_trade(
                        rows,
                        row,
                        "CORE",
                        direction,
                        entry_price,
                        cfg.entry_timing,
                        confidence,
                        gap_pp,
                        p_yes,
                        bracket_yes,
                        reconstructed_yes,
                        settlement_mismatch,
                        actual_temp,
                        kalshi_settlement_temp,
                        consensus,
                        physics_mean,
                        physics_spread,
                        ai_mean,
                        ai_spread,
                        weights,
                        cfg.label,
                    )

                yes_bid_proxy = max(0.0, market_price - 0.02)
                no_entry = min(1.0, max(0.0, 1.0 - yes_bid_proxy))
                sleeve_confidence = self._confidence_score(
                    gap_abs,
                    no_entry,
                    physics_spread,
                    ai_spread,
                    abs(physics_mean - ai_mean),
                    btype,
                )
                if p_yes < TAIL_NO_PROB_MAX and market_price > TAIL_NO_YES_PRICE_MIN:
                    self._append_trade(
                        rows,
                        row,
                        "TAIL_NO",
                        "NO",
                        no_entry,
                        cfg.entry_timing,
                        sleeve_confidence,
                        gap_pp,
                        p_yes,
                        bracket_yes,
                        reconstructed_yes,
                        settlement_mismatch,
                        actual_temp,
                        kalshi_settlement_temp,
                        consensus,
                        physics_mean,
                        physics_spread,
                        ai_mean,
                        ai_spread,
                        weights,
                        cfg.label,
                    )
                if p_yes < DEEP_TAIL_NO_PROB_MAX and market_price > DEEP_TAIL_NO_YES_PRICE_MIN:
                    self._append_trade(
                        rows,
                        row,
                        "DEEP_TAIL_NO",
                        "NO",
                        no_entry,
                        cfg.entry_timing,
                        sleeve_confidence,
                        gap_pp,
                        p_yes,
                        bracket_yes,
                        reconstructed_yes,
                        settlement_mismatch,
                        actual_temp,
                        kalshi_settlement_temp,
                        consensus,
                        physics_mean,
                        physics_spread,
                        ai_mean,
                        ai_spread,
                        weights,
                        cfg.label,
                    )
        return pd.DataFrame(rows)

    @staticmethod
    def _confidence_score(
        gap_abs: float,
        entry_price: float,
        physics_spread: float,
        ai_spread: float,
        spread_between: float,
        btype: str,
    ) -> float:
        edge_score = min(40.0, max(0.0, (gap_abs - 10.0) / 30.0 * 40.0))
        agreement_score = min(25.0, max(0.0, (2.5 - spread_between) / 2.5 * 25.0))
        spread_score = min(20.0, max(0.0, (3.0 - ((physics_spread + ai_spread) / 2.0)) / 3.0 * 20.0))
        price_score = 10.0 if entry_price < 0.40 or entry_price > 0.60 else 0.0
        bracket_score = 5.0 if btype != "central" else 0.0
        return round(float(min(100.0, edge_score + agreement_score + spread_score + price_score + bracket_score)), 2)

    @staticmethod
    def _append_trade(
        rows: list[dict],
        row: pd.Series,
        sleeve: str,
        direction: str,
        entry_price: float,
        entry_timing: str,
        confidence: float,
        gap_pp: float,
        model_prob: float,
        bracket_yes: bool,
        reconstructed_yes: Optional[bool],
        settlement_mismatch: bool,
        actual_temp: float,
        kalshi_settlement_temp: float,
        consensus: float,
        physics_mean: float,
        physics_spread: float,
        ai_mean: float,
        ai_spread: float,
        weights: dict[str, float],
        model_weight_source: str,
    ) -> None:
        win = (direction == "YES" and bracket_yes) or (direction == "NO" and not bracket_yes)
        gross = (1.0 - entry_price) if win else -entry_price
        fee = kalshi_fee(entry_price)
        net = gross - fee
        rows.append(
            {
                "date": row["target_date"],
                "ticker": row["ticker"],
                "bracket": row["bracket"],
                "bracket_type": row["bracket_type"],
                "sleeve": sleeve,
                "gap_pp": gap_pp,
                "direction": direction,
                "entry_price": entry_price,
                "entry_timing": entry_timing,
                "confidence": confidence,
                "model_prob": model_prob,
                "kalshi_result_yes": bracket_yes,
                "reconstructed_result_yes": reconstructed_yes,
                "settlement_mismatch": settlement_mismatch,
                "consensus": consensus,
                "model_weight_source": model_weight_source,
                "weight_gfs": weights["gfs"],
                "weight_ecmwf": weights["ecmwf"],
                "weight_ukmo": weights["ukmo"],
                "weight_nbm": weights["nbm"],
                "physics_mean": physics_mean,
                "physics_spread": physics_spread,
                "ai_mean": ai_mean,
                "ai_spread": ai_spread,
                "win": bool(win),
                "gross": gross,
                "fee": fee,
                "net": net,
                "actual_temp": actual_temp,
                "settlement_temp": kalshi_settlement_temp,
                "month": str(row["target_date"])[:7],
            }
        )


def sensitivity(engine: BacktestEngine) -> dict:
    rows = {}
    for threshold in [10, 15, 20, 25, 30]:
        trades = engine.run(BacktestConfig(gap_threshold=float(threshold), entry_timing=DEFAULT_ENTRY_TIMING))
        core = trades[trades["sleeve"] == "CORE"] if not trades.empty else trades
        rows[f"gap_gt_{threshold}pp"] = summarize_trades(core)
    return rows


def timing_comparison(engine: BacktestEngine) -> dict:
    rows = {}
    for timing in ["9AM", "11AM", "1PM", "3PM"]:
        trades = engine.run(BacktestConfig(gap_threshold=DEFAULT_CORE_GAP_PP, entry_timing=timing))
        core = trades[trades["sleeve"] == "CORE"] if not trades.empty else trades
        rows[timing] = summarize_trades(core)
    return rows


def monthly_breakdown(core: pd.DataFrame) -> dict:
    out = {}
    if core.empty:
        return out
    for month, group in core.groupby("month"):
        out[month] = summarize_trades(group)
    return out


def confidence_breakdown(core: pd.DataFrame) -> dict:
    if core.empty:
        return {
            "top_decile": summarize_trades(core),
            "top_quartile": summarize_trades(core),
            "middle_50pct": summarize_trades(core),
            "bottom_quartile": summarize_trades(core),
        }
    q10 = core["confidence"].quantile(0.90)
    q75 = core["confidence"].quantile(0.75)
    q25 = core["confidence"].quantile(0.25)
    bands = {
        "top_decile": core[core["confidence"] >= q10],
        "top_quartile": core[core["confidence"] >= q75],
        "middle_50pct": core[(core["confidence"] > q25) & (core["confidence"] < q75)],
        "bottom_quartile": core[core["confidence"] <= q25],
    }
    return {name: summarize_trades(group) for name, group in bands.items()}


def entry_price_breakdown(core: pd.DataFrame) -> dict:
    if core.empty:
        return {}
    bins = [0.0, 0.25, 0.40, 0.50, 0.60, 0.75, 1.0]
    labels = ["0.00-0.25", "0.25-0.40", "0.40-0.50", "0.50-0.60", "0.60-0.75", "0.75-1.00"]
    work = core.copy()
    work["entry_bucket"] = pd.cut(work["entry_price"], bins=bins, labels=labels, include_lowest=True, right=False)
    return {str(bucket): summarize_trades(group) for bucket, group in work.groupby("entry_bucket", observed=True)}


def inverse_mae_weights(model_stats: pd.DataFrame) -> dict:
    if model_stats.empty:
        return {}
    stats = model_stats.copy()
    stats["inv_mae"] = 1.0 / stats["mae"].replace(0, np.nan)
    total = stats["inv_mae"].sum()
    if not np.isfinite(total) or total <= 0:
        return {}
    return {str(row["model"]): float(row["inv_mae"] / total) for _, row in stats.iterrows()}


def settlement_audit(engine: BacktestEngine, trades: pd.DataFrame) -> dict:
    dataset = engine.dataset.copy()
    usable = dataset.dropna(subset=["kalshi_result_yes"])
    recon_mask = usable["max_temp_f"].notna()
    reconstructable = usable[recon_mask].copy()
    if not reconstructable.empty:
        reconstructed = []
        for _, row in reconstructable.iterrows():
            lo = None if pd.isna(row["floor_strike"]) else float(row["floor_strike"])
            hi = None if pd.isna(row["cap_strike"]) else float(row["cap_strike"])
            reconstructed.append(resolved_yes(float(row["max_temp_f"]), lo, hi, str(row["bracket_type"])))
        reconstructable["reconstructed_result_yes"] = reconstructed
        market_mismatches = int((reconstructable["reconstructed_result_yes"] != reconstructable["kalshi_result_yes"]).sum())
    else:
        market_mismatches = 0
    return {
        "pnl_source": "kalshi_result_yes",
        "temperature_source_for_model_error_only": "IEM NYC max_tmpf",
        "total_market_rows": int(len(dataset)),
        "market_rows_with_kalshi_result": int(dataset["kalshi_result_yes"].notna().sum()),
        "market_rows_with_iem_temp": int(dataset["max_temp_f"].notna().sum()),
        "market_rows_reconstructable_from_iem": int(len(reconstructable)),
        "market_rows_iem_vs_kalshi_mismatch": market_mismatches,
        "trade_rows": int(len(trades)),
        "trade_rows_iem_vs_kalshi_mismatch": int(trades["settlement_mismatch"].sum()) if not trades.empty else 0,
        "trade_rows_missing_iem_temp": int(trades["actual_temp"].isna().sum()) if not trades.empty else 0,
        "audit_note": "Trade win/loss and P&L use Kalshi result labels; IEM reconstruction is diagnostic only.",
    }


def recompute_trade_pnl(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy()
    wins = ((out["direction"] == "YES") & out["kalshi_result_yes"]) | (
        (out["direction"] == "NO") & ~out["kalshi_result_yes"]
    )
    out["win"] = wins.astype(bool)
    out["gross"] = np.where(out["win"], 1.0 - out["entry_price"], -out["entry_price"])
    out["fee"] = out["entry_price"].apply(kalshi_fee)
    out["net"] = out["gross"] - out["fee"]
    return out


def stress_fill_realism(trades: pd.DataFrame) -> dict:
    deep = trades[trades["sleeve"] == "DEEP_TAIL_NO"].copy() if not trades.empty else trades.copy()
    if deep.empty:
        empty = summarize_trades(deep)
        return {
            "baseline": empty,
            "extra_1c_entry_cost": empty,
            "extra_3c_entry_cost": empty,
            "extra_5c_entry_cost": empty,
            "miss_best_10pct_plus_3c": empty,
            "note": "No DEEP_TAIL_NO trades available for stress testing.",
        }

    def with_extra_cost(extra: float, source: pd.DataFrame = deep) -> pd.DataFrame:
        stressed = source.copy()
        stressed["entry_price"] = (stressed["entry_price"] + extra).clip(upper=0.99)
        return recompute_trade_pnl(stressed)

    # Missed-fill stress: assume the best 10% of model-edge opportunities do not
    # fill, then apply an additional 3c worse entry to the remaining fills.
    no_edge = (1.0 - deep["model_prob"]) - deep["entry_price"]
    cutoff = no_edge.quantile(0.90)
    missed_best = deep[no_edge < cutoff].copy()
    return {
        "baseline": summarize_trades(deep),
        "extra_1c_entry_cost": summarize_trades(with_extra_cost(0.01)),
        "extra_3c_entry_cost": summarize_trades(with_extra_cost(0.03)),
        "extra_5c_entry_cost": summarize_trades(with_extra_cost(0.05)),
        "miss_best_10pct_plus_3c": summarize_trades(with_extra_cost(0.03, missed_best)),
        "note": "Stress tests worsen DEEP_TAIL_NO entry cost and simulate missing the highest-edge 10% of fills.",
    }


def _fill_bracket_type(value: Any) -> str:
    text = str(value)
    if text == "central":
        return "central"
    if text == "wing_low":
        return "lower_tail"
    if text == "wing_high":
        return "upper_tail"
    return text


def apply_fill_scenario(trades: pd.DataFrame, scenario: str) -> pd.DataFrame:
    """Return a copy of trades with `net` recomputed for a fill scenario."""
    if trades.empty:
        return trades.copy()
    out = trades.copy()
    out["contracts"] = 1
    if scenario == "optimistic":
        out["fill_scenario"] = "optimistic"
        return out

    fill_prices = []
    fees = []
    fill_probs = []
    for _, row in out.iterrows():
        fill = simulate_fill(
            float(row["entry_price"]),
            _fill_bracket_type(row["bracket_type"]),
            str(row["direction"]),
            "maker",
            contracts=1,
        )
        fill_prices.append(fill["fill_price"])
        fees.append(fill["fee"])
        fill_probs.append(fill["fill_probability"])
    out["entry_price"] = fill_prices
    out["fee"] = fees
    out["fill_probability"] = fill_probs
    out["gross"] = np.where(out["win"], 1.0 - out["entry_price"], -out["entry_price"])
    out["net"] = out["gross"] - out["fee"]
    out["fill_scenario"] = "realistic_maker"

    if scenario == "stress_3c":
        stress_input = out.rename(columns={"net": "net_pnl"})
        stressed = stress_test_fills(stress_input, extra_cents=3.0)
        out["entry_price"] = stressed["entry_price_stressed"]
        out["net"] = stressed["net_pnl_stressed"]
        out["gross"] = out["net"] + out["fee"]
        out["fill_scenario"] = "stress_plus_3c"
    return out


def fill_scenario_summary(trades: pd.DataFrame) -> dict:
    scenarios = {
        "optimistic": apply_fill_scenario(trades, "optimistic"),
        "realistic": apply_fill_scenario(trades, "realistic"),
        "stress_plus_3c": apply_fill_scenario(trades, "stress_3c"),
    }
    return {
        name: {
            "overall": summarize_trades(frame),
            "by_sleeve": {
                sleeve: summarize_trades(frame[frame["sleeve"] == sleeve])
                for sleeve in ["CORE", "TAIL_NO", "DEEP_TAIL_NO"]
            },
        }
        for name, frame in scenarios.items()
    }


def vintage_filter_summary(engine: BacktestEngine) -> dict:
    return {
        "rows_dropped_due_to_vintage_violations": 0,
        "rows_checked": int(len(engine.dataset)),
        "status": "not_enforced_daily_cache_no_cycle_timestamps",
        "note": VINTAGE_FILTER_NOTE,
    }


def reproducibility_footer(trades: pd.DataFrame) -> dict:
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            cwd=ROOT,
        ).decode().strip()
    except Exception:
        git_sha = "unknown"
    cfg_hash = hashlib.md5((ROOT / "config.py").read_bytes()).hexdigest()[:8]
    return {
        "generated_at": datetime.now().strftime("%Y%m%d_%H%M"),
        "git_sha": git_sha,
        "config_hash": cfg_hash,
        "run_id": f"{datetime.now():%Y%m%d_%H%M}_{git_sha}_{cfg_hash}",
        "rows": int(len(trades)),
        "date_min": str(trades["date"].min()) if not trades.empty else None,
        "date_max": str(trades["date"].max()) if not trades.empty else None,
    }


def walk_forward_validation(engine: BacktestEngine, gap_threshold: float = DEFAULT_CORE_GAP_PP, min_train_months: int = 3) -> dict:
    months = sorted(engine.dataset["target_date"].dropna().astype(str).str[:7].unique())
    rows = []
    all_test_trades = []
    for index, month in enumerate(months):
        if index < min_train_months:
            continue
        month_start = f"{month}-01"
        month_end = (pd.Timestamp(month_start) + pd.offsets.MonthEnd(0)).date().isoformat()
        train_stats = engine.model_stats(end_date=(pd.Timestamp(month_start) - pd.Timedelta(days=1)).date().isoformat())
        weights = inverse_mae_weights(train_stats)
        if not weights or set(weights) != set(MODEL_COLUMNS):
            continue
        trades = engine.run(
            BacktestConfig(
                gap_threshold=gap_threshold,
                entry_timing=DEFAULT_ENTRY_TIMING,
                ensemble_weights=weights,
                label="walk_forward_inverse_mae",
                start_date=month_start,
                end_date=month_end,
            )
        )
        core = trades[trades["sleeve"] == "CORE"] if not trades.empty else trades
        summary = summarize_trades(core)
        rows.append(
            {
                "month": month,
                "train_months": index,
                "weights": weights,
                **summary,
            }
        )
        if not core.empty:
            all_test_trades.append(core)
    combined = pd.concat(all_test_trades, ignore_index=True) if all_test_trades else pd.DataFrame()
    return {
        "method": "expanding-window inverse-MAE weights; train on prior months, test on next month",
        "gap_threshold_pp": float(gap_threshold),
        "min_train_months": min_train_months,
        "overall": summarize_trades(combined),
        "months": rows,
    }


def threshold_bakeoff(engine: BacktestEngine) -> dict:
    out = {}
    for threshold in THRESHOLD_BAKEOFF_GAPS:
        trades = engine.run(
            BacktestConfig(
                gap_threshold=float(threshold),
                entry_timing=DEFAULT_ENTRY_TIMING,
                label=f"threshold_{threshold}pp",
            )
        )
        core = trades[trades["sleeve"] == "CORE"] if not trades.empty else trades
        deep = trades[trades["sleeve"] == "DEEP_TAIL_NO"] if not trades.empty else trades
        stress = stress_fill_realism(trades)["extra_3c_entry_cost"]
        out[f"{threshold}pp"] = {
            "core": summarize_trades(core),
            "deep_tail_no": summarize_trades(deep),
            "deep_tail_no_stress_3c": stress,
            "walk_forward": walk_forward_validation(engine, gap_threshold=float(threshold))["overall"],
        }
    return out


def probability_rows(engine: BacktestEngine) -> pd.DataFrame:
    rows = []
    weights = normalize_weights(FIXED_ENSEMBLE_WEIGHTS)
    required = ["kalshi_result_yes", "gfs_maxt", "ecmwf_maxt", "ukmo_maxt", "nbm_maxt"]
    df = engine.dataset.dropna(subset=required).copy()
    model = DistributionalTempModel()

    for date_value, group in df.groupby("target_date", sort=True):
        first = group.iloc[0]
        consensus = (
            weights["ecmwf"] * float(first["ecmwf_maxt"])
            + weights["gfs"] * float(first["gfs_maxt"])
            + weights["ukmo"] * float(first["ukmo_maxt"])
            + weights["nbm"] * float(first["nbm_maxt"])
        )
        brackets = []
        for _, row in group.iterrows():
            brackets.append(
                {
                    "ticker": row["ticker"],
                    "lo_f": None if pd.isna(row["floor_strike"]) else float(row["floor_strike"]),
                    "hi_f": None if pd.isna(row["cap_strike"]) else float(row["cap_strike"]),
                    "bracket_type": row["bracket_type"],
                }
            )
        coherent = model.bracket_probabilities(consensus, brackets)
        for _, row in group.iterrows():
            lo = None if pd.isna(row["floor_strike"]) else float(row["floor_strike"])
            hi = None if pd.isna(row["cap_strike"]) else float(row["cap_strike"])
            btype = str(row["bracket_type"])
            rows.append(
                {
                    "date": str(date_value),
                    "ticker": row["ticker"],
                    "bracket_type": btype,
                    "outcome": int(bool(row["kalshi_result_yes"])),
                    "old_probability": gumbel_prob(lo, hi, btype, consensus),
                    "coherent_probability": coherent.get(row["ticker"], np.nan),
                }
            )

    return pd.DataFrame(rows).dropna()


def probability_evaluation(engine: BacktestEngine) -> dict:
    prob_df = probability_rows(engine)
    if prob_df.empty:
        return {}
    model = DistributionalTempModel()
    dates = sorted(prob_df["date"].unique())
    split = max(1, len(dates) // 2)
    train_dates = set(dates[:split])
    holdout_dates = set(dates[split:])
    train = prob_df[prob_df["date"].isin(train_dates)]
    holdout = prob_df[prob_df["date"].isin(holdout_dates)].copy()

    cal_model = DistributionalTempModel()
    fitted = cal_model.fit_calibrator(train["coherent_probability"].tolist(), train["outcome"].tolist())
    calibrated_frames = []
    for date_value, group in holdout.groupby("date", sort=True):
        raw = dict(zip(group["ticker"], group["coherent_probability"]))
        calibrated = cal_model.calibrated_probabilities(raw)
        out = group[["date", "ticker", "bracket_type", "outcome"]].copy()
        out["calibrated_probability"] = out["ticker"].map(calibrated)
        calibrated_frames.append(out)
    calibrated_holdout = pd.concat(calibrated_frames, ignore_index=True) if calibrated_frames else pd.DataFrame()

    actual_all = prob_df[["date", "ticker", "bracket_type", "outcome"]]
    actual_holdout = holdout[["date", "ticker", "bracket_type", "outcome"]]
    return {
        "old_all": _evaluate_probability_frame(model, prob_df, "old_probability", actual_all),
        "coherent_raw_all": _evaluate_probability_frame(model, prob_df, "coherent_probability", actual_all),
        "old_holdout": _evaluate_probability_frame(model, holdout, "old_probability", actual_holdout),
        "coherent_raw_holdout": _evaluate_probability_frame(model, holdout, "coherent_probability", actual_holdout),
        "coherent_calibrated_holdout": _evaluate_probability_frame(
            model,
            calibrated_holdout,
            "calibrated_probability",
            calibrated_holdout[["date", "ticker", "bracket_type", "outcome"]] if not calibrated_holdout.empty else actual_holdout,
        ),
        "calibrator_fitted": fitted,
        "train_days": len(train_dates),
        "holdout_days": len(holdout_dates),
    }


def _evaluate_probability_frame(model: DistributionalTempModel, frame: pd.DataFrame, probability_col: str, actual: pd.DataFrame) -> dict:
    predicted = frame[["date", "ticker", "bracket_type", probability_col]].rename(columns={probability_col: "probability"})
    return model.evaluate(predicted, actual)


def bracket_family(value: Any) -> str:
    return "central" if str(value) == "central" else "wing"


def _empty_regime_slice() -> dict:
    return {
        "trades": 0,
        "win_rate": 0.0,
        "net_pnl": 0.0,
        "sharpe": 0.0,
        "brier_score": 0.0,
        "log_loss": 0.0,
        "prob_rows": 0,
        "prob_days": 0,
    }


def _regime_slice_summary(trades: pd.DataFrame, probs: pd.DataFrame) -> dict:
    if trades.empty and probs.empty:
        return _empty_regime_slice()
    trade_summary = summarize_trades(trades)
    if probs.empty:
        prob_summary = _empty_regime_slice()
    else:
        model = DistributionalTempModel()
        actual = probs[["date", "ticker", "bracket_type", "outcome"]]
        prob_summary = _evaluate_probability_frame(model, probs, "coherent_probability", actual)
    return {
        "trades": trade_summary["trades"],
        "win_rate": trade_summary["win_rate"],
        "net_pnl": trade_summary["net_pnl"],
        "sharpe": trade_summary["sharpe"],
        "brier_score": prob_summary["brier_score"],
        "log_loss": prob_summary["log_loss"],
        "prob_rows": prob_summary.get("n_rows", 0),
        "prob_days": prob_summary.get("n_days", 0),
    }


def regime_report(engine: BacktestEngine, trades: pd.DataFrame) -> list[dict]:
    core = trades[trades["sleeve"] == "CORE"].copy() if not trades.empty else trades.copy()
    probs = probability_rows(engine)
    if not probs.empty:
        probs["family"] = probs["bracket_type"].map(bracket_family)
    if not core.empty:
        core["family"] = core["bracket_type"].map(bracket_family)

    rows = []
    for label, start, end in REGIME_PERIODS:
        period_trades = core[(core["date"] >= start) & (core["date"] <= end)] if not core.empty else core
        period_probs = probs[(probs["date"] >= start) & (probs["date"] <= end)] if not probs.empty else probs
        rows.append(
            {
                "label": label,
                "start": start,
                "end": end,
                "overall": _regime_slice_summary(period_trades, period_probs),
                "central": _regime_slice_summary(
                    period_trades[period_trades["family"] == "central"] if not period_trades.empty else period_trades,
                    period_probs[period_probs["family"] == "central"] if not period_probs.empty else period_probs,
                ),
                "wing": _regime_slice_summary(
                    period_trades[period_trades["family"] == "wing"] if not period_trades.empty else period_trades,
                    period_probs[period_probs["family"] == "wing"] if not period_probs.empty else period_probs,
                ),
            }
        )
    return rows


def seasonal_multipliers(monthly: dict) -> dict:
    if not monthly:
        return {}
    pnls = {month: item["net_pnl"] for month, item in monthly.items() if item["trades"] > 0}
    positive = [value for value in pnls.values() if value > 0]
    baseline = float(np.median(positive)) if positive else 1.0
    out = {}
    for month, pnl in pnls.items():
        raw = pnl / baseline if baseline else 1.0
        out[month] = round(float(min(max(raw, 0.25), 2.0)), 2)
    return out


def print_summary(summary: dict) -> None:
    core = summary["core"]
    print("\n=== BACKTEST RESULTS: Oct 2024 - Apr 2026 ===\n")
    print("METHODOLOGY:")
    print("  Settlement/P&L source: Kalshi market result field")
    print(f"  IEM {CITY_CODE} temperatures: diagnostics/model-error analysis only")
    print("  Forecast vintage warning: Open-Meteo file has one daily row, so timing tests reuse same forecast values")
    print(
        "  Rows dropped due to vintage violations: "
        f"{summary['vintage_filter']['rows_dropped_due_to_vintage_violations']} "
        f"({summary['vintage_filter']['status']})"
    )
    print(f"  Baseline run: gap > {summary['baseline']['gap_threshold_pp']}pp, entry {summary['baseline']['entry_timing']}")
    print(f"  Model weights traded: {summary['baseline']['ensemble_weights']}")
    print(f"  TAIL_NO rule: P_yes < {TAIL_NO_PROB_MAX:.2f} and YES price > {TAIL_NO_YES_PRICE_MIN:.2f}")
    print(f"  DEEP_TAIL_NO rule: P_yes < {DEEP_TAIL_NO_PROB_MAX:.2f} and YES price > {DEEP_TAIL_NO_YES_PRICE_MIN:.2f}")
    print("CORE STRATEGY (Gumbel + Tiered Gates):")
    print(f"  Total days analyzed: {summary['total_days_analyzed']}")
    print(f"  Trading days (signals generated): {summary['trading_days']}")
    print(f"  Total trades: {core['trades']}")
    print(f"  Win rate: {core['win_rate']:.1%}")
    print(f"  Net P&L ($1/trade): ${core['net_pnl']:.2f}")
    print(f"  Sharpe ratio: {core['sharpe']:.2f}")
    print(f"  Max drawdown: ${core['max_drawdown']:.2f}")

    print("\nSENSITIVITY: Gap threshold")
    for threshold in [10, 15, 20, 25, 30]:
        item = summary["sensitivity"][f"gap_gt_{threshold}pp"]
        suffix = "  <- baseline threshold" if threshold == summary["baseline"]["gap_threshold_pp"] else ""
        print(f"  Gap > {threshold}pp: win rate {item['win_rate']:.1%}, P&L ${item['net_pnl']:.2f}{suffix}")

    print("\nTHRESHOLD BAKEOFF (settlement-audited):")
    print("  Threshold | Core trades | Core win | Core P&L | WF P&L | DEEP +3c stress")
    for label, item in summary["threshold_bakeoff"].items():
        core_item = item["core"]
        wf_item = item["walk_forward"]
        stress_item = item["deep_tail_no_stress_3c"]
        print(
            f"  {label:>9} | {core_item['trades']:>11} | {core_item['win_rate']:>8.1%} | "
            f"${core_item['net_pnl']:>7.2f} | ${wf_item['net_pnl']:>6.2f} | ${stress_item['net_pnl']:>14.2f}"
        )

    print("\nENTRY TIMING comparison:")
    for timing in ["9AM", "11AM", "1PM", "3PM"]:
        item = summary["entry_timing"][timing]
        suffix = "  <- baseline timing" if timing == summary["baseline"]["entry_timing"] else ""
        print(f"  {timing} entry: win rate {item['win_rate']:.1%}, P&L ${item['net_pnl']:.2f}{suffix}")

    print("\nSEASONAL breakdown:")
    for month, item in summary["seasonal"].items():
        print(f"  {month}: {item['trades']} trades, win rate {item['win_rate']:.1%}, P&L ${item['net_pnl']:.2f}")

    print("\nCONFIDENCE SCORE validation:")
    labels = {
        "top_decile": "Top decile",
        "top_quartile": "Top quartile",
        "middle_50pct": "Middle 50%",
        "bottom_quartile": "Bottom quartile",
    }
    for key, label in labels.items():
        item = summary["confidence"][key]
        print(f"  {label}: {item['trades']} trades, win rate {item['win_rate']:.1%}")

    print("\nENTRY PRICE BUCKETS (core):")
    for bucket, item in summary["entry_price_buckets"].items():
        print(f"  {bucket}: {item['trades']} trades, win rate {item['win_rate']:.1%}, P&L ${item['net_pnl']:.2f}")

    print(f"\nMODEL ACCURACY for {CITY_CODE}:")
    for item in summary["model_accuracy"]:
        print(f"  {item['model'].upper()} MAE: {item['mae']:.1f}°F, Bias: {item['bias']:.1f}°F")
    print(f"  Best model for {CITY_CODE}: {summary['best_model']}")

    print("\nSLEEVE RESULTS:")
    for sleeve in ["TAIL_NO", "DEEP_TAIL_NO"]:
        item = summary["sleeves"][sleeve]
        print(
            f"  {sleeve}: {item['trades']} trades, win rate {item['win_rate']:.1%}, "
            f"avg return {item['avg_return']:.1%}, P&L ${item['net_pnl']:.2f}"
        )

    print("\nOPTIMAL PARAMETERS (from backtest):")
    print(f"  Best gap threshold: {summary['optimal']['best_gap_threshold_pp']}pp")
    print(f"  Best entry timing: {summary['optimal']['best_entry_timing']}")
    print(f"  Best seasonal multipliers: {summary['optimal']['seasonal_kelly_multiplier']}")
    print(f"  Model weights (by MAE inverse): {summary['optimal']['ensemble_weights']}")
    print("\nMODEL WEIGHT COMPARISON:")
    for name, item in summary["weight_comparison"].items():
        print(f"  {name}: {item['trades']} trades, win rate {item['win_rate']:.1%}, P&L ${item['net_pnl']:.2f}")
    print("\nPROBABILITY MODEL EVALUATION:")
    prob_eval = summary["probability_evaluation"]
    print(f"  Calibration fitted: {prob_eval['calibrator_fitted']} (train days={prob_eval['train_days']}, holdout days={prob_eval['holdout_days']})")
    for name in ["old_holdout", "coherent_raw_holdout", "coherent_calibrated_holdout"]:
        item = prob_eval[name]
        print(
            f"  {name}: Brier {item['brier_score']:.4f}, log loss {item['log_loss']:.4f}, "
            f"mass avg {item['prob_mass_check']:.4f}"
        )
    mass = prob_eval["coherent_raw_all"]
    print(
        f"  Bracket probability mass check: avg {mass['prob_mass_check']:.4f}, "
        f"min {mass['prob_mass_min']:.4f}, max {mass['prob_mass_max']:.4f}"
    )
    print("  Central vs wing (coherent calibrated holdout):")
    for group, item in prob_eval["coherent_calibrated_holdout"]["central_vs_wing"].items():
        print(f"    {group}: rows {item['rows']}, Brier {item['brier_score']:.4f}, log loss {item['log_loss']:.4f}")
    print("\nREGIME REPORT (CORE trades + coherent raw probabilities):")
    print("  Period                 | Slice   | Trades | Win    | P&L     | Sharpe | Brier  | LogLoss")
    for period in summary["regime_report"]:
        date_range = f"{period['start']}..{period['end']}"
        print(f"  {period['label']} ({date_range})")
        for slice_name in ["overall", "central", "wing"]:
            item = period[slice_name]
            print(
                f"    {'':19} | {slice_name:7} | {item['trades']:>6} | {item['win_rate']:>6.1%} | "
                f"${item['net_pnl']:>7.2f} | {item['sharpe']:>6.2f} | {item['brier_score']:>6.4f} | {item['log_loss']:>7.4f}"
            )
    wf = summary["walk_forward"]
    print("\nWALK-FORWARD VALIDATION:")
    print(f"  Method: {wf['method']}")
    print(
        f"  Overall: {wf['overall']['trades']} trades, win rate {wf['overall']['win_rate']:.1%}, "
        f"P&L ${wf['overall']['net_pnl']:.2f}, Sharpe {wf['overall']['sharpe']:.2f}"
    )
    for row in wf["months"]:
        print(f"  {row['month']}: {row['trades']} trades, win rate {row['win_rate']:.1%}, P&L ${row['net_pnl']:.2f}")
    print("\nDEEP_TAIL_NO FILL STRESS:")
    for name, item in summary["fill_stress"]["DEEP_TAIL_NO"].items():
        if not isinstance(item, dict):
            continue
        print(f"  {name}: {item['trades']} trades, win rate {item['win_rate']:.1%}, P&L ${item['net_pnl']:.2f}")
    print("\nTHREE-TIER FILL P&L:")
    print("  Scenario      | Win Rate | Net P&L | Sharpe")
    for scenario, item in summary["fill_scenarios"].items():
        overall = item["overall"]
        print(
            f"  {scenario:13} | {overall['win_rate']:>8.1%} | "
            f"${overall['net_pnl']:>7.2f} | {overall['sharpe']:>6.2f}"
        )
    print("\nSLEEVE COMPARISON BY FILL SCENARIO:")
    print("  Scenario      | Sleeve       | Trades | Win    | Net P&L | Sharpe")
    for scenario, item in summary["fill_scenarios"].items():
        for sleeve, sleeve_item in item["by_sleeve"].items():
            print(
                f"  {scenario:13} | {sleeve:12} | {sleeve_item['trades']:>6} | "
                f"{sleeve_item['win_rate']:>6.1%} | ${sleeve_item['net_pnl']:>7.2f} | "
                f"{sleeve_item['sharpe']:>6.2f}"
            )
    print("\nSETTLEMENT CROSS-CHECK:")
    audit = summary["settlement_audit"]
    print(f"  P&L source: {audit['pnl_source']}")
    print(f"  Market rows with Kalshi result labels: {audit['market_rows_with_kalshi_result']}/{audit['total_market_rows']}")
    print(f"  Market rows reconstructable from IEM: {audit['market_rows_reconstructable_from_iem']}")
    print(f"  Market-level IEM/Kalshi mismatches: {audit['market_rows_iem_vs_kalshi_mismatch']}")
    print(f"  Trade-level IEM/Kalshi mismatches: {audit['trade_rows_iem_vs_kalshi_mismatch']}")
    print(f"\nSaved full trade-by-trade results to {RESULTS_CSV}")
    print(f"Saved summary to {SUMMARY_JSON}")
    footer = summary["run"]
    print(f"\nRun ID: {footer['run_id']}")
    print(f"Data: {footer['rows']} rows, {footer['date_min']} to {footer['date_max']}")


def build_summary(engine: BacktestEngine, trades: pd.DataFrame) -> dict:
    core = trades[trades["sleeve"] == "CORE"] if not trades.empty else trades
    model_stats = engine.model_stats()
    model_accuracy = model_stats.to_dict(orient="records")
    learned_weights = inverse_mae_weights(model_stats)
    best_model = str(model_stats.sort_values("mae").iloc[0]["model"]).upper() if not model_stats.empty else "N/A"
    sensitivity_rows = sensitivity(engine)
    timing_rows = timing_comparison(engine)
    seasonal = monthly_breakdown(core)
    confidence = confidence_breakdown(core)
    entry_buckets = entry_price_breakdown(core)
    sleeves = {
        "TAIL_NO": summarize_trades(trades[trades["sleeve"] == "TAIL_NO"]) if not trades.empty else summarize_trades(trades),
        "DEEP_TAIL_NO": summarize_trades(trades[trades["sleeve"] == "DEEP_TAIL_NO"]) if not trades.empty else summarize_trades(trades),
    }
    audit = settlement_audit(engine, trades)
    fill_stress = {"DEEP_TAIL_NO": stress_fill_realism(trades)}
    fills = fill_scenario_summary(trades)
    walk_forward = walk_forward_validation(engine)
    bakeoff = threshold_bakeoff(engine)
    prob_eval = probability_evaluation(engine)
    regimes = regime_report(engine, trades)
    learned_trades = engine.run(
        BacktestConfig(
            gap_threshold=DEFAULT_CORE_GAP_PP,
            entry_timing=DEFAULT_ENTRY_TIMING,
            ensemble_weights=learned_weights,
            label="inverse_mae_weights",
        )
    )
    learned_core = learned_trades[learned_trades["sleeve"] == "CORE"] if not learned_trades.empty else learned_trades
    best_gap_key = max(sensitivity_rows, key=lambda key: sensitivity_rows[key]["net_pnl"])
    best_timing = max(timing_rows, key=lambda key: timing_rows[key]["net_pnl"])
    return {
        "period": {"start": START_DATE.isoformat(), "end": END_DATE.isoformat()},
        "baseline": {
            "gap_threshold_pp": int(DEFAULT_CORE_GAP_PP),
            "entry_timing": DEFAULT_ENTRY_TIMING,
            "ensemble_weights": dict(FIXED_ENSEMBLE_WEIGHTS),
        },
        "methodology_notes": [
            "P&L is settled from Kalshi market result, not reconstructed IEM temperature.",
            "Open-Meteo historical dataset is daily-only; entry timing tests reuse the same model forecast values and vary market price only.",
            "Inverse-MAE weights are reported and compared, but fixed strategy weights remain the baseline unless explicitly selected.",
            "Fill scenarios are research-only and do not modify live execution.",
        ],
        "vintage_filter": vintage_filter_summary(engine),
        "total_days_analyzed": int(engine.dataset.dropna(subset=["kalshi_result_yes", *MODEL_COLUMNS.values()])["target_date"].nunique()),
        "trading_days": int(core["date"].nunique()) if not core.empty else 0,
        "core": summarize_trades(core),
        "sensitivity": sensitivity_rows,
        "threshold_bakeoff": bakeoff,
        "entry_timing": timing_rows,
        "seasonal": seasonal,
        "confidence": confidence,
        "entry_price_buckets": entry_buckets,
        "model_accuracy": model_accuracy,
        "best_model": best_model,
        "sleeves": sleeves,
        "weight_comparison": {
            "fixed_weights_baseline": summarize_trades(core),
            "inverse_mae_weights": summarize_trades(learned_core),
        },
        "probability_evaluation": prob_eval,
        "regime_report": regimes,
        "settlement_audit": audit,
        "settlement_mismatches": audit["trade_rows_iem_vs_kalshi_mismatch"],
        "fill_stress": fill_stress,
        "fill_scenarios": fills,
        "walk_forward": walk_forward,
        "run": reproducibility_footer(trades),
        "optimal": {
            "best_gap_threshold_pp": int(best_gap_key.split("_")[-1].replace("pp", "")),
            "best_entry_timing": best_timing,
            "seasonal_kelly_multiplier": seasonal_multipliers(seasonal),
            "ensemble_weights": learned_weights,
        },
    }


def main() -> int:
    global CITY_CODE, SERIES_TICKER, CITY_TZ, CITY_LAT, CITY_LON, IEM_STATION, IEM_NETWORK
    global MARKETS_CSV, PRICES_CSV, ACTUALS_CSV, OPEN_METEO_CSV, RESULTS_CSV, SUMMARY_JSON

    parser = argparse.ArgumentParser(description="Backtest weather high-temp strategy on historical data.")
    parser.add_argument("--city", default="KNYC", help="Station code from config.CITIES (e.g. KNYC, KMDW, KPHL).")
    parser.add_argument("--refresh", action="store_true", help="Re-download all source datasets before running.")
    parser.add_argument("--skip-fetch", action="store_true", help="Use existing CSVs only; fail if any are missing.")
    args = parser.parse_args()

    if args.city not in config.CITIES:
        print(f"Unknown city '{args.city}'. Valid options: {list(config.CITIES.keys())}", file=sys.stderr)
        return 2

    city_cfg = config.CITIES[args.city]
    CITY_CODE = args.city
    SERIES_TICKER = city_cfg["series_ticker"]
    CITY_TZ = ZoneInfo(city_cfg["timezone"])
    CITY_LAT = city_cfg["lat"]
    CITY_LON = city_cfg["lon"]
    IEM_STATION, IEM_NETWORK = IEM_STATION_MAP.get(args.city, (args.city.lstrip("K"), "ASOS"))

    city_lower = args.city.lower()
    series_lower = SERIES_TICKER.lower()
    MARKETS_CSV = DATA_DIR / f"{series_lower}_markets.csv"
    PRICES_CSV = DATA_DIR / f"{series_lower}_prices.csv"
    # KNYC uses legacy filenames without city prefix for backwards-compat
    if args.city == "KNYC":
        ACTUALS_CSV = DATA_DIR / "knyc_actual_temps.csv"
        OPEN_METEO_CSV = DATA_DIR / "open_meteo_historical.csv"
    else:
        ACTUALS_CSV = DATA_DIR / f"{city_lower}_actual_temps.csv"
        OPEN_METEO_CSV = DATA_DIR / f"open_meteo_{city_lower}_historical.csv"
    RESULTS_CSV = DATA_DIR / f"research/{city_lower}_backtest_results.csv"
    SUMMARY_JSON = DATA_DIR / f"research/{city_lower}_backtest_summary.json"
    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)

    missing = [path for path in [MARKETS_CSV, PRICES_CSV, ACTUALS_CSV, OPEN_METEO_CSV] if not path.exists()]
    if args.skip_fetch and missing:
        print("Missing required CSVs:", ", ".join(str(path) for path in missing), file=sys.stderr)
        return 2

    markets, prices, actuals, models = load_or_fetch(refresh=args.refresh and not args.skip_fetch)
    engine = BacktestEngine(markets, prices, actuals, models)
    trades = engine.run(BacktestConfig())
    trades.to_csv(RESULTS_CSV, index=False)
    summary = build_summary(engine, trades)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True))
    print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
