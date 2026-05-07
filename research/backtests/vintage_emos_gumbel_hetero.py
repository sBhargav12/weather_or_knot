#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.models.calibration_models import EMOSGumbelHeteroModel


DATA_DIR = ROOT / "data"
RESEARCH_DIR = DATA_DIR / "research"
REPORTS_DIR = ROOT / "reports"

MARKETS_CSV = DATA_DIR / "kxhighny_markets.csv"
PRICES_CSV = DATA_DIR / "kxhighny_prices.csv"
ACTUALS_CSV = DATA_DIR / "knyc_actual_temps_extended.csv"
ORDERBOOKS_PARQUET = RESEARCH_DIR / "predexon_orderbooks.parquet"
ORDERBOOKS_11AM_PARQUET = RESEARCH_DIR / "predexon_orderbooks_11am.parquet"

VINTAGE_CACHE = RESEARCH_DIR / "knyc_single_run_vintages_11am.csv"
OUT_PREDICTIONS = RESEARCH_DIR / "vintage_emos_gumbel_hetero_predictions.csv"
OUT_TRADES = RESEARCH_DIR / "vintage_emos_gumbel_hetero_trades.csv"
OUT_SUMMARY = RESEARCH_DIR / "vintage_emos_gumbel_hetero_summary.json"
OUT_REPORT = REPORTS_DIR / "vintage_emos_gumbel_hetero_research.md"

SINGLE_RUNS_URL = "https://single-runs-api.open-meteo.com/v1/forecast"
PREDEXON_ORDERBOOKS_URL = "https://api.predexon.com/v2/kalshi/orderbooks"
ET = ZoneInfo("America/New_York")

CITY_LAT = 40.7789
CITY_LON = -73.9692
ENTRY_CLOCK = dtime(11, 0)
TRAIN_CUTOFF = "2026-01-07"
START_DATE = "2024-10-01"
END_DATE = "2026-04-25"

MAKER_FEE_RATE = 0.0175
MIN_GAP_PP = 20.0
DEAD_ZONE_LO = 35.0
DEAD_ZONE_HI = 40.0
MIN_ENTRY_PRICE = 0.25
MAX_ENTRY_PRICE = 0.75

MODEL_SPECS = {
    # Historical fallback model family from AGENTS.md: GFS, ECMWF, ICON, GEM.
    # HGEFS member-level vintages are not available in this repo yet.
    "gfs": {
        "api_model": "gfs_seamless",
        "feature": "gfs_maxt",
        "cycles": (0, 6, 12, 18),
        "delay": timedelta(hours=4, minutes=40),
    },
    "ecmwf": {
        "api_model": "ecmwf_ifs025",
        "feature": "ecmwf_maxt",
        "cycles": (0, 12),
        "delay": timedelta(hours=7),
    },
    "icon": {
        "api_model": "icon_seamless",
        "feature": "icon_maxt",
        "cycles": (0, 6, 12, 18),
        "delay": timedelta(hours=5),
    },
    "gem": {
        "api_model": "gem_seamless",
        "feature": "gem_maxt",
        "cycles": (0, 12),
        "delay": timedelta(hours=6),
    },
}

MODEL_KEYS = ["gfs", "ecmwf", "icon", "gem"]
MODEL_COLS = [MODEL_SPECS[key]["feature"] for key in MODEL_KEYS]
FEATURES = [
    "gfs_maxt",
    "ecmwf_maxt",
    "icon_maxt",
    "gem_maxt",
    "consensus",
    "model_spread",
    "physics_mean",
    "ai_mean",
    "spread_between",
    "month",
    "day_of_year",
]


@dataclass(frozen=True)
class VintageChoice:
    model_key: str
    api_model: str
    cycle_init_utc: datetime
    available_at_utc: datetime


def maker_fee(price: float, contracts: int = 1) -> float:
    return math.ceil(MAKER_FEE_RATE * contracts * price * (1.0 - price) * 100.0) / 100.0


def sharpe(values: Iterable[float]) -> float:
    arr = np.array(list(values), dtype=float)
    if len(arr) < 2:
        return 0.0
    std = float(np.std(arr, ddof=1))
    return 0.0 if std == 0 else float(np.mean(arr) / std)


