#!/usr/bin/env python3
"""
Complete model bakeoff v2.

Improvements over v1:
- Train on all pre-2026 historical data; evaluate on 2026+ dates only.
- Entry price from predexon orderbook at 9:51 AM ET instead of 9AM CSV snapshot.
- Always-maker execution: YES buy at best_bid, NO buy at (100-best_ask)/100.
- Maker fee (0.0175 rate) instead of taker (0.07).
- Reports fill-depth availability and spread statistics.
- Includes EMOS-Gumbel, heteroscedastic EMOS-Gumbel, IDR, NGBoost, and NGBoost-Gumbel.

Run collect_orderbooks.py first to build data/research/predexon_orderbooks.parquet.
"""
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

from research.models.calibration_models import (
    EMOSModel,
    EMOSGumbelHeteroModel,
    EMOSGumbelModel,
    HGBRQuantileModel,
    IDRTemperatureModel,
    NGBoostGumbelModel,
    NGBoostModel,
    RandomForestDistributionModel,
    SeasonalEMOSModel,
)
from models.distributional_temp import DistributionalTempModel

DATA_DIR = ROOT / "data"
RESEARCH_DIR = DATA_DIR / "research"
REPORTS_DIR = ROOT / "reports"
MARKETS_CSV = DATA_DIR / "kxhighny_markets.csv"
PRICES_CSV = DATA_DIR / "kxhighny_prices.csv"
_MODELS_EXT = DATA_DIR / "open_meteo_historical_extended.csv"
_ACTUALS_EXT = DATA_DIR / "knyc_actual_temps_extended.csv"
MODELS_CSV = _MODELS_EXT if _MODELS_EXT.exists() else DATA_DIR / "open_meteo_historical.csv"
ACTUALS_CSV = _ACTUALS_EXT if _ACTUALS_EXT.exists() else DATA_DIR / "knyc_actual_temps.csv"
ORDERBOOKS_PARQUET = RESEARCH_DIR / "predexon_orderbooks.parquet"

REAL_FORECAST_CUTOFF = pd.Timestamp("2024-10-01")
HINDCAST_WEIGHT = 0.5

OUT_PREDICTIONS = RESEARCH_DIR / "model_bakeoff_v2_predictions.csv"
OUT_TRADES = RESEARCH_DIR / "model_bakeoff_v2_trades.csv"
OUT_SUMMARY = RESEARCH_DIR / "model_bakeoff_v2_summary.json"
OUT_REPORT = REPORTS_DIR / "model_bakeoff_v2_research.md"

TRAIN_CUTOFF = "2026-01-07"  # predexon orderbook availability
MAKER_FEE_RATE = 0.0175
TAKER_FEE_RATE = 0.07        # reference only — not used in execution

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

MIN_GAP_PP = 20.0
DEAD_ZONE_LO = 35.0
DEAD_ZONE_HI = 40.0
MIN_ENTRY_PRICE = 0.25
MAX_ENTRY_PRICE = 0.75

# decision time millisecond offset from midnight UTC — computed dynamically per date
# 9:51 AM ET; ET offset varies by DST


def maker_fee(price: float, contracts: int = 1) -> float:
    return math.ceil(MAKER_FEE_RATE * contracts * price * (1.0 - price) * 100.0) / 100.0


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


