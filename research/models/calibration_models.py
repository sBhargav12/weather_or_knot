from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
from scipy.stats import norm, gumbel_r
from ngboost.distns.distn import RegressionDistn
from ngboost.scores import LogScore
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LinearRegression

_EULER_GAMMA = 0.5772156649015329


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

    def fit(self, x: np.ndarray, y: np.ndarray, sample_weight: np.ndarray | None = None) -> "EMOSModel":
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        self.regressor.fit(x, y, sample_weight=sample_weight)
        residuals = y - self.regressor.predict(x)
        if sample_weight is not None:
            w = np.asarray(sample_weight, dtype=float)
            w = w / w.sum()
            sigma = float(np.sqrt(np.sum(w * residuals ** 2)))
        else:
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
class SeasonalEMOSModel:
    """Seasonal EMOS with per-model weights and heteroscedastic spread.

    Improvements over EMOSModel:
    - Fits separate (a, b₁..b₄, c, d) per meteorological season (DJF/MAM/JJA/SON).
    - Mean: μ = a + b₁·gfs + b₂·ecmwf + b₃·ukmo + b₄·nbm  (per-model bias correction)
    - Sigma: σ = max(min_σ, c + d·model_spread)  (heteroscedastic)
    - Falls back to all-season model when a season has < min_season_days training rows.

    Expects the feature matrix to follow the FEATURES column order defined in
    model_bakeoff_v2.py:
      [gfs_maxt, ecmwf_maxt, ukmo_maxt, nbm_maxt, consensus, model_spread,
       physics_mean, ai_mean, spread_between, month, day_of_year]
    Indices used: 0-3 (model forecasts), 5 (model_spread), 9 (month).
    """

    min_sigma: float = 0.75
    min_season_days: int = 30

    # feature indices (must match FEATURES in bakeoff script)
    IDX_GFS: int = 0
    IDX_ECMWF: int = 1
    IDX_UKMO: int = 2
    IDX_NBM: int = 3
    IDX_SPREAD: int = 5
    IDX_MONTH: int = 9

    SEASONS: dict = None  # populated in __post_init__

    def __post_init__(self) -> None:
        self.SEASONS = {
            "DJF": frozenset([12, 1, 2]),
            "MAM": frozenset([3, 4, 5]),
            "JJA": frozenset([6, 7, 8]),
            "SON": frozenset([9, 10, 11]),
        }
        self._season_models: dict[str, dict] = {}  # season -> {mu_reg, c, d}
        self._global_model: dict = {}
        self.fitted_: bool = False

    def _month_to_season(self, month: int) -> str:
        for season, months in self.SEASONS.items():
            if month in months:
                return season
        return "DJF"

    def _fit_one(self, x: np.ndarray, y: np.ndarray) -> dict:
        """Fit μ (per-model linear) and σ (heteroscedastic) on a data slice."""
        model_features = x[:, [self.IDX_GFS, self.IDX_ECMWF, self.IDX_UKMO, self.IDX_NBM]]
        spreads = x[:, self.IDX_SPREAD]

        mu_reg = LinearRegression()
        mu_reg.fit(model_features, y)
        residuals = y - mu_reg.predict(model_features)

        # heteroscedastic sigma: fit |residual| ~ c + d * model_spread
        abs_res = np.abs(residuals)
        if len(spreads) >= 5 and spreads.std() > 0.01:
            A = np.column_stack([np.ones_like(spreads), spreads])
            coeffs, _, _, _ = np.linalg.lstsq(A, abs_res, rcond=None)
            c = max(self.min_sigma, float(coeffs[0]))
            d = max(0.0, float(coeffs[1]))
        else:
            c = max(self.min_sigma, float(abs_res.mean()))
            d = 0.0

        return {"mu_reg": mu_reg, "c": c, "d": d}

    def fit(self, x: np.ndarray, y: np.ndarray) -> "SeasonalEMOSModel":
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        months = x[:, self.IDX_MONTH].astype(int)

        # global fallback — used when season sample is too small
        self._global_model = self._fit_one(x, y)

        for season, season_months in self.SEASONS.items():
            mask = np.isin(months, list(season_months))
            if mask.sum() >= self.min_season_days:
                self._season_models[season] = self._fit_one(x[mask], y[mask])
            else:
                self._season_models[season] = self._global_model

        self.fitted_ = True
        return self

    def predict_distribution(self, x_row: np.ndarray) -> tuple[float, float]:
        _ensure_fitted(self.fitted_)
        x_row = np.asarray(x_row, dtype=float).reshape(1, -1)
        month = int(x_row[0, self.IDX_MONTH])
        spread = float(x_row[0, self.IDX_SPREAD])
        season = self._month_to_season(month)
        model = self._season_models.get(season, self._global_model)

        model_feats = x_row[:, [self.IDX_GFS, self.IDX_ECMWF, self.IDX_UKMO, self.IDX_NBM]]
        mu = float(model["mu_reg"].predict(model_feats)[0])
        sigma = max(self.min_sigma, model["c"] + model["d"] * spread)
        return mu, sigma

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