def max_drawdown(values: Iterable[float]) -> float:
    arr = np.array(list(values), dtype=float)
    if len(arr) == 0:
        return 0.0
    equity = np.cumsum(arr)
    peak = np.maximum.accumulate(equity)
    return float(np.min(equity - peak))


def summarize(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {
            "trades": 0,
            "days": 0,
            "win_rate": 0.0,
            "net_pnl": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "avg_entry_price": 0.0,
        }
    return {
        "trades": int(len(trades)),
        "days": int(trades["date"].nunique()),
        "win_rate": float(trades["win"].mean()),
        "net_pnl": float(trades["net"].sum()),
        "sharpe": sharpe(trades["net"]),
        "max_drawdown": max_drawdown(trades["net"]),
        "avg_entry_price": float(trades["entry_price"].mean()),
    }


def bracket_label(row: pd.Series) -> str:
    if row["bracket_type"] == "wing_low":
        return f"<={row['cap_strike']:g}F"
    if row["bracket_type"] == "wing_high":
        return f">{row['floor_strike']:g}F"
    return f"{row['floor_strike']:g}-{row['cap_strike']:g}F"


def bracket_type(floor_strike, cap_strike) -> str:
    if pd.isna(floor_strike):
        return "wing_low"
    if pd.isna(cap_strike):
        return "wing_high"
    return "central"


def brackets_for_day(day_group: pd.DataFrame) -> list[dict]:
    return [
        {
            "ticker": row["ticker"],
            "lo_f": None if pd.isna(row["floor_strike"]) else float(row["floor_strike"]),
            "hi_f": None if pd.isna(row["cap_strike"]) else float(row["cap_strike"]),
            "bracket_type": row["bracket_type"],
        }
        for _, row in day_group.iterrows()
    ]


def decision_time_utc(target_date: str) -> datetime:
    day = datetime.strptime(target_date, "%Y-%m-%d").date()
    return datetime.combine(day, ENTRY_CLOCK, ET).astimezone(UTC)


def choose_vintage(target_date: str, model_key: str) -> VintageChoice | None:
    spec = MODEL_SPECS[model_key]
    decision_utc = decision_time_utc(target_date)
    target_day = datetime.strptime(target_date, "%Y-%m-%d").date()
    candidates: list[VintageChoice] = []
    for offset_days in (0, -1):
        cycle_day = target_day + timedelta(days=offset_days)
        for hour in spec["cycles"]:
            cycle = datetime(cycle_day.year, cycle_day.month, cycle_day.day, hour, tzinfo=UTC)
            available = cycle + spec["delay"]
            if available <= decision_utc:
                candidates.append(
                    VintageChoice(
                        model_key=model_key,
                        api_model=str(spec["api_model"]),
                        cycle_init_utc=cycle,
                        available_at_utc=available,
                    )
                )
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.cycle_init_utc)


def request_json(url: str, params: dict, timeout: int = 45) -> dict:
    headers = {"User-Agent": "prediction-market-analysis/forecast-vintage-audit"}
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
            if response.status_code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_exc = exc
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"request failed for {url}: {last_exc}")


def fetch_single_run_maxt(target_date: str, choice: VintageChoice) -> float | None:
    run = choice.cycle_init_utc.strftime("%Y-%m-%dT%H:%M")
    params = {
        "latitude": CITY_LAT,
        "longitude": CITY_LON,
        "run": run,
        "forecast_days": 3,
        "daily": "temperature_2m_max",
        "models": choice.api_model,
        "temperature_unit": "fahrenheit",
        "timezone": "America/New_York",
    }
    data = request_json(SINGLE_RUNS_URL, params=params)
    daily = data.get("daily", {})
    times = daily.get("time", [])
    values = daily.get("temperature_2m_max", [])
    for day, value in zip(times, values):
        if str(day) == target_date and value is not None:
            return float(value)
    return None


def load_cache() -> pd.DataFrame:
    if not VINTAGE_CACHE.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(VINTAGE_CACHE)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def save_cache(cache: pd.DataFrame) -> None:
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    if cache.empty:
        return
    cache = cache.sort_values(["target_date", "model_key"]).drop_duplicates(
        ["target_date", "model_key"], keep="last"
    )
    cache.to_csv(VINTAGE_CACHE, index=False)


