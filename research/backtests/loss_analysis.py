#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RESEARCH_DIR = DATA_DIR / "research"
REPORTS_DIR = ROOT / "reports"

BACKTEST_RESULTS = DATA_DIR / "backtest_results.csv"
LOSS_TRADES_CSV = RESEARCH_DIR / "loss_analysis_trades.csv"
FACTOR_SUMMARY_CSV = RESEARCH_DIR / "loss_analysis_factor_summary.csv"
IMPROVEMENT_TESTS_CSV = RESEARCH_DIR / "loss_analysis_improvement_tests.csv"
SUMMARY_JSON = RESEARCH_DIR / "loss_analysis_summary.json"
REPORT_MD = REPORTS_DIR / "loss_analysis_report.md"


CURRENT_SLEEVES = ["CORE", "DEEP_TAIL_NO"]


def sharpe(values) -> float:
    arr = np.array(list(values), dtype=float)
    if len(arr) < 2:
        return 0.0
    std = float(np.std(arr, ddof=1))
    return 0.0 if std == 0 else float(np.mean(arr) / std)


def max_drawdown(values) -> float:
    equity = np.cumsum(np.array(list(values), dtype=float))
    if len(equity) == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    return float(np.min(equity - peak))


def summarize(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "net_pnl": 0.0,
            "avg_entry": 0.0,
            "avg_gap_abs": 0.0,
            "avg_model_prob": 0.0,
            "avg_confidence": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
        }
    return {
        "trades": int(len(df)),
        "win_rate": float(df["win"].mean()),
        "net_pnl": float(df["net"].sum()),
        "avg_entry": float(df["entry_price"].mean()),
        "avg_gap_abs": float(df["gap_pp"].abs().mean()),
        "avg_model_prob": float(df["model_prob"].mean()),
        "avg_confidence": float(df["confidence"].mean()),
        "sharpe": sharpe(df["net"]),
        "max_drawdown": max_drawdown(df["net"]),
    }


