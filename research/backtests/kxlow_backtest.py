#!/usr/bin/env python3
"""
KXLOWT* (Daily Low Temperature) leakage-safe backtest with $500 capital simulation.

All KXLOWT cities launched Jan 28, 2026. To get a full EMOS training set without
being constrained by market history, we decouple training from market dates:

  Training period: Jan 2024 – Jan 27, 2026 (~390 days, from IEM actuals CSV)
                   Single Runs API vintage TMIN forecasts fetched for those dates.
  Eval period:     Jan 28, 2026+ (actual KXLOWT market dates, real prices used)

TRAIN_CUTOFF = "2026-01-28" (day KXLOWT markets launched)

Usage:
    uv run python research/backtests/kxlow_backtest.py
    uv run python research/backtests/kxlow_backtest.py --skip-fetch
    uv run python research/backtests/kxlow_backtest.py --cities KXLOWTNYC KXLOWTCHI
"""
from __future__ import annotations

import argparse
import math
import sys
import time
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
MAX_TRADE_PCT = 0.05
MAKER_FEE_RATE = 0.0175
MIN_GAP_PP = 20.0
YES_MIN_GAP_PP = 30.0
YES_MAX_GAP_PP = 35.0
DEAD_ZONE_LO = 35.0
DEAD_ZONE_HI = 40.0
MIN_ENTRY_PRICE = 0.25
MAX_ENTRY_PRICE = 0.75
ENTRY_CLOCK = dtime(11, 0)

# All KXLOWT markets launched Jan 28, 2026. Train on pre-market historical data.
TRAIN_CUTOFF = "2026-01-28"
# How far back to pull IEM actuals for training (Single Runs API supports ~18 months)
TRAINING_START = "2024-07-01"

MODEL_SPECS = {
    "gfs":   {"api_model": "gfs_seamless",  "feature": "gfs_mint",   "cycles": (0, 6, 12, 18), "delay": timedelta(hours=4, minutes=40)},
    "ecmwf": {"api_model": "ecmwf_ifs025",  "feature": "ecmwf_mint", "cycles": (0, 12),          "delay": timedelta(hours=7)},
    "icon":  {"api_model": "icon_seamless",  "feature": "icon_mint",  "cycles": (0, 6, 12, 18), "delay": timedelta(hours=5)},
    "gem":   {"api_model": "gem_seamless",   "feature": "gem_mint",   "cycles": (0, 12),          "delay": timedelta(hours=6)},
}
MODEL_KEYS = ["gfs", "ecmwf", "icon", "gem"]
MODEL_COLS = [MODEL_SPECS[k]["feature"] for k in MODEL_KEYS]

FEATURES = [
    "gfs_mint", "ecmwf_mint", "icon_mint", "gem_mint",
    "consensus", "model_spread", "physics_mean", "ai_mean",
    "spread_between", "month", "day_of_year",
]