def build_vintage_features(target_dates: list[str], refresh: bool = False) -> pd.DataFrame:
    cache = pd.DataFrame() if refresh else load_cache()
    rows = cache.to_dict(orient="records") if not cache.empty else []
    existing = {
        (str(row["target_date"]), str(row["model_key"]))
        for row in rows
        # Cache absence and API absence are different things. Keep NaN rows as
        # cached "not available from this archived run" records so repeated
        # reruns do not hammer the Single Runs API for dates it cannot serve.
        if pd.notna(row.get("target_date")) and pd.notna(row.get("model_key"))
    }
    total_needed = len(target_dates) * len(MODEL_KEYS)
    fetched = 0
    skipped = 0
    for idx, target_date in enumerate(target_dates, start=1):
        for model_key in MODEL_KEYS:
            if (target_date, model_key) in existing:
                skipped += 1
                continue
            choice = choose_vintage(target_date, model_key)
            if choice is None:
                continue
            try:
                maxt = fetch_single_run_maxt(target_date, choice)
            except Exception as exc:
                rows.append(
                    {
                        "target_date": target_date,
                        "model_key": model_key,
                        "api_model": choice.api_model,
                        "cycle_init_utc": choice.cycle_init_utc.isoformat(),
                        "available_at_utc": choice.available_at_utc.isoformat(),
                        "decision_time_utc": decision_time_utc(target_date).isoformat(),
                        "maxt_f": np.nan,
                        "error": str(exc),
                    }
                )
                fetched += 1
                continue
            rows.append(
                {
                    "target_date": target_date,
                    "model_key": model_key,
                    "api_model": choice.api_model,
                    "cycle_init_utc": choice.cycle_init_utc.isoformat(),
                    "available_at_utc": choice.available_at_utc.isoformat(),
                    "decision_time_utc": decision_time_utc(target_date).isoformat(),
                    "maxt_f": maxt,
                    "error": "",
                }
            )
            fetched += 1
            existing.add((target_date, model_key))
            if fetched % 25 == 0:
                print(
                    f"  vintage fetch progress: fetched {fetched}, cached {skipped}, "
                    f"date {idx}/{len(target_dates)}",
                    flush=True,
                )
                save_cache(pd.DataFrame(rows))
            time.sleep(0.03)
    out = pd.DataFrame(rows)
    save_cache(out)
    print(f"Vintage cache rows: {len(out)} ({total_needed} model-date slots requested)")
    return pivot_vintages(out)


def pivot_vintages(cache: pd.DataFrame) -> pd.DataFrame:
    if cache.empty:
        return pd.DataFrame(columns=["target_date", *MODEL_COLS])
    valid = cache.copy()
    valid["maxt_f"] = pd.to_numeric(valid["maxt_f"], errors="coerce")
    wide = valid.pivot_table(index="target_date", columns="model_key", values="maxt_f", aggfunc="last")
    wide = wide.rename(columns={key: MODEL_SPECS[key]["feature"] for key in MODEL_KEYS}).reset_index()
    for col in MODEL_COLS:
        if col not in wide.columns:
            wide[col] = np.nan
    return wide[["target_date", *MODEL_COLS]]


def load_markets() -> pd.DataFrame:
    markets = pd.read_csv(MARKETS_CSV)
    markets["target_date"] = markets["target_date"].astype(str)
    markets["floor_strike"] = pd.to_numeric(markets["floor_strike"], errors="coerce")
    markets["cap_strike"] = pd.to_numeric(markets["cap_strike"], errors="coerce")
    markets["bracket_type"] = markets.apply(lambda row: bracket_type(row["floor_strike"], row["cap_strike"]), axis=1)
    markets["bracket"] = markets.apply(bracket_label, axis=1)
    markets["kalshi_result_yes"] = markets["settlement_value"].astype(str).str.lower().eq("yes")
    markets = markets[(markets["target_date"] >= START_DATE) & (markets["target_date"] <= END_DATE)].copy()
    return markets


