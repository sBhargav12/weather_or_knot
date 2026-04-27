from __future__ import annotations

from decimal import Decimal

import config

"""
Paper-only research promotion settings.

This module is intentionally separate from config.py so research-guided paper
policy can evolve without changing the frozen live defaults. Nothing in this
file is approved for live execution by itself.

Research context:
- CORE is execution-fragile: +3c fill stress turned core negative in the
  cached coherent-probability backtest.
- Wings and central brackets behave differently: calibrated holdout Brier was
  much stronger on wings than central brackets.
- TAIL_NO remains suspended for paper trading because the sleeve has not earned
  enough forward confidence, even though it is useful as a logged candidate.
- Seasonal and regime logic should be soft sizing only, not a hard production
  shutdown. These multipliers need forward paper validation.
"""


# Feature flags. These affect future paper-policy wiring only; live config.py
# stays canonical for the always-on pipeline.
PAPER_USE_RESEARCH_WEIGHTS = True
PAPER_USE_WING_CENTRAL_SPLIT = True
PAPER_TAIL_NO_ENABLED = False
PAPER_DEEP_TAIL_NO_ENABLED = True
PAPER_REQUIRE_EXECUTION_MARGIN = True
PAPER_USE_SEASONAL_SCALING = True
PAPER_USE_REGIME_SCALING = True
PAPER_USE_CALIBRATED_PROBS = False
PAPER_SUSPEND_LOWER_WING = True


# Research weights are allowed in paper-only fallback experiments. These do not
# replace HGEFS-first live behavior and do not overwrite config.py defaults.
PAPER_ENSEMBLE_WEIGHTS = dict(config.FALLBACK_ENSEMBLE_WEIGHTS)


# Raw edge must clear an execution-cost reserve before paper entry. Defaults are
# conservative placeholders derived from the fill stress warning, not optimized
# live thresholds.
PAPER_MIN_NET_EDGE_PP_CORE = 10.0
PAPER_MIN_NET_EDGE_PP_WING = 6.0
PAPER_MIN_NET_EDGE_PP_DEEP_TAIL = 4.0
PAPER_FEE_MARGIN_PP = 1.0
PAPER_CORE_MIN_CONFIDENCE = 60.0
PAPER_CORE_STRESS_BUFFER_PP = 3.0
PAPER_DEEP_TAIL_STRESS_BUFFER_PP = 1.0
PAPER_WING_STRESS_BUFFER_PP = 1.0


# Soft sizing controls. No month or regime is forced to zero. Weak periods are
# scaled down for paper observation while preserving forward data collection.
PAPER_SEASONAL_MULTIPLIERS = {
    1: 0.50,
    2: 0.65,
    3: 0.50,
    4: 0.75,
    5: 1.00,
    6: 1.00,
    7: 1.00,
    8: 1.15,
    9: 1.15,
    10: 1.15,
    11: 1.05,
    12: 0.50,
}

PAPER_REGIME_MULTIPLIERS = {
    "pre_HGEFS": 1.05,
    "HGEFS_to_AIFS": 0.60,
    "AIFS_to_NBM_v43": 0.90,
    "NBM_v43_to_AIFS_ENS": 0.85,
    "AIFS_ENS_to_NBM_v50": 0.80,
    "NBM_v50_on": 0.90,
    "unknown": 0.75,
}

PAPER_MIN_SIZE_MULT = 0.25
PAPER_MAX_SIZE_MULT = 1.15


# Paper sleeve state. These mirror current research conclusions and are meant
# to drive candidate reporting in later phases.
PAPER_SLEEVE_STATES = {
    "CORE": "active",
    "TAIL_NO": "suspended_policy",
    "DEEP_TAIL_NO": "active",
    "LOWER_WING": "suspended_policy",
}


# Paper-only defaults that can be reported by dashboard/daily_report.py in later
# phases. Use Decimal for price-like values to stay consistent with Kalshi price
# handling.
PAPER_ASSUMED_MAKER_ONLY = True
PAPER_CORE_STRESS_WARNING = "CORE negative under +3c stress in cached backtest"
PAPER_DEEP_TAIL_STRESS_WARNING = "DEEP_TAIL_NO survived +3c stress but with thin residual edge"
PAPER_MAX_TRADE_PCT = Decimal(str(config.MAX_TRADE_PCT))