def _gumbel_bracket_probs(loc: float, beta: float, brackets: list[dict]) -> dict[str, float]:
    """Shared Gumbel bracket probability computation for EMOS-Gumbel variants."""
    raw: dict[str, float] = {}
    for bracket in brackets:
        ticker = str(bracket["ticker"])
        lo = _finite_or_none(bracket.get("lo_f", bracket.get("floor_strike")))
        hi = _finite_or_none(bracket.get("hi_f", bracket.get("cap_strike")))
        btype = _normalise_bracket_type(bracket.get("bracket_type", "central"))
        if btype == "lower_tail":
            threshold = hi if hi is not None else lo
            prob = float(gumbel_r.cdf(threshold, loc, beta)) if threshold is not None else 0.0
        elif btype == "upper_tail":
            threshold = lo if lo is not None else hi
            prob = float(1.0 - gumbel_r.cdf(threshold, loc, beta)) if threshold is not None else 0.0
        elif lo is not None and hi is not None:
            prob = float(gumbel_r.cdf(hi, loc, beta) - gumbel_r.cdf(lo, loc, beta))
        else:
            prob = 0.0
        raw[ticker] = max(0.0, prob)
    return normalize_probability_mass(raw)


@dataclass
class EMOSGumbelModel:
    """EMOS with Gumbel predictive distribution.

    Fits mu via OLS on all ensemble features. Estimates the Gumbel scale
    beta from residual std (beta = std * sqrt(6) / pi). Shifts the Gumbel
    location so its mean equals the OLS prediction: loc = mu_ols - beta * gamma.
    """

    min_beta: float = 0.5

    def __post_init__(self) -> None:
        self.regressor = LinearRegression()
        self.beta_: float = 1.0
        self.fitted_: bool = False

    def fit(self, x: np.ndarray, y: np.ndarray, sample_weight: np.ndarray | None = None) -> "EMOSGumbelModel":
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        self.regressor.fit(x, y, sample_weight=sample_weight)
        residuals = y - self.regressor.predict(x)
        if sample_weight is not None:
            w = np.asarray(sample_weight, dtype=float)
            w = w / w.sum()
            sigma = float(np.sqrt(np.sum(w * residuals ** 2)))
        else:
            sigma = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else self.min_beta
        self.beta_ = max(self.min_beta, sigma * np.sqrt(6.0) / np.pi)
        self.fitted_ = True
        return self

    def predict_distribution(self, x_row: np.ndarray) -> tuple[float, float]:
        _ensure_fitted(self.fitted_)
        mu_mean = float(self.regressor.predict(np.asarray(x_row, dtype=float).reshape(1, -1))[0])
        loc = mu_mean - self.beta_ * _EULER_GAMMA
        return loc, self.beta_

    def bracket_probabilities(self, x_row: np.ndarray, brackets: list[dict]) -> dict[str, float]:
        loc, beta = self.predict_distribution(x_row)
        return _gumbel_bracket_probs(loc, beta, brackets)


