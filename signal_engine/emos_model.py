"""
Live EMOS model for paper trading.

Trains once at startup from data/open_meteo_historical_extended.csv +
data/knyc_actual_temps_extended.csv (falls back to non-extended versions).
Accepts live wethr/HGEFS features and returns bracket probabilities.

This is a paper-only probability source. It does not replace the Gumbel model
for gate logic — it provides a parallel probability estimate for the CORE_HGEFS_EMOS
paper sleeve.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import norm

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"

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

REAL_FORECAST_CUTOFF = pd.Timestamp("2024-10-01")
HINDCAST_WEIGHT = 0.5
MIN_TRAIN_DAYS = 120


def _bracket_prob_from_normal(
    mu: float,
    sigma: float,
    lo: Optional[float],
    hi: Optional[float],
    bracket_type: str,
) -> float:
    btype = bracket_type.lower()
    if btype in ("lower_tail", "wing_low"):
        threshold = hi if hi is not None else lo
        return float(norm.cdf(threshold, mu, sigma)) if threshold is not None else 0.0
    if btype in ("upper_tail", "wing_high"):
        threshold = lo if lo is not None else hi
        return float(1.0 - norm.cdf(threshold, mu, sigma)) if threshold is not None else 0.0
    # central / range
    if lo is not None and hi is not None:
        return float(norm.cdf(hi, mu, sigma) - norm.cdf(lo, mu, sigma))
    return 0.0


class LiveEMOSModel:
    """EMOS model for live paper trading.

    Call train() once on startup, then bracket_probability() per bracket.
    Returns None if the model is not trained or features are incomplete.
    """

    def __init__(self, city_code: str = "KNYC") -> None:
        from research.models.calibration_models import EMOSModel
        self._emos = EMOSModel()
        self._fitted = False
        self._city = city_code
        self._train_consensus_min: float = -999.0
        self._train_consensus_max: float = 999.0

    # Maps KXLOWT series → the corresponding KXHIGH base city whose Open-Meteo
    # TMAX forecast CSV is used as the feature source. The EMOS trains on
    # (TMAX_forecast, TMIN_actual) pairs, which is physically valid (r ≈ 0.9).
    _KXLOWT_BASE: dict[str, str] = {
        "KXLOWTNYC":  "knyc",
        "KXLOWTCHI":  "kmdw",
        "KXLOWTMIA":  "kmia",
        "KXLOWTAUS":  "kaus",
        "KXLOWTLAX":  "klax",
        "KXLOWTDEN":  "kden",
        "KXLOWTPHIL": "kphl",
    }

    def _csv_paths(self) -> tuple[Path, Path]:
        """Return (models_csv, actuals_csv) for this city."""
        city_lower = self._city.lower()

        # KXLOWT daily-low markets: use TMAX forecast CSV for the paired KXHIGH
        # city alongside TMIN actuals. Live inference also receives TMAX forecasts,
        # so train/infer are consistent.
        if self._city in self._KXLOWT_BASE:
            base = self._KXLOWT_BASE[self._city]
            if base == "knyc":
                models_csv = DATA_DIR / "open_meteo_historical_extended.csv"
            else:
                models_csv = DATA_DIR / f"open_meteo_{base}_historical_extended.csv"
            actuals_csv = DATA_DIR / f"{city_lower}_actual_tmin_extended.csv"
            return models_csv, actuals_csv

        if self._city == "KNYC":
            ext_models = DATA_DIR / "open_meteo_historical_extended.csv"
            ext_actuals = DATA_DIR / "knyc_actual_temps_extended.csv"
            fallback_models = DATA_DIR / "open_meteo_historical.csv"
            fallback_actuals = DATA_DIR / "knyc_actual_temps.csv"
        else:
            ext_models = DATA_DIR / f"open_meteo_{city_lower}_historical_extended.csv"
            ext_actuals = DATA_DIR / f"{city_lower}_actual_temps_extended.csv"
            fallback_models = DATA_DIR / f"open_meteo_{city_lower}_historical.csv"
            fallback_actuals = DATA_DIR / f"{city_lower}_actual_temps.csv"
        models_csv = ext_models if ext_models.exists() else fallback_models
        actuals_csv = ext_actuals if ext_actuals.exists() else fallback_actuals
        return models_csv, actuals_csv

    def train(self) -> bool:
        """Train from extended (or fallback) CSVs. Returns True if successful."""
        models_csv, actuals_csv = self._csv_paths()

        try:
            forecasts = pd.read_csv(models_csv).rename(columns={"date": "target_date"})
            actuals_raw = pd.read_csv(actuals_csv).rename(columns={"date": "target_date"})
            # Support both TMAX (max_temp_f) and TMIN (min_temp_f) actuals columns
            temp_col = "min_temp_f" if "min_temp_f" in actuals_raw.columns else "max_temp_f"
            actuals = actuals_raw.rename(columns={temp_col: "actual_temp"})
        except Exception as exc:
            logger.warning("LiveEMOSModel[%s]: failed to load training CSVs: %s", self._city, exc)
            return False

        model_cols = ["gfs_maxt", "ecmwf_maxt", "ukmo_maxt", "nbm_maxt"]
        forecasts = forecasts[forecasts["gfs_maxt"].notna()].copy()
        row_mean = forecasts[model_cols].mean(axis=1)
        for col in model_cols:
            forecasts[col] = forecasts[col].fillna(row_mean)

        daily = forecasts.merge(actuals, on="target_date", how="inner")
        daily = daily.dropna(subset=["actual_temp"])
        if len(daily) < MIN_TRAIN_DAYS:
            logger.warning("LiveEMOSModel[%s]: only %d training rows (need %d)", self._city, len(daily), MIN_TRAIN_DAYS)
            return False

        daily["target_date"] = pd.to_datetime(daily["target_date"])
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
        daily["sample_weight"] = np.where(daily["target_date"] >= REAL_FORECAST_CUTOFF, 1.0, HINDCAST_WEIGHT)

        x = daily[FEATURES].to_numpy(dtype=float)
        y = daily["actual_temp"].to_numpy(dtype=float)
        w = daily["sample_weight"].to_numpy(dtype=float)

        consensus_vals = daily["consensus"].to_numpy(dtype=float)
        self._train_consensus_min = float(consensus_vals.min())
        self._train_consensus_max = float(consensus_vals.max())

        try:
            self._emos.fit(x, y, sample_weight=w)
            self._fitted = True
            logger.info(
                "LiveEMOSModel[%s]: trained on %d days (%d real-forecast, %d hindcast)",
                self._city,
                len(daily),
                int((daily["target_date"] >= REAL_FORECAST_CUTOFF).sum()),
                int((daily["target_date"] < REAL_FORECAST_CUTOFF).sum()),
            )
            return True
        except Exception as exc:
            logger.warning("LiveEMOSModel[%s]: training failed: %s", self._city, exc)
            return False

    def _build_features(
        self,
        hgefs_like: dict,
        wethr_models: dict,
        nbm: dict,
        target_date: str,
    ) -> Optional[np.ndarray]:
        """Build the 11-feature vector from live pipeline dicts."""
        gfs = wethr_models.get("GFS")
        ecmwf = wethr_models.get("ECMWF")
        ukmo = wethr_models.get("UKMO")
        nbm_p50 = nbm.get("p50") or wethr_models.get("NBM")
        physics_mean = hgefs_like.get("physics_mean")
        ai_mean = hgefs_like.get("ai_mean")

        # Need at least physics_mean (always available from HGEFS/fallback)
        if physics_mean is None:
            return None

        # Guard: if no real wethr model values exist, all forecasts will be filled
        # with physics_mean → degenerate feature vector → EMOS extrapolates badly.
        has_real_forecasts = any(
            wethr_models.get(k) is not None for k in ["GFS", "ECMWF", "UKMO", "NBM"]
        )
        if not has_real_forecasts:
            logger.debug(
                "LiveEMOSModel[%s]: no real wethr forecasts for %s — deferring to Gumbel",
                self._city, target_date,
            )
            return None

        # Use HGEFS means as primary model values when individual members unavailable
        if gfs is None:
            gfs = physics_mean
        if ecmwf is None:
            ecmwf = physics_mean
        if ukmo is None:
            ukmo = ai_mean if ai_mean is not None else physics_mean
        if nbm_p50 is None:
            nbm_p50 = ai_mean if ai_mean is not None else physics_mean
        if ai_mean is None:
            ai_mean = physics_mean

        available = [v for v in [gfs, ecmwf, ukmo, nbm_p50] if v is not None]
        consensus = (0.25 * gfs + 0.35 * ecmwf + 0.20 * ukmo + 0.20 * nbm_p50)
        model_spread = float(np.std(available)) if len(available) > 1 else 0.0
        spread_between = abs(float(physics_mean) - float(ai_mean))

        try:
            dt = datetime.strptime(target_date, "%Y-%m-%d")
            month = dt.month
            day_of_year = dt.timetuple().tm_yday
        except Exception:
            return None

        return np.array([
            gfs, ecmwf, ukmo, nbm_p50,
            consensus, model_spread,
            physics_mean, ai_mean, spread_between,
            month, day_of_year,
        ], dtype=float)

    def bracket_probability(
        self,
        bracket_lo: Optional[float],
        bracket_hi: Optional[float],
        bracket_type: str,
        hgefs_like: dict,
        wethr_models: dict,
        nbm: dict,
        target_date: str,
    ) -> Optional[float]:
        """Return EMOS P(yes) for a single bracket. Returns None if not fitted."""
        if not self._fitted:
            return None
        features = self._build_features(hgefs_like, wethr_models, nbm, target_date)
        if features is None:
            return None
        # Guard: reject if live consensus is outside the training range (±4°F).
        # LinearRegression extrapolates freely — cold or warm outliers produce garbage.
        live_consensus = float(features[4])  # index 4 = consensus in FEATURES
        if (live_consensus < self._train_consensus_min - 4.0 or
                live_consensus > self._train_consensus_max + 4.0):
            logger.debug(
                "LiveEMOSModel[%s]: consensus %.1f°F outside training range "
                "[%.1f, %.1f] — deferring to Gumbel",
                self._city, live_consensus,
                self._train_consensus_min, self._train_consensus_max,
            )
            return None
        try:
            mu, sigma = self._emos.predict_distribution(features)
            prob = _bracket_prob_from_normal(mu, sigma, bracket_lo, bracket_hi, bracket_type)
            return float(min(max(prob, 0.0), 1.0))
        except Exception as exc:
            logger.debug("LiveEMOSModel.bracket_probability failed: %s", exc)
            return None
