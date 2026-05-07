#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import research.backtests.backtest as backtest
from research.backtests.backtest import BacktestConfig, BacktestEngine

DATA_DIR = ROOT / "data"
RESEARCH_DIR = DATA_DIR / "research"
REPORTS_DIR = ROOT / "reports"

CORE_GRID_CSV = RESEARCH_DIR / "strategy_variation_core_grid.csv"
EXIT_GRID_CSV = RESEARCH_DIR / "strategy_variation_exit_grid.csv"
BECKER_EXIT_GRID_CSV = RESEARCH_DIR / "strategy_variation_becker_exit_grid.csv"
SLEEVE_GRID_CSV = RESEARCH_DIR / "strategy_variation_sleeve_grid.csv"
TOP_TRADES_CSV = RESEARCH_DIR / "strategy_variation_top_trades.csv"
SUMMARY_JSON = RESEARCH_DIR / "strategy_variation_summary.json"
REPORT_MD = REPORTS_DIR / "strategy_variation_research.md"

ENTRY_TIMINGS = ["open", "9AM", "11AM", "1PM", "3PM"]
CHECKPOINTS = ["open", "9AM", "11AM", "1PM", "3PM"]
CHECKPOINT_COLS = {
    "open": "yes_price_open",
    "9AM": "yes_price_9AM",
    "11AM": "yes_price_11AM",
    "1PM": "yes_price_1PM",
    "3PM": "yes_price_3PM",
}
CHECKPOINT_ORDER = {"open": 0, "9AM": 9, "11AM": 11, "1PM": 13, "3PM": 15}


@dataclass(frozen=True)
class GateProfile:
    name: str
    physics_spread_max: float | None
    ai_spread_max: float | None
    spread_between_max: float | None


GATE_PROFILES = [
    GateProfile("current_backtest_gate", 3.0, 3.0, 2.5),
    GateProfile("live_hgefs_strict", 3.0, 3.0, 1.5),
    GateProfile("loose_3f_between", 3.0, 3.0, 3.0),
    GateProfile("very_strict_1f_between", 2.0, 2.0, 1.0),
    GateProfile("no_gate1", None, None, None),
]


PRICE_BANDS = [
    ("15_85", 0.15, 0.85),
    ("20_80", 0.20, 0.80),
    ("25_75_current", 0.25, 0.75),
    ("30_70", 0.30, 0.70),
    ("35_65", 0.35, 0.65),
    ("40_60", 0.40, 0.60),
]


def fee(price: float, order_type: str = "taker") -> float:
    rate = 0.07 if order_type == "taker" else 0.0175
    return math.ceil(rate * price * (1.0 - price) * 100.0) / 100.0


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


def summarize(df: pd.DataFrame, net_col: str = "net", win_col: str = "win") -> dict:
    if df.empty:
        return {
            "trades": 0,
            "trading_days": 0,
            "win_rate": 0.0,
            "profitable_days": 0,
            "profitable_day_rate": 0.0,
            "net_pnl": 0.0,
            "gross_pnl": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "avg_entry_price": 0.0,
            "median_entry_price": 0.0,
            "avg_return": 0.0,
        }
    daily = df.groupby("date")[net_col].sum()
    entry = df["entry_price"].replace(0, np.nan)
    return {
        "trades": int(len(df)),
        "trading_days": int(daily.size),
        "win_rate": float(df[win_col].mean()),
        "profitable_days": int((daily > 0).sum()),
        "profitable_day_rate": float((daily > 0).mean()) if daily.size else 0.0,
        "net_pnl": float(df[net_col].sum()),
        "gross_pnl": float(df.get("gross", pd.Series(dtype=float)).sum()) if "gross" in df else 0.0,
        "sharpe": sharpe(df[net_col]),
        "max_drawdown": max_drawdown(df[net_col]),
        "avg_entry_price": float(df["entry_price"].mean()),
        "median_entry_price": float(df["entry_price"].median()),
        "avg_return": float((df[net_col] / entry).mean()),
    }