def load_actuals(markets: pd.DataFrame) -> pd.DataFrame:
    if ACTUALS_CSV.exists():
        actuals = pd.read_csv(ACTUALS_CSV).rename(columns={"date": "target_date", "max_temp_f": "actual_temp"})
    else:
        actuals = pd.DataFrame(columns=["target_date", "actual_temp"])
    kalshi_actuals = (
        markets[markets["kalshi_result_yes"] & markets["raw_settlement_temp"].notna()][
            ["target_date", "raw_settlement_temp"]
        ]
        .drop_duplicates("target_date")
        .rename(columns={"raw_settlement_temp": "actual_temp_kalshi"})
    )
    actuals["target_date"] = actuals["target_date"].astype(str)
    actuals["actual_temp"] = pd.to_numeric(actuals.get("actual_temp"), errors="coerce")
    daily = pd.DataFrame({"target_date": sorted(markets["target_date"].unique())})
    daily = daily.merge(actuals[["target_date", "actual_temp"]], on="target_date", how="left")
    daily = daily.merge(kalshi_actuals, on="target_date", how="left")
    daily["actual_temp"] = daily["actual_temp"].fillna(pd.to_numeric(daily["actual_temp_kalshi"], errors="coerce"))
    return daily[["target_date", "actual_temp"]].dropna(subset=["actual_temp"])


def add_features(daily: pd.DataFrame) -> pd.DataFrame:
    out = daily.dropna(subset=MODEL_COLS).copy()
    out["target_date_dt"] = pd.to_datetime(out["target_date"])
    out["consensus"] = out[MODEL_COLS].mean(axis=1)
    out["model_spread"] = out[MODEL_COLS].std(axis=1)
    out["physics_mean"] = out[["gfs_maxt", "ecmwf_maxt"]].mean(axis=1)
    out["ai_mean"] = out[["icon_maxt", "gem_maxt"]].mean(axis=1)
    out["spread_between"] = (out["physics_mean"] - out["ai_mean"]).abs()
    out["month"] = out["target_date_dt"].dt.month
    out["day_of_year"] = out["target_date_dt"].dt.dayofyear
    out["date"] = out["target_date"]
    return out


def load_orderbooks() -> pd.DataFrame:
    if ORDERBOOKS_11AM_PARQUET.exists():
        ob = pd.read_parquet(ORDERBOOKS_11AM_PARQUET)
    elif ORDERBOOKS_PARQUET.exists():
        # Legacy cache is a 9:45-10:05 AM METAR-window file. Keep it as a
        # fallback for inspection, but it will generally be too far from 11 AM.
        ob = pd.read_parquet(ORDERBOOKS_PARQUET)
    else:
        return pd.DataFrame()
    ob["target_date"] = ob["target_date"].astype(str)
    return ob


def et_window_ms(target_date: str, start_hour: int, start_minute: int, end_hour: int, end_minute: int) -> tuple[int, int]:
    day = datetime.strptime(target_date, "%Y-%m-%d")
    start_et = datetime(day.year, day.month, day.day, start_hour, start_minute, tzinfo=ET)
    end_et = datetime(day.year, day.month, day.day, end_hour, end_minute, tzinfo=ET)
    return int(start_et.timestamp() * 1000), int(end_et.timestamp() * 1000)


def fetch_predexon_snapshots(ticker: str, start_ms: int, end_ms: int) -> list[dict]:
    api_key = os.environ.get("PREDEXON_API_KEY")
    if not api_key:
        print("  WARNING: PREDEXON_API_KEY not set; using candle fallback for missing 11AM orderbooks.", flush=True)
        return []
    headers = {"x-api-key": api_key}
    snapshots: list[dict] = []
    pagination_key: str | None = None
    seen_pagination_keys: set[str] = set()
    pages = 0
    while True:
        pages += 1
        if pages > 20:
            print(f"  WARNING: stopping pagination after 20 pages for {ticker}", flush=True)
            break
        params: dict = {
            "ticker": ticker,
            "start_time": start_ms,
            "end_time": end_ms,
            "limit": 200,
        }
        if pagination_key:
            params["pagination_key"] = pagination_key
        for attempt in range(4):
            try:
                response = requests.get(PREDEXON_ORDERBOOKS_URL, params=params, headers=headers, timeout=30)
                if response.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                response.raise_for_status()
                break
            except requests.RequestException:
                if attempt == 3:
                    return snapshots
                time.sleep(1.0 * (attempt + 1))
        data = response.json()
        snapshots.extend(data.get("snapshots", []))
        pagination = data.get("pagination", {})
        if not pagination.get("has_more"):
            break
        pagination_key = pagination.get("pagination_key")
        if not pagination_key or pagination_key in seen_pagination_keys:
            print(f"  WARNING: repeated/empty pagination key for {ticker}", flush=True)
            break
        seen_pagination_keys.add(pagination_key)
        time.sleep(0.2)
    return snapshots


