#!/usr/bin/env python3
"""Strategy 1 and Strategy 3 backtest using Predexon 3 PM orderbooks.

Strategy 3: BRACKET_LOCK YES on the bracket implied by the 3 PM observed high.
Strategy 1: NO overlay on clearly wrong brackets after Strategy 3 confirms the event.

This is event-level research only. It uses orderbook top-of-book snapshots and
does not claim passive maker queue fills.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ASOS_CSV = ROOT / "data" / "research" / "knyc_intraday_asos.csv"
MARKETS_CSV = ROOT / "data" / "kxhighny_markets.csv"
ORDERBOOKS_3PM = ROOT / "data" / "research" / "predexon_orderbooks_3pm.parquet"
OUT_TRADES = ROOT / "data" / "research" / "strategy13_predexon_trades.csv"
OUT_SUMMARY = ROOT / "data" / "research" / "strategy13_predexon_summary.csv"
REPORT_MD = ROOT / "reports" / "strategy13_predexon_backtest.md"

CONTRACTS = 100
ENTRY_TIME_LABEL = "3:00 PM ET"


def kalshi_fee(price: float, contracts: int = CONTRACTS) -> float:
    return math.ceil(0.0175 * contracts * price * (1 - price) * 100) / 100


def sharpe(values: pd.Series) -> float:
    arr = values.astype(float).to_numpy()
    if len(arr) < 2:
        return 0.0
    std = float(np.std(arr, ddof=1))
    return 0.0 if std == 0 else float(np.mean(arr) / std)


def max_drawdown(values: pd.Series) -> float:
    equity = values.astype(float).cumsum()
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    return float((equity - peak).min())


def running_max_at_3pm(asos_day: pd.DataFrame) -> float | None:
    # At exactly 3 PM, the most recent hourly KNYC observation is typically 2:51 PM.
    subset = asos_day[(asos_day["hour_et"] < 15) | ((asos_day["hour_et"] == 15) & (asos_day["minute_et"] <= 0))]
    if subset.empty:
        return None
    return float(subset["tmpf"].max())


def bracket_for_temp(temp_f: float, markets_day: pd.DataFrame) -> pd.Series | None:
    rounded = int(round(temp_f))
    central = markets_day[markets_day["bracket_type"] == "central"].copy()
    for _, row in central.sort_values("floor_strike").iterrows():
        if int(row["floor_strike"]) <= rounded <= int(row["cap_strike"]):
            return row
    return None


def conservative_upper_margin(temp_f: float, bracket: pd.Series) -> float:
    # Same conservative concept as the existing BRACKET_LOCK research: require the
    # running high to be at least 1F below the bracket's integer cap.
    return float(bracket["cap_strike"]) - temp_f


def orderbook_at_entry(orderbooks: pd.DataFrame) -> pd.DataFrame:
    ob = orderbooks.copy()
    ob = ob.dropna(subset=["timestamp_ms", "best_bid", "best_ask"])
    if ob.empty:
        return ob
    ob["target_date"] = ob["target_date"].astype(str)
    ob["ticker"] = ob["ticker"].astype(str)
    # Use last snapshot at or before the end of the 2:55-3:05 collection window.
    idx = ob.sort_values("timestamp_ms").groupby(["target_date", "ticker"], sort=False).tail(1).index
    latest = ob.loc[idx].copy()
    latest["yes_bid"] = latest["best_bid"] / 100.0
    latest["yes_ask"] = latest["best_ask"] / 100.0
    latest["no_bid"] = (100 - latest["best_ask"]) / 100.0
    latest["no_ask"] = (100 - latest["best_bid"]) / 100.0
    return latest


def pnl_for_leg(direction: str, entry_price: float, won: bool, contracts: int = CONTRACTS) -> float:
    gross = (1.0 - entry_price) * contracts if won else -entry_price * contracts
    return gross - kalshi_fee(entry_price, contracts)


def build_strategy3_trades(markets: pd.DataFrame, asos: pd.DataFrame, books: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for date, markets_day in markets.groupby("target_date"):
        asos_day = asos[asos["date"] == date]
        rmax = running_max_at_3pm(asos_day)
        if rmax is None:
            continue

        predicted = bracket_for_temp(rmax, markets_day)
        if predicted is None:
            continue
        margin = conservative_upper_margin(rmax, predicted)
        if margin < 1.0:
            continue

        ticker = str(predicted["ticker"])
        book = books[(books["target_date"] == date) & (books["ticker"] == ticker)]
        if book.empty:
            continue
        b = book.iloc[0]
        entry = float(b["yes_bid"])
        if not (0.01 <= entry <= 0.99):
            continue

        won = str(predicted["settlement_value"]).lower() == "yes"
        rows.append(
            {
                "date": date,
                "strategy": "S3_BRACKET_LOCK_YES",
                "ticker": ticker,
                "direction": "YES",
                "entry_price": entry,
                "running_max_3pm": rmax,
                "upper_margin_f": margin,
                "won": won,
                "pnl": pnl_for_leg("YES", entry, won),
                "bid_depth": b.get("bid_depth", 0),
                "ask_depth": b.get("ask_depth", 0),
            }
        )
    return pd.DataFrame(rows)


def build_strategy1_overlay(markets: pd.DataFrame, books: pd.DataFrame, s3: pd.DataFrame) -> pd.DataFrame:
    rows = []
    s3_keys = s3[["date", "running_max_3pm"]].drop_duplicates()
    for _, signal in s3_keys.iterrows():
        date = str(signal["date"])
        rmax = float(signal["running_max_3pm"])
        markets_day = markets[markets["target_date"] == date]
        predicted = bracket_for_temp(rmax, markets_day)
        if predicted is None:
            continue
        pred_floor = float(predicted["floor_strike"])

        for _, market in markets_day.iterrows():
            ticker = str(market["ticker"])
            if ticker == str(predicted["ticker"]):
                continue
            book = books[(books["target_date"] == date) & (books["ticker"] == ticker)]
            if book.empty:
                continue
            b = book.iloc[0]

            # Strategy 1 overlay: buy NO on far-away wrong central brackets only.
            # Tail markets have asymmetric rules and are deliberately excluded here.
            if market["bracket_type"] != "central":
                continue
            dist = abs(float(market["floor_strike"]) - pred_floor)
            if dist < 4.0:
                continue

            entry = float(b["no_bid"])
            if not (0.85 <= entry <= 0.99):
                continue
            won = str(market["settlement_value"]).lower() == "no"
            rows.append(
                {
                    "date": date,
                    "strategy": "S1_FAR_BRACKET_NO_OVERLAY",
                    "ticker": ticker,
                    "direction": "NO",
                    "entry_price": entry,
                    "running_max_3pm": rmax,
                    "upper_margin_f": float(signal.get("upper_margin_f", np.nan)),
                    "won": won,
                    "pnl": pnl_for_leg("NO", entry, won),
                    "distance_from_pred_floor_f": dist,
                    "bid_depth": b.get("bid_depth", 0),
                    "ask_depth": b.get("ask_depth", 0),
                }
            )
    return pd.DataFrame(rows)


def summarize(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for strategy, group in trades.groupby("strategy"):
        rows.append(
            {
                "strategy": strategy,
                "trades": len(group),
                "days": group["date"].nunique(),
                "win_rate": group["won"].mean(),
                "avg_entry_price": group["entry_price"].mean(),
                "total_pnl": group["pnl"].sum(),
                "ev_per_trade": group["pnl"].mean(),
                "sharpe": sharpe(group["pnl"]),
                "max_drawdown": max_drawdown(group["pnl"]),
            }
        )

    day = trades.groupby("date")["pnl"].sum().reset_index()
    if not day.empty:
        rows.append(
            {
                "strategy": "COMBINED_EVENT_PORTFOLIO",
                "trades": len(trades),
                "days": day["date"].nunique(),
                "win_rate": np.nan,
                "avg_entry_price": np.nan,
                "total_pnl": day["pnl"].sum(),
                "ev_per_trade": day["pnl"].mean(),
                "sharpe": sharpe(day["pnl"]),
                "max_drawdown": max_drawdown(day["pnl"]),
            }
        )
    return pd.DataFrame(rows)


def write_report(summary: pd.DataFrame, trades: pd.DataFrame) -> None:
    lines = [
        "# Strategy 1 + Strategy 3 Predexon 3 PM Backtest\n",
        "\n",
        f"Entry window: {ENTRY_TIME_LABEL}, using Predexon top-of-book snapshots.\n\n",
        "Strategy 3 buys YES on the BRACKET_LOCK bracket. Strategy 1 is a conservative NO overlay on far-away central brackets after Strategy 3 fires.\n\n",
        "## Summary\n\n",
        "```text\n",
        summary.to_string(index=False),
        "\n```\n\n",
        "## Notes\n\n",
        "- Prices are maker-style entries at visible best bid: YES uses `yes_bid`; NO uses implied `no_bid = 1 - yes_ask`.\n",
        "- This does not prove passive fill probability or queue position.\n",
        "- The Strategy 1 overlay excludes tail markets for now and only trades central brackets at least 4F away from the predicted bracket floor.\n",
        "- PnL assumes 100 contracts per leg and real Kalshi maker fee formula.\n",
    ]
    if not trades.empty:
        worst = trades.groupby("date")["pnl"].sum().sort_values().head(8)
        lines.extend(["\n## Worst Event Days\n\n", "```text\n", worst.to_string(), "\n```\n"])
    REPORT_MD.write_text("".join(lines))


def main() -> None:
    if not ORDERBOOKS_3PM.exists():
        raise SystemExit(f"Missing {ORDERBOOKS_3PM}; run research/data/fetch_predexon_3pm_orderbooks.py first")

    markets = pd.read_csv(MARKETS_CSV)
    markets["target_date"] = markets["target_date"].astype(str)
    markets = markets[markets["target_date"] >= "2026-01-07"].copy()
    asos = pd.read_csv(ASOS_CSV)
    asos["date"] = asos["date"].astype(str)
    raw_books = pd.read_parquet(ORDERBOOKS_3PM)
    books = orderbook_at_entry(raw_books)

    s3 = build_strategy3_trades(markets, asos, books)
    s1 = build_strategy1_overlay(markets, books, s3)
    trades = pd.concat([s3, s1], ignore_index=True)
    summary = summarize(trades) if not trades.empty else pd.DataFrame()

    OUT_TRADES.parent.mkdir(parents=True, exist_ok=True)
    trades.to_csv(OUT_TRADES, index=False)
    summary.to_csv(OUT_SUMMARY, index=False)
    write_report(summary, trades)

    print(summary.to_string(index=False))
    print(f"Wrote {OUT_TRADES}")
    print(f"Wrote {OUT_SUMMARY}")
    print(f"Wrote {REPORT_MD}")


if __name__ == "__main__":
    main()
