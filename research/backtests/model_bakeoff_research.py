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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.calibration_models import EMOSModel, HGBRQuantileModel, RandomForestDistributionModel
from models.distributional_temp import DistributionalTempModel


DATA_DIR = ROOT / "data"
RESEARCH_DIR = DATA_DIR / "research"
REPORTS_DIR = ROOT / "reports"
MARKETS_CSV = DATA_DIR / "kxhighny_markets.csv"
PRICES_CSV = DATA_DIR / "kxhighny_prices.csv"
MODELS_CSV = DATA_DIR / "open_meteo_historical.csv"
OUT_PREDICTIONS = RESEARCH_DIR / "model_bakeoff_predictions.csv"
OUT_TRADES = RESEARCH_DIR / "model_bakeoff_strategy_trades.csv"
OUT_SUMMARY = RESEARCH_DIR / "model_bakeoff_summary.json"
OUT_REPORT = REPORTS_DIR / "model_bakeoff_research.md"

FEATURES = [
    "gfs_maxt",
    "ecmwf_maxt",
    "ukmo_maxt",
    "nbm_maxt",
    "consensus",
    "model_spread",
    "physics_mean",
    "ai_mean",
    "spread_between",
    "month",
    "day_of_year",
]

TRAIN_MIN_DAYS = 120
EVAL_STRIDE_DAYS = 7
ENTRY_COL = "yes_price_9AM"


def kalshi_fee(price: float) -> float:
    return math.ceil(0.07 * price * (1.0 - price) * 100.0) / 100.0


def sharpe(values: Iterable[float]) -> float:
    arr = np.array(list(values), dtype=float)
    if len(arr) < 2:
        return 0.0
    std = float(np.std(arr, ddof=1))
    return 0.0 if std == 0 else float(np.mean(arr) / std)


def max_drawdown(values: Iterable[float]) -> float:
    arr = np.array(list(values), dtype=float)
    if len(arr) == 0:
        return 0.0
    equity = np.cumsum(arr)
    peak = np.maximum.accumulate(equity)
    return float(np.min(equity - peak))


def bracket_label(row: pd.Series) -> str:
    btype = row["bracket_type"]
    lo = row["floor_strike"]
    hi = row["cap_strike"]
    if btype == "wing_low":
        return f"<={hi:g}F"
    if btype == "wing_high":
        return f">{lo:g}F"
    return f"{lo:g}-{hi:g}F"


def build_dataset() -> tuple[pd.DataFrame, pd.DataFrame]:
    markets = pd.read_csv(MARKETS_CSV)
    prices = pd.read_csv(PRICES_CSV)
    forecasts = pd.read_csv(MODELS_CSV).rename(columns={"date": "target_date"})

    markets["kalshi_result_yes"] = markets["settlement_value"].astype(str).str.lower().eq("yes")
    winners = markets[markets["kalshi_result_yes"] & markets["raw_settlement_temp"].notna()][
        ["target_date", "raw_settlement_temp"]
    ].drop_duplicates("target_date")
    daily = forecasts.merge(winners, on="target_date", how="inner").dropna(
        subset=["gfs_maxt", "ecmwf_maxt", "ukmo_maxt", "nbm_maxt", "raw_settlement_temp"]
    )
    daily["target_date"] = pd.to_datetime(daily["target_date"])
    daily = daily.sort_values("target_date").reset_index(drop=True)
    daily["physics_mean"] = daily[["gfs_maxt", "ecmwf_maxt"]].mean(axis=1)
    daily["ai_mean"] = daily[["ukmo_maxt", "nbm_maxt"]].mean(axis=1)
    daily["spread_between"] = (daily["physics_mean"] - daily["ai_mean"]).abs()
    daily["consensus"] = (
        0.25 * daily["gfs_maxt"]
        + 0.35 * daily["ecmwf_maxt"]
        + 0.20 * daily["ukmo_maxt"]
        + 0.20 * daily["nbm_maxt"]
    )
    daily["model_spread"] = daily[["gfs_maxt", "ecmwf_maxt", "ukmo_maxt", "nbm_maxt"]].std(axis=1)
    daily["month"] = daily["target_date"].dt.month
    daily["day_of_year"] = daily["target_date"].dt.dayofyear
    daily["date"] = daily["target_date"].dt.strftime("%Y-%m-%d")

    rows = markets.merge(prices, on=["ticker", "target_date"], how="left")
    rows = rows.merge(daily[["date", *FEATURES]], left_on="target_date", right_on="date", how="inner")
    rows["bracket"] = rows.apply(bracket_label, axis=1)
    rows = rows[rows[ENTRY_COL].notna()].copy()
    return daily, rows