def add_diagnostics(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out["month_num"] = out["date"].dt.month
    out["quarter"] = out["date"].dt.to_period("Q").astype(str)
    out["is_current_tradeable"] = out["sleeve"].isin(CURRENT_SLEEVES)
    out["gap_abs"] = out["gap_pp"].abs()
    out["spread_between"] = (out["physics_mean"] - out["ai_mean"]).abs()
    out["actual_minus_consensus"] = out["settlement_temp"] - out["consensus"]
    out["entry_bucket"] = pd.cut(
        out["entry_price"],
        bins=[0, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 1.0],
        labels=["<25c", "25-35c", "35-45c", "45-55c", "55-65c", "65-75c", ">75c"],
        include_lowest=True,
    )
    out["gap_bucket"] = pd.cut(
        out["gap_abs"],
        bins=[0, 15, 20, 25, 30, 35, 40, 50, 100],
        labels=["0-15", "15-20", "20-25", "25-30", "30-35", "35-40", "40-50", "50+"],
        include_lowest=True,
    )
    out["prob_bucket"] = pd.cut(
        out["model_prob"],
        bins=[0, 0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0],
        labels=["0-0.5%", "0.5-1%", "1-2%", "2-5%", "5-10%", "10-25%", "25-50%", "50-75%", "75-100%"],
        include_lowest=True,
    )
    out["model_error_bucket"] = pd.cut(
        out["actual_minus_consensus"],
        bins=[-20, -8, -5, -3, -1, 1, 3, 5, 8, 20],
        labels=["<-8F", "-8:-5F", "-5:-3F", "-3:-1F", "-1:+1F", "+1:+3F", "+3:+5F", "+5:+8F", ">+8F"],
        include_lowest=True,
    )
    out["loss_mode"] = out.apply(classify_loss_mode, axis=1)
    return out


def classify_loss_mode(row: pd.Series) -> str:
    if bool(row["win"]):
        return "winner"
    direction = str(row["direction"])
    btype = str(row["bracket_type"])
    err = row.get("actual_minus_consensus")
    if direction == "NO":
        if btype == "wing_high":
            return "NO_loss_hot_upper_tail_hit"
        if btype == "wing_low":
            return "NO_loss_cold_lower_tail_hit"
        if pd.notna(err) and err > 2:
            return "NO_loss_actual_hotter_than_model"
        if pd.notna(err) and err < -2:
            return "NO_loss_actual_colder_than_model"
        return "NO_loss_bracket_hit"
    if btype == "wing_high":
        return "YES_loss_upper_tail_missed"
    if btype == "wing_low":
        return "YES_loss_lower_tail_missed"
    if pd.notna(err) and err > 2:
        return "YES_loss_actual_hotter_than_model"
    if pd.notna(err) and err < -2:
        return "YES_loss_actual_colder_than_model"
    return "YES_loss_near_model_or_adjacent"


def factor_table(df: pd.DataFrame, column: str, label: str) -> pd.DataFrame:
    rows = []
    for value, group in df.groupby(column, dropna=False, observed=False):
        s = summarize(group)
        losers = group[~group["win"]]
        s.update(
            {
                "factor": label,
                "value": str(value),
                "losses": int((~group["win"]).sum()),
                "loss_net": float(losers["net"].sum()) if not losers.empty else 0.0,
                "loss_share": float((~group["win"]).mean()) if not group.empty else 0.0,
            }
        )
        rows.append(s)
    return pd.DataFrame(rows)


def improvement_tests(df: pd.DataFrame) -> pd.DataFrame:
    tests = {
        "baseline_current": df.index == df.index,
        "drop_core_yes": ~((df["sleeve"] == "CORE") & (df["direction"] == "YES")),
        "drop_core_wing_low": ~((df["sleeve"] == "CORE") & (df["bracket_type"] == "wing_low")),
        "core_no_only_plus_deep": ~((df["sleeve"] == "CORE") & (df["direction"] == "YES")),
        "drop_core_entry_45_65": ~((df["sleeve"] == "CORE") & (df["entry_price"].between(0.45, 0.65))),
        "drop_jan_dec": ~df["month_num"].isin([1, 12]),
        "drop_core_conf_lt_60": ~((df["sleeve"] == "CORE") & (df["confidence"] < 60)),
        "require_core_gap_gt_25": (df["sleeve"] != "CORE") | (df["gap_abs"] > 25),
        "require_core_gap_gt_30": (df["sleeve"] != "CORE") | (df["gap_abs"] > 30),
        "deep_tail_stricter_p_lt_1pct": (df["sleeve"] != "DEEP_TAIL_NO") | (df["model_prob"] < 0.01),
        "drop_high_model_disagreement_gt_2f": df["spread_between"] <= 2.0,
        "drop_high_subset_spread_gt_2f": (df["physics_spread"] <= 2.0) & (df["ai_spread"] <= 2.0),
        "drop_settlement_mismatch_rows": ~df["settlement_mismatch"].astype(bool),
    }
    rows = []
    base = summarize(df)
    for name, mask in tests.items():
        kept = df[mask].copy()
        s = summarize(kept)
        s.update(
            {
                "test": name,
                "trades_removed": int(len(df) - len(kept)),
                "net_delta_vs_baseline": s["net_pnl"] - base["net_pnl"],
                "win_rate_delta_vs_baseline": s["win_rate"] - base["win_rate"],
            }
        )
        rows.append(s)
    return pd.DataFrame(rows)


def write_report(df: pd.DataFrame, factors: pd.DataFrame, tests: pd.DataFrame, summary: dict) -> None:
    current = df[df["is_current_tradeable"]].copy()
    losers = current[~current["win"]].copy()
    core = current[current["sleeve"] == "CORE"]
    deep = current[current["sleeve"] == "DEEP_TAIL_NO"]

    def table(frame: pd.DataFrame, cols: list[str], n: int = 12) -> str:
        if frame.empty:
            return "_No rows._"
        view = frame.loc[:, [col for col in cols if col in frame.columns]].head(n).copy()
        for col in view.select_dtypes(include=["float"]).columns:
            view[col] = view[col].map(lambda x: round(float(x), 4))
        headers = list(view.columns)
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
        ]
        for _, row in view.iterrows():
            lines.append("| " + " | ".join(str(row[col]).replace("|", "\\|") for col in headers) + " |")
        return "\n".join(lines)

    top_loss_modes = (
        losers.groupby(["sleeve", "loss_mode"])
        .agg(trades=("ticker", "count"), net=("net", "sum"), avg_entry=("entry_price", "mean"), avg_error=("actual_minus_consensus", "mean"))
        .sort_values("trades", ascending=False)
        .reset_index()
    )
    worst_rows = losers.sort_values("net").head(20)
    key_factor = factors.sort_values(["loss_net", "losses"], ascending=[True, False]).head(30)
    best_tests = tests.sort_values("net_pnl", ascending=False).head(15)

    report = f"""# Loss Analysis Report

Generated from `data/backtest_results.csv`.

This is research-only. It does not change live thresholds, paper policy, execution, `main.py`, or `event_triggers.py`.

## Current Tradeable Strategy Summary

Current tradeable set = `CORE + DEEP_TAIL_NO` (`TAIL_NO` is disabled/suspended).

| Metric | Value |
| --- | ---: |
| Trades | {summary['current']['trades']} |
| Wins | {summary['current']['wins']} |
| Losses | {summary['current']['losses']} |
| Win rate | {summary['current']['win_rate']:.1%} |
| Net P&L | ${summary['current']['net_pnl']:.2f} |
| Loss-side net | ${summary['current']['loss_net']:.2f} |

## Losses By Sleeve

{table(pd.DataFrame(summary['by_sleeve']), ['sleeve', 'trades', 'losses', 'win_rate', 'net_pnl', 'loss_net', 'avg_entry'], 10)}

## Why We Lost

### Loss Mode Breakdown

{table(top_loss_modes, ['sleeve', 'loss_mode', 'trades', 'net', 'avg_entry', 'avg_error'], 20)}

### Worst Individual Losing Trades

{table(worst_rows, ['date', 'ticker', 'sleeve', 'bracket', 'bracket_type', 'direction', 'entry_price', 'gap_pp', 'model_prob', 'confidence', 'consensus', 'settlement_temp', 'actual_minus_consensus', 'loss_mode', 'net'], 20)}

## Factor Diagnostics

The table below shows the factor buckets that contributed the most losing P&L.

{table(key_factor, ['factor', 'value', 'trades', 'losses', 'win_rate', 'net_pnl', 'loss_net', 'avg_entry', 'avg_gap_abs', 'avg_model_prob', 'avg_confidence'], 30)}

## Improvement Tests

These are simple exclusion tests on the current tradeable set. They are not recommendations by themselves because removing trades can improve historical P&L while overfitting.

{table(best_tests, ['test', 'trades', 'trades_removed', 'win_rate', 'net_pnl', 'net_delta_vs_baseline', 'sharpe', 'max_drawdown'], 15)}

## Interpretation

1. Core losses are mostly ordinary model misses: the forecast distribution assigned a bracket too much or too little probability, then the official Kalshi settlement landed against that side.
2. Core YES trades remain weaker than core NO trades. The YES side has lower win rate and needs separate calibration before sizing up.
3. Lower-tail/wing-low core trades are a recurring weak spot in the cached backtest.
4. Deep-tail losses are rare but expensive because the NO entry is often high; a single bracket that actually settles YES can wipe out many small wins.
5. Months and regimes matter. January/December and some high-disagreement/high-spread periods account for a large share of avoidable pain.
6. Settlement mismatches against reconstructed IEM temperatures are diagnostic red flags. P&L uses Kalshi labels, but mismatches identify days where station/settlement reconstruction uncertainty is high.

## Practical Improvements To Research Next

1. Split probability calibration by side: YES core, NO core, deep-tail NO.
2. Add a core wing-low penalty or require larger edge for lower-tail brackets.
3. Keep DEEP_TAIL_NO strict at `P_yes < 2%` until fill-stressed forward paper data says otherwise.
4. Add a paper-only flag that logs would-have-skipped results for high model disagreement or high subset spread.
5. Build true forecast-vintage rows so we can identify whether losses came from forecast leakage, late model changes, or price timing.
6. Add post-entry path labels from Becker trade prints for each losing core trade: adverse excursion, favorable excursion, target touched, stop touched.
7. Preserve 20pp live threshold until these filters are walk-forward validated.

## Output Files

- `{LOSS_TRADES_CSV.relative_to(ROOT)}`
- `{FACTOR_SUMMARY_CSV.relative_to(ROOT)}`
- `{IMPROVEMENT_TESTS_CSV.relative_to(ROOT)}`
- `{SUMMARY_JSON.relative_to(ROOT)}`
"""
    REPORT_MD.write_text(report)