def ensure_11am_orderbooks(markets: pd.DataFrame, refresh: bool = False) -> pd.DataFrame:
    """Fetch/cache Predexon orderbooks in the actual 11AM entry window."""
    existing = pd.DataFrame()
    cached_keys: set[tuple[str, str]] = set()
    if ORDERBOOKS_11AM_PARQUET.exists() and not refresh:
        existing = pd.read_parquet(ORDERBOOKS_11AM_PARQUET)
        if not existing.empty:
            existing["target_date"] = existing["target_date"].astype(str)
            cached_keys = set(zip(existing["ticker"].astype(str), existing["target_date"].astype(str)))

    ticker_dates = (
        markets[markets["target_date"] >= TRAIN_CUTOFF][["ticker", "target_date"]]
        .drop_duplicates()
        .sort_values(["target_date", "ticker"])
        .reset_index(drop=True)
    )
    rows = existing.to_dict("records") if not existing.empty else []
    fetched = 0
    skipped = 0
    for i, item in ticker_dates.iterrows():
        ticker = str(item["ticker"])
        target_date = str(item["target_date"])
        key = (ticker, target_date)
        if key in cached_keys:
            skipped += 1
            continue
        start_ms, end_ms = et_window_ms(target_date, 10, 55, 11, 5)
        snaps = fetch_predexon_snapshots(ticker, start_ms, end_ms)
        if snaps:
            for snap in snaps:
                rows.append(
                    {
                        "target_date": target_date,
                        "ticker": ticker,
                        "timestamp_ms": snap["timestamp"],
                        "best_bid": snap.get("best_bid"),
                        "best_ask": snap.get("best_ask"),
                        "bid_depth": snap.get("bid_depth"),
                        "ask_depth": snap.get("ask_depth"),
                        "sequence": snap.get("sequence", 0),
                    }
                )
        else:
            rows.append(
                {
                    "target_date": target_date,
                    "ticker": ticker,
                    "timestamp_ms": np.nan,
                    "best_bid": np.nan,
                    "best_ask": np.nan,
                    "bid_depth": 0,
                    "ask_depth": 0,
                    "sequence": 0,
                }
            )
        fetched += 1
        if fetched % 50 == 0:
            print(
                f"  11AM orderbook fetch: fetched {fetched}, skipped {skipped}, "
                f"row {i + 1}/{len(ticker_dates)}",
                flush=True,
            )
            pd.DataFrame(rows).to_parquet(ORDERBOOKS_11AM_PARQUET, index=False)
        time.sleep(0.25)

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["target_date", "ticker", "timestamp_ms"], na_position="last").reset_index(drop=True)
        out.to_parquet(ORDERBOOKS_11AM_PARQUET, index=False)
    return out


def decision_ms_for_date(target_date: str) -> int:
    return int(decision_time_utc(target_date).timestamp() * 1000)


def nearest_snapshot(ob_ticker: pd.DataFrame, target_ms: int) -> pd.Series | None:
    if ob_ticker.empty:
        return None
    idx = (ob_ticker["timestamp_ms"] - target_ms).abs().idxmin()
    snap = ob_ticker.loc[idx]
    if abs(int(snap["timestamp_ms"]) - target_ms) > 30 * 60 * 1000:
        return None
    return snap


def fallback_11am_book(row: pd.Series) -> tuple[int, int, int, int, str] | None:
    price = row.get("yes_price_11AM")
    if pd.isna(price):
        return None
    mid_c = int(round(float(price) * 100))
    return max(0, mid_c - 1), min(100, mid_c + 1), 10, 10, "fallback_11am"