CITY_CONFIG = {
    "KXLOWTNYC": {
        "lat": 40.7789, "lon": -73.9692, "tz": "America/New_York",
        "markets_csv":  DATA_DIR / "kxlowtnyc_markets.csv",
        "prices_csv":   DATA_DIR / "kxlowtnyc_prices.csv",
        "actuals_csv":  DATA_DIR / "kxlowtnyc_actual_tmin_extended.csv",
        "vintage_cache": RESEARCH_DIR / "kxlowtnyc_single_run_vintages_11am.csv",
        "label": "New York City Low",
    },
    "KXLOWTCHI": {
        "lat": 41.7868, "lon": -87.7522, "tz": "America/Chicago",
        "markets_csv":  DATA_DIR / "kxlowtchi_markets.csv",
        "prices_csv":   DATA_DIR / "kxlowtchi_prices.csv",
        "actuals_csv":  DATA_DIR / "kxlowtchi_actual_tmin_extended.csv",
        "vintage_cache": RESEARCH_DIR / "kxlowtchi_single_run_vintages_11am.csv",
        "label": "Chicago Midway Low",
    },
    "KXLOWTMIA": {
        "lat": 25.7959, "lon": -80.2870, "tz": "America/New_York",
        "markets_csv":  DATA_DIR / "kxlowtmia_markets.csv",
        "prices_csv":   DATA_DIR / "kxlowtmia_prices.csv",
        "actuals_csv":  DATA_DIR / "kxlowtmia_actual_tmin_extended.csv",
        "vintage_cache": RESEARCH_DIR / "kxlowtmia_single_run_vintages_11am.csv",
        "label": "Miami Low",
    },
    "KXLOWTAUS": {
        "lat": 30.1944, "lon": -97.6699, "tz": "America/Chicago",
        "markets_csv":  DATA_DIR / "kxlowtaus_markets.csv",
        "prices_csv":   DATA_DIR / "kxlowtaus_prices.csv",
        "actuals_csv":  DATA_DIR / "kxlowtaus_actual_tmin_extended.csv",
        "vintage_cache": RESEARCH_DIR / "kxlowtaus_single_run_vintages_11am.csv",
        "label": "Austin Low",
    },
    "KXLOWTLAX": {
        "lat": 33.9425, "lon": -118.4081, "tz": "America/Los_Angeles",
        "markets_csv":  DATA_DIR / "kxlowtlax_markets.csv",
        "prices_csv":   DATA_DIR / "kxlowtlax_prices.csv",
        "actuals_csv":  DATA_DIR / "kxlowtlax_actual_tmin_extended.csv",
        "vintage_cache": RESEARCH_DIR / "kxlowtlax_single_run_vintages_11am.csv",
        "label": "Los Angeles Low",
    },
    "KXLOWTDEN": {
        "lat": 39.8561, "lon": -104.6737, "tz": "America/Denver",
        "markets_csv":  DATA_DIR / "kxlowtden_markets.csv",
        "prices_csv":   DATA_DIR / "kxlowtden_prices.csv",
        "actuals_csv":  DATA_DIR / "kxlowtden_actual_tmin_extended.csv",
        "vintage_cache": RESEARCH_DIR / "kxlowtden_single_run_vintages_11am.csv",
        "label": "Denver Low",
    },
    "KXLOWTPHIL": {
        "lat": 39.8729, "lon": -75.2408, "tz": "America/New_York",
        "markets_csv":  DATA_DIR / "kxlowtphil_markets.csv",
        "prices_csv":   DATA_DIR / "kxlowtphil_prices.csv",
        "actuals_csv":  DATA_DIR / "kxlowtphil_actual_tmin_extended.csv",
        "vintage_cache": RESEARCH_DIR / "kxlowtphil_single_run_vintages_11am.csv",
        "label": "Philadelphia Low",
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


def decision_time_utc(target_date: str, city_tz: str = "America/New_York") -> datetime:
    day = datetime.strptime(target_date, "%Y-%m-%d").date()
    tz = ZoneInfo(city_tz)
    return datetime.combine(day, ENTRY_CLOCK, tz).astimezone(UTC)


def choose_vintage(target_date: str, model_key: str, city_tz: str = "America/New_York"):
    spec = MODEL_SPECS[model_key]
    decision_utc = decision_time_utc(target_date, city_tz)
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
    headers = {"User-Agent": "prediction-market-analysis/kxlow-backtest"}
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


def fetch_vintage_tmin(target_date: str, model_key: str, lat: float, lon: float,
                       city_tz: str = "America/New_York") -> float | None:
    result = choose_vintage(target_date, model_key, city_tz)
    if result is None:
        return None
    cycle, available, api_model = result
    params = {
        "latitude": lat, "longitude": lon,
        "run": cycle.strftime("%Y-%m-%dT%H:%M"),
        "forecast_days": 3, "daily": "temperature_2m_min",
        "models": api_model, "temperature_unit": "fahrenheit",
        "timezone": city_tz,
    }
    data = request_json(SINGLE_RUNS_URL, params)
    times = data.get("daily", {}).get("time", [])
    values = data.get("daily", {}).get("temperature_2m_min", [])
    for day, val in zip(times, values):
        if str(day) == target_date and val is not None:
            return float(val)
    return None


def build_vintage_features(city: str, target_dates: list[str], refresh: bool = False) -> pd.DataFrame:
    cfg = CITY_CONFIG[city]
    cache_path = cfg["vintage_cache"]
    lat, lon = cfg["lat"], cfg["lon"]
    city_tz = cfg["tz"]

    cache = pd.DataFrame()
    if cache_path.exists() and not refresh:
        try:
            cache = pd.read_csv(cache_path)
        except pd.errors.EmptyDataError:
            pass

    rows = cache.to_dict("records") if not cache.empty else []
    existing = set()
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
            result = choose_vintage(target_date, model_key, city_tz)
            if result is None:
                continue
            cycle, available, api_model = result
            needed.append((target_date, model_key, cycle, available, api_model))

    if needed:
        def _fetch_one(args):
            target_date, model_key, cycle, available, api_model = args
            try:
                mint = fetch_vintage_tmin(target_date, model_key, lat, lon, city_tz=city_tz)
            except Exception:
                mint = None
            return {
                "target_date": target_date, "model_key": model_key,
                "api_model": api_model,
                "cycle_init_utc": cycle.isoformat(),
                "available_at_utc": available.isoformat(),
                "decision_time_utc": decision_time_utc(target_date, city_tz).isoformat(),
                "mint_f": mint if mint is not None else np.nan,
                "error": "" if mint is not None else "no_value",
            }

        from concurrent.futures import ThreadPoolExecutor, as_completed
        fetched = 0
        total_needed = len(needed)
        print(f"  [{city}] fetching {total_needed} vintage TMIN entries (8 workers)...", flush=True)
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_fetch_one, arg): arg for arg in needed}
            for future in as_completed(futures):
                rows.append(future.result())
                fetched += 1
                if fetched % 50 == 0:
                    pd.DataFrame(rows).to_csv(cache_path, index=False)
                    print(f"  [{city}] vintage fetch: {fetched}/{total_needed}", flush=True)

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["target_date", "model_key"]).drop_duplicates(["target_date", "model_key"], keep="last")
        out.to_csv(cache_path, index=False)

    if out.empty:
        return pd.DataFrame(columns=["target_date", *MODEL_COLS])

    valid = out.copy()
    valid["mint_f"] = pd.to_numeric(valid["mint_f"], errors="coerce")
    wide = valid.pivot_table(index="target_date", columns="model_key", values="mint_f", aggfunc="last")
    wide = wide.rename(columns={k: MODEL_SPECS[k]["feature"] for k in MODEL_KEYS}).reset_index()
    for col in MODEL_COLS:
        if col not in wide.columns:
            wide[col] = np.nan
    return wide[["target_date", *MODEL_COLS]]


