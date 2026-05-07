#!/usr/bin/env python3
from __future__ import annotations

import json
import math
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

from execution.fill_model import HALF_SPREADS, kalshi_fee


BACKTEST_CSV = ROOT / "data" / "backtest_results.csv"
RESEARCH_DIR = ROOT / "data" / "research"
REPORT_MD = ROOT / "reports" / "report_improvement_backtest.md"
OUTPUT_CSV = RESEARCH_DIR / "report_improvement_backtest_trades.csv"
OUTPUT_SUMMARY = RESEARCH_DIR / "report_improvement_backtest_summary.json"

CURRENT_TRADEABLE_SLEEVES = {"CORE", "DEEP_TAIL_NO"}


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


def compute_pnl(frame: pd.DataFrame, entry_col: str, fee_col: str) -> pd.Series:
    win = frame["win"].astype(bool)
    entry = frame[entry_col]
    return np.where(win, 1.0 - entry, -entry) - frame[fee_col]


def add_execution_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    half_spread = out["bracket_type"].map(HALF_SPREADS).fillna(0.02)

    out["maker_fee"] = out["entry_price"].apply(lambda p: kalshi_fee(float(p), 1, "maker"))
    out["maker_net"] = compute_pnl(out, "entry_price", "maker_fee")

    out["stress_entry_price"] = (out["entry_price"] + 0.03).clip(upper=0.99)
    out["stress_fee"] = out["stress_entry_price"].apply(lambda p: kalshi_fee(float(p), 1, "maker"))
    out["stress_net"] = compute_pnl(out, "stress_entry_price", "stress_fee") - 0.03

    out["est_half_spread_pp"] = half_spread * 100.0
    out["est_maker_fee_pp"] = out["maker_fee"] * 100.0
    out["est_stress_buffer_pp"] = np.where(out["sleeve"].eq("CORE"), 3.0, 1.0)
    out["est_execution_cost_pp"] = (
        out["est_half_spread_pp"] + out["est_maker_fee_pp"] + out["est_stress_buffer_pp"]
    )
    out["est_net_edge_pp"] = out["gap_pp"].abs() - out["est_execution_cost_pp"]
    return out


def summarize(frame: pd.DataFrame, net_col: str = "net") -> dict:
    if frame.empty:
        return {
            "trades": 0,
            "trading_days": 0,
            "win_rate": 0.0,
            "net_pnl": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "avg_entry_price": 0.0,
            "median_entry_price": 0.0,
            "avg_net_edge_pp": 0.0,
        }
    return {
        "trades": int(len(frame)),
        "trading_days": int(frame["date"].nunique()),
        "win_rate": float(frame["win"].mean()),
        "net_pnl": float(frame[net_col].sum()),
        "sharpe": sharpe(frame[net_col]),
        "max_drawdown": max_drawdown(frame[net_col]),
        "avg_entry_price": float(frame["entry_price"].mean()),
        "median_entry_price": float(frame["entry_price"].median()),
        "avg_net_edge_pp": float(frame["est_net_edge_pp"].mean()) if "est_net_edge_pp" in frame else 0.0,
    }


def policy_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    current = frame["sleeve"].isin(CURRENT_TRADEABLE_SLEEVES)
    not_cold_wing = ~frame["bracket_type"].eq("wing_low")

    cost_gate = (
        ((frame["sleeve"].eq("CORE")) & (frame["est_net_edge_pp"] >= 10.0))
        | ((frame["sleeve"].eq("DEEP_TAIL_NO")) & (frame["est_net_edge_pp"] >= 4.0))
    )

    core_conf = (~frame["sleeve"].eq("CORE")) | (frame["confidence"] >= 60.0)
    core_gap = (~frame["sleeve"].eq("CORE")) | (frame["gap_pp"].abs() >= 20.0)
    central_more_selective = (
        (~frame["sleeve"].eq("CORE"))
        | (~frame["bracket_type"].eq("central"))
        | (frame["confidence"] >= 60.0)
    )
    wing_high_ok = (~frame["sleeve"].eq("CORE")) | (~frame["bracket_type"].eq("wing_high")) | (
        frame["est_net_edge_pp"] >= 8.0
    )

    return {
        "current_strategy": current,
        "cost_gate_only": current & cost_gate,
        "drop_cold_wing": current & not_cold_wing,
        "core_confidence_60": current & core_conf,
        "report_combined_policy": (
            current
            & not_cold_wing
            & cost_gate
            & core_conf
            & core_gap
            & central_more_selective
            & wing_high_ok
        ),
    }


