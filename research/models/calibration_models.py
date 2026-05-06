from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
from scipy.stats import norm
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression


def bracket_probabilities_from_samples(samples: Iterable[float], brackets: list[dict]) -> dict[str, float]:
    """Map empirical temperature samples to coherent bracket probabilities."""
    arr = np.asarray(list(samples), dtype=float)
    if arr.size == 0:
        return {str(b["ticker"]): 0.0 for b in brackets}
    raw = {}
    for bracket in brackets:
        ticker = str(bracket["ticker"])
        lo = _finite_or_none(bracket.get("lo_f", bracket.get("floor_strike")))
        hi = _finite_or_none(bracket.get("hi_f", bracket.get("cap_strike")))
        btype = _normalise_bracket_type(bracket.get("bracket_type", "central"))
        if btype == "lower_tail":
            threshold = hi if hi is not None else lo
            prob = float(np.mean(arr <= threshold)) if threshold is not None else 0.0
        elif btype == "upper_tail":
            threshold = lo if lo is not None else hi
            prob = float(np.mean(arr > threshold)) if threshold is not None else 0.0
        elif lo is not None and hi is not None:
            prob = float(np.mean((arr >= lo) & (arr <= hi)))
        else:
            prob = 0.0
        raw[ticker] = max(0.0, prob)
    return normalize_probability_mass(raw)


def normalize_probability_mass(probs: dict[str, float]) -> dict[str, float]:
    """Clip non-negative and normalize a probability map to daily mass 1.0."""
    clipped = {key: max(0.0, float(value)) for key, value in probs.items()}
    total = sum(clipped.values())
    if total <= 0:
        if not clipped:
            return {}
        uniform = 1.0 / len(clipped)
        return {key: uniform for key in clipped}
    out = {key: value / total for key, value in clipped.items()}
    residual = 1.0 - sum(out.values())
    if out and abs(residual) > 0:
        largest = max(out, key=out.get)
        out[largest] = max(0.0, out[largest] + residual)
    return out


