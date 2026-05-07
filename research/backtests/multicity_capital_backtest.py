#!/usr/bin/env python3
"""
Multi-city leakage-safe backtest with $500 capital simulation.

Cities: KNYC (New York) + KMDW (Chicago Midway)
Model: EMOS_GUMBEL_HETERO per city, trained on city-specific data
Filter: YES trades only in 30–35pp gap window (leakage-safe finding)
Capital: $500 starting bankroll, quarter-Kelly with 5% max per trade

Usage:
    uv run python research/backtests/multicity_capital_backtest.py
    uv run python research/backtests/multicity_capital_backtest.py --skip-fetch
    uv run python research/backtests/multicity_capital_backtest.py --months 2
"""
from __future__ import annotations

import argparse
import json
import math
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
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

ET = ZoneInfo("America/New_York")
SINGLE_RUNS_URL = "https://single-runs-api.open-meteo.com/v1/forecast"

STARTING_CAPITAL = 500.0
MAX_TRADE_PCT = 0.05        # 5% of bankroll max per trade (conf >= 80)
MAKER_FEE_RATE = 0.0175
MIN_GAP_PP = 20.0
YES_MIN_GAP_PP = 30.0
YES_MAX_GAP_PP = 35.0
DEAD_ZONE_LO = 35.0
DEAD_ZONE_HI = 40.0
MIN_ENTRY_PRICE = 0.25
MAX_ENTRY_PRICE = 0.75
ENTRY_CLOCK = dtime(11, 0)
TRAIN_CUTOFF = "2026-01-07"

MODEL_SPECS = {
    "gfs":    {"api_model": "gfs_seamless",  "feature": "gfs_maxt",  "cycles": (0,6,12,18), "delay": timedelta(hours=4, minutes=40)},
    "ecmwf":  {"api_model": "ecmwf_ifs025",  "feature": "ecmwf_maxt","cycles": (0,12),       "delay": timedelta(hours=7)},
    "icon":   {"api_model": "icon_seamless",  "feature": "icon_maxt", "cycles": (0,6,12,18), "delay": timedelta(hours=5)},
    "gem":    {"api_model": "gem_seamless",   "feature": "gem_maxt",  "cycles": (0,12),       "delay": timedelta(hours=6)},
}
MODEL_KEYS = ["gfs", "ecmwf", "icon", "gem"]
MODEL_COLS = [MODEL_SPECS[k]["feature"] for k in MODEL_KEYS]

FEATURES = [
    "gfs_maxt", "ecmwf_maxt", "icon_maxt", "gem_maxt",
    "consensus", "model_spread", "physics_mean", "ai_mean",
    "spread_between", "month", "day_of_year",
]

