"""DEEP_TAIL_NO backtest using Kalshi 1-minute bid/ask candlesticks.

Kalshi candlesticks are not full orderbook snapshots, but they do provide
1-minute OHLC for best YES bid and best YES ask.  For binary markets:

    NO ask = 1 - YES bid
    NO bid = 1 - YES ask

This script tests the next-day 10:15 AM ET rule with official historical
candlestick bid/ask instead of trade prints.
"""

from __future__ import annotations

import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config


PREDICTIONS_CSV = ROOT / "data/research/model_bakeoff_nyc_predictions.csv"
CANDLE_CACHE = ROOT / "data/research/deep_tail_kalshi_1m_candles.parquet"
OUT_TRADES_CSV = ROOT / "data/research/deep_tail_candlestick_backtest_trades.csv"
OUT_SUMMARY_JSON = ROOT / "data/research/deep_tail_candlestick_backtest_summary.json"
OUT_REPORT_MD = ROOT / "reports/deep_tail_candlestick_backtest.md"

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
SERIES = "KXHIGHNY"
ET = ZoneInfo("America/New_York")
FOCUS_MODELS = ["EMOS_GUMBEL_HETERO", "EMOS_GUMBEL", "EMOS", "GUMBEL"]
STAKE_DOLLARS = 15.0


@dataclass(frozen=True)
class Scenario:
    name: str
    entry_day_offset: int
    entry_time: dt_time


@dataclass(frozen=True)
class StopPolicy:
    name: str
    stop_loss_diff: float | None


SCENARIOS = [
    Scenario("next_day_1015", -1, dt_time(10, 15)),
    Scenario("same_day_1015", 0, dt_time(10, 15)),
    Scenario("same_day_1100", 0, dt_time(11, 0)),
]

STOP_POLICIES = [
    StopPolicy("current_20c_stop", float(config.STOP_LOSS_DIFF)),
    StopPolicy("no_stop", None),
]


def local_dt(day: date, clock: dt_time) -> datetime:
    return datetime.combine(day, clock, tzinfo=ET)


def target_day_before(target_date: date) -> date:
    return target_date - timedelta(days=1)


def dollars(obj: dict | None, key: str = "close") -> float | None:
    if not isinstance(obj, dict):
        return None
    value = obj.get(f"{key}_dollars", obj.get(key))
    if value is None:
        return None
    return float(value)


def candle_row(ticker: str, target_date: str, candle: dict) -> dict:
    return {
        "ticker": ticker,
        "target_date": target_date,
        "end_ts": int(candle["end_period_ts"]),
        "yes_bid_open": dollars(candle.get("yes_bid"), "open"),
        "yes_bid_close": dollars(candle.get("yes_bid"), "close"),
        "yes_ask_open": dollars(candle.get("yes_ask"), "open"),
        "yes_ask_close": dollars(candle.get("yes_ask"), "close"),
        "price_close": dollars(candle.get("price"), "close"),
        "volume": float(candle.get("volume", candle.get("volume_fp", 0)) or 0),
    }


def fetch_candles(ticker: str, target_date: date) -> list[dict]:
    start = int(local_dt(target_day_before(target_date), dt_time(9, 30)).timestamp())
    end = int(local_dt(target_date, dt_time(23, 5)).timestamp())
    params = {"start_ts": start, "end_ts": end, "period_interval": 1}
    urls = [
        f"{KALSHI_BASE}/historical/markets/{ticker}/candlesticks",
        f"{KALSHI_BASE}/series/{SERIES}/markets/{ticker}/candlesticks",
    ]
    last_error = ""
    for url in urls:
        for attempt in range(4):
            try:
                response = requests.get(url, params=params, timeout=30)
                if response.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                if response.status_code == 404:
                    last_error = response.text[:200]
                    break
                response.raise_for_status()
                return response.json().get("candlesticks", [])
            except requests.RequestException as exc:
                last_error = str(exc)
                time.sleep(0.5 * (attempt + 1))
    print(f"WARNING: no candles for {ticker} {target_date}: {last_error}")
    return []


