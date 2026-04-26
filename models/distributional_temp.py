from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import gumbel_r

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