CITY_CONFIG = {
    "KNYC": {
        "lat": 40.7789, "lon": -73.9692,
        "markets_csv": DATA_DIR / "kxhighny_markets.csv",
        "prices_csv":  DATA_DIR / "kxhighny_prices.csv",
        "actuals_csv": DATA_DIR / "knyc_actual_temps_extended.csv",
        "vintage_cache": RESEARCH_DIR / "knyc_single_run_vintages_11am.csv",
        "label": "New York (KNYC)",
        "tz": "America/New_York",
    },
    "KMDW": {
        "lat": 41.7860, "lon": -87.7522,
        "markets_csv": DATA_DIR / "kxhighchi_markets.csv",
        "prices_csv":  DATA_DIR / "kxhighchi_prices.csv",
        "actuals_csv": DATA_DIR / "kmdw_actual_temps_extended.csv",
        "vintage_cache": RESEARCH_DIR / "kmdw_single_run_vintages_11am.csv",
        "label": "Chicago Midway (KMDW)",
        "tz": "America/Chicago",
    },
    "KMIA": {
        "lat": 25.7959, "lon": -80.2870,
        "markets_csv": DATA_DIR / "kxhighmia_markets.csv",
        "prices_csv":  DATA_DIR / "kxhighmia_prices.csv",
        "actuals_csv": DATA_DIR / "kmia_actual_temps_extended.csv",
        "vintage_cache": RESEARCH_DIR / "kmia_single_run_vintages_11am.csv",
        "label": "Miami (KMIA)",
        "tz": "America/New_York",
    },
    "KAUS": {
        "lat": 30.1944, "lon": -97.6699,
        "markets_csv": DATA_DIR / "kxhighaus_markets.csv",
        "prices_csv":  DATA_DIR / "kxhighaus_prices.csv",
        "actuals_csv": DATA_DIR / "kaus_actual_temps_extended.csv",
        "vintage_cache": RESEARCH_DIR / "kaus_single_run_vintages_11am.csv",
        "label": "Austin (KAUS)",
        "tz": "America/Chicago",
    },
    "KLAX": {
        "lat": 33.9425, "lon": -118.4081,
        "markets_csv": DATA_DIR / "kxhighlax_markets.csv",
        "prices_csv":  DATA_DIR / "kxhighlax_prices.csv",
        "actuals_csv": DATA_DIR / "klax_actual_temps_extended.csv",
        "vintage_cache": RESEARCH_DIR / "klax_single_run_vintages_11am.csv",
        "label": "Los Angeles (KLAX)",
        "tz": "America/Los_Angeles",
    },
    "KDEN": {
        "lat": 39.8561, "lon": -104.6737,
        "markets_csv": DATA_DIR / "kxhighden_markets.csv",
        "prices_csv":  DATA_DIR / "kxhighden_prices.csv",
        "actuals_csv": DATA_DIR / "kden_actual_temps_extended.csv",
        "vintage_cache": RESEARCH_DIR / "kden_single_run_vintages_11am.csv",
        "label": "Denver (KDEN)",
        "tz": "America/Denver",
    },
    "KPHL": {
        "lat": 39.8729, "lon": -75.2408,
        "markets_csv": DATA_DIR / "kxhighphil_markets.csv",
        "prices_csv":  DATA_DIR / "kxhighphil_prices.csv",
        "actuals_csv": DATA_DIR / "kphl_actual_temps_extended.csv",
        "vintage_cache": RESEARCH_DIR / "kphl_single_run_vintages_11am.csv",
        "label": "Philadelphia (KPHL)",
        "tz": "America/New_York",
    },
}


def maker_fee(price: float, contracts: int = 1) -> float:
    return math.ceil(MAKER_FEE_RATE * contracts * price * (1.0 - price) * 100.0) / 100.0


def sharpe(values: Iterable[float]) -> float:
    arr = np.array(list(values), dtype=float)
    if len(arr) < 2:
        return 0.0
    std = float(np.std(arr, ddof=1))
    return 0.0 if std == 0 else float(np.mean(arr) / std)


def max_drawdown(values: Iterable[float]) -> float:
    arr = np.cumsum(np.array(list(values), dtype=float))
    if len(arr) == 0:
        return 0.0
    return float(np.min(arr - np.maximum.accumulate(arr)))


def decision_time_utc(target_date: str) -> datetime:
    day = datetime.strptime(target_date, "%Y-%m-%d").date()
    return datetime.combine(day, ENTRY_CLOCK, ET).astimezone(UTC)


def choose_vintage(target_date: str, model_key: str):
    spec = MODEL_SPECS[model_key]
    decision_utc = decision_time_utc(target_date)
    target_day = datetime.strptime(target_date, "%Y-%m-%d").date()
    candidates = []
    for offset_days in (0, -1):
        cycle_day = target_day + timedelta(days=offset_days)
        for hour in spec["cycles"]:
            cycle = datetime(cycle_day.year, cycle_day.month, cycle_day.day, hour, tzinfo=UTC)
            available = cycle + spec["delay"]
            if available <= decision_utc:
                candidates.append((cycle, available))
    if not candidates:
        return None
    cycle, available = max(candidates, key=lambda x: x[0])
    return cycle, available, str(spec["api_model"])


def request_json(url: str, params: dict) -> dict:
    headers = {"User-Agent": "prediction-market-analysis/multicity-backtest"}
    for attempt in range(4):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=45)
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            time.sleep(1.0 * (attempt + 1))
            if attempt == 3:
                raise RuntimeError(f"request failed: {exc}") from exc
    raise RuntimeError("request exhausted retries")


