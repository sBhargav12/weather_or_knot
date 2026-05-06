"""Shared utilities for Polymarket weather-wallet research.

All helpers here are research-only and operate on the public Data API recent
slice collected in Phase 1. They do not modify live/paper trading behavior.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


DATA_DIR = Path("data/research")
REPORT_DIR = Path("reports")
ET = ZoneInfo("America/New_York")

CITY_RE = re.compile(r"highest temperature in ([A-Za-z .'-]+?) (?:be|on)", re.I)
BETWEEN_RE = re.compile(r"between\s+(-?\d+(?:\.\d+)?)\s*(?:-|and)\s*(-?\d+(?:\.\d+)?)", re.I)
OR_BELOW_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:°?[CF])?\s*or below", re.I)
OR_ABOVE_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:°?[CF])?\s*or above", re.I)
EXACT_TEMP_RE = re.compile(r"be\s+(-?\d+(?:\.\d+)?)\s*°?[CF]\b", re.I)


def pct(numer: float, denom: float) -> float:
    return 0.0 if denom == 0 else 100.0 * numer / denom


def safe_div(numer: float, denom: float) -> float:
    return 0.0 if denom == 0 else float(numer / denom)


def entropy(series: pd.Series) -> float:
    counts = series.dropna().value_counts()
    if counts.empty:
        return 0.0
    probs = counts / counts.sum()
    return float(-(probs * np.log2(probs)).sum())


def normalized_entropy(series: pd.Series) -> float:
    n = series.dropna().nunique()
    if n <= 1:
        return 0.0
    return entropy(series) / math.log2(n)


def price_bucket(price: float | None) -> str:
    if price is None or pd.isna(price):
        return "unknown"
    p = float(price)
    if p < 0.05:
        return "00-05"
    if p < 0.10:
        return "05-10"
    if p < 0.20:
        return "10-20"
    if p < 0.40:
        return "20-40"
    if p < 0.60:
        return "40-60"
    if p < 0.80:
        return "60-80"
    if p < 0.95:
        return "80-95"
    return "95-100"


def hours_bucket(hours: float | None) -> str:
    if hours is None or pd.isna(hours):
        return "unknown"
    h = float(hours)
    if h < 0:
        return "after_close_or_resolved"
    if h <= 1:
        return "0-1h"
    if h <= 6:
        return "1-6h"
    if h <= 24:
        return "6-24h"
    if h <= 72:
        return "1-3d"
    if h <= 168:
        return "3-7d"
    return "7d+"


def parse_city(title: str) -> str:
    match = CITY_RE.search(title or "")
    if match:
        return match.group(1).strip()
    s = (title or "").lower()
    if "global temperature" in s or "temperature increase" in s:
        return "Global"
    return "Unknown"


def market_family(title: str) -> str:
    s = (title or "").lower()
    if "global temperature" in s or "temperature increase" in s:
        return "macro_temperature"
    if "highest temperature" in s or "lowest temperature" in s or "temperature" in s or "°c" in s or "°f" in s:
        return "daily_temperature"
    if "rain" in s or "precipitation" in s:
        return "precipitation"
    if "snow" in s:
        return "snow"
    if "hurricane" in s or "storm" in s or "tornado" in s:
        return "storm"
    return "other_weather"


def bracket_family(title: str) -> str:
    s = title or ""
    if OR_BELOW_RE.search(s):
        return "lower_tail"
    if OR_ABOVE_RE.search(s):
        return "upper_tail"
    if BETWEEN_RE.search(s):
        return "range"
    if EXACT_TEMP_RE.search(s):
        return "exact_temp"
    return "non_temperature_or_unknown"


def load_phase_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any]]:
    leaderboard = pd.read_csv(DATA_DIR / "polymarket_top_weather_traders.csv")
    trades = pd.read_parquet(DATA_DIR / "polymarket_trades_raw.parquet")
    outcomes = pd.read_parquet(DATA_DIR / "polymarket_market_outcomes.parquet")
    profiles = pd.read_parquet(DATA_DIR / "polymarket_wallet_profiles.parquet")
    phase1 = json.loads((DATA_DIR / "polymarket_phase1_summary.json").read_text())
    phase2 = json.loads((DATA_DIR / "polymarket_phase2_readiness.json").read_text())
    return leaderboard, trades, outcomes, profiles, phase1, phase2


def enriched_trades() -> pd.DataFrame:
    _leaderboard, trades, outcomes, _profiles, _phase1, _phase2 = load_phase_data()
    t = trades.copy()
    t["dt_et"] = pd.to_datetime(t["timestamp"], unit="s", utc=True).dt.tz_convert("America/New_York")
    t["date_et"] = t["dt_et"].dt.date.astype(str)
    t["hour_et"] = t["dt_et"].dt.hour
    t["weekday_et"] = t["dt_et"].dt.day_name()
    t["price_bucket"] = t["price"].map(price_bucket)
    t["city"] = t["title"].fillna("").map(parse_city)
    t["market_family"] = t["title"].fillna("").map(market_family)
    t["bracket_family"] = t["title"].fillna("").map(bracket_family)
    t["is_buy"] = t["side"].astype(str).str.upper().eq("BUY")
    t["is_sell"] = t["side"].astype(str).str.upper().eq("SELL")
    t["is_yes"] = t["outcome"].astype(str).str.lower().eq("yes")
    t["is_no"] = t["outcome"].astype(str).str.lower().eq("no")
    t["is_extreme_price"] = (t["price"] <= 0.10) | (t["price"] >= 0.90)
    t["is_mid_price"] = (t["price"] >= 0.35) & (t["price"] <= 0.65)
    t["signed_qty"] = np.where(t["is_buy"], t["size"], -t["size"])
    t["signed_notional_proxy"] = np.where(t["is_buy"], t["notional_usd_proxy"], -t["notional_usd_proxy"])

    keep = [
        "conditionId",
        "endDate",
        "closed",
        "active",
        "resolved_outcome",
        "resolved_yes",
        "event_closed",
        "event_title",
        "event_endDate",
    ]
    t = t.merge(outcomes[keep], on="conditionId", how="left", validate="many_to_one")
    end = pd.to_datetime(t["endDate"], utc=True, errors="coerce").dt.tz_convert("America/New_York")
    t["end_dt_et"] = end
    t["hours_to_close"] = (end - t["dt_et"]).dt.total_seconds() / 3600
    t["time_to_close_bucket"] = t["hours_to_close"].map(hours_bucket)

    resolved = t["resolved_outcome"].astype(str).str.lower()
    outcome = t["outcome"].astype(str).str.lower()
    t["token_settlement_value"] = np.where(t["resolved_outcome"].notna() & outcome.eq(resolved), 1.0, 0.0)
    t.loc[t["resolved_outcome"].isna(), "token_settlement_value"] = np.nan
    t["settlement_return_pp"] = np.where(
        t["is_buy"],
        (t["token_settlement_value"] - t["price"]) * 100,
        (t["price"] - t["token_settlement_value"]) * 100,
    )
    t["settlement_pnl_proxy"] = t["settlement_return_pp"] / 100.0 * t["size"].fillna(0)
    return t


def compute_trade_markouts(t: pd.DataFrame) -> pd.DataFrame:
    """Compute execution-to-next-trade markouts on same asset.

    This is trade-to-trade context, not full orderbook replay. Markouts are
    signed from the wallet action: BUY benefits if later same-asset price rises;
    SELL benefits if later same-asset price falls.
    """
    base = t.sort_values(["asset", "timestamp", "transactionHash"]).copy()
    left = base.reset_index(names="row_id").sort_values(["asset", "timestamp"])
    out = left[["row_id"]].copy()
    horizons = {"1m": 60, "5m": 300, "60m": 3600, "1d": 86400}

    for label, seconds in horizons.items():
        later = left[["asset", "timestamp", "price"]].rename(
            columns={"timestamp": f"future_ts_{label}", "price": f"future_price_{label}"}
        )
        # Strictly future trades only.
        left_key = f"timestamp_key_{label}"
        right_key = f"future_ts_key_{label}"
        left[left_key] = left["timestamp"].astype(float)
        later[right_key] = later[f"future_ts_{label}"].astype(float) - 1e-6
        merged = pd.merge_asof(
            left.sort_values("timestamp"),
            later.sort_values(right_key),
            left_on=left_key,
            right_on=right_key,
            by="asset",
            direction="forward",
            tolerance=seconds,
        ).sort_values("row_id")
        price_col = f"future_price_{label}"
        signed = np.where(left.sort_values("timestamp")["is_buy"].to_numpy(), 1.0, -1.0)
        markout = (merged[price_col].to_numpy() - left.sort_values("timestamp")["price"].to_numpy()) * signed * 100
        tmp = pd.DataFrame(
            {
                "row_id": merged["row_id"].to_numpy(),
                f"future_price_{label}": merged[price_col].to_numpy(),
                f"signed_markout_pp_{label}": markout,
            }
        )
        out = out.merge(tmp, on="row_id", how="left")

    # To-close proxy: last observed same-asset trade before close/end in the captured slice.
    last_asset = (
        base.groupby("asset")
        .agg(last_observed_price=("price", "last"), last_observed_ts=("timestamp", "last"))
        .reset_index()
    )
    out = out.merge(left[["row_id", "asset", "price", "is_buy"]], on="row_id", how="left")
    out = out.merge(last_asset, on="asset", how="left")
    out["signed_markout_pp_to_last_observed"] = (
        (out["last_observed_price"] - out["price"]) * np.where(out["is_buy"], 1.0, -1.0) * 100
    )
    return base.reset_index(names="row_id").merge(out.drop(columns=["asset", "price", "is_buy"]), on="row_id", how="left")


def summarize_group(df: pd.DataFrame, group_cols: list[str], value_col: str = "settlement_return_pp") -> pd.DataFrame:
    return (
        df.groupby(group_cols, dropna=False)
        .agg(
            trades=("transactionHash", "count"),
            wallets=("proxyWallet", "nunique"),
            markets=("conditionId", "nunique"),
            events=("eventSlug", "nunique"),
            avg_price=("price", "mean"),
            avg_size=("size", "mean"),
            notional_proxy=("notional_usd_proxy", "sum"),
            avg_return_pp=(value_col, "mean"),
            win_rate=(value_col, lambda s: float((s > 0).mean() * 100) if s.notna().any() else np.nan),
        )
        .reset_index()
        .sort_values("trades", ascending=False)
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n")


def md_table(df: pd.DataFrame, max_rows: int = 20) -> str:
    d = df.head(max_rows).copy()
    cols = list(d.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for row in d.itertuples(index=False, name=None):
        lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |")
    return "\n".join(lines)
