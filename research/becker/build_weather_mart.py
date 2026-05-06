#!/usr/bin/env python3
from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import gumbel_r


ROOT = Path(__file__).resolve().parents[1]
SQL_PATH = ROOT / "research" / "sql" / "weather_mart.sql"
DATA_DIR = ROOT / "data"
RESEARCH_DIR = DATA_DIR / "research"
REPORTS_DIR = ROOT / "reports"

WEATHER_MART = RESEARCH_DIR / "weather_mart.parquet"
WEATHER_MART_SAMPLE = RESEARCH_DIR / "weather_mart_sample.parquet"
WEATHER_MART_METADATA = RESEARCH_DIR / "weather_mart_metadata.json"
DICTIONARY_MD = REPORTS_DIR / "weather_mart_dictionary.md"

CITY_NAMES = {
    "NYC": "New York",
    "CHI": "Chicago",
    "AUS": "Austin",
    "MIA": "Miami",
    "DEN": "Denver",
    "PHIL": "Philadelphia",
    "LAX": "Los Angeles",
    "HOU": "Houston",
}


def gumbel_probability(row: pd.Series) -> Optional[float]:
    consensus = row.get("consensus_temp_f")
    if consensus is None or pd.isna(consensus):
        return None
    mu = float(consensus) - 0.45
    beta = 0.742
    lo = row.get("bracket_lo_f")
    hi = row.get("bracket_hi_f")
    btype = str(row.get("bracket_type"))
    if btype == "central" and pd.notna(lo) and pd.notna(hi):
        prob = gumbel_r.cdf(float(hi) + 0.5, mu, beta) - gumbel_r.cdf(float(lo) - 0.5, mu, beta)
    elif btype == "lower_tail" and pd.notna(hi):
        # Titles are "be <N°"; use N - 0.5 continuity threshold.
        prob = gumbel_r.cdf(float(hi) - 0.5, mu, beta)
    elif btype == "upper_tail" and pd.notna(lo):
        # Titles are "be >N°"; use N + 0.5 continuity threshold.
        prob = 1.0 - gumbel_r.cdf(float(lo) + 0.5, mu, beta)
    else:
        return None
    return float(min(max(prob, 0.0), 1.0))


def load_base_mart() -> pd.DataFrame:
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    sql = SQL_PATH.read_text().format(
        markets_glob=str(DATA_DIR / "kalshi" / "markets" / "*.parquet"),
        trades_glob=str(DATA_DIR / "kalshi" / "trades" / "*.parquet"),
        open_meteo_csv=str(DATA_DIR / "open_meteo_historical.csv"),
        actuals_csv=str(DATA_DIR / "knyc_actual_temps.csv"),
    )
    con.execute(sql)
    return con.execute("SELECT * FROM weather_mart_base ORDER BY city, target_date_et, ticker, decision_time_et").fetch_df()


def add_probability_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    nyc_mask = out["city"] == "NYC"
    out.loc[nyc_mask, "model_prob_raw"] = out.loc[nyc_mask].apply(gumbel_probability, axis=1)
    # Phase 2 mart keeps calibration nullable: fitting belongs to later model phases.
    out["model_prob_calibrated"] = np.nan
    out["edge_pp_raw"] = (out["model_prob_raw"] - out["market_price_yes"]) * 100.0
    out["edge_pp_calibrated"] = np.nan

    # Diagnostic mismatch is NYC-only because current external actuals are KNYC.
    has_actual = out["actual_temp_f_diagnostic"].notna()
    lower = out["bracket_type"] == "lower_tail"
    upper = out["bracket_type"] == "upper_tail"
    central = out["bracket_type"] == "central"
    reconstructed = pd.Series(np.nan, index=out.index, dtype=object)
    reconstructed.loc[lower & has_actual] = (
        out.loc[lower & has_actual, "actual_temp_f_diagnostic"] < out.loc[lower & has_actual, "bracket_hi_f"]
    )
    reconstructed.loc[upper & has_actual] = (
        out.loc[upper & has_actual, "actual_temp_f_diagnostic"] > out.loc[upper & has_actual, "bracket_lo_f"]
    )
    reconstructed.loc[central & has_actual] = (
        (out.loc[central & has_actual, "actual_temp_f_diagnostic"] >= out.loc[central & has_actual, "bracket_lo_f"])
        & (out.loc[central & has_actual, "actual_temp_f_diagnostic"] <= out.loc[central & has_actual, "bracket_hi_f"])
    )
    out["settlement_mismatch_flag"] = np.where(
        reconstructed.notna() & out["kalshi_result_yes"].notna(),
        reconstructed.astype("boolean") != out["kalshi_result_yes"].astype("boolean"),
        pd.NA,
    )
    return out


