#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from paper_trader import config_paper
from execution.fill_model import HALF_SPREADS, kalshi_fee
from paper_trader.policy import regime_for_date


BACKTEST_CSV = ROOT / "data" / "backtest_results.csv"
RESEARCH_DIR = ROOT / "data" / "research"
REPORT_MD = ROOT / "reports" / "report7_policy_stress_backtest.md"
SUMMARY_JSON = RESEARCH_DIR / "report7_policy_stress_backtest_summary.json"
POLICY_CSV = RESEARCH_DIR / "report7_policy_stress_backtest.csv"

TRADEABLE_SLEEVES = {"CORE", "DEEP_TAIL_NO"}
STRESS_CENTS = [0, 1, 3, 5]


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


def bracket_family(row: pd.Series) -> str:
    btype = str(row.get("bracket_type", "")).lower()
    if btype in {"wing_low", "lower_tail", "lower"}:
        return "lower_tail"
    if btype in {"wing_high", "upper_tail", "upper"}:
        return "upper_tail"
    return "central"


def raw_edge_pp(row: pd.Series) -> float:
    return abs(float(row["gap_pp"]))


def execution_cost_pp(row: pd.Series) -> float:
    family = row["bracket_family"]
    spread_pp = HALF_SPREADS.get(family, HALF_SPREADS["central"]) * 100.0
    maker_fee_pp = kalshi_fee(float(row["entry_price"]), 1, "maker") * 100.0
    return float(spread_pp + maker_fee_pp + config_paper.PAPER_FEE_MARGIN_PP)


def required_net_edge_pp(row: pd.Series) -> float:
    if row["sleeve"] == "DEEP_TAIL_NO":
        return float(config_paper.PAPER_MIN_NET_EDGE_PP_DEEP_TAIL)
    if row["bracket_family"] != "central":
        return float(config_paper.PAPER_MIN_NET_EDGE_PP_WING)
    return float(config_paper.PAPER_MIN_NET_EDGE_PP_CORE)


def seasonal_mult(row: pd.Series) -> float:
    month = int(str(row["date"])[5:7])
    return float(config_paper.PAPER_SEASONAL_MULTIPLIERS.get(month, 1.0))


def regime_mult(row: pd.Series) -> float:
    regime = regime_for_date(str(row["date"]))
    return float(config_paper.PAPER_REGIME_MULTIPLIERS.get(regime, config_paper.PAPER_REGIME_MULTIPLIERS["unknown"]))


def size_mult(row: pd.Series) -> float:
    raw = seasonal_mult(row) * regime_mult(row)
    return float(min(max(raw, config_paper.PAPER_MIN_SIZE_MULT), config_paper.PAPER_MAX_SIZE_MULT))


def net_for_entry(frame: pd.DataFrame, entry_col: str, fee_col: str, stress_cents: int = 0) -> pd.Series:
    win = frame["win"].astype(bool)
    entry = frame[entry_col].astype(float)
    gross = np.where(win, 1.0 - entry, -entry)
    # Subtract the same cents again for exit/repricing friction in stress modes.
    return gross - frame[fee_col].astype(float) - (stress_cents / 100.0)


def add_research_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["bracket_family"] = out.apply(bracket_family, axis=1)
    out["raw_edge_pp"] = out.apply(raw_edge_pp, axis=1)
    out["est_execution_cost_pp"] = out.apply(execution_cost_pp, axis=1)
    out["est_net_edge_pp"] = out["raw_edge_pp"] - out["est_execution_cost_pp"]
    out["required_net_edge_pp"] = out.apply(required_net_edge_pp, axis=1)
    out["seasonal_mult"] = out.apply(seasonal_mult, axis=1)
    out["regime"] = out["date"].apply(lambda value: regime_for_date(str(value)))
    out["regime_mult"] = out.apply(regime_mult, axis=1)
    out["size_mult"] = out.apply(size_mult, axis=1)
    out["maker_fee"] = out["entry_price"].apply(lambda p: kalshi_fee(float(p), 1, "maker"))
    out["maker_net"] = net_for_entry(out, "entry_price", "maker_fee", 0)
    for cents in STRESS_CENTS:
        entry_col = f"stress_{cents}c_entry"
        fee_col = f"stress_{cents}c_fee"
        net_col = f"stress_{cents}c_net"
        out[entry_col] = (out["entry_price"].astype(float) + cents / 100.0).clip(upper=0.99)
        out[fee_col] = out[entry_col].apply(lambda p: kalshi_fee(float(p), 1, "maker"))
        out[net_col] = net_for_entry(out, entry_col, fee_col, cents)
        out[f"stress_{cents}c_sized_net"] = out[net_col] * out["size_mult"]
    return out