def load_candidates() -> pd.DataFrame:
    pred = pd.read_csv(PREDICTIONS_CSV, parse_dates=["date"])
    pred = pred[pred["model_name"].isin(FOCUS_MODELS)].copy()
    pred = pred[pred["probability"] < float(config.DEEP_TAIL_NO_PROB_MAX)].copy()
    pred = pred.rename(columns={"date": "target_date"})
    pred["target_date"] = pred["target_date"].dt.date
    return pred


def ensure_candles(candidates: pd.DataFrame, refresh: bool = False) -> pd.DataFrame:
    CANDLE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    existing = pd.DataFrame()
    cached_keys: set[tuple[str, str]] = set()
    if CANDLE_CACHE.exists() and not refresh:
        existing = pd.read_parquet(CANDLE_CACHE)
        if not existing.empty:
            existing["target_date"] = existing["target_date"].astype(str)
            cached_keys = set(zip(existing["ticker"].astype(str), existing["target_date"].astype(str)))

    ticker_dates = (
        candidates[["ticker", "target_date"]]
        .drop_duplicates()
        .sort_values(["target_date", "ticker"])
        .reset_index(drop=True)
    )
    rows = existing.to_dict("records") if not existing.empty else []
    fetched = 0
    skipped = 0
    for i, item in ticker_dates.iterrows():
        ticker = str(item["ticker"])
        target_date = item["target_date"]
        target_str = str(target_date)
        key = (ticker, target_str)
        if key in cached_keys:
            skipped += 1
            continue
        candles = fetch_candles(ticker, target_date)
        rows.extend(candle_row(ticker, target_str, candle) for candle in candles)
        fetched += 1
        if fetched % 25 == 0:
            print(f"  fetched {fetched}, skipped {skipped}, row {i + 1}/{len(ticker_dates)}")
            pd.DataFrame(rows).to_parquet(CANDLE_CACHE, index=False)
        time.sleep(0.03)

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["target_date", "ticker", "end_ts"]).reset_index(drop=True)
    out.to_parquet(CANDLE_CACHE, index=False)
    return out


def pick_entry(candles: pd.DataFrame, timestamp: datetime) -> pd.Series | None:
    cutoff = int(timestamp.timestamp())
    scoped = candles[candles["end_ts"] <= cutoff]
    if scoped.empty:
        return None
    return scoped.iloc[-1]


