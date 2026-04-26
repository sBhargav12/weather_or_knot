from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import gumbel_r
from sklearn.isotonic import IsotonicRegression

import config


DEFAULT_WEIGHTS = {
    "ecmwf_maxt": 0.35,
    "gfs_maxt": 0.25,
    "ukmo_maxt": 0.20,
    "nbm_maxt": 0.20,
}


@dataclass
class DistributionalTempModel:
    """Coherent Gumbel daily-high distribution mapped onto all brackets."""

    mu_correction: float = config.GUMBEL_MU_CORRECTION
    beta: float = config.GUMBEL_BETA
    calibrator: Optional[IsotonicRegression] = None

    def compute_consensus(
        self,
        model_temps: dict,
        weights: Optional[dict[str, float]] = None,
    ) -> tuple[Optional[float], Optional[float]]:
        """Return weighted consensus and simple spread across available models."""
        w = weights or DEFAULT_WEIGHTS
        available = {
            key: float(value)
            for key, value in model_temps.items()
            if key in w and value is not None and pd.notna(value)
        }
        if not available:
            return None, None
        total_weight = sum(float(w[key]) for key in available)
        if total_weight <= 0:
            return None, None
        consensus = sum(float(w[key]) * value for key, value in available.items()) / total_weight
        spread = float(np.std(list(available.values()))) if len(available) > 1 else 0.0
        return float(consensus), spread

    def bracket_probabilities(self, consensus_f: float, brackets: list[dict]) -> dict[str, float]:
        """Return non-negative bracket probabilities normalized to sum to 1.0."""
        mu = float(consensus_f) + self.mu_correction
        beta = self.beta
        raw_probs: dict[str, float] = {}

        for bracket in brackets:
            ticker = str(bracket["ticker"])
            lo = _finite_or_none(bracket.get("lo_f", bracket.get("floor_strike", bracket.get("strike_lo"))))
            hi = _finite_or_none(bracket.get("hi_f", bracket.get("cap_strike", bracket.get("strike_hi"))))
            btype = _normalise_bracket_type(str(bracket.get("bracket_type", "range")))

            if btype == "range" and lo is not None and hi is not None:
                prob = gumbel_r.cdf(hi + 0.5, mu, beta) - gumbel_r.cdf(lo - 0.5, mu, beta)
            elif btype == "lower_tail":
                threshold = hi if hi is not None else lo
                prob = gumbel_r.cdf(threshold - 0.5, mu, beta) if threshold is not None else 0.0
            elif btype == "upper_tail":
                threshold = lo if lo is not None else hi
                prob = 1.0 - gumbel_r.cdf(threshold + 0.5, mu, beta) if threshold is not None else 0.0
            else:
                prob = 0.0

            raw_probs[ticker] = max(0.0, float(prob))

        total = sum(raw_probs.values())
        if total <= 0:
            return {ticker: 0.0 for ticker in raw_probs}

        probs = {ticker: value / total for ticker, value in raw_probs.items()}
        # Remove tiny floating residual so daily mass is exactly coherent.
        residual = 1.0 - sum(probs.values())
        if probs and abs(residual) > 0:
            largest = max(probs, key=probs.get)
            probs[largest] = max(0.0, probs[largest] + residual)
        return probs

    def fit_calibrator(self, raw_probs: list[float], outcomes: list[int]) -> bool:
        """Fit optional isotonic calibration when enough resolved samples exist."""
        clean = [
            (float(prob), int(outcome))
            for prob, outcome in zip(raw_probs, outcomes)
            if prob is not None and pd.notna(prob) and outcome is not None and pd.notna(outcome)
        ]
        if len(clean) < 10:
            self.calibrator = None
            return False
        probs = np.array([item[0] for item in clean], dtype=float)
        labels = np.array([item[1] for item in clean], dtype=int)
        self.calibrator = IsotonicRegression(out_of_bounds="clip")
        self.calibrator.fit(probs, labels)
        return True

    def calibrated_prob(self, raw_prob: float) -> float:
        """Return calibrated single-market probability, clipped to [0, 1]."""
        if self.calibrator is None:
            return float(np.clip(raw_prob, 0.0, 1.0))
        calibrated = float(self.calibrator.predict(np.array([raw_prob], dtype=float))[0])
        return float(np.clip(calibrated, 0.0, 1.0))

    def calibrated_probabilities(self, raw_probs: dict[str, float]) -> dict[str, float]:
        """Calibrate each bracket and renormalize so daily mass remains 1.0."""
        calibrated = {ticker: self.calibrated_prob(prob) for ticker, prob in raw_probs.items()}
        total = sum(calibrated.values())
        if total <= 0:
            return dict(raw_probs)
        normalized = {ticker: value / total for ticker, value in calibrated.items()}
        residual = 1.0 - sum(normalized.values())
        if normalized and abs(residual) > 0:
            largest = max(normalized, key=normalized.get)
            normalized[largest] = max(0.0, normalized[largest] + residual)
        return normalized

    def evaluate(self, predicted: pd.DataFrame, actual: pd.DataFrame) -> dict:
        """Evaluate flattened bracket probabilities and daily mass coherence."""
        merged = predicted.merge(actual, on=["date", "ticker"], how="inner", suffixes=("", "_actual"))
        if merged.empty:
            return _empty_eval()
        probs = merged["probability"].astype(float).clip(1e-9, 1 - 1e-9)
        outcomes = merged["outcome"].astype(int)
        brier = float(np.mean((probs - outcomes) ** 2))
        log_loss = float(-np.mean(outcomes * np.log(probs) + (1 - outcomes) * np.log(1 - probs)))
        mass_by_day = predicted.groupby("date")["probability"].sum()
        return {
            "brier_score": brier,
            "log_loss": log_loss,
            "prob_mass_check": float(mass_by_day.mean()) if not mass_by_day.empty else 0.0,
            "prob_mass_min": float(mass_by_day.min()) if not mass_by_day.empty else 0.0,
            "prob_mass_max": float(mass_by_day.max()) if not mass_by_day.empty else 0.0,
            "n_days": int(predicted["date"].nunique()),
            "n_rows": int(len(merged)),
            "calibration_curve": calibration_curve_summary(probs, outcomes),
            "per_bracket": _breakdown(merged, "ticker"),
            "central_vs_wing": _breakdown(merged.assign(group=merged["bracket_type"].map(_central_or_wing)), "group"),
        }