def add_features(daily: pd.DataFrame) -> pd.DataFrame:
    out = daily.dropna(subset=MODEL_COLS).copy()
    out["target_date_dt"] = pd.to_datetime(out["target_date"])
    out["consensus"] = out[MODEL_COLS].mean(axis=1)
    out["model_spread"] = out[MODEL_COLS].std(axis=1)
    out["physics_mean"] = out[["gfs_mint", "ecmwf_mint"]].mean(axis=1)
    out["ai_mean"] = out[["icon_mint", "gem_mint"]].mean(axis=1)
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
    desired = full_kelly * 0.25 * bankroll
    return min(desired, bankroll * MAX_TRADE_PCT)


def simulate_city(city: str, end_date: str, refresh: bool = False) -> pd.DataFrame:
    cfg = CITY_CONFIG[city]
    city_tz = cfg["tz"]

    # --- Load markets (eval period: Jan 28, 2026+) ---
    markets = pd.read_csv(cfg["markets_csv"])
    markets["target_date"] = markets["target_date"].astype(str)
    markets["floor_strike"] = pd.to_numeric(markets["floor_strike"], errors="coerce")
    markets["cap_strike"] = pd.to_numeric(markets["cap_strike"], errors="coerce")
    markets["bracket_type"] = markets.apply(
        lambda r: "wing_low" if pd.isna(r["floor_strike"]) else
                  "wing_high" if pd.isna(r["cap_strike"]) else "central", axis=1)
    markets["kalshi_result_yes"] = markets["settlement_value"].astype(str).str.lower().eq("yes")
    markets = markets[
        (markets["target_date"] >= TRAIN_CUTOFF) & (markets["target_date"] <= end_date)
    ].copy()

    prices = pd.read_csv(cfg["prices_csv"])
    prices["target_date"] = prices["target_date"].astype(str)

    # --- Load IEM actuals (full history: training + eval) ---
    all_actuals = pd.read_csv(cfg["actuals_csv"]).rename(
        columns={"date": "target_date", "min_temp_f": "actual_temp"})
    all_actuals["target_date"] = all_actuals["target_date"].astype(str)

    # Also pull settlement temps from the markets CSV where available
    kalshi_actuals = (
        markets[markets["kalshi_result_yes"] & markets["raw_settlement_temp"].notna()]
        [["target_date", "raw_settlement_temp"]]
        .drop_duplicates("target_date")
        .rename(columns={"raw_settlement_temp": "actual_temp_kalshi"})
    )

    # Training actuals: pre-market IEM data
    train_actuals = all_actuals[
        (all_actuals["target_date"] >= TRAINING_START) &
        (all_actuals["target_date"] < TRAIN_CUTOFF)
    ].copy()

    # Eval actuals: market dates, IEM + Kalshi fallback
    eval_market_dates = sorted(markets["target_date"].unique())
    eval_actuals = (
        pd.DataFrame({"target_date": eval_market_dates})
        .merge(all_actuals[["target_date", "actual_temp"]], on="target_date", how="left")
        .merge(kalshi_actuals, on="target_date", how="left")
    )
    eval_actuals["actual_temp"] = eval_actuals["actual_temp"].fillna(
        pd.to_numeric(eval_actuals["actual_temp_kalshi"], errors="coerce"))
    eval_actuals = eval_actuals[["target_date", "actual_temp"]].dropna(subset=["actual_temp"])

    print(f"  {city}: {len(train_actuals)} training days, {len(eval_actuals)} eval days", flush=True)
    if len(train_actuals) < 30:
        raise RuntimeError(
            f"{city}: only {len(train_actuals)} pre-market training days "
            f"(run fetch_tmin_training_data.py --city {city})")

    # --- Fetch vintages for all dates (training + eval) ---
    all_dates = sorted(set(train_actuals["target_date"].tolist() + eval_actuals["target_date"].tolist()))
    vintages = build_vintage_features(city, all_dates, refresh=refresh)

    # --- Build training features ---
    train_df = train_actuals.merge(vintages, on="target_date", how="inner")
    train_df = add_features(train_df)

    if len(train_df) < 30:
        raise RuntimeError(
            f"{city}: only {len(train_df)} training rows after vintage merge "
            f"(Single Runs API may not have data back to {TRAINING_START})")

    # --- Fit EMOS ---
    model = EMOSGumbelHeteroModel().fit(
        train_df[FEATURES].to_numpy(dtype=float),
        train_df["actual_temp"].to_numpy(dtype=float),
    )
    print(f"  {city}: EMOS trained on {len(train_df)} days", flush=True)

    # --- Build eval frame ---
    eval_df = eval_actuals.merge(vintages, on="target_date", how="inner")
    eval_df = add_features(eval_df)
    eval_dates = set(eval_df["target_date"])

    rows_merged = markets.merge(prices, on=["ticker", "target_date"], how="left")
    rows_merged = rows_merged.merge(eval_df[["target_date", *FEATURES]], on="target_date", how="inner")

    trades = []
    for target_date, day_group in rows_merged[rows_merged["target_date"].isin(eval_dates)].groupby("target_date", sort=True):
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
                "train_days": len(train_df),
                "eval_days": len(eval_df),
            })

    return pd.DataFrame(trades)