def executable_book(row: pd.Series, ob_by_ticker: dict[str, pd.DataFrame]) -> tuple[int, int, int, int, str] | None:
    target_ms = decision_ms_for_date(str(row["target_date"]))
    ob_ticker = ob_by_ticker.get(str(row["ticker"]))
    if ob_ticker is not None:
        snap = nearest_snapshot(ob_ticker, target_ms)
        if snap is not None and pd.notna(snap.get("best_bid")) and pd.notna(snap.get("best_ask")):
            return (
                int(snap["best_bid"]),
                int(snap["best_ask"]),
                int(snap.get("bid_depth") or 0),
                int(snap.get("ask_depth") or 0),
                "orderbook_11am",
            )
    return fallback_11am_book(row)


def simulate(
    daily: pd.DataFrame,
    markets: pd.DataFrame,
    prices: pd.DataFrame,
    orderbooks: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    prices = prices.copy()
    prices["target_date"] = prices["target_date"].astype(str)
    rows = markets.merge(prices, on=["ticker", "target_date"], how="left")
    rows = rows.merge(daily[["target_date", *FEATURES]], on="target_date", how="inner")
    train_daily = daily[daily["target_date"] < TRAIN_CUTOFF].copy()
    eval_daily = daily[daily["target_date"] >= TRAIN_CUTOFF].copy()
    if len(train_daily) < 30:
        raise RuntimeError("Not enough vintage training days for EMOS_GUMBEL_HETERO")

    model = EMOSGumbelHeteroModel().fit(
        train_daily[FEATURES].to_numpy(dtype=float),
        train_daily["actual_temp"].to_numpy(dtype=float),
    )

    ob_by_ticker = {
        ticker: group.sort_values("timestamp_ms").reset_index(drop=True)
        for ticker, group in orderbooks.groupby("ticker")
    } if not orderbooks.empty else {}

    predictions: list[dict] = []
    trades: list[dict] = []
    eval_dates = set(eval_daily["target_date"])
    for target_date, day_group in rows[rows["target_date"].isin(eval_dates)].groupby("target_date", sort=True):
        first = day_group.iloc[0]
        x = first[FEATURES].to_numpy(dtype=float)
        brackets = brackets_for_day(day_group)
        probs = model.bracket_probabilities(x, brackets)
        for _, row in day_group.iterrows():
            book = executable_book(row, ob_by_ticker)
            if book is None:
                continue
            best_bid_c, best_ask_c, bid_depth, ask_depth, entry_source = book
            prob = float(probs.get(row["ticker"], np.nan))
            if not np.isfinite(prob):
                continue
            mid = (best_bid_c + best_ask_c) / 200.0
            if prob > mid:
                direction = "YES"
                entry_price = best_bid_c / 100.0
                gap_pp = (prob - entry_price) * 100.0
                fill_depth = bid_depth
            else:
                direction = "NO"
                entry_price = (100 - best_ask_c) / 100.0
                gap_pp = ((1.0 - prob) - entry_price) * 100.0
                fill_depth = ask_depth
            fee = maker_fee(entry_price)
            prediction = {
                "date": target_date,
                "ticker": row["ticker"],
                "bracket": row["bracket"],
                "bracket_type": row["bracket_type"],
                "model_name": "EMOS_GUMBEL_HETERO_VINTAGE",
                "probability": prob,
                "kalshi_result_yes": bool(row["kalshi_result_yes"]),
                "direction": direction,
                "entry_price": entry_price,
                "mid_price": mid,
                "spread_cents": best_ask_c - best_bid_c,
                "fill_depth": fill_depth,
                "gap_pp": gap_pp,
                "maker_fee": fee,
                "net_edge_pp": gap_pp - fee * 100.0,
                "entry_source": entry_source,
                "consensus": float(first["consensus"]),
                "model_spread": float(first["model_spread"]),
                "spread_between": float(first["spread_between"]),
            }
            predictions.append(prediction)

            if gap_pp <= MIN_GAP_PP:
                continue
            if DEAD_ZONE_LO <= gap_pp <= DEAD_ZONE_HI:
                continue
            if not MIN_ENTRY_PRICE <= entry_price <= MAX_ENTRY_PRICE:
                continue
            if row["bracket_type"] == "wing_low":
                continue
            result_yes = bool(row["kalshi_result_yes"])
            win = result_yes if direction == "YES" else not result_yes
            gross = (1.0 - entry_price) if win else -entry_price
            trade = dict(prediction)
            trade.update(
                {
                    "win": bool(win),
                    "gross": gross,
                    "net": gross - fee,
                    "no_fill": fill_depth == 0,
                }
            )
            trades.append(trade)
    return pd.DataFrame(predictions), pd.DataFrame(trades)


def probability_metrics(preds: pd.DataFrame) -> dict:
    if preds.empty:
        return {}
    p = preds["probability"].astype(float).clip(1e-9, 1 - 1e-9)
    y = preds["kalshi_result_yes"].astype(int)
    mass = preds.groupby("date")["probability"].sum()
    true_rows = preds[preds["kalshi_result_yes"]]
    return {
        "rows": int(len(preds)),
        "days": int(preds["date"].nunique()),
        "brier_score": float(np.mean((p - y) ** 2)),
        "binary_log_loss": float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))),
        "winner_log_loss": float(-np.mean(np.log(true_rows["probability"].clip(1e-9, 1.0)))) if not true_rows.empty else 0.0,
        "prob_mass_avg": float(mass.mean()) if not mass.empty else 0.0,
        "prob_mass_min": float(mass.min()) if not mass.empty else 0.0,
        "prob_mass_max": float(mass.max()) if not mass.empty else 0.0,
    }