def summarize(df: pd.DataFrame, net_col: str) -> dict:
    if df.empty:
        return {
            "trades": 0,
            "days": 0,
            "win_rate": 0.0,
            "net_pnl": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "avg_size_mult": 0.0,
            "avg_entry_price": 0.0,
        }
    return {
        "trades": int(len(df)),
        "days": int(df["date"].nunique()),
        "win_rate": float(df["win"].mean()),
        "net_pnl": float(df[net_col].sum()),
        "sharpe": sharpe(df[net_col]),
        "max_drawdown": max_drawdown(df[net_col]),
        "avg_size_mult": float(df["size_mult"].mean()),
        "avg_entry_price": float(df["entry_price"].mean()),
    }


def policy_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    current = df["sleeve"].isin(TRADEABLE_SLEEVES)
    paper_net_edge = df["est_net_edge_pp"] >= df["required_net_edge_pp"]
    not_lower_tail = ~df["bracket_family"].eq("lower_tail")
    core_confidence = (~df["sleeve"].eq("CORE")) | (df["confidence"] >= 60.0)
    central_core_strict = (
        (~df["sleeve"].eq("CORE"))
        | (~df["bracket_family"].eq("central"))
        | ((df["confidence"] >= 60.0) & (df["raw_edge_pp"] >= 20.0))
    )
    return {
        "current_strategy": current,
        "paper_net_edge_policy": current & paper_net_edge,
        "paper_net_edge_sized": current & paper_net_edge,
        "report7_lower_tail_caution": current & paper_net_edge & not_lower_tail,
        "report7_strict_selection": current & paper_net_edge & not_lower_tail & core_confidence & central_core_strict,
    }


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def format_row(row: dict) -> str:
    return (
        f"| {row['policy']} | {row['trades']} | {row['days']} | {row['win_rate']:.1%} | "
        f"{row['win_rate_delta_pp']:+.1f}pp | ${row['net_0c']:.2f} | ${row['net_1c']:.2f} | "
        f"${row['net_3c']:.2f} | ${row['net_5c']:.2f} | {row['avg_size_mult']:.2f} |"
    )