def simulate_capital(all_trades: pd.DataFrame, starting_capital: float = STARTING_CAPITAL) -> pd.DataFrame:
    if all_trades.empty:
        return pd.DataFrame()
    records = []
    bankroll = starting_capital
    all_trades = all_trades.sort_values(["date", "city", "ticker"]).reset_index(drop=True)
    for _, trade in all_trades.iterrows():
        prob_dir = float(trade["probability"]) if trade["direction"] == "YES" else 1.0 - float(trade["probability"])
        stake = quarter_kelly_stake(bankroll, prob_dir, trade["entry_price"])
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
            "bankroll_end": g["bankroll_after"].iloc[-1],
        })
    return pd.DataFrame(rows)


def write_report(city_summaries: dict, capital_df: pd.DataFrame, monthly: pd.DataFrame) -> None:
    from datetime import datetime, UTC
    lines = [
        "# KXLOWT Daily Low Temperature Backtest\n\n",
        f"Generated: {datetime.now(tz=UTC).isoformat(timespec='seconds')}\n",
        f"Model: EMOS_GUMBEL_HETERO on daily TMIN forecasts\n",
        f"Training: {TRAINING_START} – {TRAIN_CUTOFF} (pre-market IEM actuals + Single Runs API)\n",
        f"Eval: {TRAIN_CUTOFF}+ (actual KXLOWT markets)  |  YES filter: {YES_MIN_GAP_PP:.0f}–{YES_MAX_GAP_PP:.0f}pp gap\n\n",
        "## Per-City Results (unit-sized, leakage-safe)\n\n",
        "| City | Trades | Win% | Net PnL | Sharpe | YES | NO | Train days | Eval days |\n",
        "|------|--------|------|---------|--------|-----|----|-----------|-----------|\n",
    ]
    for city, s in city_summaries.items():
        lines.append(
            f"| {city} | {s['trades']} | {s['win_rate']:.1%} | ${s['net_pnl']:.2f} | "
            f"{s['sharpe']:.3f} | {s['yes_trades']} ({s['yes_wr']:.0%}) | "
            f"{s['no_trades']} ({s['no_wr']:.0%}) | {s['train_days']} | {s['eval_days']} |\n"
        )

    lines.append("\n## Capital Simulation ($500 quarter-Kelly, all cities combined)\n\n")
    total_net = capital_df["net_dollars"].sum() if not capital_df.empty else 0
    final_br = capital_df["bankroll_after"].iloc[-1] if not capital_df.empty else STARTING_CAPITAL
    lines.append(f"- Starting: ${STARTING_CAPITAL:.0f}  →  Final: ${final_br:.2f}  (+${final_br - STARTING_CAPITAL:.2f})\n")
    lines.append(f"- Total trades: {len(capital_df)}\n")
    if not capital_df.empty:
        lines.append(f"- Win rate: {capital_df['win'].mean():.1%}\n")
        lines.append(f"- Net P&L: ${total_net:.2f}\n")
        lines.append(f"- Sharpe: {sharpe(capital_df['net_dollars']):.3f}\n")
        lines.append(f"- Max drawdown: ${max_drawdown(capital_df['net_dollars']):.2f}\n")

    lines.append("\n## Monthly Breakdown\n\n")
    lines.append("| Month | Trades | Cities | Win% | Net P&L | Bankroll End |\n")
    lines.append("|---|---|---|---|---|---|\n")
    for _, r in monthly.iterrows():
        lines.append(
            f"| {r['month']} | {r['trades']} | {r['cities']} | {r['win_rate']:.1%} | "
            f"${r['net_pnl']:.2f} | ${r['bankroll_end']:.2f} |\n"
        )

    report_path = REPORTS_DIR / "kxlow_backtest.md"
    report_path.write_text("".join(lines))
    print(f"Report: {report_path.relative_to(ROOT)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-fetch", action="store_true")
    parser.add_argument("--end-date", default="2026-05-04")
    parser.add_argument("--cities", nargs="+", default=list(CITY_CONFIG.keys()))
    args = parser.parse_args()

    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    city_dfs = {}
    city_summaries = {}

    for city in args.cities:
        if city not in CITY_CONFIG:
            print(f"Unknown city {city}, skipping")
            continue
        cfg = CITY_CONFIG[city]
        missing = [k for k in ("markets_csv", "prices_csv", "actuals_csv") if not cfg[k].exists()]
        if missing:
            print(f"  {city}: missing {[cfg[k].name for k in missing]} — run fetch scripts first")
            continue

        print(f"\n=== {city} ({cfg['label']}) ===", flush=True)
        try:
            df = simulate_city(city, args.end_date, refresh=not args.skip_fetch)
        except Exception as exc:
            print(f"  {city}: SKIPPED — {exc}")
            continue

        if df.empty:
            print(f"  No qualifying trades for {city}")
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
            "train_days": int(df["train_days"].iloc[0]),
            "eval_days": int(df["eval_days"].iloc[0]),
        }
        city_dfs[city] = df
        print(f"  trades={len(df)}, WR={df['win'].mean():.1%}, "
              f"PnL=${df['net'].sum():.2f}, Sharpe={sharpe(df['net']):.3f}")

    if not city_dfs:
        print("No data. Run fetch scripts first.")
        return 1

    all_trades = pd.concat(city_dfs.values(), ignore_index=True)
    capital_df = simulate_capital(all_trades, STARTING_CAPITAL)
    monthly = monthly_summary(capital_df) if not capital_df.empty else pd.DataFrame()

    all_trades.to_csv(RESEARCH_DIR / "kxlow_trades.csv", index=False)
    if not capital_df.empty:
        capital_df.to_csv(RESEARCH_DIR / "kxlow_capital_trades.csv", index=False)
    if not monthly.empty:
        monthly.to_csv(RESEARCH_DIR / "kxlow_monthly.csv", index=False)

    write_report(city_summaries, capital_df, monthly)

    print("\n=== COMBINED KXLOWT RESULTS ===")
    if not capital_df.empty:
        final_br = capital_df["bankroll_after"].iloc[-1]
        print(f"Starting: ${STARTING_CAPITAL:.0f}  →  Final: ${final_br:.2f} (+${final_br - STARTING_CAPITAL:.2f})")
        print(f"Trades:   {len(capital_df)}  WR: {capital_df['win'].mean():.1%}")
        print(f"Net P&L:  ${capital_df['net_dollars'].sum():.2f}")
        print(f"Sharpe:   {sharpe(capital_df['net_dollars']):.3f}")
        print(f"Max DD:   ${max_drawdown(capital_df['net_dollars']):.2f}")
        print("\n=== MONTHLY ===")
        for _, r in monthly.iterrows():
            print(f"  {r['month']}: {r['trades']} trades ({r['cities']} cities), "
                  f"WR={r['win_rate']:.1%}, PnL=${r['net_pnl']:.2f}, bankroll=${r['bankroll_end']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