def load_engine() -> BacktestEngine:
    markets, prices, actuals, models = backtest.load_or_fetch(refresh=False)
    return BacktestEngine(markets, prices, actuals, models)


def candidate_universe(engine: BacktestEngine) -> pd.DataFrame:
    rows = []
    for timing in ENTRY_TIMINGS:
        cfg = BacktestConfig(gap_threshold=0.0, entry_timing=timing, label=f"universe_{timing}")
        trades = engine.run(cfg)
        if trades.empty:
            continue
        trades = trades[trades["sleeve"] == "CORE"].copy()
        # engine.run(gap=0) still applies current no-dead-zone and price band, so
        # rebuild a wider universe manually from engine.dataset below.
        rows.append(trades)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def build_daily_probability_frame(engine: BacktestEngine) -> pd.DataFrame:
    df = engine.dataset.dropna(
        subset=["kalshi_result_yes", "gfs_maxt", "ecmwf_maxt", "ukmo_maxt", "nbm_maxt"]
    ).copy()
    dist_model = backtest.DistributionalTempModel()
    weights = backtest.normalize_weights(backtest.FIXED_ENSEMBLE_WEIGHTS)
    rows = []
    for target_date, day_group in df.groupby("target_date", sort=True):
        first = day_group.iloc[0]
        gfs = float(first["gfs_maxt"])
        ecmwf = float(first["ecmwf_maxt"])
        ukmo = float(first["ukmo_maxt"])
        nbm = float(first["nbm_maxt"])
        physics_mean = float(np.mean([gfs, ecmwf]))
        physics_spread = float(np.std([gfs, ecmwf]))
        ai_mean = float(np.mean([ukmo, nbm]))
        ai_spread = float(np.std([ukmo, nbm]))
        spread_between = abs(physics_mean - ai_mean)
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
        probs = dist_model.bracket_probabilities(consensus, brackets)
        for _, row in day_group.iterrows():
            for timing, col in CHECKPOINT_COLS.items():
                price = row.get(col)
                if pd.isna(price):
                    continue
                p_yes = float(probs.get(row["ticker"], np.nan))
                if not np.isfinite(p_yes):
                    continue
                yes_price = float(price)
                gap_pp = (p_yes - yes_price) * 100.0
                direction = "YES" if gap_pp > 0 else "NO"
                entry_price = yes_price if direction == "YES" else 1.0 - yes_price
                win = bool(row["kalshi_result_yes"]) if direction == "YES" else not bool(row["kalshi_result_yes"])
                gross = (1.0 - entry_price) if win else -entry_price
                rows.append(
                    {
                        "date": target_date,
                        "ticker": row["ticker"],
                        "bracket": row["bracket"],
                        "bracket_type": row["bracket_type"],
                        "timing": timing,
                        "yes_price": yes_price,
                        "model_prob": p_yes,
                        "gap_pp": gap_pp,
                        "gap_abs": abs(gap_pp),
                        "direction": direction,
                        "entry_price": entry_price,
                        "kalshi_result_yes": bool(row["kalshi_result_yes"]),
                        "win": win,
                        "gross": gross,
                        "fee": fee(entry_price),
                        "net": gross - fee(entry_price),
                        "physics_spread": physics_spread,
                        "ai_spread": ai_spread,
                        "spread_between": spread_between,
                        "consensus": consensus,
                    }
                )
    return pd.DataFrame(rows)


def gate_pass(frame: pd.DataFrame, profile: GateProfile) -> pd.Series:
    if profile.physics_spread_max is None:
        return pd.Series(True, index=frame.index)
    return (
        (frame["physics_spread"] < profile.physics_spread_max)
        & (frame["ai_spread"] < profile.ai_spread_max)
        & (frame["spread_between"] < profile.spread_between_max)
    )


