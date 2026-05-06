from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from models.distributional_temp import DistributionalTempModel

MODEL_COLS = ["ecmwf_maxt", "gfs_maxt", "ukmo_maxt", "nbm_maxt"]
NY_TZ = ZoneInfo("America/New_York")


def build_feature_matrix(
    market_df: pd.DataFrame,
    forecast_df: pd.DataFrame,
    obs_df: pd.DataFrame,
    entry_time: str = "11:00",
) -> pd.DataFrame:
    """Build one research feature row per date/bracket combination."""
    markets = _normalise_market_columns(market_df)
    forecasts = _normalise_date_column(forecast_df)
    obs = _normalise_date_column(obs_df)
    if "actual_temp_f" not in obs.columns and "max_temp_f" in obs.columns:
        obs = obs.rename(columns={"max_temp_f": "actual_temp_f"})

    df = markets.merge(forecasts, on="date", how="left")
    if "actual_temp_f" in obs.columns:
        df = df.merge(obs[["date", "actual_temp_f"]], on="date", how="left")

    model = DistributionalTempModel()
    feature_rows = []
    for date_value, group in df.groupby("date", sort=True):
        model_temps = {col: group.iloc[0].get(col) for col in MODEL_COLS if col in group.columns}
        consensus, spread = model.compute_consensus(model_temps)
        brackets = group.apply(_bracket_dict, axis=1).tolist()
        bracket_probs = model.bracket_probabilities(consensus, brackets) if consensus is not None else {}

        for _, row in group.iterrows():
            lo = row.get("lo_f")
            hi = row.get("hi_f")
            btype = row.get("bracket_type", "range")
            market_price = _float_or_nan(row.get("market_price", row.get("yes_price")))
            model_prob = bracket_probs.get(str(row["ticker"]), np.nan)
            actual_temp = _float_or_nan(row.get("actual_temp_f"))
            prior_day_error = _prior_day_error(forecasts, obs, str(date_value))

            feature_rows.append(
                {
                    "date": date_value,
                    "ticker": row["ticker"],
                    "bracket_type": btype,
                    "consensus_temp_f": consensus,
                    "model_spread_f": spread,
                    "distance_lo_f": None if pd.isna(lo) or consensus is None else consensus - float(lo),
                    "distance_hi_f": None if pd.isna(hi) or consensus is None else float(hi) - consensus,
                    "is_wing_bracket": int(btype in {"lower_tail", "upper_tail", "wing_low", "wing_high"}),
                    "is_central_bracket": int(btype in {"range", "central"}),
                    "prior_day_error_f": prior_day_error,
                    "hours_to_close": _hours_to_close(str(date_value), entry_time),
                    "market_price": market_price,
                    "model_prob": model_prob,
                    "gap_pp": None if pd.isna(market_price) or pd.isna(model_prob) else (model_prob - market_price) * 100,
                    "actual_temp_f": actual_temp,
                    **_regime_flags(str(date_value)),
                }
            )
    return pd.DataFrame(feature_rows)


def _normalise_date_column(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "date" not in out.columns and "target_date" in out.columns:
        out = out.rename(columns={"target_date": "date"})
    out["date"] = out["date"].astype(str)
    return out


def _normalise_market_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = _normalise_date_column(df)
    rename = {}
    if "lo_f" not in out.columns:
        for candidate in ("floor_strike", "strike_lo", "bracket_lo"):
            if candidate in out.columns:
                rename[candidate] = "lo_f"
                break
    if "hi_f" not in out.columns:
        for candidate in ("cap_strike", "strike_hi", "bracket_hi"):
            if candidate in out.columns:
                rename[candidate] = "hi_f"
                break
    out = out.rename(columns=rename)
    if "bracket_type" not in out.columns:
        out["bracket_type"] = "range"
    out["bracket_type"] = out["bracket_type"].replace({"wing_low": "lower_tail", "wing_high": "upper_tail", "central": "range"})
    return out


def _bracket_dict(row: pd.Series) -> dict:
    return {
        "ticker": row["ticker"],
        "lo_f": row.get("lo_f"),
        "hi_f": row.get("hi_f"),
        "bracket_type": row.get("bracket_type", "range"),
    }


def _prior_day_error(forecasts: pd.DataFrame, obs: pd.DataFrame, date_value: str) -> float:
    previous = (pd.Timestamp(date_value) - pd.Timedelta(days=1)).date().isoformat()
    if "actual_temp_f" not in obs.columns:
        return np.nan
    forecast_row = forecasts[forecasts["date"] == previous]
    obs_row = obs[obs["date"] == previous]
    if forecast_row.empty or obs_row.empty:
        return np.nan
    model = DistributionalTempModel()
    consensus, _ = model.compute_consensus({col: forecast_row.iloc[0].get(col) for col in MODEL_COLS if col in forecast_row.columns})
    if consensus is None:
        return np.nan
    return float(consensus - float(obs_row.iloc[0]["actual_temp_f"]))


def _hours_to_close(date_value: str, entry_time: str) -> float:
    hour, minute = [int(part) for part in entry_time.split(":")]
    entry_dt = datetime.combine(pd.Timestamp(date_value).date(), time(hour, minute), tzinfo=NY_TZ)
    close_dt = datetime.combine(pd.Timestamp(date_value).date(), time(23, 0), tzinfo=NY_TZ)
    return max(0.0, (close_dt - entry_dt).total_seconds() / 3600.0)


def _regime_flags(date_value: str) -> dict:
    return {
        "regime_hgefs": int(date_value >= "2024-12-17"),
        "regime_aifs": int(date_value >= "2025-02-25"),
        "regime_nbm_v43": int(date_value >= "2025-05-27"),
        "regime_aifs_ens": int(date_value >= "2025-07-01"),
        "regime_nbm_v50": int(date_value >= "2026-04-15"),
        "month": pd.Timestamp(date_value).month,
        "is_peak_season": int(pd.Timestamp(date_value).month in (8, 9, 10, 11)),
        "day_of_week": pd.Timestamp(date_value).dayofweek,
    }


def _float_or_nan(value) -> float:
    if value is None or pd.isna(value):
        return np.nan
    return float(value)
