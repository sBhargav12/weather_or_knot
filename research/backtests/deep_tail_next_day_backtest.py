"""Backtest the DEEP_TAIL_NO next-day 10:15 AM entry rule.

This isolates the live-code timing change:

- New rule: at 10:15 AM ET, only evaluate markets whose target date is tomorrow.
- Old mistaken interpretation: evaluate the same target date at 10:15 AM ET.

Inputs:
- Model probabilities: data/research/model_bakeoff_nyc_predictions.csv
- Intraday prices: full Becker/Kalshi trade tape in data/kalshi/trades/*.parquet

The Becker trade tape has trades, not historical order books.  For entry and
exit prices, this uses the latest traded YES price at or before the decision
time, matching the project convention that last trade is close enough to VWAP
for weather brackets.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[2]))

import config


PREDICTIONS_CSV = Path("data/research/model_bakeoff_nyc_predictions.csv")
TRADES_GLOB = "data/kalshi/trades/*.parquet"
OUT_TRADES_CSV = Path("data/research/deep_tail_next_day_backtest_trades.csv")
OUT_SUMMARY_JSON = Path("data/research/deep_tail_next_day_backtest_summary.json")
OUT_REPORT_MD = Path("reports/deep_tail_next_day_backtest.md")

ET = ZoneInfo("America/New_York")
ENTRY_TIME = time(10, 15)
MARKET_OPEN_TIME = time(10, 0)
TIME_EXIT = time(23, 0)
STAKE_DOLLARS = 15.0
FOCUS_MODELS = ["EMOS_GUMBEL_HETERO", "EMOS_GUMBEL", "EMOS", "GUMBEL"]


@dataclass(frozen=True)
class Scenario:
    name: str
    entry_day_offset: int
    entry_time: time


SCENARIOS = [
    Scenario("next_day_1015", -1, ENTRY_TIME),
    Scenario("same_day_1015", 0, ENTRY_TIME),
    Scenario("same_day_1100", 0, time(11, 0)),
]


def local_dt(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock, tzinfo=ET)


def iso_utc(ts: datetime) -> str:
    return ts.astimezone(ZoneInfo("UTC")).isoformat()


def maker_fee(contracts: int, price: float) -> float:
    return config.maker_fee(contracts, price)


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
    running_max = cum.cummax()
    return float((cum - running_max).min())


def load_candidates() -> pd.DataFrame:
    pred = pd.read_csv(PREDICTIONS_CSV, parse_dates=["date"])
    pred = pred[pred["model_name"].isin(FOCUS_MODELS)].copy()
    pred = pred[pred["probability"] < float(config.DEEP_TAIL_NO_PROB_MAX)].copy()
    pred = pred.rename(columns={"date": "target_date"})
    pred["target_date"] = pred["target_date"].dt.date
    pred["candidate_key"] = pred.index.astype(str)

    rows = []
    for scenario in SCENARIOS:
        frame = pred.copy()
        entry_dates = frame["target_date"].apply(lambda d: d + timedelta(days=scenario.entry_day_offset))
        open_dates = frame["target_date"].apply(lambda d: d - timedelta(days=1))
        frame["scenario"] = scenario.name
        frame["entry_utc"] = [iso_utc(local_dt(d, scenario.entry_time)) for d in entry_dates]
        frame["market_open_utc"] = [iso_utc(local_dt(d, MARKET_OPEN_TIME)) for d in open_dates]
        frame["time_exit_utc"] = [iso_utc(local_dt(d, TIME_EXIT)) for d in frame["target_date"]]
        frame["candidate_id"] = (
            frame["scenario"]
            + "|"
            + frame["model_name"]
            + "|"
            + frame["ticker"]
            + "|"
            + frame["target_date"].astype(str)
        )
        rows.append(frame)
    return pd.concat(rows, ignore_index=True)


def attach_entries(con: duckdb.DuckDBPyConnection, candidates: pd.DataFrame) -> pd.DataFrame:
    con.register("candidates", candidates)
    query = f"""
        SELECT
            c.*,
            arg_max(t.yes_price, t.created_time) / 100.0 AS yes_entry,
            max(t.created_time) AS entry_trade_time
        FROM candidates c
        LEFT JOIN read_parquet('{TRADES_GLOB}') t
          ON t.ticker = c.ticker
         AND t.created_time >= CAST(c.market_open_utc AS TIMESTAMPTZ)
         AND t.created_time <= CAST(c.entry_utc AS TIMESTAMPTZ)
        GROUP BY ALL
    """
    out = con.execute(query).fetchdf()
    out["entry_no_price"] = 1.0 - out["yes_entry"]
    out["entry_pass"] = out["yes_entry"] > float(config.DEEP_TAIL_NO_YES_PRICE_MIN)
    return out


def load_paths(con: duckdb.DuckDBPyConnection, entries: pd.DataFrame) -> pd.DataFrame:
    tradable = entries[entries["entry_pass"] & entries["yes_entry"].notna()].copy()
    con.register("tradable_entries", tradable[["candidate_id", "ticker", "entry_utc", "time_exit_utc"]])
    query = f"""
        SELECT
            c.candidate_id,
            t.created_time,
            t.yes_price / 100.0 AS yes_price
        FROM tradable_entries c
        JOIN read_parquet('{TRADES_GLOB}') t
          ON t.ticker = c.ticker
         AND t.created_time > CAST(c.entry_utc AS TIMESTAMPTZ)
         AND t.created_time <= CAST(c.time_exit_utc AS TIMESTAMPTZ)
        ORDER BY c.candidate_id, t.created_time
    """
    return con.execute(query).fetchdf()


def simulate_exits(entries: pd.DataFrame, paths: pd.DataFrame) -> pd.DataFrame:
    by_id = {key: grp for key, grp in paths.groupby("candidate_id", sort=False)}
    rows = []
    for row in entries[entries["entry_pass"] & entries["yes_entry"].notna()].to_dict("records"):
        entry = float(row["entry_no_price"])
        stop = max(0.0, entry - float(config.STOP_LOSS_DIFF))
        target = float(config.TARGET_EXIT_PRICE)
        exit_price = entry
        exit_reason = "NO_PATH_MARK_TO_ENTRY"
        exit_time = None
        path = by_id.get(row["candidate_id"])
        if path is not None and not path.empty:
            exit_reason = "TIME_LIMIT"
            for item in path.itertuples(index=False):
                side_price = 1.0 - float(item.yes_price)
                exit_price = side_price
                exit_time = item.created_time
                if entry < target and side_price >= target:
                    exit_price = target
                    exit_reason = "TARGET"
                    break
                if side_price <= stop:
                    exit_reason = "STOP"
                    break

        settlement_exit = 0.0 if bool(row["kalshi_result_yes"]) else 1.0
        contracts = max(1, math.floor(STAKE_DOLLARS / entry))
        entry_fee = maker_fee(contracts, entry)
        exit_fee = maker_fee(contracts, exit_price)
        settlement_exit_fee = maker_fee(contracts, settlement_exit)
        gross = contracts * (exit_price - entry)
        net = gross - entry_fee - exit_fee
        settlement_gross = contracts * (settlement_exit - entry)
        settlement_net = settlement_gross - entry_fee - settlement_exit_fee
        per_contract_fee = maker_fee(1, entry) + maker_fee(1, exit_price)
        per_contract_net = (exit_price - entry) - per_contract_fee

        row.update(
            {
                "contracts": contracts,
                "exit_price": round(exit_price, 4),
                "exit_time": exit_time,
                "exit_reason": exit_reason,
                "gross_pnl": round(gross, 4),
                "net_pnl": round(net, 4),
                "settlement_exit": settlement_exit,
                "settlement_net_pnl": round(settlement_net, 4),
                "per_contract_net": round(per_contract_net, 4),
                "trade_win": net > 0,
                "settlement_win": settlement_exit > entry,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def summarize(trades: pd.DataFrame, entries: pd.DataFrame) -> dict:
    summary: dict[str, object] = {
        "inputs": {
            "predictions_csv": str(PREDICTIONS_CSV),
            "trades_glob": TRADES_GLOB,
            "stake_dollars": STAKE_DOLLARS,
            "probability_threshold": float(config.DEEP_TAIL_NO_PROB_MAX),
            "min_yes_entry": float(config.DEEP_TAIL_NO_YES_PRICE_MIN),
            "stop_loss_diff": float(config.STOP_LOSS_DIFF),
            "time_exit_et": TIME_EXIT.strftime("%H:%M"),
            "entry_price_source": "latest traded YES price at or before scenario time",
        },
        "coverage": {},
        "results": [],
    }
    priced = entries[entries["yes_entry"].notna()].copy()
    for scenario in SCENARIOS:
        scoped = priced[priced["scenario"] == scenario.name]
        summary["coverage"][scenario.name] = {
            "priced_candidates": int(len(scoped)),
            "tradable_candidates": int(scoped["entry_pass"].sum()),
            "first_target_date": str(scoped["target_date"].min()) if not scoped.empty else None,
            "last_target_date": str(scoped["target_date"].max()) if not scoped.empty else None,
        }

    for (model, scenario), grp in trades.groupby(["model_name", "scenario"], sort=True):
        daily = grp.groupby("target_date", sort=True)["net_pnl"].sum()
        cum = daily.cumsum()
        settlement_daily = grp.groupby("target_date", sort=True)["settlement_net_pnl"].sum()
        summary["results"].append(
            {
                "model_name": model,
                "scenario": scenario,
                "trades": int(len(grp)),
                "target_days": int(grp["target_date"].nunique()),
                "win_rate": float(grp["trade_win"].mean()),
                "settlement_win_rate": float(grp["settlement_win"].mean()),
                "net_pnl": float(grp["net_pnl"].sum()),
                "settlement_net_pnl": float(grp["settlement_net_pnl"].sum()),
                "avg_yes_entry": float(grp["yes_entry"].mean()),
                "avg_no_entry": float(grp["entry_no_price"].mean()),
                "avg_contracts": float(grp["contracts"].mean()),
                "sharpe_daily": sharpe(daily),
                "settlement_sharpe_daily": sharpe(settlement_daily),
                "max_drawdown": max_drawdown(cum),
                "stop_rate": float((grp["exit_reason"] == "STOP").mean()),
                "no_path_rate": float((grp["exit_reason"] == "NO_PATH_MARK_TO_ENTRY").mean()),
            }
        )
    return summary


def write_report(summary: dict) -> None:
    results = pd.DataFrame(summary["results"]).sort_values(["model_name", "scenario"])
    lines = [
        "# DEEP_TAIL_NO Next-Day 10:15 Backtest",
        "",
        "This tests the live-code update that the early deep-tail scan should only evaluate tomorrow's newly opened markets.",
        "",
        "Entry price source: latest traded YES price at or before the scenario timestamp in the full Becker/Kalshi trade tape.",
        "",
        "## Coverage",
        "",
    ]
    for scenario, data in summary["coverage"].items():
        lines.append(
            f"- `{scenario}`: {data['tradable_candidates']} tradable of {data['priced_candidates']} priced candidates, "
            f"{data['first_target_date']} to {data['last_target_date']}"
        )
    lines.extend(["", "## Results", ""])
    if not results.empty:
        table = results[
            [
                "model_name",
                "scenario",
                "trades",
                "target_days",
                "win_rate",
                "net_pnl",
                "sharpe_daily",
                "max_drawdown",
                "stop_rate",
                "settlement_net_pnl",
            ]
        ].copy()
        for col in ["win_rate", "stop_rate"]:
            table[col] = (table[col] * 100).round(1).astype(str) + "%"
        for col in ["net_pnl", "sharpe_daily", "max_drawdown", "settlement_net_pnl"]:
            table[col] = table[col].map(lambda x: "" if pd.isna(x) else f"{x:.2f}")
        lines.append(markdown_table(table))
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- The primary PnL uses live-style stop and 11 PM time exit over observed trade prints.",
            "- `settlement_net_pnl` is included as a diagnostic only; live rules do not intentionally hold to settlement.",
            "- Historical order-book bid/ask was unavailable in the Becker trade tape, so entries use last trade as the price proxy.",
        ]
    )
    OUT_REPORT_MD.write_text("\n".join(lines) + "\n")


def markdown_table(frame: pd.DataFrame) -> str:
    headers = [str(col) for col in frame.columns]
    rows = [[str(value) for value in row] for row in frame.to_numpy()]
    out = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    out.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(out)


def main() -> None:
    con = duckdb.connect()
    candidates = load_candidates()
    entries = attach_entries(con, candidates)
    paths = load_paths(con, entries)
    trades = simulate_exits(entries, paths)
    trades.to_csv(OUT_TRADES_CSV, index=False)
    summary = summarize(trades, entries)
    OUT_SUMMARY_JSON.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    write_report(summary)

    print("DEEP_TAIL_NO next-day backtest complete")
    print(f"Candidates: {len(candidates):,}")
    print(f"Priced candidates: {int(entries['yes_entry'].notna().sum()):,}")
    print(f"Tradable candidates: {len(trades):,}")
    print(f"Wrote: {OUT_TRADES_CSV}")
    print(f"Wrote: {OUT_SUMMARY_JSON}")
    print(f"Wrote: {OUT_REPORT_MD}")
    results = pd.DataFrame(summary["results"]).sort_values(["model_name", "scenario"])
    if not results.empty:
        print()
        print(results[["model_name", "scenario", "trades", "win_rate", "net_pnl", "sharpe_daily", "max_drawdown", "stop_rate"]].to_string(index=False))


if __name__ == "__main__":
    main()