def brackets_for_day(day_group: pd.DataFrame) -> list[dict]:
    return [
        {
            "ticker": row["ticker"],
            "lo_f": None if pd.isna(row["floor_strike"]) else float(row["floor_strike"]),
            "hi_f": None if pd.isna(row["cap_strike"]) else float(row["cap_strike"]),
            "bracket_type": row["bracket_type"],
        }
        for _, row in day_group.iterrows()
    ]


def gumbel_probs(row: pd.Series, day_group: pd.DataFrame) -> dict[str, float]:
    dist = DistributionalTempModel()
    return dist.bracket_probabilities(float(row["consensus"]), brackets_for_day(day_group))


def fit_predict_model(model_name: str, train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray, brackets: list[dict]) -> dict:
    if model_name == "EMOS":
        return EMOSModel().fit(train_x, train_y).bracket_probabilities(test_x, brackets)
    if model_name == "RF_DISTRIBUTION":
        return RandomForestDistributionModel(n_estimators=60, min_samples_leaf=6).fit(train_x, train_y).bracket_probabilities(test_x, brackets)
    if model_name == "HGBR_QUANTILE":
        return HGBRQuantileModel(max_iter=50, learning_rate=0.05).fit(train_x, train_y).bracket_probabilities(test_x, brackets)
    raise ValueError(model_name)


def rolling_predictions(daily: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    predictions = []
    daily = daily.reset_index(drop=True)
    model_names = ["GUMBEL", "EMOS", "RF_DISTRIBUTION", "HGBR_QUANTILE"]
    for idx in range(TRAIN_MIN_DAYS, len(daily), EVAL_STRIDE_DAYS):
        train = daily.iloc[:idx]
        test = daily.iloc[idx]
        day = test["date"]
        day_group = rows[rows["target_date"] == day]
        if day_group.empty:
            continue
        brackets = brackets_for_day(day_group)
        train_x = train[FEATURES].to_numpy(dtype=float)
        train_y = train["raw_settlement_temp"].to_numpy(dtype=float)
        test_x = test[FEATURES].to_numpy(dtype=float)
        probs_by_model = {"GUMBEL": gumbel_probs(test, day_group)}
        for model_name in model_names[1:]:
            try:
                probs_by_model[model_name] = fit_predict_model(model_name, train_x, train_y, test_x, brackets)
            except Exception as exc:
                print(f"WARNING: {model_name} failed for {day}: {exc}")
                continue
        for model_name, probs in probs_by_model.items():
            for _, row in day_group.iterrows():
                prob = float(probs.get(row["ticker"], np.nan))
                if not np.isfinite(prob):
                    continue
                predictions.append(
                    {
                        "date": day,
                        "ticker": row["ticker"],
                        "bracket": row["bracket"],
                        "bracket_type": row["bracket_type"],
                        "model_name": model_name,
                        "probability": prob,
                        "kalshi_result_yes": bool(row["kalshi_result_yes"]),
                        "yes_price_9AM": float(row[ENTRY_COL]),
                    }
                )
    return pd.DataFrame(predictions)


def probability_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for model_name, group in predictions.groupby("model_name"):
        p = group["probability"].astype(float).clip(1e-9, 1 - 1e-9)
        y = group["kalshi_result_yes"].astype(int)
        true_rows = group[group["kalshi_result_yes"]]
        multiclass_log_loss = float(-np.mean(np.log(true_rows["probability"].clip(1e-9, 1.0)))) if not true_rows.empty else 0.0
        mass = group.groupby("date")["probability"].sum()
        rows.append(
            {
                "model_name": model_name,
                "rows": int(len(group)),
                "days": int(group["date"].nunique()),
                "brier_score": float(np.mean((p - y) ** 2)),
                "binary_log_loss": float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))),
                "winner_log_loss": multiclass_log_loss,
                "mass_avg": float(mass.mean()),
                "mass_min": float(mass.min()),
                "mass_max": float(mass.max()),
            }
        )
    return pd.DataFrame(rows).sort_values("winner_log_loss")