@dataclass
class EMOSModel:
    """Simple EMOS-style normal postprocessor for daily max temperature.

    This research baseline learns a linear bias correction from ensemble
    features and uses residual spread as the predictive sigma.
    """

    min_sigma: float = 0.75

    def __post_init__(self) -> None:
        self.regressor = LinearRegression()
        self.sigma_: float = 2.0
        self.fitted_: bool = False

    def fit(self, x: np.ndarray, y: np.ndarray) -> "EMOSModel":
        self.regressor.fit(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
        residuals = np.asarray(y, dtype=float) - self.regressor.predict(np.asarray(x, dtype=float))
        sigma = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else self.min_sigma
        self.sigma_ = max(self.min_sigma, sigma)
        self.fitted_ = True
        return self

    def predict_distribution(self, x_row: np.ndarray) -> tuple[float, float]:
        _ensure_fitted(self.fitted_)
        mu = float(self.regressor.predict(np.asarray(x_row, dtype=float).reshape(1, -1))[0])
        return mu, self.sigma_

    def bracket_probabilities(self, x_row: np.ndarray, brackets: list[dict]) -> dict[str, float]:
        mu, sigma = self.predict_distribution(x_row)
        raw = {}
        for bracket in brackets:
            ticker = str(bracket["ticker"])
            lo = _finite_or_none(bracket.get("lo_f", bracket.get("floor_strike")))
            hi = _finite_or_none(bracket.get("hi_f", bracket.get("cap_strike")))
            btype = _normalise_bracket_type(bracket.get("bracket_type", "central"))
            if btype == "lower_tail":
                threshold = hi if hi is not None else lo
                prob = norm.cdf(threshold, mu, sigma) if threshold is not None else 0.0
            elif btype == "upper_tail":
                threshold = lo if lo is not None else hi
                prob = 1.0 - norm.cdf(threshold, mu, sigma) if threshold is not None else 0.0
            elif lo is not None and hi is not None:
                prob = norm.cdf(hi, mu, sigma) - norm.cdf(lo, mu, sigma)
            else:
                prob = 0.0
            raw[ticker] = max(0.0, float(prob))
        return normalize_probability_mass(raw)


@dataclass
class RandomForestDistributionModel:
    """Empirical distribution baseline from random-forest tree predictions."""

    n_estimators: int = 200
    min_samples_leaf: int = 5
    random_state: int = 17

    def __post_init__(self) -> None:
        self.model = RandomForestRegressor(
            n_estimators=self.n_estimators,
            min_samples_leaf=self.min_samples_leaf,
            random_state=self.random_state,
            n_jobs=-1,
        )
        self.fitted_: bool = False

    def fit(self, x: np.ndarray, y: np.ndarray) -> "RandomForestDistributionModel":
        self.model.fit(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
        self.fitted_ = True
        return self

    def predict_samples(self, x_row: np.ndarray) -> np.ndarray:
        _ensure_fitted(self.fitted_)
        row = np.asarray(x_row, dtype=float).reshape(1, -1)
        return np.asarray([tree.predict(row)[0] for tree in self.model.estimators_], dtype=float)

    def bracket_probabilities(self, x_row: np.ndarray, brackets: list[dict]) -> dict[str, float]:
        return bracket_probabilities_from_samples(self.predict_samples(x_row), brackets)


@dataclass
class HGBRQuantileModel:
    """Histogram gradient-boosting quantile distribution baseline."""

    quantiles: tuple[float, ...] = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
    max_iter: int = 150
    learning_rate: float = 0.05
    random_state: int = 17

    def __post_init__(self) -> None:
        self.models: dict[float, HistGradientBoostingRegressor] = {}
        self.fitted_: bool = False

    def fit(self, x: np.ndarray, y: np.ndarray) -> "HGBRQuantileModel":
        x_arr = np.asarray(x, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        self.models = {}
        for quantile in self.quantiles:
            model = HistGradientBoostingRegressor(
                loss="quantile",
                quantile=float(quantile),
                max_iter=self.max_iter,
                learning_rate=self.learning_rate,
                random_state=self.random_state,
            )
            model.fit(x_arr, y_arr)
            self.models[float(quantile)] = model
        self.fitted_ = True
        return self

    def predict_quantiles(self, x_row: np.ndarray) -> dict[float, float]:
        _ensure_fitted(self.fitted_)
        row = np.asarray(x_row, dtype=float).reshape(1, -1)
        preds = {q: float(model.predict(row)[0]) for q, model in self.models.items()}
        # Enforce monotone quantiles; boosting can cross on small samples.
        sorted_q = sorted(preds)
        values = np.maximum.accumulate([preds[q] for q in sorted_q])
        return {q: float(v) for q, v in zip(sorted_q, values)}

    def predict_samples(self, x_row: np.ndarray, n: int = 400) -> np.ndarray:
        quantile_map = self.predict_quantiles(x_row)
        qs = np.array(sorted(quantile_map), dtype=float)
        vals = np.array([quantile_map[q] for q in qs], dtype=float)
        grid = np.linspace(qs.min(), qs.max(), n)
        return np.interp(grid, qs, vals)

    def bracket_probabilities(self, x_row: np.ndarray, brackets: list[dict]) -> dict[str, float]:
        return bracket_probabilities_from_samples(self.predict_samples(x_row), brackets)


def _finite_or_none(value) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if np.isfinite(parsed) else None


def _normalise_bracket_type(value) -> str:
    lowered = str(value).lower()
    if lowered in {"wing_low", "lower", "lower_tail"}:
        return "lower_tail"
    if lowered in {"wing_high", "upper", "upper_tail"}:
        return "upper_tail"
    return "central"


def _ensure_fitted(is_fitted: bool) -> None:
    if not is_fitted:
        raise RuntimeError("model must be fitted before prediction")
