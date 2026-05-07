from __future__ import annotations

import numpy as np

from research.models.calibration_models import (
    EMOSModel,
    HGBRQuantileModel,
    NGBoostGumbelModel,
    RandomForestDistributionModel,
    bracket_probabilities_from_samples,
    normalize_probability_mass,
)


BRACKETS = [
    {"ticker": "LOW", "lo_f": None, "hi_f": 50.0, "bracket_type": "wing_low"},
    {"ticker": "MID", "lo_f": 50.0, "hi_f": 70.0, "bracket_type": "central"},
    {"ticker": "HIGH", "lo_f": 70.0, "hi_f": None, "bracket_type": "wing_high"},
]


def sample_training_data():
    rng = np.random.default_rng(7)
    x = np.column_stack(
        [
            np.linspace(45, 85, 80),
            rng.normal(0, 1, 80),
            np.sin(np.linspace(0, 6, 80)),
        ]
    )
    y = x[:, 0] + 0.5 * x[:, 1] + rng.normal(0, 1.2, 80)
    return x, y


def test_normalize_probability_mass():
    probs = normalize_probability_mass({"a": 2.0, "b": 1.0, "c": -1.0})
    assert abs(sum(probs.values()) - 1.0) < 1e-12
    assert all(value >= 0.0 for value in probs.values())


def test_empirical_bracket_probabilities_sum_to_one():
    probs = bracket_probabilities_from_samples([45, 55, 75], BRACKETS)
    assert abs(sum(probs.values()) - 1.0) < 1e-12
    assert probs["LOW"] > 0
    assert probs["MID"] > 0
    assert probs["HIGH"] > 0


def test_emos_model_fits_and_predicts_coherent_probs():
    x, y = sample_training_data()
    model = EMOSModel().fit(x, y)
    probs = model.bracket_probabilities(x[-1], BRACKETS)
    assert abs(sum(probs.values()) - 1.0) < 1e-9
    assert all(0.0 <= value <= 1.0 for value in probs.values())


def test_random_forest_distribution_model_runs():
    x, y = sample_training_data()
    model = RandomForestDistributionModel(n_estimators=20, min_samples_leaf=3).fit(x, y)
    probs = model.bracket_probabilities(x[-1], BRACKETS)
    assert abs(sum(probs.values()) - 1.0) < 1e-9
    assert all(0.0 <= value <= 1.0 for value in probs.values())


def test_hgbr_quantile_model_runs_and_quantiles_are_monotone():
    x, y = sample_training_data()
    model = HGBRQuantileModel(quantiles=(0.1, 0.5, 0.9), max_iter=20).fit(x, y)
    q = model.predict_quantiles(x[-1])
    values = [q[key] for key in sorted(q)]
    assert values == sorted(values)
    probs = model.bracket_probabilities(x[-1], BRACKETS)
    assert abs(sum(probs.values()) - 1.0) < 1e-9


def test_ngboost_gumbel_model_runs():
    x, y = sample_training_data()
    model = NGBoostGumbelModel(n_estimators=5).fit(x, y)
    probs = model.bracket_probabilities(x[-1], BRACKETS)
    assert abs(sum(probs.values()) - 1.0) < 1e-9
    assert all(0.0 <= value <= 1.0 for value in probs.values())