def simulate_strategy(predictions: pd.DataFrame) -> pd.DataFrame:
    trades = []
    for _, row in predictions.iterrows():
        price = float(row["yes_price_9AM"])
        prob = float(row["probability"])
        gap_pp = (prob - price) * 100.0
        direction = "YES" if gap_pp > 0 else "NO"
        entry_price = price if direction == "YES" else 1.0 - price
        if abs(gap_pp) <= 20.0:
            continue
        if 35.0 <= abs(gap_pp) <= 40.0:
            continue
        if not 0.25 <= entry_price <= 0.75:
            continue
        if row["bracket_type"] == "wing_low":
            continue
        win = bool(row["kalshi_result_yes"]) if direction == "YES" else not bool(row["kalshi_result_yes"])
        gross = 1.0 - entry_price if win else -entry_price
        fee = kalshi_fee(entry_price)
        trades.append(
            {
                "date": row["date"],
                "ticker": row["ticker"],
                "model_name": row["model_name"],
                "bracket_type": row["bracket_type"],
                "direction": direction,
                "entry_price": entry_price,
                "gap_pp": gap_pp,
                "win": win,
                "net": gross - fee,
            }
        )
    return pd.DataFrame(trades)


def trade_metrics(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for model_name, group in trades.groupby("model_name"):
        rows.append(
            {
                "model_name": model_name,
                "trades": int(len(group)),
                "days": int(group["date"].nunique()),
                "win_rate": float(group["win"].mean()),
                "net_pnl": float(group["net"].sum()),
                "sharpe": sharpe(group["net"]),
                "max_drawdown": max_drawdown(group["net"]),
                "avg_entry_price": float(group["entry_price"].mean()),
            }
        )
    return pd.DataFrame(rows).sort_values("net_pnl", ascending=False)


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_No rows._"
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for _, row in df.iterrows():
        values = []
        for col in cols:
            val = row[col]
            if isinstance(val, float):
                values.append(f"{val:.4f}")
            else:
                values.append(str(val))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def main() -> None:
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    daily, rows = build_dataset()
    predictions = rolling_predictions(daily, rows)
    trades = simulate_strategy(predictions)
    prob_summary = probability_metrics(predictions)
    trade_summary = trade_metrics(trades)
    predictions.to_csv(OUT_PREDICTIONS, index=False)
    trades.to_csv(OUT_TRADES, index=False)

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "train_min_days": TRAIN_MIN_DAYS,
        "eval_stride_days": EVAL_STRIDE_DAYS,
        "entry_col": ENTRY_COL,
        "days_total": int(daily["date"].nunique()),
        "days_evaluated": int(predictions["date"].nunique()) if not predictions.empty else 0,
        "probability_metrics": prob_summary.to_dict(orient="records"),
        "strategy_metrics": trade_summary.to_dict(orient="records"),
        "scope": "Research-only rolling-origin model bakeoff; no live strategy code changed.",
    }
    OUT_SUMMARY.write_text(json.dumps(summary, indent=2))

    report = f"""# Model Bakeoff Research

Generated: {summary['generated_at']}

Git SHA: `{summary['git_sha']}`

## Scope

This is a research-only implementation of the valid parts of
`/Users/bhargavsukhavasi/Downloads/deep-research-report (8).md`.

It compares the current coherent Gumbel baseline against three offline
post-processing models:

- `EMOS`: linear bias correction plus residual normal spread,
- `RF_DISTRIBUTION`: random-forest tree-prediction empirical distribution,
- `HGBR_QUANTILE`: histogram gradient boosting quantile distribution.

The bakeoff uses weekly rolling-origin validation with at least {TRAIN_MIN_DAYS}
prior training days. It uses Kalshi settlement labels for bracket outcomes and the
winning market's raw settlement temperature for continuous training. It does not
touch live strategy logic, `config.py`, `main.py`, `event_triggers.py`, or the
LaunchAgent.

## Probability Metrics

{markdown_table(prob_summary)}

## Strategy Overlay Metrics

The strategy overlay uses the same basic research gates for each model's
probability map: 9AM price, 20pp edge, 35-40pp dead-zone exclusion, 25-75c side
price band, and lower-tail caution.

{markdown_table(trade_summary)}

## Read

This establishes the model-bakeoff framework the report asked for. Do not
promote any model from this single retrospective run. A model is only a future
paper candidate if it improves probability metrics and survives the existing
execution-stress policy tests.
"""
    OUT_REPORT.write_text(report)

    print("=== MODEL BAKEOFF RESEARCH ===")
    print(f"Daily rows: {len(daily)}")
    print(f"Evaluation days: {summary['days_evaluated']}")
    print("\nProbability metrics:")
    print(prob_summary.to_string(index=False))
    print("\nStrategy overlay metrics:")
    print(trade_summary.to_string(index=False))
    print(f"\nReport saved: {OUT_REPORT.relative_to(ROOT)}")
    print(f"Predictions saved: {OUT_PREDICTIONS.relative_to(ROOT)}")
    print(f"Trades saved: {OUT_TRADES.relative_to(ROOT)}")
    print(f"Summary saved: {OUT_SUMMARY.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