def main() -> None:
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    raw = pd.read_csv(BACKTEST_RESULTS)
    df = add_diagnostics(raw)
    current = df[df["is_current_tradeable"]].copy()
    losers = current[~current["win"]].copy()
    losers.to_csv(LOSS_TRADES_CSV, index=False)

    factor_frames = []
    for column, label in [
        ("sleeve", "sleeve"),
        ("direction", "direction"),
        ("bracket_type", "bracket_type"),
        ("month", "month"),
        ("entry_bucket", "entry_bucket"),
        ("gap_bucket", "gap_bucket"),
        ("prob_bucket", "model_prob_bucket"),
        ("model_error_bucket", "actual_minus_consensus_bucket"),
        ("loss_mode", "loss_mode"),
        ("settlement_mismatch", "settlement_mismatch"),
    ]:
        factor_frames.append(factor_table(current, column, label))
    factors = pd.concat(factor_frames, ignore_index=True)
    factors.to_csv(FACTOR_SUMMARY_CSV, index=False)

    tests = improvement_tests(current)
    tests.to_csv(IMPROVEMENT_TESTS_CSV, index=False)

    by_sleeve = []
    for sleeve, group in current.groupby("sleeve"):
        s = summarize(group)
        s.update(
            {
                "sleeve": sleeve,
                "losses": int((~group["win"]).sum()),
                "wins": int(group["win"].sum()),
                "loss_net": float(group.loc[~group["win"], "net"].sum()),
            }
        )
        by_sleeve.append(s)

    summary = {
        "current": {
            **summarize(current),
            "wins": int(current["win"].sum()),
            "losses": int((~current["win"]).sum()),
            "loss_net": float(current.loc[~current["win"], "net"].sum()),
        },
        "all_saved": {
            **summarize(df),
            "wins": int(df["win"].sum()),
            "losses": int((~df["win"]).sum()),
            "loss_net": float(df.loc[~df["win"], "net"].sum()),
        },
        "by_sleeve": by_sleeve,
        "top_loss_modes": (
            losers.groupby(["sleeve", "loss_mode"])
            .size()
            .sort_values(ascending=False)
            .head(20)
            .reset_index(name="trades")
            .to_dict(orient="records")
        ),
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, default=str))
    write_report(df, factors, tests, summary)

    print("=== LOSS ANALYSIS COMPLETE ===")
    print(f"Current tradeable trades: {summary['current']['trades']}")
    print(f"Current tradeable losses: {summary['current']['losses']}")
    print(f"Current tradeable win rate: {summary['current']['win_rate']:.1%}")
    print(f"Current tradeable net P&L: ${summary['current']['net_pnl']:.2f}")
    print(f"Loss-side net: ${summary['current']['loss_net']:.2f}")
    print("\nBy sleeve:")
    for row in by_sleeve:
        print(
            f"  {row['sleeve']}: trades={row['trades']}, losses={row['losses']}, "
            f"win={row['win_rate']:.1%}, net=${row['net_pnl']:.2f}, loss_net=${row['loss_net']:.2f}"
        )
    print(f"\nReport saved to {REPORT_MD}")


if __name__ == "__main__":
    main()