def fetch_vintage_for_city(target_date: str, model_key: str, lat: float, lon: float,
                           city_tz: str = "America/New_York") -> float | None:
    result = choose_vintage(target_date, model_key)
    if result is None:
        return None
    cycle, available, api_model = result
    params = {
        "latitude": lat, "longitude": lon,
        "run": cycle.strftime("%Y-%m-%dT%H:%M"),
        "forecast_days": 3, "daily": "temperature_2m_max",
        "models": api_model, "temperature_unit": "fahrenheit",
        "timezone": city_tz,
    }
    data = request_json(SINGLE_RUNS_URL, params)
    times = data.get("daily", {}).get("time", [])
    values = data.get("daily", {}).get("temperature_2m_max", [])
    for day, val in zip(times, values):
        if str(day) == target_date and val is not None:
            return float(val)
    return None


def build_vintage_features(city: str, target_dates: list[str], refresh: bool = False) -> pd.DataFrame:
    cfg = CITY_CONFIG[city]
    cache_path = cfg["vintage_cache"]
    lat, lon = cfg["lat"], cfg["lon"]

    cache = pd.DataFrame()
    if cache_path.exists() and not refresh:
        try:
            cache = pd.read_csv(cache_path)
        except pd.errors.EmptyDataError:
            pass

    existing = set()
    rows = cache.to_dict("records") if not cache.empty else []
    if not cache.empty:
        existing = {
            (str(r["target_date"]), str(r["model_key"]))
            for r in rows
            if pd.notna(r.get("target_date")) and pd.notna(r.get("model_key"))
        }

    needed = []
    for target_date in target_dates:
        for model_key in MODEL_KEYS:
            if (target_date, model_key) in existing:
                continue
            result = choose_vintage(target_date, model_key)
            if result is None:
                continue
            cycle, available, api_model = result
            needed.append((target_date, model_key, cycle, available, api_model))

    city_tz_str = cfg.get("tz", "America/New_York")

    def _fetch_one(args):
        target_date, model_key, cycle, available, api_model = args
        try:
            maxt = fetch_vintage_for_city(target_date, model_key, lat, lon, city_tz=city_tz_str)
        except Exception:
            maxt = None
        return {
            "target_date": target_date, "model_key": model_key,
            "api_model": api_model,
            "cycle_init_utc": cycle.isoformat(),
            "available_at_utc": available.isoformat(),
            "decision_time_utc": decision_time_utc(target_date).isoformat(),
            "maxt_f": maxt if maxt is not None else np.nan,
            "error": "" if maxt is not None else "no_value",
        }

    from concurrent.futures import ThreadPoolExecutor, as_completed
    fetched = 0
    total_needed = len(needed)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_one, arg): arg for arg in needed}
        for future in as_completed(futures):
            rows.append(future.result())
            fetched += 1
            if fetched % 20 == 0:
                pd.DataFrame(rows + (cache.to_dict("records") if not cache.empty else [])).to_csv(cache_path, index=False)
                print(f"  [{city}] vintage fetch: {fetched}/{total_needed}", flush=True)

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["target_date","model_key"]).drop_duplicates(["target_date","model_key"], keep="last")
        out.to_csv(cache_path, index=False)

    # Pivot wide
    if out.empty:
        return pd.DataFrame(columns=["target_date", *MODEL_COLS])
    valid = out.copy()
    valid["maxt_f"] = pd.to_numeric(valid["maxt_f"], errors="coerce")
    wide = valid.pivot_table(index="target_date", columns="model_key", values="maxt_f", aggfunc="last")
    wide = wide.rename(columns={k: MODEL_SPECS[k]["feature"] for k in MODEL_KEYS}).reset_index()
    for col in MODEL_COLS:
        if col not in wide.columns:
            wide[col] = np.nan
    return wide[["target_date", *MODEL_COLS]]