def build_dataset() -> tuple[pd.DataFrame, pd.DataFrame]:
    markets = pd.read_csv(MARKETS_CSV)
    prices = pd.read_csv(PRICES_CSV)
    forecasts = pd.read_csv(MODELS_CSV).rename(columns={"date": "target_date"})
    actuals = pd.read_csv(ACTUALS_CSV).rename(columns={"date": "target_date", "max_temp_f": "actual_temp"})

    model_cols = ["gfs_maxt", "ecmwf_maxt", "ukmo_maxt", "nbm_maxt"]
    forecasts = forecasts[forecasts["gfs_maxt"].notna()].copy()
    row_mean = forecasts[model_cols].mean(axis=1)
    for col in model_cols:
        forecasts[col] = forecasts[col].fillna(row_mean)

    markets["kalshi_result_yes"] = (
        markets["settlement_value"].astype(str).str.lower().eq("yes")
    )
    kalshi_actuals = (
        markets[markets["kalshi_result_yes"] & markets["raw_settlement_temp"].notna()][
            ["target_date", "raw_settlement_temp"]
        ]
        .drop_duplicates("target_date")
        .rename(columns={"raw_settlement_temp": "actual_temp"})
    )

    daily = forecasts.merge(actuals, on="target_date", how="left")
    missing_mask = daily["actual_temp"].isna()
    if missing_mask.any():
        daily = daily.merge(kalshi_actuals, on="target_date", how="left", suffixes=("", "_kalshi"))
        daily["actual_temp"] = daily["actual_temp"].fillna(daily["actual_temp_kalshi"])
        daily = daily.drop(columns=["actual_temp_kalshi"], errors="ignore")
    daily = daily.dropna(subset=["actual_temp"])

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
    daily["model_spread"] = daily[model_cols].std(axis=1)
    daily["month"] = daily["target_date"].dt.month
    daily["day_of_year"] = daily["target_date"].dt.dayofyear
    daily["date"] = daily["target_date"].dt.strftime("%Y-%m-%d")
    daily["sample_weight"] = np.where(daily["target_date"] >= REAL_FORECAST_CUTOFF, 1.0, HINDCAST_WEIGHT)

    rows = markets.merge(prices, on=["ticker", "target_date"], how="left")
    rows = rows.merge(
        daily[["date", *FEATURES]], left_on="target_date", right_on="date", how="inner"
    )
    rows["bracket"] = rows.apply(bracket_label, axis=1)
    return daily, rows


def load_orderbooks() -> pd.DataFrame:
    if not ORDERBOOKS_PARQUET.exists():
        print(f"WARNING: {ORDERBOOKS_PARQUET} not found — run collect_orderbooks.py first")
        return pd.DataFrame()
    ob = pd.read_parquet(ORDERBOOKS_PARQUET)
    ob["target_date"] = ob["target_date"].astype(str)
    return ob


def decision_ms_for_date(date_str: str) -> int:
    """9:51 AM ET in milliseconds, accounting for DST."""
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
    d = datetime.strptime(date_str, "%Y-%m-%d")
    dt_et = datetime(d.year, d.month, d.day, 9, 51, tzinfo=ET)
    return int(dt_et.timestamp() * 1000)


def nearest_snapshot(
    ob_ticker: pd.DataFrame, target_ms: int
) -> pd.Series | None:
    if ob_ticker.empty:
        return None
    idx = (ob_ticker["timestamp_ms"] - target_ms).abs().idxmin()
    snap = ob_ticker.loc[idx]
    # reject if snapshot is more than 30 minutes away
    if abs(int(snap["timestamp_ms"]) - target_ms) > 30 * 60 * 1000:
        return None
    return snap


def gumbel_probs(row: pd.Series, day_group: pd.DataFrame) -> dict[str, float]:
    dist = DistributionalTempModel()
    return dist.bracket_probabilities(float(row["consensus"]), brackets_for_day(day_group))