def core_grid(candidates: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    selected_frames = []
    for timing in ENTRY_TIMINGS:
        base_timing = candidates[candidates["timing"] == timing]
        if base_timing.empty:
            continue
        for profile in GATE_PROFILES:
            g1 = gate_pass(base_timing, profile)
            for gap in [5, 10, 15, 20, 25, 30, 35, 40]:
                for dead_zone in [True, False]:
                    dz = ~base_timing["gap_abs"].between(35.0, 40.0, inclusive="both") if dead_zone else True
                    for band_name, min_price, max_price in PRICE_BANDS:
                        price_ok = base_timing["entry_price"].between(min_price, max_price, inclusive="both")
                        for directions in ["both", "YES", "NO"]:
                            direction_ok = True if directions == "both" else base_timing["direction"].eq(directions)
                            for family in ["all", "central", "wings", "wing_high", "wing_low"]:
                                if family == "all":
                                    fam_ok = True
                                elif family == "central":
                                    fam_ok = base_timing["bracket_type"].eq("central")
                                elif family == "wings":
                                    fam_ok = ~base_timing["bracket_type"].eq("central")
                                else:
                                    fam_ok = base_timing["bracket_type"].eq(family)
                                mask = (
                                    g1
                                    & (base_timing["gap_abs"] > gap)
                                    & dz
                                    & price_ok
                                    & direction_ok
                                    & fam_ok
                                )
                                trades = base_timing[mask].copy()
                                s = summarize(trades)
                                s.update(
                                    {
                                        "strategy": "CORE",
                                        "timing": timing,
                                        "gate_profile": profile.name,
                                        "gap_threshold": gap,
                                        "dead_zone_enabled": dead_zone,
                                        "price_band": band_name,
                                        "min_price": min_price,
                                        "max_price": max_price,
                                        "directions": directions,
                                        "family": family,
                                    }
                                )
                                rows.append(s)
                                if (
                                    timing == "9AM"
                                    and profile.name == "current_backtest_gate"
                                    and gap == 20
                                    and dead_zone
                                    and band_name == "25_75_current"
                                    and directions == "both"
                                    and family == "all"
                                ):
                                    trades["variant"] = "current_core"
                                    selected_frames.append(trades)
    grid = pd.DataFrame(rows)
    selected = pd.concat(selected_frames, ignore_index=True) if selected_frames else pd.DataFrame()
    return grid, selected


def simulate_checkpoint_exits(trades: pd.DataFrame, target: float | None, stop_diff: float | None) -> pd.DataFrame:
    out_rows = []
    for _, row in trades.iterrows():
        entry_order = CHECKPOINT_ORDER[row["timing"]]
        path = []
        for label, order in CHECKPOINT_ORDER.items():
            if order <= entry_order:
                continue
            col = f"path_{label}"
            if col in row and pd.notna(row[col]):
                side_price = float(row[col]) if row["direction"] == "YES" else 1.0 - float(row[col])
                path.append((label, side_price))
        exit_reason = "SETTLEMENT"
        exit_price = 1.0 if bool(row["win"]) else 0.0
        for label, side_price in path:
            if target is not None and side_price >= target:
                exit_reason = f"TARGET_{label}"
                exit_price = target
                break
            if stop_diff is not None and side_price <= max(0.0, float(row["entry_price"]) - stop_diff):
                exit_reason = f"STOP_{label}"
                exit_price = side_price
                break
        gross = exit_price - float(row["entry_price"])
        total_fee = fee(float(row["entry_price"])) if exit_reason == "SETTLEMENT" else fee(float(row["entry_price"])) + fee(exit_price)
        r = row.to_dict()
        r.update(
            {
                "exit_reason": exit_reason,
                "exit_price": exit_price,
                "gross": gross,
                "fee": total_fee,
                "net": gross - total_fee,
                "win": gross > 0,
            }
        )
        out_rows.append(r)
    return pd.DataFrame(out_rows)


def checkpoint_exit_grid(candidates: pd.DataFrame, baseline_core: pd.DataFrame) -> pd.DataFrame:
    if baseline_core.empty:
        return pd.DataFrame()
    path_cols = candidates.pivot_table(
        index=["date", "ticker"],
        columns="timing",
        values="yes_price",
        aggfunc="first",
    ).reset_index()
    path_cols = path_cols.rename(columns={col: f"path_{col}" for col in CHECKPOINTS if col in path_cols.columns})
    trades = baseline_core.merge(path_cols, on=["date", "ticker"], how="left")
    rows = []
    for target in [0.60, 0.65, 0.68, 0.70, 0.75, 0.80, None]:
        for stop in [0.10, 0.15, 0.20, 0.25, None]:
            sim = simulate_checkpoint_exits(trades, target, stop)
            s = summarize(sim)
            s.update(
                {
                    "strategy": "CORE_CHECKPOINT_EXIT",
                    "target": target if target is not None else "none",
                    "stop_diff": stop if stop is not None else "none",
                    "exit_counts": json.dumps(sim["exit_reason"].value_counts().to_dict(), sort_keys=True),
                }
            )
            rows.append(s)
    return pd.DataFrame(rows)


def sleeve_grid(candidates: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for timing in ENTRY_TIMINGS:
        frame = candidates[candidates["timing"] == timing]
        if frame.empty:
            continue
        g1 = gate_pass(frame, GATE_PROFILES[0])
        for sleeve in ["DEEP_TAIL_NO", "TAIL_NO", "NEAR_CONFIRMED_NO"]:
            if sleeve == "DEEP_TAIL_NO":
                for pmax in [0.005, 0.01, 0.02, 0.03, 0.05, 0.10]:
                    for yes_min in [0.01, 0.03, 0.05, 0.10, 0.15, 0.25]:
                        mask = g1 & (frame["model_prob"] < pmax) & (frame["yes_price"] > yes_min)
                        trades = no_side_trades(frame[mask], sleeve)
                        s = summarize(trades)
                        s.update(
                            {
                                "strategy": sleeve,
                                "timing": timing,
                                "p_yes_max": pmax,
                                "yes_price_min": yes_min,
                                "yes_price_max": None,
                            }
                        )
                        rows.append(s)
            elif sleeve == "TAIL_NO":
                for pmax in [0.20, 0.30, 0.40]:
                    for yes_min in [0.45, 0.55, 0.65, 0.75]:
                        mask = g1 & (frame["model_prob"] < pmax) & (frame["yes_price"] > yes_min)
                        trades = no_side_trades(frame[mask], sleeve)
                        s = summarize(trades)
                        s.update(
                            {
                                "strategy": sleeve,
                                "timing": timing,
                                "p_yes_max": pmax,
                                "yes_price_min": yes_min,
                                "yes_price_max": None,
                            }
                        )
                        rows.append(s)
            else:
                for pmax in [0.005, 0.01, 0.02, 0.05]:
                    for yes_max in [0.01, 0.03, 0.05, 0.10]:
                        mask = g1 & (frame["model_prob"] <= pmax) & (frame["yes_price"] <= yes_max)
                        trades = no_side_trades(frame[mask], sleeve, require_min_no_entry=0.95)
                        s = summarize(trades)
                        s.update(
                            {
                                "strategy": sleeve,
                                "timing": timing,
                                "p_yes_max": pmax,
                                "yes_price_min": None,
                                "yes_price_max": yes_max,
                            }
                        )
                        rows.append(s)
    return pd.DataFrame(rows)


def no_side_trades(frame: pd.DataFrame, sleeve: str, require_min_no_entry: float | None = None) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    out = frame.copy()
    yes_bid_proxy = (out["yes_price"] - 0.02).clip(lower=0.0)
    out["sleeve"] = sleeve
    out["direction"] = "NO"
    out["entry_price"] = (1.0 - yes_bid_proxy).clip(lower=0.0, upper=0.99)
    if require_min_no_entry is not None:
        out = out[out["entry_price"] >= require_min_no_entry].copy()
    out["win"] = ~out["kalshi_result_yes"].astype(bool)
    out["gross"] = np.where(out["win"], 1.0 - out["entry_price"], -out["entry_price"])
    out["fee"] = out["entry_price"].apply(fee)
    out["net"] = out["gross"] - out["fee"]
    return out


def becker_exit_replay(baseline_core: pd.DataFrame) -> pd.DataFrame:
    if baseline_core.empty:
        return pd.DataFrame()
    tickers = baseline_core[["ticker"]].drop_duplicates()
    con = duckdb.connect()
    con.register("tickers", tickers)
    trades = con.execute(
        """
        SELECT ticker, created_time, yes_price, no_price
        FROM read_parquet('data/kalshi/trades/*.parquet')
        WHERE ticker IN (SELECT ticker FROM tickers)
        """
    ).fetchdf()
    if trades.empty:
        return pd.DataFrame()
    trades["created_time"] = pd.to_datetime(trades["created_time"], utc=True).dt.tz_convert("America/New_York")
    trades["yes_side_price"] = pd.to_numeric(trades["yes_price"], errors="coerce") / 100.0
    trades["no_side_price"] = pd.to_numeric(trades["no_price"], errors="coerce") / 100.0
    by_ticker = {ticker: group.sort_values("created_time") for ticker, group in trades.groupby("ticker")}
    rows = []
    for target in [0.60, 0.65, 0.68, 0.70, 0.75, 0.80, None]:
        for stop in [0.10, 0.15, 0.20, 0.25, None]:
            sim = simulate_becker_path(baseline_core, by_ticker, target, stop)
            s = summarize(sim)
            s.update(
                {
                    "strategy": "CORE_BECKER_PRINT_REPLAY",
                    "target": target if target is not None else "none",
                    "stop_diff": stop if stop is not None else "none",
                    "path_available_trades": int(sim["path_available"].sum()),
                    "path_available_rate": float(sim["path_available"].mean()),
                    "exit_counts": json.dumps(sim["exit_reason"].value_counts().to_dict(), sort_keys=True),
                }
            )
            rows.append(s)
    return pd.DataFrame(rows)


def simulate_becker_path(
    trades: pd.DataFrame,
    by_ticker: dict[str, pd.DataFrame],
    target: float | None,
    stop_diff: float | None,
) -> pd.DataFrame:
    rows = []
    for _, row in trades.iterrows():
        day = pd.Timestamp(str(row["date"]), tz="America/New_York")
        entry_hour = CHECKPOINT_ORDER.get(str(row["timing"]), 9)
        entry_time = day + pd.Timedelta(hours=entry_hour)
        close_time = day + pd.Timedelta(hours=23, minutes=59)
        exit_reason = "SETTLEMENT"
        exit_price = 1.0 if bool(row["win"]) else 0.0
        path_available = False
        ticker_trades = by_ticker.get(row["ticker"])
        if ticker_trades is not None:
            path = ticker_trades[
                (ticker_trades["created_time"] >= entry_time) & (ticker_trades["created_time"] <= close_time)
            ].copy()
            if not path.empty:
                path_available = True
                path["side_price"] = (
                    path["yes_side_price"] if row["direction"] == "YES" else path["no_side_price"]
                )
                for _, item in path.iterrows():
                    side_price = float(item["side_price"])
                    if target is not None and side_price >= target:
                        exit_reason = "TARGET"
                        exit_price = target
                        break
                    if stop_diff is not None and side_price <= max(0.0, float(row["entry_price"]) - stop_diff):
                        exit_reason = "STOP"
                        exit_price = side_price
                        break
        gross = exit_price - float(row["entry_price"])
        total_fee = fee(float(row["entry_price"])) if exit_reason == "SETTLEMENT" else fee(float(row["entry_price"])) + fee(exit_price)
        r = row.to_dict()
        r.update(
            {
                "path_available": path_available,
                "exit_reason": exit_reason,
                "exit_price": exit_price,
                "gross": gross,
                "fee": total_fee,
                "net": gross - total_fee,
                "win": gross > 0,
            }
        )
        rows.append(r)
    return pd.DataFrame(rows)


def top_table(df: pd.DataFrame, min_trades: int = 100) -> pd.DataFrame:
    if df.empty:
        return df
    sort_cols = ["net_pnl", "sharpe", "win_rate"]
    return (
        df[df["trades"] >= min_trades]
        .sort_values(sort_cols, ascending=[False, False, False])
        .head(20)
        .reset_index(drop=True)
    )


def write_report(
    core: pd.DataFrame,
    exit_grid: pd.DataFrame,
    becker_grid: pd.DataFrame,
    sleeves: pd.DataFrame,
    baseline: dict,
) -> None:
    def md_table(df: pd.DataFrame, cols: list[str], n: int = 10) -> str:
        if df.empty:
            return "_No rows._"
        view = df.loc[:, [col for col in cols if col in df.columns]].head(n).copy()
        for col in view.select_dtypes(include=["float"]).columns:
            view[col] = view[col].map(lambda x: round(float(x), 4))
        headers = list(view.columns)
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
        ]
        for _, row in view.iterrows():
            values = [str(row[col]).replace("|", "\\|") for col in headers]
            lines.append("| " + " | ".join(values) + " |")
        return "\n".join(lines)

    top_core = top_table(core, 100)
    top_exit = top_table(exit_grid, 100)
    top_becker = top_table(becker_grid, 100)
    top_sleeves = top_table(sleeves, 100)
    report = f"""# Strategy Variation Research

Generated: {datetime.now():%Y-%m-%d %H:%M:%S}

This is research-only. It does not change `config.py`, live thresholds, paper trader behavior, `main.py`, LaunchAgent, or execution code.

## Scope And Limits

- Uses cached KXHIGHNY API/backtest data from `data/kxhighny_*.csv`, `data/open_meteo_historical.csv`, and `data/backtest_results.csv`.
- Uses Kalshi settlement labels as payoff truth.
- Forecast vintage remains limited because cached Open-Meteo rows do not store cycle timestamps.
- Exit replay has two versions:
  - checkpoint replay using open/9AM/11AM/1PM/3PM API prices.
  - Becker observed-trade replay using trade prints only, not full orderbook/queue data.
- Becker replay can prove observed touches but cannot prove a passive maker order would have filled.

## Current Baseline

{json.dumps(baseline, indent=2)}

## Top Core Variants By Net P&L

{md_table(top_core, ['timing','gate_profile','gap_threshold','dead_zone_enabled','price_band','directions','family','trades','win_rate','net_pnl','sharpe','max_drawdown','avg_entry_price'], 15)}

## Top Checkpoint Exit Variants

{md_table(top_exit, ['target','stop_diff','trades','win_rate','net_pnl','sharpe','max_drawdown','profitable_day_rate','exit_counts'], 15)}

## Top Becker Trade-Print Exit Variants

{md_table(top_becker, ['target','stop_diff','trades','path_available_rate','win_rate','net_pnl','sharpe','max_drawdown','exit_counts'], 15)}

## Top Sleeve Variants

{md_table(top_sleeves, ['strategy','timing','p_yes_max','yes_price_min','yes_price_max','trades','win_rate','net_pnl','sharpe','max_drawdown','avg_entry_price'], 20)}

## Main Research Takeaways

1. The highest-P&L core variants are research candidates only. They often trade more or loosen constraints, so they must be judged under walk-forward and stress, not raw in-sample P&L alone.
2. Exit targets are not automatically beneficial. A low target can raise hit rate while capping winners and adding exit fees.
3. Stop-loss variants are especially dangerous in trade-print replay because many eventual winners wobble intraday before settlement.
4. NO-side and wing behavior should continue to be analyzed separately from central YES-style trades.
5. Near-confirmed NO harvest can show extremely high win rate but weak net P&L when entry is near 99c; fees and one rare loss dominate.

## Output Files

- `{CORE_GRID_CSV.relative_to(ROOT)}`
- `{EXIT_GRID_CSV.relative_to(ROOT)}`
- `{BECKER_EXIT_GRID_CSV.relative_to(ROOT)}`
- `{SLEEVE_GRID_CSV.relative_to(ROOT)}`
- `{TOP_TRADES_CSV.relative_to(ROOT)}`
- `{SUMMARY_JSON.relative_to(ROOT)}`
"""
    REPORT_MD.write_text(report)


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT).decode().strip()
    except Exception:
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="Research-only strategy variation sweep.")
    parser.add_argument("--skip-becker", action="store_true", help="Skip Becker trade-print exit replay.")
    args = parser.parse_args()

    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading cached datasets...")
    engine = load_engine()
    print("Building daily coherent probability frame...")
    candidates = build_daily_probability_frame(engine)
    print(f"Candidate rows: {len(candidates):,}")

    print("Running core grid...")
    core, baseline_core = core_grid(candidates)
    core.to_csv(CORE_GRID_CSV, index=False)
    print(f"Core variants: {len(core):,}")

    print("Running checkpoint exit grid...")
    exit_grid = checkpoint_exit_grid(candidates, baseline_core)
    exit_grid.to_csv(EXIT_GRID_CSV, index=False)
    print(f"Checkpoint exit variants: {len(exit_grid):,}")

    print("Running sleeve grid...")
    sleeves = sleeve_grid(candidates)
    sleeves.to_csv(SLEEVE_GRID_CSV, index=False)
    print(f"Sleeve variants: {len(sleeves):,}")

    print("Running Becker trade-print exit replay..." if not args.skip_becker else "Skipping Becker replay.")
    becker = pd.DataFrame()
    if not args.skip_becker:
        becker = becker_exit_replay(baseline_core)
    becker.to_csv(BECKER_EXIT_GRID_CSV, index=False)
    print(f"Becker exit variants: {len(becker):,}")

    baseline_summary = {
        "git_sha": git_sha(),
        "candidate_rows": int(len(candidates)),
        "date_min": str(candidates["date"].min()) if not candidates.empty else None,
        "date_max": str(candidates["date"].max()) if not candidates.empty else None,
        "current_core": summarize(baseline_core),
    }
    top_combined = pd.concat(
        [
            top_table(core, 100).assign(source="core_grid"),
            top_table(exit_grid, 100).assign(source="checkpoint_exit_grid"),
            top_table(becker, 100).assign(source="becker_exit_grid") if not becker.empty else pd.DataFrame(),
            top_table(sleeves, 100).assign(source="sleeve_grid"),
        ],
        ignore_index=True,
        sort=False,
    )
    top_combined.to_csv(TOP_TRADES_CSV, index=False)
    summary = {
        "baseline": baseline_summary,
        "top_core": top_table(core, 100).head(10).to_dict(orient="records"),
        "top_checkpoint_exits": top_table(exit_grid, 100).head(10).to_dict(orient="records"),
        "top_becker_exits": top_table(becker, 100).head(10).to_dict(orient="records") if not becker.empty else [],
        "top_sleeves": top_table(sleeves, 100).head(10).to_dict(orient="records"),
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, default=str))
    write_report(core, exit_grid, becker, sleeves, baseline_summary)

    print("\n=== STRATEGY VARIATION RESEARCH COMPLETE ===")
    print(f"Baseline current core: {baseline_summary['current_core']}")
    print("\nTop core variants:")
    cols = ["timing", "gate_profile", "gap_threshold", "price_band", "directions", "family", "trades", "win_rate", "net_pnl", "sharpe"]
    print(top_table(core, 100)[cols].head(10).to_string(index=False))
    print("\nTop sleeve variants:")
    cols = ["strategy", "timing", "p_yes_max", "yes_price_min", "yes_price_max", "trades", "win_rate", "net_pnl", "sharpe"]
    print(top_table(sleeves, 100)[cols].head(10).to_string(index=False))
    print(f"\nReport saved to {REPORT_MD}")


if __name__ == "__main__":
    main()