def load_city_data(city: str, start_date: str, end_date: str):
    cfg = CITY_CONFIG[city]
    markets = pd.read_csv(cfg["markets_csv"])
    markets["target_date"] = markets["target_date"].astype(str)
    markets["floor_strike"] = pd.to_numeric(markets["floor_strike"], errors="coerce")
    markets["cap_strike"] = pd.to_numeric(markets["cap_strike"], errors="coerce")
    markets["bracket_type"] = markets.apply(
        lambda r: "wing_low" if pd.isna(r["floor_strike"]) else
                  "wing_high" if pd.isna(r["cap_strike"]) else "central", axis=1)
    markets["kalshi_result_yes"] = markets["settlement_value"].astype(str).str.lower().eq("yes")
    markets = markets[(markets["target_date"] >= start_date) & (markets["target_date"] <= end_date)].copy()

    prices = pd.read_csv(cfg["prices_csv"])
    prices["target_date"] = prices["target_date"].astype(str)

    actuals_raw = pd.read_csv(cfg["actuals_csv"]).rename(columns={"date": "target_date", "max_temp_f": "actual_temp"})
    actuals_raw["target_date"] = actuals_raw["target_date"].astype(str)
    kalshi_actuals = (
        markets[markets["kalshi_result_yes"] & markets["raw_settlement_temp"].notna()][["target_date","raw_settlement_temp"]]
        .drop_duplicates("target_date")
        .rename(columns={"raw_settlement_temp": "actual_temp_kalshi"})
    )
    daily = pd.DataFrame({"target_date": sorted(markets["target_date"].unique())})
    daily = daily.merge(actuals_raw[["target_date","actual_temp"]], on="target_date", how="left")
    daily = daily.merge(kalshi_actuals, on="target_date", how="left")
    daily["actual_temp"] = daily["actual_temp"].fillna(pd.to_numeric(daily["actual_temp_kalshi"], errors="coerce"))
    daily = daily[["target_date","actual_temp"]].dropna(subset=["actual_temp"])

    return markets, prices, daily


def add_features(daily: pd.DataFrame) -> pd.DataFrame:
    out = daily.dropna(subset=MODEL_COLS).copy()
    out["target_date_dt"] = pd.to_datetime(out["target_date"])
    out["consensus"] = out[MODEL_COLS].mean(axis=1)
    out["model_spread"] = out[MODEL_COLS].std(axis=1)
    out["physics_mean"] = out[["gfs_maxt","ecmwf_maxt"]].mean(axis=1)
    out["ai_mean"] = out[["icon_maxt","gem_maxt"]].mean(axis=1)
    out["spread_between"] = (out["physics_mean"] - out["ai_mean"]).abs()
    out["month"] = out["target_date_dt"].dt.month
    out["day_of_year"] = out["target_date_dt"].dt.dayofyear
    out["date"] = out["target_date"]
    return out


def quarter_kelly_stake(bankroll: float, prob: float, price: float) -> float:
    if price <= 0 or price >= 1:
        return 0.0
    b = (1 - price) / price
    full_kelly = max(0.0, (b * prob - (1 - prob)) / b)
    quarter_kelly = full_kelly * 0.25
    desired = quarter_kelly * bankroll
    cap = bankroll * MAX_TRADE_PCT
    return min(desired, cap)