def run_bakeoff(
    daily: pd.DataFrame, rows: pd.DataFrame, ob: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    train_daily = daily[daily["date"] < TRAIN_CUTOFF].reset_index(drop=True)
    eval_daily = daily[daily["date"] >= TRAIN_CUTOFF].reset_index(drop=True)

    print(f"Training days: {len(train_daily)}  |  Evaluation days: {len(eval_daily)}")

    if len(train_daily) < 30:
        raise RuntimeError("Not enough training data (need ≥30 days pre-2026)")

    train_x = train_daily[FEATURES].to_numpy(dtype=float)
    train_y = train_daily["actual_temp"].to_numpy(dtype=float)
    train_w = train_daily["sample_weight"].to_numpy(dtype=float) if "sample_weight" in train_daily.columns else None

    model_names = [
        "GUMBEL",
        "EMOS",
        "EMOS_GUMBEL",
        "EMOS_GUMBEL_HETERO",
        "IDR",
        "NGBOOST",
        "NGBOOST_GUMBEL",
        "SEASONAL_EMOS",
        "RF_DISTRIBUTION",
        "HGBR_QUANTILE",
    ]
    # fit ML models once on all training data
    fitted: dict[str, object] = {}
    for model_name in model_names[1:]:
        try:
            if model_name == "EMOS":
                fitted[model_name] = EMOSModel().fit(train_x, train_y, sample_weight=train_w)
            elif model_name == "EMOS_GUMBEL":
                fitted[model_name] = EMOSGumbelModel().fit(train_x, train_y, sample_weight=train_w)
            elif model_name == "EMOS_GUMBEL_HETERO":
                fitted[model_name] = EMOSGumbelHeteroModel().fit(train_x, train_y, sample_weight=train_w)
            elif model_name == "IDR":
                fitted[model_name] = IDRTemperatureModel().fit(train_x, train_y, sample_weight=train_w)
            elif model_name == "NGBOOST":
                fitted[model_name] = NGBoostModel(n_estimators=100).fit(
                    train_x, train_y, sample_weight=train_w
                )
            elif model_name == "NGBOOST_GUMBEL":
                fitted[model_name] = NGBoostGumbelModel(n_estimators=100).fit(
                    train_x, train_y, sample_weight=train_w
                )
            elif model_name == "SEASONAL_EMOS":
                fitted[model_name] = SeasonalEMOSModel().fit(train_x, train_y)
            elif model_name == "RF_DISTRIBUTION":
                fitted[model_name] = RandomForestDistributionModel(
                    n_estimators=60, min_samples_leaf=6
                ).fit(train_x, train_y)
            elif model_name == "HGBR_QUANTILE":
                fitted[model_name] = HGBRQuantileModel(
                    max_iter=50, learning_rate=0.05
                ).fit(train_x, train_y)
        except Exception as exc:
            print(f"WARNING: {model_name} fit failed: {exc}")

    ob_by_ticker: dict[str, pd.DataFrame] = {}
    if not ob.empty:
        for ticker, grp in ob.groupby("ticker"):
            ob_by_ticker[ticker] = grp.sort_values("timestamp_ms").reset_index(drop=True)

    predictions: list[dict] = []

    for _, test in eval_daily.iterrows():
        day = test["date"]
        day_group = rows[rows["target_date"] == day]
        if day_group.empty:
            continue
        brackets = brackets_for_day(day_group)
        test_x = test[FEATURES].to_numpy(dtype=float)

        probs_by_model: dict[str, dict] = {
            "GUMBEL": gumbel_probs(test, day_group)
        }
        for model_name, model in fitted.items():
            try:
                probs_by_model[model_name] = model.bracket_probabilities(test_x, brackets)
            except Exception as exc:
                print(f"WARNING: {model_name} predict failed for {day}: {exc}")

        target_ms = decision_ms_for_date(day)

        for model_name, probs in probs_by_model.items():
            for _, row in day_group.iterrows():
                prob = float(probs.get(row["ticker"], np.nan))
                if not np.isfinite(prob):
                    continue

                # orderbook execution at 9:51 AM ET
                snap = None
                ob_ticker_df = ob_by_ticker.get(row["ticker"])
                if ob_ticker_df is not None:
                    snap = nearest_snapshot(ob_ticker_df, target_ms)

                if snap is not None and pd.notna(snap.get("best_bid")) and pd.notna(snap.get("best_ask")):
                    best_bid_c = int(snap["best_bid"])   # cents
                    best_ask_c = int(snap["best_ask"])   # cents
                    bid_depth = int(snap["bid_depth"] or 0)
                    ask_depth = int(snap["ask_depth"] or 0)
                    entry_source = "orderbook"
                else:
                    # fallback to 9AM CSV price (treat as mid; set synthetic spread)
                    p9am = row.get("yes_price_9AM")
                    if pd.isna(p9am):
                        continue
                    best_bid_c = round(float(p9am) * 100) - 1
                    best_ask_c = round(float(p9am) * 100) + 1
                    bid_depth = 10
                    ask_depth = 10
                    entry_source = "fallback_9am"

                mid = (best_bid_c + best_ask_c) / 200.0
                spread_cents = best_ask_c - best_bid_c

                # direction: compare model prob to market mid
                if prob > mid:
                    direction = "YES"
                    entry_price = best_bid_c / 100.0   # maker: post at best bid
                    fill_depth = bid_depth              # depth queue we join
                    gap_pp = (prob - entry_price) * 100.0
                else:
                    direction = "NO"
                    entry_price = (100 - best_ask_c) / 100.0  # maker: best no_bid
                    fill_depth = ask_depth
                    gap_pp = ((1.0 - prob) - entry_price) * 100.0

                fee = maker_fee(entry_price)

                predictions.append({
                    "date": day,
                    "ticker": row["ticker"],
                    "bracket": row["bracket"],
                    "bracket_type": row["bracket_type"],
                    "model_name": model_name,
                    "probability": prob,
                    "kalshi_result_yes": bool(row["kalshi_result_yes"]),
                    "direction": direction,
                    "entry_price": entry_price,
                    "mid_price": mid,
                    "spread_cents": spread_cents,
                    "fill_depth": fill_depth,
                    "gap_pp": gap_pp,
                    "maker_fee": fee,
                    "net_edge_pp": gap_pp - fee * 100.0,
                    "entry_source": entry_source,
                    "best_bid_c": best_bid_c,
                    "best_ask_c": best_ask_c,
                })

    predictions_df = pd.DataFrame(predictions)
    if predictions_df.empty:
        return predictions_df, pd.DataFrame()

    trades = simulate_strategy(predictions_df)
    return predictions_df, trades


def simulate_strategy(preds: pd.DataFrame) -> pd.DataFrame:
    trades: list[dict] = []
    for _, row in preds.iterrows():
        gap_pp = float(row["gap_pp"])
        entry_price = float(row["entry_price"])
        fill_depth = int(row["fill_depth"])
        fee = float(row["maker_fee"])

        if gap_pp <= MIN_GAP_PP:
            continue
        if DEAD_ZONE_LO <= gap_pp <= DEAD_ZONE_HI:
            continue
        if not MIN_ENTRY_PRICE <= entry_price <= MAX_ENTRY_PRICE:
            continue
        if row["bracket_type"] == "wing_low":
            continue

        direction = row["direction"]
        result_yes = bool(row["kalshi_result_yes"])
        win = result_yes if direction == "YES" else not result_yes
        gross = (1.0 - entry_price) if win else (-entry_price)
        net = gross - fee
        no_fill = fill_depth == 0

        trades.append({
            "date": row["date"],
            "ticker": row["ticker"],
            "model_name": row["model_name"],
            "bracket_type": row["bracket_type"],
            "direction": direction,
            "entry_price": entry_price,
            "spread_cents": row["spread_cents"],
            "fill_depth": fill_depth,
            "gap_pp": gap_pp,
            "maker_fee": fee,
            "net_edge_pp": row["net_edge_pp"],
            "entry_source": row["entry_source"],
            "win": win,
            "net": net,
            "no_fill": no_fill,
        })
    return pd.DataFrame(trades)


def stress_test_trades(trades: pd.DataFrame, shock_pp: float) -> pd.DataFrame:
    """
    Adverse execution shock: entry price worsens by shock_pp/100.
    Models what happens if your limit order only fills 2pp worse than best_bid/no_bid
    (e.g., queue priority or stale book between decision and fill).
    Trades that no longer clear the MIN_GAP_PP gate after stress are dropped.
    """
    if trades.empty:
        return pd.DataFrame()
    shock = shock_pp / 100.0
    stressed = trades.copy()
    stressed["entry_price"] = stressed["entry_price"] + shock
    stressed["gap_pp"] = stressed["gap_pp"] - shock_pp
    stressed["maker_fee"] = stressed.apply(
        lambda r: maker_fee(float(r["entry_price"])), axis=1
    )
    stressed["net_edge_pp"] = stressed["gap_pp"] - stressed["maker_fee"] * 100.0
    # re-apply entry price band after stress
    stressed = stressed[
        (stressed["gap_pp"] > MIN_GAP_PP)
        & (stressed["entry_price"] >= MIN_ENTRY_PRICE)
        & (stressed["entry_price"] <= MAX_ENTRY_PRICE)
    ].copy()
    # recompute net outcome with stressed entry
    def recompute_net(row: pd.Series) -> float:
        gross = (1.0 - row["entry_price"]) if row["win"] else (-row["entry_price"])
        return gross - row["maker_fee"]
    stressed["net"] = stressed.apply(recompute_net, axis=1)
    return stressed


def stress_metrics(stressed: pd.DataFrame, baseline_trades: pd.DataFrame, shock_pp: float) -> pd.DataFrame:
    rows = []
    all_models = baseline_trades["model_name"].unique() if not baseline_trades.empty else []
    for model_name in all_models:
        base = baseline_trades[baseline_trades["model_name"] == model_name]
        st = stressed[stressed["model_name"] == model_name] if not stressed.empty else pd.DataFrame()
        base_trades = len(base[~base["no_fill"]])
        st_trades = len(st)
        rows.append({
            "model_name": model_name,
            "base_trades": base_trades,
            "stressed_trades": st_trades,
            "trades_dropped_pct": round((1 - st_trades / base_trades) * 100, 1) if base_trades > 0 else 0.0,
            "stressed_win_rate": float(st["win"].mean()) if not st.empty else float("nan"),
            "stressed_net_pnl": float(st["net"].sum()) if not st.empty else 0.0,
            "stressed_sharpe": sharpe(st["net"]) if not st.empty else 0.0,
            "stressed_max_dd": max_drawdown(st["net"]) if not st.empty else 0.0,
        })
    return pd.DataFrame(rows).sort_values("stressed_net_pnl", ascending=False)


def probability_metrics(preds: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for model_name, group in preds.groupby("model_name"):
        p = group["probability"].astype(float).clip(1e-9, 1 - 1e-9)
        y = group["kalshi_result_yes"].astype(int)
        true_rows = group[group["kalshi_result_yes"]]
        winner_ll = (
            float(-np.mean(np.log(true_rows["probability"].clip(1e-9, 1.0))))
            if not true_rows.empty
            else 0.0
        )
        rows.append({
            "model_name": model_name,
            "rows": int(len(group)),
            "days": int(group["date"].nunique()),
            "brier_score": float(np.mean((p - y) ** 2)),
            "binary_log_loss": float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))),
            "winner_log_loss": winner_ll,
        })
    return pd.DataFrame(rows).sort_values("brier_score")