def simulate(candidates: pd.DataFrame, candles: pd.DataFrame) -> pd.DataFrame:
    candles = candles.copy()
    candles["target_date"] = candles["target_date"].astype(str)
    by_key = {
        key: group.sort_values("end_ts")
        for key, group in candles.groupby(["ticker", "target_date"], sort=False)
    }
    rows = []
    for stop_policy in STOP_POLICIES:
        for scenario in SCENARIOS:
            for item in candidates.to_dict("records"):
                target_date = item["target_date"]
                target_str = str(target_date)
                ticker = item["ticker"]
                group = by_key.get((ticker, target_str))
                if group is None or group.empty:
                    continue
                entry_dt = local_dt(target_date + timedelta(days=scenario.entry_day_offset), scenario.entry_time)
                entry = pick_entry(group, entry_dt)
                if entry is None or pd.isna(entry["yes_bid_close"]):
                    continue

                yes_bid = float(entry["yes_bid_close"])
                yes_ask = float(entry["yes_ask_close"]) if pd.notna(entry["yes_ask_close"]) else None
                if yes_bid <= float(config.DEEP_TAIL_NO_YES_PRICE_MIN):
                    continue
                no_entry = 1.0 - yes_bid  # executable NO ask, conservative for buying NO.
                if no_entry <= 0 or no_entry >= 1:
                    continue

                stop = None if stop_policy.stop_loss_diff is None else max(0.0, no_entry - stop_policy.stop_loss_diff)
                target = float(config.TARGET_EXIT_PRICE)
                exit_cutoff = int(local_dt(target_date, dt_time(23, 0)).timestamp())
                path = group[(group["end_ts"] > int(entry_dt.timestamp())) & (group["end_ts"] <= exit_cutoff)]

                exit_price = no_entry
                exit_reason = "NO_PATH_MARK_TO_ENTRY"
                exit_ts = None
                for c in path.itertuples(index=False):
                    if pd.isna(c.yes_ask_close):
                        continue
                    no_bid = 1.0 - float(c.yes_ask_close)  # conservative exit if selling NO.
                    exit_price = no_bid
                    exit_ts = c.end_ts
                    exit_reason = "TIME_LIMIT"
                    if no_entry < target and no_bid >= target:
                        exit_price = target
                        exit_reason = "TARGET"
                        break
                    if stop is not None and no_bid <= stop:
                        exit_reason = "STOP"
                        break

                settlement_exit = 0.0 if bool(item["kalshi_result_yes"]) else 1.0
                contracts = max(1, math.floor(STAKE_DOLLARS / no_entry))
                entry_fee = config.maker_fee(contracts, no_entry)
                exit_fee = config.maker_fee(contracts, exit_price)
                settlement_fee = config.maker_fee(contracts, settlement_exit)
                gross = contracts * (exit_price - no_entry)
                net = gross - entry_fee - exit_fee
                settlement_net = contracts * (settlement_exit - no_entry) - entry_fee - settlement_fee

                rows.append(
                    {
                        **item,
                        "target_date": target_str,
                        "scenario": scenario.name,
                        "stop_policy": stop_policy.name,
                        "stop_loss_diff": stop_policy.stop_loss_diff,
                        "entry_ts": int(entry_dt.timestamp()),
                        "entry_candle_ts": int(entry["end_ts"]),
                        "yes_bid_entry": yes_bid,
                        "yes_ask_entry": yes_ask,
                        "no_entry": round(no_entry, 4),
                        "contracts": contracts,
                        "exit_ts": exit_ts,
                        "exit_price": round(exit_price, 4),
                        "exit_reason": exit_reason,
                        "gross_pnl": round(gross, 4),
                        "net_pnl": round(net, 4),
                        "settlement_net_pnl": round(settlement_net, 4),
                        "trade_win": net > 0,
                        "settlement_win": settlement_exit > no_entry,
                    }
                )
    return pd.DataFrame(rows)


def sharpe(values: pd.Series) -> float | None:
    if len(values) < 2:
        return None
    std = float(values.std(ddof=1))
    if std == 0:
        return None
    return float(values.mean() / std * math.sqrt(252))


def max_drawdown(cum: pd.Series) -> float:
    if cum.empty:
        return 0.0
    return float((cum - cum.cummax()).min())


def summarize(trades: pd.DataFrame, candles: pd.DataFrame, candidates: pd.DataFrame) -> dict:
    results = []
    for (model, scenario, stop_policy), group in trades.groupby(["model_name", "scenario", "stop_policy"], sort=True):
        daily = group.groupby("target_date", sort=True)["net_pnl"].sum()
        results.append(
            {
                "model_name": model,
                "scenario": scenario,
                "stop_policy": stop_policy,
                "trades": int(len(group)),
                "target_days": int(group["target_date"].nunique()),
                "win_rate": float(group["trade_win"].mean()),
                "net_pnl": float(group["net_pnl"].sum()),
                "settlement_net_pnl": float(group["settlement_net_pnl"].sum()),
                "avg_yes_bid_entry": float(group["yes_bid_entry"].mean()),
                "avg_yes_ask_entry": float(group["yes_ask_entry"].mean()),
                "avg_no_entry": float(group["no_entry"].mean()),
                "sharpe_daily": sharpe(daily),
                "max_drawdown": max_drawdown(daily.cumsum()),
                "stop_rate": float((group["exit_reason"] == "STOP").mean()),
                "target_rate": float((group["exit_reason"] == "TARGET").mean()),
            }
        )
    return {
        "inputs": {
            "predictions_csv": str(PREDICTIONS_CSV.relative_to(ROOT)),
            "candle_cache": str(CANDLE_CACHE.relative_to(ROOT)),
            "candidate_rows": int(len(candidates)),
            "candidate_tickers": int(candidates["ticker"].nunique()),
            "candle_rows": int(len(candles)),
            "candle_tickers": int(candles["ticker"].nunique()) if not candles.empty else 0,
            "entry_pricing": "NO ask = 1 - 1m yes_bid_close",
            "exit_pricing": "NO bid = 1 - 1m yes_ask_close",
            "stop_policies": [
                {"name": policy.name, "stop_loss_diff": policy.stop_loss_diff}
                for policy in STOP_POLICIES
            ],
        },
        "results": results,
    }