def simulate_city(city: str, start_date: str, end_date: str, refresh: bool = False) -> pd.DataFrame:
    markets, prices, daily_actuals = load_city_data(city, start_date, end_date)
    target_dates = sorted(daily_actuals["target_date"].unique())
    vintages = build_vintage_features(city, target_dates, refresh=refresh)
    daily = daily_actuals.merge(vintages, on="target_date", how="inner")
    daily = add_features(daily)

    train = daily[daily["target_date"] < TRAIN_CUTOFF].copy()
    eval_ = daily[daily["target_date"] >= TRAIN_CUTOFF].copy()
    if len(train) < 30:
        raise RuntimeError(f"{city}: only {len(train)} training days, need >=30")

    model = EMOSGumbelHeteroModel().fit(
        train[FEATURES].to_numpy(dtype=float),
        train["actual_temp"].to_numpy(dtype=float),
    )

    prices_t = prices.copy()
    prices_t["target_date"] = prices_t["target_date"].astype(str)
    rows = markets.merge(prices_t, on=["ticker","target_date"], how="left")
    rows = rows.merge(daily[["target_date",*FEATURES]], on="target_date", how="inner")

    trades = []
    eval_dates = set(eval_["target_date"])

    for target_date, day_group in rows[rows["target_date"].isin(eval_dates)].groupby("target_date", sort=True):
        first = day_group.iloc[0]
        x = first[FEATURES].to_numpy(dtype=float)
        brackets = [
            {"ticker": r["ticker"],
             "lo_f": None if pd.isna(r["floor_strike"]) else float(r["floor_strike"]),
             "hi_f": None if pd.isna(r["cap_strike"]) else float(r["cap_strike"]),
             "bracket_type": r["bracket_type"]}
            for _, r in day_group.iterrows()
        ]
        probs = model.bracket_probabilities(x, brackets)

        for _, row in day_group.iterrows():
            price_11am = row.get("yes_price_11AM")
            if pd.isna(price_11am):
                continue
            mid_c = float(price_11am) * 100
            best_bid_c = max(0, int(mid_c - 1))
            best_ask_c = min(100, int(mid_c + 1))

            prob = float(probs.get(row["ticker"], np.nan))
            if not np.isfinite(prob):
                continue

            mid = (best_bid_c + best_ask_c) / 200.0
            if prob > mid:
                direction = "YES"
                entry_price = best_bid_c / 100.0
                gap_pp = (prob - entry_price) * 100.0
            else:
                direction = "NO"
                entry_price = (100 - best_ask_c) / 100.0
                gap_pp = ((1.0 - prob) - entry_price) * 100.0

            if gap_pp <= MIN_GAP_PP:
                continue
            if DEAD_ZONE_LO <= gap_pp <= DEAD_ZONE_HI:
                continue
            if not MIN_ENTRY_PRICE <= entry_price <= MAX_ENTRY_PRICE:
                continue
            if row["bracket_type"] == "wing_low":
                continue

            # YES gap window filter (core finding from loss analysis)
            if direction == "YES" and not (YES_MIN_GAP_PP <= gap_pp <= YES_MAX_GAP_PP):
                continue

            result_yes = bool(row["kalshi_result_yes"])
            win = result_yes if direction == "YES" else not result_yes
            gross = (1.0 - entry_price) if win else -entry_price
            fee = maker_fee(entry_price)
            net = gross - fee

            trades.append({
                "city": city,
                "date": target_date,
                "ticker": row["ticker"],
                "bracket_type": row["bracket_type"],
                "direction": direction,
                "entry_price": entry_price,
                "gap_pp": gap_pp,
                "probability": prob,
                "win": win,
                "gross": gross,
                "fee": fee,
                "net": net,
            })

    return pd.DataFrame(trades)


def simulate_capital(all_trades: pd.DataFrame, starting_capital: float = STARTING_CAPITAL) -> pd.DataFrame:
    """Replay trades chronologically with quarter-Kelly sizing across all cities."""
    if all_trades.empty:
        return pd.DataFrame()

    records = []
    bankroll = starting_capital
    all_trades = all_trades.sort_values(["date", "city", "ticker"]).reset_index(drop=True)

    for _, trade in all_trades.iterrows():
        # Use directional probability: P(win) = P(NO) for NO trades = 1 - P(YES)
        prob_directional = (
            float(trade["probability"]) if trade["direction"] == "YES"
            else 1.0 - float(trade["probability"])
        )
        stake = quarter_kelly_stake(bankroll, prob_directional, trade["entry_price"])
        contracts = max(1, int(stake / trade["entry_price"])) if stake >= trade["entry_price"] else 0
        if contracts == 0:
            continue
        actual_stake = contracts * float(trade["entry_price"])
        fee = maker_fee(float(trade["entry_price"]), contracts)
        gross = contracts * ((1.0 - float(trade["entry_price"])) if trade["win"] else -float(trade["entry_price"]))
        net = gross - fee
        bankroll += net
        records.append({
            **trade.to_dict(),
            "contracts": contracts,
            "actual_stake": actual_stake,
            "fee_dollars": fee,
            "net_dollars": net,
            "bankroll_after": bankroll,
            "pct_of_capital": actual_stake / starting_capital * 100,
        })
    return pd.DataFrame(records)


