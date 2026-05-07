#!/usr/bin/env python3
"""Strategy 3 / BRACKET_LOCK backtest.

Strategy 3 is the late-day YES entry:
  1. At 3 PM ET, use the observed KNYC running high.
  2. Map that observed high to the active Kalshi central bracket.
  3. Enter YES only if the observed high is at least 1F below the bracket cap.

This script reports two views:
  - Historical snapshot backtest using `data/kxhighny_prices.csv` 3 PM prices.
  - Predexon orderbook validation using actual 3 PM top-of-book snapshots.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

ASOS_CSV = ROOT / "data" / "research" / "knyc_intraday_asos.csv"
CLI_CSV = ROOT / "data" / "knyc_actual_temps_extended.csv"
PRICES_CSV = ROOT / "data" / "kxhighny_prices.csv"
MARKETS_CSV = ROOT / "data" / "kxhighny_markets.csv"
ORDERBOOKS_3PM = ROOT / "data" / "research" / "predexon_orderbooks_3pm.parquet"

OUT_TRADES = ROOT / "data" / "research" / "strategy3_bracket_lock_trades.csv"
OUT_SUMMARY = ROOT / "data" / "research" / "strategy3_bracket_lock_summary.csv"
REPORT_MD = ROOT / "reports" / "strategy3_bracket_lock_backtest.md"

CONTRACTS = 100
MIN_UPPER_MARGIN_F = 1.0


def kalshi_maker_fee(price: float, contracts: int = CONTRACTS) -> float:
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
    return float((equity - equity.cummax()).min())


def pnl(entry_price: float, won: bool, contracts: int = CONTRACTS) -> float:
    gross = (1.0 - entry_price) * contracts if won else -entry_price * contracts
    return gross - kalshi_maker_fee(entry_price, contracts)


def running_max_at_3pm(asos_day: pd.DataFrame) -> float | None:
    # At 3:00 PM, the last full hourly KNYC METAR is typically 2:51 PM.
    rows = asos_day[(asos_day["hour_et"] < 15) | ((asos_day["hour_et"] == 15) & (asos_day["minute_et"] <= 0))]
    if rows.empty:
        return None
    return float(rows["tmpf"].max())


def bracket_mid_for_cli(cli_high: int, available_mids: list[float]) -> float | None:
    for mid in sorted(available_mids):
        lo = int(mid - 0.5)
        hi = int(mid + 0.5)
        if lo <= cli_high <= hi:
            return mid
    return None


def predicted_mid_from_running_max(running_max: float, available_mids: list[float]) -> tuple[float | None, float]:
    rounded_high = int(round(running_max))
    mid = bracket_mid_for_cli(rounded_high, available_mids)
    if mid is None:
        return None, 0.0
    upper_margin = (mid + 0.5) - running_max
    return mid, max(0.0, upper_margin)


def load_asos() -> pd.DataFrame:
    asos = pd.read_csv(ASOS_CSV)
    asos["date"] = asos["date"].astype(str)
    return asos


def load_cli_map() -> dict[str, float]:
    cli = pd.read_csv(CLI_CSV)
    cli["date"] = pd.to_datetime(cli["date"]).dt.date.astype(str)
    return dict(zip(cli["date"], cli["max_temp_f"]))


def load_snapshot_prices() -> pd.DataFrame:
    prices = pd.read_csv(PRICES_CSV)
    prices = prices[prices["ticker"].str.contains("-B", na=False)].copy()
    prices["target_date"] = prices["target_date"].astype(str)
    prices["mid"] = prices["ticker"].str.extract(r"-B([0-9.]+)")[0].astype(float)
    return prices


def snapshot_backtest() -> pd.DataFrame:
    asos = load_asos()
    cli_map = load_cli_map()
    prices = load_snapshot_prices()

    rows = []
    for date, prices_day in prices.groupby("target_date"):
        cli = cli_map.get(str(date))
        if cli is None or pd.isna(cli):
            continue
        asos_day = asos[asos["date"] == str(date)]
        running_max = running_max_at_3pm(asos_day)
        if running_max is None:
            continue

        mids = sorted(prices_day["mid"].unique().tolist())
        predicted_mid, upper_margin = predicted_mid_from_running_max(running_max, mids)
        if predicted_mid is None or upper_margin < MIN_UPPER_MARGIN_F:
            continue

        winning_mid = bracket_mid_for_cli(int(round(cli)), mids)
        if winning_mid is None:
            continue

        match = prices_day[prices_day["mid"] == predicted_mid]
        if match.empty:
            continue
        row = match.iloc[0]
        entry = float(row["yes_price_3PM"])
        if not (0.01 <= entry <= 0.99):
            continue
        won = predicted_mid == winning_mid
        rows.append(
            {
                "source": "historical_3pm_snapshot",
                "date": str(date),
                "ticker": row["ticker"],
                "entry_price": entry,
                "running_max_3pm": running_max,
                "cli_high": cli,
                "predicted_mid": predicted_mid,
                "winning_mid": winning_mid,
                "upper_margin_f": upper_margin,
                "won": won,
                "pnl": pnl(entry, won),
            }
        )
    return pd.DataFrame(rows)


def load_predexon_books() -> pd.DataFrame:
    if not ORDERBOOKS_3PM.exists():
        return pd.DataFrame()
    books = pd.read_parquet(ORDERBOOKS_3PM)
    books = books.dropna(subset=["timestamp_ms", "best_bid", "best_ask"]).copy()
    if books.empty:
        return books
    books["target_date"] = books["target_date"].astype(str)
    books["ticker"] = books["ticker"].astype(str)
    idx = books.sort_values("timestamp_ms").groupby(["target_date", "ticker"], sort=False).tail(1).index
    latest = books.loc[idx].copy()
    latest["yes_bid"] = latest["best_bid"] / 100.0
    latest["yes_ask"] = latest["best_ask"] / 100.0
    return latest


def predexon_backtest() -> pd.DataFrame:
    markets = pd.read_csv(MARKETS_CSV)
    markets["target_date"] = markets["target_date"].astype(str)
    markets = markets[(markets["target_date"] >= "2026-01-07") & (markets["bracket_type"] == "central")].copy()
    asos = load_asos()
    books = load_predexon_books()
    if books.empty:
        return pd.DataFrame()

    rows = []
    for date, markets_day in markets.groupby("target_date"):
        asos_day = asos[asos["date"] == str(date)]
        running_max = running_max_at_3pm(asos_day)
        if running_max is None:
            continue

        predicted = None
        rounded_high = int(round(running_max))
        for _, market in markets_day.sort_values("floor_strike").iterrows():
            if int(market["floor_strike"]) <= rounded_high <= int(market["cap_strike"]):
                predicted = market
                break
        if predicted is None:
            continue

        upper_margin = float(predicted["cap_strike"]) - running_max
        if upper_margin < MIN_UPPER_MARGIN_F:
            continue

        ticker = str(predicted["ticker"])
        book = books[(books["target_date"] == str(date)) & (books["ticker"] == ticker)]
        if book.empty:
            continue
        b = book.iloc[0]
        entry = float(b["yes_bid"])
        if not (0.01 <= entry <= 0.99):
            continue

        won = str(predicted["settlement_value"]).lower() == "yes"
        rows.append(
            {
                "source": "predexon_3pm_orderbook",
                "date": str(date),
                "ticker": ticker,
                "entry_price": entry,
                "running_max_3pm": running_max,
                "cli_high": np.nan,
                "predicted_mid": np.nan,
                "winning_mid": np.nan,
                "upper_margin_f": upper_margin,
                "won": won,
                "pnl": pnl(entry, won),
                "bid_depth": b.get("bid_depth", 0),
                "ask_depth": b.get("ask_depth", 0),
            }
        )
    return pd.DataFrame(rows)


def summarize(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for source, group in trades.groupby("source", sort=False):
        rows.append(
            {
                "source": source,
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
    return pd.DataFrame(rows)


def write_report(summary: pd.DataFrame, trades: pd.DataFrame) -> None:
    lines = [
        "# Strategy 3 BRACKET_LOCK Backtest\n\n",
        "Strategy 3 buys YES on the central KXHIGHNY bracket implied by the 3 PM ET observed running high.\n\n",
        f"Rule: enter only when upper margin is at least {MIN_UPPER_MARGIN_F:.1f}F. PnL assumes {CONTRACTS} maker contracts and the real Kalshi maker fee formula.\n\n",
        "## Summary\n\n",
        "```text\n",
        summary.to_string(index=False),
        "\n```\n\n",
    ]
    for source, group in trades.groupby("source", sort=False):
        lines.extend(
            [
                f"## {source}\n\n",
                f"- Date range: {group['date'].min()} to {group['date'].max()}\n",
                f"- Trades: {len(group)}\n",
                f"- Win rate: {group['won'].mean():.1%}\n",
                f"- Avg entry: {group['entry_price'].mean():.3f}\n",
                f"- Total PnL: ${group['pnl'].sum():.2f}\n",
                f"- EV/trade: ${group['pnl'].mean():.2f}\n",
                f"- Max drawdown: ${max_drawdown(group['pnl']):.2f}\n\n",
            ]
        )
        worst = group.sort_values("pnl").head(8)
        lines.extend(["Worst trades:\n\n", "```text\n", worst.to_string(index=False), "\n```\n\n"])
    REPORT_MD.write_text("".join(lines))


def main() -> None:
    snapshot = snapshot_backtest()
    predexon = predexon_backtest()
    trades = pd.concat([snapshot, predexon], ignore_index=True)
    summary = summarize(trades)

    OUT_TRADES.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    trades.to_csv(OUT_TRADES, index=False)
    summary.to_csv(OUT_SUMMARY, index=False)
    write_report(summary, trades)

    print(summary.to_string(index=False))
    print(f"Wrote {OUT_TRADES}")
    print(f"Wrote {OUT_SUMMARY}")
    print(f"Wrote {REPORT_MD}")


if __name__ == "__main__":
    main()