@dataclass
class EMOSGumbelHeteroModel:
    """EMOS-Gumbel with spread-linked scale (heteroscedastic beta).

    Fits mu the same way as EMOSGumbelModel. Then fits beta as a linear function
    of model_spread (feature index 5): beta_i = max(min_beta, c + d*spread_i).
    c and d are estimated by regressing |residuals|*sqrt(6)/pi onto spread.
    """

    min_beta: float = 0.5
    IDX_SPREAD: int = 5  # model_spread in FEATURES

    def __post_init__(self) -> None:
        self.regressor = LinearRegression()
        self._c: float = 1.0
        self._d: float = 0.0
        self.fitted_: bool = False

    def fit(self, x: np.ndarray, y: np.ndarray, sample_weight: np.ndarray | None = None) -> "EMOSGumbelHeteroModel":
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        self.regressor.fit(x, y, sample_weight=sample_weight)
        residuals = y - self.regressor.predict(x)
        # Convert residual std to Gumbel scale targets
        gumbel_scales = np.abs(residuals) * np.sqrt(6.0) / np.pi
        spreads = x[:, self.IDX_SPREAD]
        if len(spreads) >= 10 and float(spreads.std()) > 0.01:
            A = np.column_stack([np.ones_like(spreads), spreads])
            coeffs, _, _, _ = np.linalg.lstsq(A, gumbel_scales, rcond=None)
            self._c = max(self.min_beta, float(coeffs[0]))
            self._d = max(0.0, float(coeffs[1]))
        else:
            self._c = max(self.min_beta, float(np.mean(gumbel_scales)))
            self._d = 0.0
        self.fitted_ = True
        return self

    def predict_distribution(self, x_row: np.ndarray) -> tuple[float, float]:
        _ensure_fitted(self.fitted_)
        x_row = np.asarray(x_row, dtype=float)
        mu_mean = float(self.regressor.predict(x_row.reshape(1, -1))[0])
        spread = float(x_row[self.IDX_SPREAD])
        beta = max(self.min_beta, self._c + self._d * spread)
        loc = mu_mean - beta * _EULER_GAMMA
        return loc, beta

    def bracket_probabilities(self, x_row: np.ndarray, brackets: list[dict]) -> dict[str, float]:
        loc, beta = self.predict_distribution(x_row)
        return _gumbel_bracket_probs(loc, beta, brackets)