def markdown_table(frame: pd.DataFrame) -> str:
    headers = [str(col) for col in frame.columns]
    rows = [[str(value) for value in row] for row in frame.to_numpy()]
    out = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    out.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(out)


def write_report(summary: dict) -> None:
    results = pd.DataFrame(summary["results"]).sort_values(["model_name", "scenario"])
    table = results[
        [
            "model_name",
            "scenario",
            "stop_policy",
            "trades",
            "target_days",
            "win_rate",
            "net_pnl",
            "sharpe_daily",
            "max_drawdown",
            "stop_rate",
            "target_rate",
        ]
    ].copy()
    for col in ["win_rate", "stop_rate", "target_rate"]:
        table[col] = (table[col] * 100).round(1).astype(str) + "%"
    for col in ["net_pnl", "sharpe_daily", "max_drawdown"]:
        table[col] = table[col].map(lambda x: "" if pd.isna(x) else f"{x:.2f}")
    lines = [
        "# DEEP_TAIL_NO Candlestick Bid/Ask Backtest",
        "",
        "Uses official Kalshi 1-minute candlestick bid/ask data, not trade prints.",
        "",
        f"- Candidate rows: {summary['inputs']['candidate_rows']}",
        f"- Candidate tickers: {summary['inputs']['candidate_tickers']}",
        f"- Candle rows cached: {summary['inputs']['candle_rows']}",
        f"- Candle tickers cached: {summary['inputs']['candle_tickers']}",
        "",
        "Entry is conservative buy-NO pricing: `NO ask = 1 - yes_bid_close`.",
        "Exit is conservative sell-NO pricing: `NO bid = 1 - yes_ask_close`.",
        "",
        "## Results",
        "",
        markdown_table(table),
        "",
    ]
    OUT_REPORT_MD.write_text("\n".join(lines))


def main() -> None:
    candidates = load_candidates()
    print(f"Candidates: {len(candidates):,} rows, {candidates['ticker'].nunique():,} tickers")
    candles = ensure_candles(candidates)
    print(f"Candles: {len(candles):,} rows, {candles['ticker'].nunique() if not candles.empty else 0:,} tickers")
    trades = simulate(candidates, candles)
    trades.to_csv(OUT_TRADES_CSV, index=False)
    summary = summarize(trades, candles, candidates)
    OUT_SUMMARY_JSON.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    write_report(summary)
    print(f"Wrote {OUT_TRADES_CSV.relative_to(ROOT)}")
    print(f"Wrote {OUT_SUMMARY_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_REPORT_MD.relative_to(ROOT)}")
    results = pd.DataFrame(summary["results"]).sort_values(["model_name", "scenario", "stop_policy"])
    print(results[["model_name", "scenario", "stop_policy", "trades", "win_rate", "net_pnl", "sharpe_daily", "max_drawdown", "stop_rate"]].to_string(index=False))


if __name__ == "__main__":
    main()