def write_report(summary: dict) -> None:
    report = f"""# Vintage EMOS-Gumbel-Hetero Backtest

Generated: {summary['generated_at']}

## Scope

This is the leakage-controlled rerun. Forecast features come from Open-Meteo
Single Runs API, one explicit archived model run at a time, with each run
required to be available before the simulated 11:00 AM ET decision.

Model: `EMOS_GUMBEL_HETERO`

Forecast model features: GFS, ECMWF, ICON, GEM. This is the pre-HGEFS historical
fallback family from `AGENTS.md`; member-level HGEFS vintages are not yet present
in this repository.

Training: `{summary['train_period']['start']}` to `{summary['train_period']['end']}`.

Evaluation: `{summary['eval_period']['start']}` to `{summary['eval_period']['end']}`.

Entry: 11:00 AM ET maker price, using orderbook snapshot within 30 minutes when
available, otherwise the 11AM Kalshi candle with a synthetic 2c spread.

## Results

Core strategy:

- Trades: {summary['strategy']['trades']}
- Days: {summary['strategy']['days']}
- Win rate: {summary['strategy']['win_rate']:.1%}
- Net P&L: ${summary['strategy']['net_pnl']:.2f}
- Sharpe: {summary['strategy']['sharpe']:.2f}
- Max drawdown: ${summary['strategy']['max_drawdown']:.2f}
- Avg entry: {summary['strategy']['avg_entry_price']:.1%}

Probability:

- Rows: {summary['probability']['rows']}
- Days: {summary['probability']['days']}
- Brier: {summary['probability']['brier_score']:.4f}
- Binary log loss: {summary['probability']['binary_log_loss']:.4f}
- Winner log loss: {summary['probability']['winner_log_loss']:.4f}
- Probability mass avg: {summary['probability']['prob_mass_avg']:.4f}

## Data Integrity

- Vintage rows: {summary['vintage_rows']}
- Complete vintage days: {summary['complete_vintage_days']}
- Rows with unavailable-later-than-entry violations: {summary['availability_violations']}
- Orderbook entry share: {summary['orderbook_entry_share_pct']:.1f}%

Outputs:

- `{OUT_PREDICTIONS.relative_to(ROOT)}`
- `{OUT_TRADES.relative_to(ROOT)}`
- `{OUT_SUMMARY.relative_to(ROOT)}`
"""
    OUT_REPORT.write_text(report)


