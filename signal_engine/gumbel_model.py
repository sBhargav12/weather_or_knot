from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

import numpy as np
from scipy.stats import gumbel_r

import config


class GumbelModel:
    """Temperature bracket probability model using Gumbel only."""

    def __init__(self):
        self.calibrator = None
        self.calibration_data = []
        self._dynamic_weights: Dict[str, float] = {}
        self._dynamic_biases: Dict[str, float] = {}

    def update_dynamic_weights(self, weights: Dict[str, float], biases: Dict[str, float]) -> None:
        self._dynamic_weights = {k.upper(): v for k, v in weights.items()}
        self._dynamic_biases = {k.upper(): v for k, v in biases.items()}
        top = sorted(weights.items(), key=lambda x: -x[1])[:5]
        import logging
        logging.getLogger(__name__).info(
            "Dynamic model weights updated (top 5): %s",
            ", ".join(f"{m}={w:.3f}" for m, w in top),
        )

    def compute_bracket_prob(
        self,
        bracket_lo: Optional[float],
        bracket_hi: Optional[float],
        consensus_f: float,
        bracket_type: str = "range",
    ) -> float:
        mu = consensus_f + config.GUMBEL_MU_CORRECTION
        beta = config.GUMBEL_BETA
        if bracket_type in ("range", "central"):
            if bracket_lo is None or bracket_hi is None:
                raise ValueError("range bracket requires bracket_lo and bracket_hi")
            prob = gumbel_r.cdf(bracket_hi + 0.5, mu, beta) - gumbel_r.cdf(bracket_lo - 0.5, mu, beta)
        elif bracket_type in ("lower_tail", "wing_low"):
            threshold = bracket_hi if bracket_hi is not None else bracket_lo
            if threshold is None:
                raise ValueError("lower-tail bracket requires a threshold")
            prob = gumbel_r.cdf(threshold - 0.5, mu, beta)
        elif bracket_type in ("upper_tail", "wing_high"):
            threshold = bracket_lo if bracket_lo is not None else bracket_hi
            if threshold is None:
                raise ValueError("upper-tail bracket requires a threshold")
            prob = 1 - gumbel_r.cdf(threshold + 0.5, mu, beta)
        else:
            raise ValueError(f"unknown bracket_type: {bracket_type}")
        return float(min(max(prob, 0.0), 1.0))

    def bayesian_update_with_nbm(
        self,
        gumbel_prob: float,
        nbm_p50: Optional[float],
        nbm_p10: Optional[float],
        nbm_p90: Optional[float],
        bracket_lo: Optional[float],
        bracket_hi: Optional[float],
        bracket_type: str = "range",
        percentiles_real: bool = True,
    ) -> float:
        if not percentiles_real or nbm_p50 is None or nbm_p10 is None or nbm_p90 is None:
            return float(gumbel_prob)
        mu_nbm = nbm_p50 + config.GUMBEL_MU_CORRECTION
        beta_nbm = max((nbm_p90 - nbm_p10) / 4.0, 0.1)
        if bracket_type in ("range", "central"):
            if bracket_lo is None or bracket_hi is None:
                return float(gumbel_prob)
            nbm_prob = gumbel_r.cdf(bracket_hi + 0.5, mu_nbm, beta_nbm) - gumbel_r.cdf(
                bracket_lo - 0.5, mu_nbm, beta_nbm
            )
        elif bracket_type in ("lower_tail", "wing_low"):
            threshold = bracket_hi if bracket_hi is not None else bracket_lo
            nbm_prob = gumbel_r.cdf(threshold - 0.5, mu_nbm, beta_nbm)
        else:
            threshold = bracket_lo if bracket_lo is not None else bracket_hi
            nbm_prob = 1 - gumbel_r.cdf(threshold + 0.5, mu_nbm, beta_nbm)
        blended = config.WEIGHT_HGEFS * gumbel_prob + config.WEIGHT_NBM * float(nbm_prob)
        return float(min(max(blended, 0.0), 1.0))

    def calibrate(self, outcomes: list) -> None:
        self.calibration_data = list(outcomes)
        if len(self.calibration_data) < 10:
            self.calibrator = None
            return
        from sklearn.isotonic import IsotonicRegression

        x = np.array([row[0] for row in self.calibration_data], dtype=float)
        y = np.array([row[1] for row in self.calibration_data], dtype=float)
        self.calibrator = IsotonicRegression(out_of_bounds="clip").fit(x, y)

    def apply_calibration(self, raw_prob: float) -> float:
        if self.calibrator is None:
            return float(raw_prob)
        return float(self.calibrator.predict(np.array([raw_prob], dtype=float))[0])

    def compute_consensus_from_wethr(self, model_forecasts: Dict[str, float], target_date: Optional[str] = None) -> Optional[float]:
        use_dynamic = bool(self._dynamic_weights)
        month = None
        if target_date:
            month = datetime.strptime(target_date, "%Y-%m-%d").month
        corrected = []
        weighted = []
        for model, value in model_forecasts.items():
            if value is None:
                continue
            model_upper = model.upper()
            adjusted = float(value)
            if use_dynamic:
                adjusted -= self._dynamic_biases.get(model_upper, 0.0)
            else:
                if model_upper == "ECMWF":
                    adjusted -= config.ECMWF_BIAS
                elif model_upper == "GFS":
                    adjusted -= config.GFS_BIAS
                elif model_upper == "HRRR" and month in (6, 7, 8):
                    adjusted += config.HRRR_SUMMER_BIAS
            corrected.append(adjusted)
            weight = (
                self._dynamic_weights.get(model_upper)
                if use_dynamic
                else config.FALLBACK_ENSEMBLE_WEIGHTS.get(model_upper)
            )
            if weight is not None:
                weighted.append((adjusted, float(weight)))
        if not corrected:
            return None
        if weighted:
            total_weight = sum(w for _, w in weighted)
            if total_weight > 0:
                return float(sum(v * w for v, w in weighted) / total_weight)
        return float(np.mean(corrected))

    def compute_all_bracket_probs(
        self,
        city: str,
        target_date: str,
        hgefs_result: dict,
        nbm_result: dict,
        wethr_models: dict,
    ) -> dict:
        hgefs_values = [
            value
            for value in [hgefs_result.get("physics_mean"), hgefs_result.get("ai_mean")]
            if value is not None
        ]
        if hgefs_values:
            consensus = float(np.mean(hgefs_values))
        else:
            consensus = self.compute_consensus_from_wethr(wethr_models, target_date)
        if consensus is None:
            return {}

        result = {}
        for bracket in hgefs_result.get("brackets", []):
            raw = self.compute_bracket_prob(
                bracket.get("strike_lo"),
                bracket.get("strike_hi"),
                consensus,
                bracket.get("bracket_type", "range"),
            )
            blended = self.bayesian_update_with_nbm(
                raw,
                nbm_result.get("p50"),
                nbm_result.get("p10"),
                nbm_result.get("p90"),
                bracket.get("strike_lo"),
                bracket.get("strike_hi"),
                bracket.get("bracket_type", "range"),
                bool(nbm_result.get("percentiles_real", True)),
            )
            result[bracket["ticker"]] = self.apply_calibration(blended)
        return result