@dataclass
class IDRTemperatureModel:
    """Isotonic Distributional Regression on consensus temperature.

    Learns F(y | consensus) = P(actual_temp <= y | consensus) non-parametrically
    under the stochastic order constraint (higher consensus -> warmer distribution).
    Bracket probabilities are derived from the IDR-calibrated CDF at each boundary.

    Reference: Henzi, Ziegel, Gneiting (JRSS-B 2021).
    """

    IDX_CONSENSUS: int = 4  # consensus feature index in FEATURES

    def __post_init__(self) -> None:
        self._consensus_train: np.ndarray = np.array([])
        self._actual_train: np.ndarray = np.array([])
        self.fitted_: bool = False

    def fit(self, x: np.ndarray, y: np.ndarray, sample_weight: np.ndarray | None = None) -> "IDRTemperatureModel":
        self._consensus_train = np.asarray(x, dtype=float)[:, self.IDX_CONSENSUS]
        self._actual_train = np.asarray(y, dtype=float)
        self.fitted_ = True
        return self

    def _cdf_at(self, threshold: float, consensus_test: float) -> float:
        """P(actual_temp <= threshold | consensus = consensus_test) via isotonic regression."""
        outcomes = (self._actual_train <= threshold).astype(float)
        # Higher consensus -> warmer -> less likely actual <= threshold -> increasing=False
        ir = IsotonicRegression(increasing=False, out_of_bounds="clip")
        ir.fit(self._consensus_train, outcomes)
        return float(np.clip(ir.predict([consensus_test])[0], 0.0, 1.0))

    def bracket_probabilities(self, x_row: np.ndarray, brackets: list[dict]) -> dict[str, float]:
        _ensure_fitted(self.fitted_)
        consensus_test = float(np.asarray(x_row, dtype=float)[self.IDX_CONSENSUS])
        raw: dict[str, float] = {}
        for bracket in brackets:
            ticker = str(bracket["ticker"])
            lo = _finite_or_none(bracket.get("lo_f", bracket.get("floor_strike")))
            hi = _finite_or_none(bracket.get("hi_f", bracket.get("cap_strike")))
            btype = _normalise_bracket_type(bracket.get("bracket_type", "central"))
            if btype == "lower_tail":
                threshold = hi if hi is not None else lo
                prob = self._cdf_at(threshold, consensus_test) if threshold is not None else 0.0
            elif btype == "upper_tail":
                threshold = lo if lo is not None else hi
                prob = 1.0 - self._cdf_at(threshold, consensus_test) if threshold is not None else 0.0
            elif lo is not None and hi is not None:
                p_hi = self._cdf_at(hi, consensus_test)
                p_lo = self._cdf_at(lo, consensus_test)
                prob = max(0.0, p_hi - p_lo)
            else:
                prob = 0.0
            raw[ticker] = max(0.0, float(prob))
        return normalize_probability_mass(raw)


@dataclass
class NGBoostModel:
    """NGBoost with Normal predictive distribution.

    Uses natural gradient boosting to jointly learn mu and sigma from all
    ensemble features. Unlike rolling-window EMOS, benefits from the full
    accumulated training history as more data arrives.

    Reference: Duan et al. (ICML 2020) — NGBoost: Natural Gradient Boosting
    for Probabilistic Prediction.
    """

    n_estimators: int = 200
    learning_rate: float = 0.05
    random_state: int = 17

    def __post_init__(self) -> None:
        self._model = None
        self.fitted_: bool = False

    def fit(self, x: np.ndarray, y: np.ndarray, sample_weight: np.ndarray | None = None) -> "NGBoostModel":
        try:
            from ngboost import NGBRegressor
        except ImportError as exc:
            raise RuntimeError("ngboost not installed: run 'uv add ngboost'") from exc
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        self._model = NGBRegressor(
            n_estimators=self.n_estimators,
            learning_rate=self.learning_rate,
            random_state=self.random_state,
            verbose=False,
        )
        self._model.fit(x, y, sample_weight=sample_weight)
        self.fitted_ = True
        return self

    def predict_distribution(self, x_row: np.ndarray) -> tuple[float, float]:
        _ensure_fitted(self.fitted_)
        row = np.asarray(x_row, dtype=float).reshape(1, -1)
        dist = self._model.pred_dist(row)
        mu = float(dist.loc[0])
        sigma = max(0.5, float(dist.scale[0]))
        return mu, sigma

    def bracket_probabilities(self, x_row: np.ndarray, brackets: list[dict]) -> dict[str, float]:
        mu, sigma = self.predict_distribution(x_row)
        raw: dict[str, float] = {}
        for bracket in brackets:
            ticker = str(bracket["ticker"])
            lo = _finite_or_none(bracket.get("lo_f", bracket.get("floor_strike")))
            hi = _finite_or_none(bracket.get("hi_f", bracket.get("cap_strike")))
            btype = _normalise_bracket_type(bracket.get("bracket_type", "central"))
            if btype == "lower_tail":
                threshold = hi if hi is not None else lo
                prob = float(norm.cdf(threshold, mu, sigma)) if threshold is not None else 0.0
            elif btype == "upper_tail":
                threshold = lo if lo is not None else hi
                prob = float(1.0 - norm.cdf(threshold, mu, sigma)) if threshold is not None else 0.0
            elif lo is not None and hi is not None:
                prob = float(norm.cdf(hi, mu, sigma) - norm.cdf(lo, mu, sigma))
            else:
                prob = 0.0
            raw[ticker] = max(0.0, prob)
        return normalize_probability_mass(raw)