def main() -> None:
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(BACKTEST_CSV)
    df = add_research_columns(df)
    masks = policy_masks(df)
    baseline = df[masks["current_strategy"]]
    baseline_win = float(baseline["win"].mean())

    rows = []
    policy_frames = []
    for policy, mask in masks.items():
        frame = df[mask].copy()
        if policy == "paper_net_edge_sized":
            net_cols = {c: f"stress_{c}c_sized_net" for c in STRESS_CENTS}
        else:
            net_cols = {c: f"stress_{c}c_net" for c in STRESS_CENTS}
        row = {
            "policy": policy,
            "win_rate_delta_pp": 0.0,
            **summarize(frame, net_cols[0]),
            "net_0c": summarize(frame, net_cols[0])["net_pnl"],
            "net_1c": summarize(frame, net_cols[1])["net_pnl"],
            "net_3c": summarize(frame, net_cols[3])["net_pnl"],
            "net_5c": summarize(frame, net_cols[5])["net_pnl"],
        }
        row["win_rate_delta_pp"] = (row["win_rate"] - baseline_win) * 100.0
        rows.append(row)
        frame["policy"] = policy
        policy_frames.append(frame)

    out = pd.concat(policy_frames, ignore_index=True)
    out.to_csv(POLICY_CSV, index=False)

    by_sleeve = []
    strict = df[masks["report7_strict_selection"]].copy()
    for sleeve, group in strict.groupby("sleeve"):
        item = summarize(group, "stress_0c_net")
        by_sleeve.append(
            {
                "sleeve": sleeve,
                "trades": item["trades"],
                "win_rate": item["win_rate"],
                "net_0c": item["net_pnl"],
                "net_3c": summarize(group, "stress_3c_net")["net_pnl"],
            }
        )

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "input": str(BACKTEST_CSV.relative_to(ROOT)),
        "scope": "Research-only stress test for deep-research-report (7). No live files are modified.",
        "policies": rows,
        "strict_policy_by_sleeve": by_sleeve,
        "valid_report7_items": [
            "Net-edge gate after fill/fee reserve",
            "Wing/central and lower-tail split",
            "Soft seasonal/regime sizing as research sizing, not a hard skip",
            "Stress scenarios at +1c/+3c/+5c",
        ],
        "not_implemented": [
            "Market-making, paired/straddle, cross-market arb, condor, and RL ideas need order-book/action data and are not validated here.",
            "EMOS/QRF/HGBR retraining requires a separate vintage-aware model bakeoff.",
        ],
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2))

    table = "\n".join(
        [
            "| Policy | Trades | Days | Win Rate | Δ Win Rate | Net 0c | Net +1c | Net +3c | Net +5c | Avg Size Mult |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            *[format_row(row) for row in rows],
        ]
    )
    sleeve_table = "\n".join(
        [
            "| Sleeve | Trades | Win Rate | Net 0c | Net +3c |",
            "|---|---:|---:|---:|---:|",
            *[
                f"| {row['sleeve']} | {row['trades']} | {row['win_rate']:.1%} | ${row['net_0c']:.2f} | ${row['net_3c']:.2f} |"
                for row in by_sleeve
            ],
        ]
    )
    report = f"""# Deep Research Report 7 Policy Stress Backtest

Generated: {summary['generated_at']}

Git SHA: `{summary['git_sha']}`

Input: `{summary['input']}`

## Scope

This is a research-only validation of the actionable parts of
`/Users/bhargavsukhavasi/Downloads/deep-research-report (7).md`.

The report's paper-only config, TAIL_NO suspension, wing/central split, net-edge
gate, and strategy-health reporting already exist in this repo. This run adds a
dedicated stress comparison with +1c, +3c, and +5c worse execution assumptions
and a soft seasonal/regime sized variant.

Ideas not tested here: market making, straddles, cross-market arbitrage, condor
spreads, reinforcement learning, EMOS/QRF/HGBR retraining. Those need additional
order-book/action data or a separate forecast-vintage-aware model bakeoff.

## Results

{table}

## Strict Policy By Sleeve

{sleeve_table}

## Read

The report's valid improvement is better trade selection under execution stress,
not a new forecasting signal. The best-performing strict selection is smaller
than the current strategy, but it raises win rate and keeps more P&L under +3c
and +5c stress by removing lower-tail/cold-wing exposure and marginal core rows.

Soft seasonal/regime sizing changes capital exposure and drawdown shape, not raw
win rate. It should be evaluated as a bankroll-control layer, not as alpha.
"""
    REPORT_MD.write_text(report)

    print("=== DEEP RESEARCH REPORT 7 POLICY STRESS BACKTEST ===")
    print(table)
    print()
    print("Strict policy by sleeve:")
    print(sleeve_table)
    print()
    print(f"Report saved: {REPORT_MD.relative_to(ROOT)}")
    print(f"CSV saved: {POLICY_CSV.relative_to(ROOT)}")
    print(f"Summary saved: {SUMMARY_JSON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