def trade_metrics(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    rows = []
    for model_name, group in trades.groupby("model_name"):
        fillable = group[~group["no_fill"]]
        rows.append({
            "model_name": model_name,
            "trades": int(len(group)),
            "no_fill_trades": int(group["no_fill"].sum()),
            "days": int(group["date"].nunique()),
            "win_rate": float(fillable["win"].mean()) if not fillable.empty else float("nan"),
            "net_pnl": float(fillable["net"].sum()),
            "sharpe": sharpe(fillable["net"]),
            "max_drawdown": max_drawdown(fillable["net"]),
            "avg_entry_price": float(fillable["entry_price"].mean()) if not fillable.empty else float("nan"),
            "avg_spread_cents": float(group["spread_cents"].mean()),
            "avg_maker_fee": float(group["maker_fee"].mean()),
            "avg_net_edge_pp": float(group["net_edge_pp"].mean()),
            "pct_from_orderbook": float((group["entry_source"] == "orderbook").mean() * 100),
        })
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
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
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
    ob = load_orderbooks()

    ob_dates = ob["target_date"].nunique() if not ob.empty else 0
    ob_tickers = ob["ticker"].nunique() if not ob.empty else 0
    print(f"Orderbook data: {ob_dates} dates, {ob_tickers} tickers, {len(ob)} total snapshots")

    preds, trades = run_bakeoff(daily, rows, ob)

    if preds.empty:
        print("No predictions generated — check data coverage.")
        return

    prob_summary = probability_metrics(preds)
    trade_summary = trade_metrics(trades)

    stress_summaries: dict[float, pd.DataFrame] = {}
    for shock_pp in (1.0, 2.0, 3.0, 5.0):
        stressed = stress_test_trades(trades, shock_pp=shock_pp)
        stress_summaries[shock_pp] = stress_metrics(stressed, trades, shock_pp=shock_pp)

    preds.to_csv(OUT_PREDICTIONS, index=False)
    if not trades.empty:
        trades.to_csv(OUT_TRADES, index=False)

    avg_maker = float(trades["maker_fee"].mean()) if not trades.empty else 0.0

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "train_cutoff": TRAIN_CUTOFF,
        "train_days": int((daily["date"] < TRAIN_CUTOFF).sum()),
        "eval_days": int((daily["date"] >= TRAIN_CUTOFF).sum()),
        "ob_dates_covered": ob_dates,
        "ob_tickers_covered": ob_tickers,
        "total_snapshots": len(ob),
        "avg_maker_fee_per_trade": avg_maker,
        "probability_metrics": prob_summary.to_dict(orient="records"),
        "strategy_metrics": trade_summary.to_dict(orient="records"),
        "stress_1pp": stress_summaries[1.0].to_dict(orient="records"),
        "stress_2pp": stress_summaries[2.0].to_dict(orient="records"),
        "stress_3pp": stress_summaries[3.0].to_dict(orient="records"),
        "stress_5pp": stress_summaries[5.0].to_dict(orient="records"),
        "scope": (
            "v2 complete bakeoff: maker-only execution, orderbook entry prices at 9:51 AM ET, "
            "trained on pre-2026 history, evaluated on 2026+ predexon window."
        ),
    }
    OUT_SUMMARY.write_text(json.dumps(summary, indent=2))

    report = f"""# Model Bakeoff v2 — Complete Test

Generated: {summary['generated_at']}

Git SHA: `{summary['git_sha']}`

## Scope

Complete model bakeoff with realistic execution.

**Training:** all pre-{TRAIN_CUTOFF} historical data ({summary['train_days']} days)
with weather features from `open_meteo_historical.csv` and Kalshi settlement labels.
No orderbook data used in training — models learn from temperature forecasts only.

**Evaluation:** {summary['eval_days']} days from {TRAIN_CUTOFF} onward.
Entry prices sourced from predexon orderbook snapshots at 9:51 AM ET
(the METAR gate decision time). Orderbook coverage: {ob_dates} dates / {ob_tickers} tickers.
Dates or tickers with no snapshot fall back to the 9AM CSV price ± 1¢ synthetic spread.

**Execution model:** always limit (maker) orders.
- YES buy: limit at `best_bid` (cents/100), fee rate {MAKER_FEE_RATE:.4f}
- NO buy: limit at `(100 - best_ask) / 100`, same fee rate
- No-fill flag raised when depth at entry level = 0

**Models:** GUMBEL (current), EMOS, EMOS_GUMBEL, EMOS_GUMBEL_HETERO,
IDR, NGBOOST (100 trees), NGBOOST_GUMBEL (100 trees), SEASONAL_EMOS,
RF_DISTRIBUTION, HGBR_QUANTILE.

## Probability Metrics (Evaluation Period)

{markdown_table(prob_summary)}

Lower Brier and winner_log_loss = better calibration.

## Strategy Metrics (Maker Execution, All Gates Applied)

Gates: edge > {MIN_GAP_PP:.0f}pp from maker entry, dead zone {DEAD_ZONE_LO:.0f}–{DEAD_ZONE_HI:.0f}pp excluded,
price band {MIN_ENTRY_PRICE:.2f}–{MAX_ENTRY_PRICE:.2f}, wing_low excluded.

{markdown_table(trade_summary)}

`no_fill_trades` = snapshots where depth at entry price was zero.
`pct_from_orderbook` = % of trades where entry price came from real predexon snapshot vs 9AM fallback.

## Key Differences vs v1

- **Entry price**: orderbook at 9:51 AM ET vs 9AM CSV snapshot
- **Fee**: maker {MAKER_FEE_RATE:.4f} rate vs taker {TAKER_FEE_RATE:.4f} rate (4× cheaper)
- **Training**: full single-pass train/test split vs rolling-origin (more eval power on short window)
- **Evaluation window**: 2026 dates only (predexon coverage) vs longer mixed window

## Execution Stress Test — +1pp Adverse Fill

Simulates limit orders filling 1pp worse than best_bid/no_bid. Trades that fall
below the {MIN_GAP_PP:.0f}pp gate after stress are dropped.

{markdown_table(stress_summaries[1.0])}

## Execution Stress Test — +2pp Adverse Fill

Simulates limit orders filling 2pp worse than best_bid/no_bid (queue delay,
stale book). Trades that fall below the {MIN_GAP_PP:.0f}pp gate after stress are dropped.

{markdown_table(stress_summaries[2.0])}

## Execution Stress Test — +3pp Adverse Fill

Extreme scenario: 3pp slippage (wide spread day or thin book).

{markdown_table(stress_summaries[3.0])}

## Execution Stress Test — +5pp Adverse Fill

Severe stale-book / missed-queue scenario. This is a break-glass comparison,
not a normal execution assumption.

{markdown_table(stress_summaries[5.0])}

## Verdict

A model passes stress if it remains profitable (`stressed_net_pnl > 0`) and
retains > 50% of its baseline trades at +2pp shock.
If it survives +3pp it is considered execution-robust.

## Next Step

Any model that beats GUMBEL on brier_score AND survives both stress tiers
is ready for paper-trading promotion via the standard paper_trader/policy.py path.
Re-run this script after collecting full orderbook coverage (run collect_orderbooks.py
to completion) for the final evaluation.
"""
    OUT_REPORT.write_text(report)

    print("\n=== MODEL BAKEOFF V2 ===")
    print(f"Train days: {summary['train_days']}  |  Eval days: {summary['eval_days']}")
    print(f"Orderbook coverage: {ob_dates} dates, {ob_tickers} tickers")
    print(f"\nProbability metrics:")
    print(prob_summary.to_string(index=False))
    print(f"\nStrategy metrics (maker execution):")
    print(trade_summary.to_string(index=False))
    for shock_pp, stress_summary in stress_summaries.items():
        print(f"\nStress test +{shock_pp:.0f}pp:")
        print(stress_summary.to_string(index=False))
    print(f"\nReport: {OUT_REPORT.relative_to(ROOT)}")
    print(f"Trades: {OUT_TRADES.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