def write_outputs(df: pd.DataFrame) -> dict:
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    df.to_parquet(WEATHER_MART, index=False)
    sample = (
        df.sort_values(["city", "target_date_et", "decision_time_et", "ticker"])
        .groupby("city", group_keys=False)
        .head(25)
        .head(250)
    )
    sample.to_parquet(WEATHER_MART_SAMPLE, index=False)

    metadata = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "canonical_row": "one row per ticker x hourly decision_time_et with at least one trade in the trailing 60 minutes",
        "market_state_rule": "point-in-time state comes from trailing trade flow; Becker market bid/ask snapshots are not historical and are left null",
        "settlement_truth": "kalshi_result_yes from Becker markets.result",
        "external_weather_role": "diagnostic only; current Open-Meteo/KNYC joins are NYC-only",
        "forecast_vintage_status": "daily Open-Meteo rows do not carry true intraday vintage timestamps",
        "row_count": int(len(df)),
        "unique_tickers": int(df["ticker"].nunique()),
        "unique_event_tickers": int(df["event_ticker"].nunique()),
        "cities": df.groupby("city")["ticker"].nunique().sort_index().to_dict(),
        "decision_hours": sorted(int(x) for x in df["decision_hour_et"].dropna().unique()),
        "target_date_min": str(df["target_date_et"].min()),
        "target_date_max": str(df["target_date_et"].max()),
        "rows_with_kalshi_settlement_label": int(df["kalshi_result_yes"].notna().sum()),
        "nyc_rows_with_model_prob_raw": int(df["model_prob_raw"].notna().sum()),
        "nyc_rows_with_actual_temp_diagnostic": int(df["actual_temp_f_diagnostic"].notna().sum()),
    }
    WEATHER_MART_METADATA.write_text(json.dumps(metadata, indent=2, sort_keys=True))
    write_dictionary(df, metadata)
    return metadata