def format_summary_table(rows: list[dict]) -> str:
    header = (
        "| Policy | Trades | Days | Win Rate | Δ Win Rate | Saved Net | Maker Net | Stress +3c Net | Avg Entry | Avg Net Edge |\n"
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    )
    body = []
    for row in rows:
        body.append(
            f"| {row['policy']} | {row['trades']} | {row['trading_days']} | "
            f"{row['win_rate']:.1%} | {row['win_rate_delta_pp']:+.1f}pp | "
            f"${row['saved_net_pnl']:.2f} | ${row['maker_net_pnl']:.2f} | "
            f"${row['stress_net_pnl']:.2f} | {row['avg_entry_price']:.1%} | "
            f"{row['avg_net_edge_pp']:.1f}pp |"
        )
    return "\n".join([header, *body])


def simple_markdown_table(rows: list[dict], columns: list[str]) -> str:
    if not rows:
        return "_No rows._"
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for row in rows:
        body.append("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |")
    return "\n".join([header, sep, *body])


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def main() -> None:
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)

    raw = pd.read_csv(BACKTEST_CSV)
    raw = add_execution_columns(raw)
    masks = policy_masks(raw)

    baseline = raw[masks["current_strategy"]].copy()
    baseline_summary = summarize(baseline, "net")
    baseline_win = baseline_summary["win_rate"]

    rows = []
    policy_frames = []
    for name, mask in masks.items():
        frame = raw[mask].copy()
        frame["policy"] = name
        policy_frames.append(frame)
        saved = summarize(frame, "net")
        maker = summarize(frame, "maker_net")
        stress = summarize(frame, "stress_net")
        rows.append(
            {
                "policy": name,
                "trades": saved["trades"],
                "trading_days": saved["trading_days"],
                "win_rate": saved["win_rate"],
                "win_rate_delta_pp": (saved["win_rate"] - baseline_win) * 100.0,
                "saved_net_pnl": saved["net_pnl"],
                "maker_net_pnl": maker["net_pnl"],
                "stress_net_pnl": stress["net_pnl"],
                "sharpe": saved["sharpe"],
                "max_drawdown": saved["max_drawdown"],
                "avg_entry_price": saved["avg_entry_price"],
                "median_entry_price": saved["median_entry_price"],
                "avg_net_edge_pp": saved["avg_net_edge_pp"],
            }
        )

    all_policy_trades = pd.concat(policy_frames, ignore_index=True)
    all_policy_trades.to_csv(OUTPUT_CSV, index=False)

    combined = raw[masks["report_combined_policy"]].copy()
    sleeve_rows = []
    for sleeve, group in combined.groupby("sleeve"):
        saved = summarize(group, "net")
        stress = summarize(group, "stress_net")
        sleeve_rows.append(
            {
                "sleeve": sleeve,
                "trades": saved["trades"],
                "win_rate": saved["win_rate"],
                "saved_net_pnl": saved["net_pnl"],
                "stress_net_pnl": stress["net_pnl"],
                "avg_entry_price": saved["avg_entry_price"],
            }
        )

    family_rows = []
    for family, group in combined.groupby("bracket_type"):
        saved = summarize(group, "net")
        family_rows.append(
            {
                "bracket_type": family,
                "trades": saved["trades"],
                "win_rate": saved["win_rate"],
                "saved_net_pnl": saved["net_pnl"],
                "avg_entry_price": saved["avg_entry_price"],
            }
        )

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "input": str(BACKTEST_CSV.relative_to(ROOT)),
        "scope": (
            "Research-only overlay on cached settlement-style KXHIGHNY backtest rows. "
            "It tests report selection/execution-policy ideas; it does not retrain EMOS, "
            "quantile forests, or change live strategy logic."
        ),
        "policies": rows,
        "combined_by_sleeve": sleeve_rows,
        "combined_by_bracket_type": family_rows,
        "combined_policy_rules": {
            "tradeable_sleeves": sorted(CURRENT_TRADEABLE_SLEEVES),
            "tail_no": "excluded/suspended",
            "cold_wing": "excluded from combined report policy because cached losses show negative net in CORE and DEEP_TAIL_NO",
            "core_confidence_min": 60.0,
            "core_min_est_net_edge_pp": 10.0,
            "deep_tail_min_est_net_edge_pp": 4.0,
            "execution_cost_pp": "half_spread + maker_fee + sleeve stress buffer",
            "stress_scenario": "+3c worse entry plus +3c additional exit/repricing friction",
        },
    }
    OUTPUT_SUMMARY.write_text(json.dumps(summary, indent=2))

    table = format_summary_table(rows)
    sleeve_table = simple_markdown_table(
        sleeve_rows,
        ["sleeve", "trades", "win_rate", "saved_net_pnl", "stress_net_pnl", "avg_entry_price"],
    )
    family_table = simple_markdown_table(
        family_rows,
        ["bracket_type", "trades", "win_rate", "saved_net_pnl", "avg_entry_price"],
    )
    report = f"""# Report Improvement Backtest

Generated: {summary['generated_at']}

Git SHA: `{summary['git_sha']}`

Input: `{summary['input']}`

## Scope

This is a research-only backtest overlay inspired by `/Users/bhargavsukhavasi/Downloads/deep-research-report (6).md`.

It compares the current cached tradeable strategy (`CORE` + `DEEP_TAIL_NO`, with `TAIL_NO` suspended) against report-inspired selection improvements that are testable from the saved backtest rows:

- require positive edge after an execution-cost prior,
- split bracket families instead of treating central and wings identically,
- keep `DEEP_TAIL_NO` strict,
- avoid the cold/lower-wing subset that has been loss-making in the current cached data,
- require stronger core confidence before deploying capital.

It does **not** retrain EMOS, quantile forests, or gradient boosting. Those need a separate model-training study and true forecast-vintage features. It also does not touch live config, paper/live execution, `main.py`, `event_triggers.py`, or LaunchAgent files.

## Policy Comparison

{table}

## Combined Report Policy By Sleeve

{sleeve_table}

## Combined Report Policy By Bracket Type

{family_table}

## Main Result

The current cached tradeable strategy has a win rate of **{baseline_win:.1%}**.

The combined report-policy overlay has a win rate of **{rows[-1]['win_rate']:.1%}**, a change of **{rows[-1]['win_rate_delta_pp']:+.1f} percentage points**.

Saved-net P&L changes from **${rows[0]['saved_net_pnl']:.2f}** to **${rows[-1]['saved_net_pnl']:.2f}** at $1 contract sizing.

Under the simple `+3c` stress scenario, net P&L changes from **${rows[0]['stress_net_pnl']:.2f}** to **${rows[-1]['stress_net_pnl']:.2f}**.

## Interpretation

The improvement comes mostly from better selection, not a better temperature forecast. The largest rejected subset is the lower/cold wing family, which is negative in both `CORE` and `DEEP_TAIL_NO` in the cached results. The second major improvement is requiring `CORE` confidence >= 60 and enough estimated net edge after execution cost.

Treat this as in-sample research. It is useful evidence for a paper-only policy candidate, not live approval.
"""
    REPORT_MD.write_text(report)

    print("=== REPORT IMPROVEMENT BACKTEST ===")
    print(f"Input: {BACKTEST_CSV.relative_to(ROOT)}")
    print(f"Rows: {len(raw)} total, {len(baseline)} current tradeable")
    print()
    print(table)
    print()
    print("Combined report policy by sleeve:")
    print(pd.DataFrame(sleeve_rows).to_string(index=False))
    print()
    print("Combined report policy by bracket type:")
    print(pd.DataFrame(family_rows).to_string(index=False))
    print()
    print(f"Report saved: {REPORT_MD.relative_to(ROOT)}")
    print(f"Trade rows saved: {OUTPUT_CSV.relative_to(ROOT)}")
    print(f"Summary saved: {OUTPUT_SUMMARY.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