class _NGBoostGumbelLogScore(LogScore):
    """Log score for a right-skewed Gumbel regression distribution."""

    def score(self, y: np.ndarray) -> np.ndarray:
        return -self.dist.logpdf(y)

    def d_score(self, y: np.ndarray) -> np.ndarray:
        y = np.asarray(y, dtype=float)
        z = (y - self.loc) / self.scale
        exp_neg_z = np.exp(-np.clip(z, -50.0, 50.0))
        grad = np.zeros((len(y), 2))
        grad[:, 0] = (exp_neg_z - 1.0) / self.scale
        grad[:, 1] = 1.0 - z + z * exp_neg_z
        return grad

    def metric(self, n_mc_samples: int = 100) -> np.ndarray:
        grads = np.stack([self.d_score(sample) for sample in self.sample(n_mc_samples)])
        return np.mean(np.einsum("sik,sij->sijk", grads, grads), axis=0)


class _NGBoostGumbelDistribution(RegressionDistn):
    """Minimal NGBoost-compatible scipy Gumbel-right distribution."""

    n_params = 2
    scores = [_NGBoostGumbelLogScore]

    def __init__(self, params: np.ndarray) -> None:
        self.loc = params[0]
        self.scale = np.maximum(0.1, np.exp(params[1]))
        self.dist = gumbel_r(loc=self.loc, scale=self.scale)

    def fit(y: np.ndarray) -> np.ndarray:
        loc, scale = gumbel_r.fit(np.asarray(y, dtype=float))
        return np.array([loc, np.log(max(0.1, float(scale)))])

    def sample(self, m: int) -> np.ndarray:
        return np.array([self.rvs() for _ in range(m)])

    def __getattr__(self, name: str):
        if name in dir(self.dist):
            return getattr(self.dist, name)
        return None

    @property
    def params(self) -> dict[str, np.ndarray]:
        return {"loc": self.loc, "scale": self.scale}


@dataclass
class NGBoostGumbelModel:
    """NGBoost with a Gumbel predictive distribution.

    This keeps NGBoost's nonlinear feature learning but uses a daily-maximum
    distribution shape instead of the default Normal likelihood.
    """

    n_estimators: int = 100
    learning_rate: float = 0.05
    random_state: int = 17

    def __post_init__(self) -> None:
        self._model = None
        self.fitted_: bool = False

    def fit(self, x: np.ndarray, y: np.ndarray, sample_weight: np.ndarray | None = None) -> "NGBoostGumbelModel":
        try:
            from ngboost import NGBRegressor
        except ImportError as exc:
            raise RuntimeError("ngboost not installed: run 'uv add ngboost'") from exc
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        self._model = NGBRegressor(
            Dist=_NGBoostGumbelDistribution,
            n_estimators=self.n_estimators,
            learning_rate=self.learning_rate,
            random_state=self.random_state,
            verbose=False,
        )
        self._model.fit(x, y, sample_weight=sample_weight)
        self.fitted_ = True
        return self

    def predict_distribution(self, x_row: np.ndarray) -> tuple[float, float]:
        _ensure_fitted(self.fitted_)
        row = np.asarray(x_row, dtype=float).reshape(1, -1)
        dist = self._model.pred_dist(row)
        loc = float(dist.loc[0])
        beta = max(0.1, float(dist.scale[0]))
        return loc, beta

    def bracket_probabilities(self, x_row: np.ndarray, brackets: list[dict]) -> dict[str, float]:
        loc, beta = self.predict_distribution(x_row)
        return _gumbel_bracket_probs(loc, beta, brackets)