def _finite_or_none(value) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    parsed = float(value)
    return parsed if np.isfinite(parsed) else None


def _normalise_bracket_type(value: str) -> str:
    lowered = value.lower()
    if lowered in {"wing_low", "lower", "lower_tail"}:
        return "lower_tail"
    if lowered in {"wing_high", "upper", "upper_tail"}:
        return "upper_tail"
    if lowered in {"central", "range"}:
        return "range"
    return lowered


def calibration_curve_summary(probs, outcomes, bins: int = 5) -> list[dict]:
    frame = pd.DataFrame({"probability": probs, "outcome": outcomes})
    frame["bin"] = pd.cut(frame["probability"], bins=np.linspace(0, 1, bins + 1), include_lowest=True)
    rows = []
    for bucket, group in frame.groupby("bin", observed=True):
        rows.append(
            {
                "bin": str(bucket),
                "count": int(len(group)),
                "avg_pred": float(group["probability"].mean()),
                "empirical_rate": float(group["outcome"].mean()),
            }
        )
    return rows


def _breakdown(frame: pd.DataFrame, column: str) -> dict:
    rows = {}
    for key, group in frame.groupby(column):
        probs = group["probability"].astype(float).clip(1e-9, 1 - 1e-9)
        outcomes = group["outcome"].astype(int)
        rows[str(key)] = {
            "rows": int(len(group)),
            "brier_score": float(np.mean((probs - outcomes) ** 2)),
            "log_loss": float(-np.mean(outcomes * np.log(probs) + (1 - outcomes) * np.log(1 - probs))),
            "avg_prob": float(probs.mean()),
            "hit_rate": float(outcomes.mean()),
        }
    return rows


def _central_or_wing(value: str) -> str:
    return "central" if _normalise_bracket_type(str(value)) == "range" else "wing"


def _empty_eval() -> dict:
    return {
        "brier_score": 0.0,
        "log_loss": 0.0,
        "prob_mass_check": 0.0,
        "prob_mass_min": 0.0,
        "prob_mass_max": 0.0,
        "n_days": 0,
        "n_rows": 0,
        "calibration_curve": [],
        "per_bracket": {},
        "central_vs_wing": {},
    }