def main() -> int:
    parser = argparse.ArgumentParser(description="Vintage-safe EMOS_GUMBEL_HETERO weather backtest.")
    parser.add_argument("--refresh-vintages", action="store_true", help="Refetch all Single Runs API vintage rows.")
    parser.add_argument("--refresh-orderbooks", action="store_true", help="Refetch Predexon 10:55-11:05 AM ET orderbooks.")
    parser.add_argument("--skip-orderbook-fetch", action="store_true", help="Use cached orderbooks or 11AM candles only.")
    parser.add_argument("--start-date", default=START_DATE)
    parser.add_argument("--end-date", default=END_DATE)
    args = parser.parse_args()

    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    markets = load_markets()
    markets = markets[(markets["target_date"] >= args.start_date) & (markets["target_date"] <= args.end_date)].copy()
    prices = pd.read_csv(PRICES_CSV)
    actuals = load_actuals(markets)
    target_dates = sorted(actuals["target_date"].unique())
    vintages = build_vintage_features(target_dates, refresh=args.refresh_vintages)
    daily = actuals.merge(vintages, on="target_date", how="inner")
    daily = add_features(daily)
    orderbooks = (
        load_orderbooks()
        if args.skip_orderbook_fetch
        else ensure_11am_orderbooks(markets, refresh=args.refresh_orderbooks)
    )
    preds, trades = simulate(daily, markets, prices, orderbooks)

    preds.to_csv(OUT_PREDICTIONS, index=False)
    trades.to_csv(OUT_TRADES, index=False)

    cache = load_cache()
    if not cache.empty:
        cache["available_at_utc_dt"] = pd.to_datetime(cache["available_at_utc"], utc=True, errors="coerce")
        cache["decision_time_utc_dt"] = pd.to_datetime(cache["decision_time_utc"], utc=True, errors="coerce")
        violations = int((cache["available_at_utc_dt"] > cache["decision_time_utc_dt"]).sum())
    else:
        violations = 0

    train = daily[daily["target_date"] < TRAIN_CUTOFF]
    eval_ = daily[daily["target_date"] >= TRAIN_CUTOFF]
    strategy_summary = summarize(trades[~trades["no_fill"]] if not trades.empty else trades)
    prob_summary = probability_metrics(preds)
    orderbook_share = float((trades["entry_source"] == "orderbook_11am").mean() * 100.0) if not trades.empty else 0.0
    complete_days = int(daily["target_date"].nunique())
    summary = {
        "generated_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "model": "EMOS_GUMBEL_HETERO",
        "forecast_source": "Open-Meteo Single Runs API explicit run vintages",
        "entry_time_et": "11:00",
        "train_period": {
            "start": str(train["target_date"].min()) if not train.empty else None,
            "end": str(train["target_date"].max()) if not train.empty else None,
            "days": int(train["target_date"].nunique()),
        },
        "eval_period": {
            "start": str(eval_["target_date"].min()) if not eval_.empty else None,
            "end": str(eval_["target_date"].max()) if not eval_.empty else None,
            "days": int(eval_["target_date"].nunique()),
        },
        "feature_models": MODEL_KEYS,
        "strategy": strategy_summary,
        "probability": prob_summary,
        "vintage_rows": int(len(cache)) if not cache.empty else 0,
        "complete_vintage_days": complete_days,
        "availability_violations": violations,
        "orderbook_entry_share_pct": orderbook_share,
        "outputs": {
            "predictions": str(OUT_PREDICTIONS.relative_to(ROOT)),
            "trades": str(OUT_TRADES.relative_to(ROOT)),
            "summary": str(OUT_SUMMARY.relative_to(ROOT)),
            "report": str(OUT_REPORT.relative_to(ROOT)),
        },
    }
    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, sort_keys=True))
    write_report(summary)

    print("\n=== VINTAGE EMOS_GUMBEL_HETERO BACKTEST ===")
    print(f"Training days: {summary['train_period']['days']} | Eval days: {summary['eval_period']['days']}")
    print(f"Vintage rows: {summary['vintage_rows']} | Availability violations: {violations}")
    print(f"Trades: {strategy_summary['trades']}")
    print(f"Win rate: {strategy_summary['win_rate']:.1%}")
    print(f"Net P&L: ${strategy_summary['net_pnl']:.2f}")
    print(f"Sharpe: {strategy_summary['sharpe']:.2f}")
    print(f"Max drawdown: ${strategy_summary['max_drawdown']:.2f}")
    print(f"Orderbook entry share: {orderbook_share:.1f}%")
    print(f"Report: {OUT_REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