def monthly_summary(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["year_month"] = pd.to_datetime(df["date"]).dt.to_period("M")
    rows = []
    for ym, g in df.groupby("year_month"):
        rows.append({
            "month": str(ym),
            "trades": len(g),
            "cities": g["city"].nunique(),
            "win_rate": g["win"].mean(),
            "net_pnl": g["net_dollars"].sum(),
            "avg_stake": g["actual_stake"].mean(),
            "max_stake": g["actual_stake"].max(),
            "peak_exposure": g["actual_stake"].sum(),  # conservative: all same day
            "bankroll_end": g["bankroll_after"].iloc[-1],
        })
    return pd.DataFrame(rows)


def write_report(city_summaries: dict, capital_df: pd.DataFrame, monthly: pd.DataFrame) -> None:
    lines = ["# Multi-City Capital Backtest\n",
             f"Generated: {datetime.now(tz=UTC).isoformat(timespec='seconds')}\n",
             f"Capital: ${STARTING_CAPITAL:.0f}  |  Cities: {', '.join(city_summaries.keys())}\n",
             f"YES filter: {YES_MIN_GAP_PP:.0f}–{YES_MAX_GAP_PP:.0f}pp gap window only\n",
             "\n## Per-City Results (unit-sized, leakage-safe)\n"]

    for city, s in city_summaries.items():
        lines.append(f"\n### {city}\n")
        lines.append(f"- Trades: {s['trades']}  Win rate: {s['win_rate']:.1%}  Net PnL: ${s['net_pnl']:.2f}  Sharpe: {s['sharpe']:.3f}\n")
        lines.append(f"- YES: {s['yes_trades']} trades ({s['yes_wr']:.1%} WR)  NO: {s['no_trades']} trades ({s['no_wr']:.1%} WR)\n")

    lines.append("\n## Combined Capital Simulation ($500 quarter-Kelly)\n")
    total_net = capital_df["net_dollars"].sum() if not capital_df.empty else 0
    final_br = capital_df["bankroll_after"].iloc[-1] if not capital_df.empty else STARTING_CAPITAL
    avg_stake = capital_df["actual_stake"].mean() if not capital_df.empty else 0
    max_stake = capital_df["actual_stake"].max() if not capital_df.empty else 0
    lines.append(f"- Starting capital: ${STARTING_CAPITAL:.0f}\n")
    lines.append(f"- Final bankroll: ${final_br:.2f}  (+${final_br - STARTING_CAPITAL:.2f})\n")
    lines.append(f"- Total net: ${total_net:.2f}\n")
    lines.append(f"- Avg stake/trade: ${avg_stake:.2f}  Max stake/trade: ${max_stake:.2f}\n")
    lines.append(f"- Sharpe: {sharpe(capital_df['net_dollars']):.3f}\n")
    lines.append(f"- Max drawdown: ${max_drawdown(capital_df['net_dollars']):.2f}\n")

    lines.append("\n## Monthly Breakdown\n")
    lines.append("| Month | Trades | Win% | Net P&L | Avg Stake | Bankroll End |\n")
    lines.append("|---|---|---|---|---|---|\n")
    for _, r in monthly.iterrows():
        lines.append(
            f"| {r['month']} | {r['trades']} | {r['win_rate']:.1%} | "
            f"${r['net_pnl']:.2f} | ${r['avg_stake']:.2f} | ${r['bankroll_end']:.2f} |\n"
        )

    report_path = REPORTS_DIR / "multicity_capital_backtest.md"
    report_path.write_text("".join(lines))
    print(f"Report: {report_path.relative_to(ROOT)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-fetch", action="store_true", help="Use cached vintage data only")
    parser.add_argument("--start-date", default="2024-10-01")
    parser.add_argument("--end-date", default="2026-04-25")
    parser.add_argument("--months", type=int, default=None, help="Evaluate only last N months")
    parser.add_argument("--cities", nargs="+", default=list(CITY_CONFIG.keys()))
    args = parser.parse_args()

    start_date = args.start_date
    end_date = args.end_date
    if args.months:
        eval_start = (datetime.now() - timedelta(days=args.months * 31)).strftime("%Y-%m-%d")
        # keep train period but restrict eval reporting
        print(f"Evaluation window: last {args.months} months (from ~{eval_start})")

    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    city_dfs = {}
    city_summaries = {}
    for city in args.cities:
        if city not in CITY_CONFIG:
            print(f"Unknown city {city}, skipping")
            continue
        cfg = CITY_CONFIG[city]
        missing = [key for key in ("markets_csv", "prices_csv", "actuals_csv") if not cfg[key].exists()]
        if missing:
            print(f"  {city}: missing {[cfg[k].name for k in missing]} — run fetch_city_kalshi_data.py + fetch_extended_training_data.py first")
            continue
        print(f"\n=== {city} ===", flush=True)
        try:
            df = simulate_city(city, start_date, end_date, refresh=not args.skip_fetch)
        except Exception as exc:
            print(f"  {city}: SKIPPED — {exc}")
            continue
        if df.empty:
            print(f"  No trades for {city}")
            continue

        yes_t = df[df["direction"] == "YES"]
        no_t = df[df["direction"] == "NO"]
        city_summaries[city] = {
            "trades": len(df),
            "win_rate": df["win"].mean(),
            "net_pnl": df["net"].sum(),
            "sharpe": sharpe(df["net"]),
            "yes_trades": len(yes_t),
            "yes_wr": yes_t["win"].mean() if not yes_t.empty else 0.0,
            "no_trades": len(no_t),
            "no_wr": no_t["win"].mean() if not no_t.empty else 0.0,
        }
        city_dfs[city] = df
        print(f"  trades={len(df)}, WR={df['win'].mean():.1%}, PnL=${df['net'].sum():.2f}, Sharpe={sharpe(df['net']):.3f}")

    if not city_dfs:
        print("No city data to combine")
        return 1

    all_trades = pd.concat(city_dfs.values(), ignore_index=True)
    capital_df = simulate_capital(all_trades, STARTING_CAPITAL)
    monthly = monthly_summary(capital_df) if not capital_df.empty else pd.DataFrame()

    # Save outputs
    all_trades.to_csv(RESEARCH_DIR / "multicity_trades.csv", index=False)
    capital_df.to_csv(RESEARCH_DIR / "multicity_capital_trades.csv", index=False)
    if not monthly.empty:
        monthly.to_csv(RESEARCH_DIR / "multicity_monthly.csv", index=False)

    write_report(city_summaries, capital_df, monthly)

    print("\n=== COMBINED RESULTS ===")
    if not capital_df.empty:
        final_br = capital_df["bankroll_after"].iloc[-1]
        total_trades = len(capital_df)
        wr = capital_df["win"].mean()
        net = capital_df["net_dollars"].sum()
        avg_stake = capital_df["actual_stake"].mean()
        max_stake = capital_df["actual_stake"].max()
        max_concurrent = (
            capital_df.groupby("date")["actual_stake"].sum().max()
        )
        print(f"Starting capital: ${STARTING_CAPITAL:.0f}")
        print(f"Final bankroll:   ${final_br:.2f} (+${final_br - STARTING_CAPITAL:.2f})")
        print(f"Total trades:     {total_trades} ({total_trades / (capital_df['date'].nunique() or 1) * 30:.0f}/mo est)")
        print(f"Win rate:         {wr:.1%}")
        print(f"Net P&L:          ${net:.2f}")
        print(f"Avg stake:        ${avg_stake:.2f}  Max: ${max_stake:.2f}")
        print(f"Max daily exposure: ${max_concurrent:.2f} ({max_concurrent/STARTING_CAPITAL*100:.1f}% of capital)")
        print(f"Sharpe:           {sharpe(capital_df['net_dollars']):.3f}")
        print(f"Max drawdown:     ${max_drawdown(capital_df['net_dollars']):.2f}")

        print("\n=== MONTHLY ===")
        for _, r in monthly.iterrows():
            print(f"  {r['month']}: {r['trades']} trades, WR={r['win_rate']:.1%}, PnL=${r['net_pnl']:.2f}, bankroll=${r['bankroll_end']:.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