def write_dictionary(df: pd.DataFrame, metadata: dict) -> None:
    field_groups = {
        "Identity/time": [
            "ticker",
            "event_ticker",
            "target_date_et",
            "city",
            "bracket_type",
            "bracket_lo_f",
            "bracket_hi_f",
            "decision_time_et",
            "decision_hour_et",
            "hours_to_close",
        ],
        "Market state": [
            "yes_bid",
            "yes_ask",
            "no_bid",
            "no_ask",
            "last_price",
            "implied_mid_yes",
            "spread_yes",
            "spread_no",
            "open_interest",
            "volume",
            "volume_24h",
            "recent_trade_count_15m",
            "recent_trade_count_60m",
            "recent_signed_flow_15m",
            "recent_signed_flow_60m",
            "taker_yes_share_15m",
            "taker_yes_share_60m",
            "vwap_yes_15m",
            "vwap_yes_60m",
            "price_change_15m",
            "price_change_60m",
            "realized_vol_60m",
        ],
        "Weather/fair-value state": [
            "consensus_temp_f",
            "model_spread_f",
            "physics_mean_f",
            "ai_mean_f",
            "spread_between_f",
            "prior_day_error_f",
            "morning_obs_f",
            "morning_vs_forecast_f",
            "regime_hgefs",
            "regime_aifs",
            "regime_nbm_v43",
            "regime_nbm_v50",
            "month",
            "is_peak_season",
        ],
        "Label state": [
            "kalshi_result_yes",
            "settlement_source",
            "actual_temp_f_diagnostic",
            "settlement_mismatch_flag",
        ],
        "Decision state": [
            "model_prob_raw",
            "model_prob_calibrated",
            "market_price_yes",
            "edge_pp_raw",
            "edge_pp_calibrated",
        ],
        "Audit/metadata": [
            "last_trade_time_et",
            "open_time",
            "close_time",
            "status",
            "result",
            "title",
            "market_metadata_fetched_at",
            "market_state_source",
            "forecast_vintage_status",
        ],
    }
    descriptions = {
        "ticker": "Kalshi market ticker.",
        "decision_time_et": "Hourly decision timestamp ending a trailing trade-flow window.",
        "yes_bid": "Null in Phase 2 because Becker market bid snapshots are not point-in-time.",
        "last_price": "Latest prior YES trade price in the trailing 60-minute decision window, as 0-1 fraction.",
        "implied_mid_yes": "Phase 2 proxy equal to last trade price; true point-in-time orderbook midpoint is unavailable.",
        "kalshi_result_yes": "Settlement label from Kalshi/Becker market result; this is the P&L truth field.",
        "actual_temp_f_diagnostic": "External KNYC daily max diagnostic, NYC only; never P&L truth.",
        "model_prob_calibrated": "Reserved for later calibration phases; null in Phase 2 mart.",
        "forecast_vintage_status": "Documents whether forecast data has true intraday vintage timestamps.",
    }
    lines = [
        "# Weather Mart Data Dictionary",
        "",
        "Research-only Phase 2 mart for Kalshi KXHIGH daily high-temperature markets.",
        "",
        "## Canonical Row Definition",
        "",
        metadata["canonical_row"] + ".",
        "",
        "Market state is derived from trailing executions. Becker market parquet bid/ask fields are latest metadata snapshots, not historical orderbook snapshots, so Phase 2 leaves bid/ask and spread fields null to avoid leakage.",
        "",
        "## Coverage",
        "",
        f"- Rows: {metadata['row_count']:,}",
        f"- Unique tickers: {metadata['unique_tickers']:,}",
        f"- Unique event tickers: {metadata['unique_event_tickers']:,}",
        f"- Rows with Kalshi settlement labels: {metadata['rows_with_kalshi_settlement_label']:,}",
        f"- Target dates: {metadata['target_date_min']} to {metadata['target_date_max']}",
        f"- Decision hours ET: {metadata['decision_hours']}",
        f"- Cities: {metadata['cities']}",
        "",
        "## Fields",
        "",
    ]
    for group, cols in field_groups.items():
        lines.extend([f"### {group}", "", "| Field | dtype | Description |", "|---|---|---|"])
        for col in cols:
            dtype = str(df[col].dtype) if col in df.columns else "missing"
            desc = descriptions.get(col, "")
            lines.append(f"| `{col}` | `{dtype}` | {desc} |")
        lines.append("")
    lines.extend(
        [
            "## Known Phase 2 Limitations",
            "",
            "- This is not a full orderbook-history mart. Bid/ask and spread fields remain null until a true point-in-time book source is available.",
            "- Forecast features are currently NYC-only because local historical Open-Meteo/KNYC files cover KNYC. Other cities retain market/trade/label structure with null forecast fields.",
            "- Open-Meteo historical rows are daily and do not carry real intraday model-run vintage timestamps. The mart labels this explicitly via `forecast_vintage_status`.",
            "- `model_prob_calibrated` is intentionally null; calibration belongs to later research phases.",
            "",
        ]
    )
    DICTIONARY_MD.write_text("\n".join(lines))


def print_summary(df: pd.DataFrame, metadata: dict) -> None:
    print("Weather mart build complete")
    print(f"Mart: {WEATHER_MART}")
    print(f"Sample: {WEATHER_MART_SAMPLE}")
    print(f"Metadata: {WEATHER_MART_METADATA}")
    print(f"Dictionary: {DICTIONARY_MD}")
    print(f"Rows: {len(df):,}")
    print(f"Unique tickers: {df['ticker'].nunique():,}")
    print(f"Unique event tickers: {df['event_ticker'].nunique():,}")
    print(f"Rows with Kalshi settlement labels: {metadata['rows_with_kalshi_settlement_label']:,}")
    print(f"Cities: {metadata['cities']}")
    print(f"Decision hours ET: {metadata['decision_hours']}")
    print(f"Target dates: {metadata['target_date_min']} -> {metadata['target_date_max']}")
    print(f"NYC rows with raw model probability: {metadata['nyc_rows_with_model_prob_raw']:,}")
    print(f"NYC rows with diagnostic actual temp: {metadata['nyc_rows_with_actual_temp_diagnostic']:,}")
    print("Example rows:")
    display_cols = [
        "ticker",
        "city",
        "target_date_et",
        "bracket_type",
        "decision_time_et",
        "market_price_yes",
        "recent_trade_count_60m",
        "model_prob_raw",
        "edge_pp_raw",
        "kalshi_result_yes",
    ]
    print(df[display_cols].head(10).to_string(index=False))


def main() -> int:
    df = load_base_mart()
    df = add_probability_features(df)
    metadata = write_outputs(df)
    print_summary(df, metadata)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
