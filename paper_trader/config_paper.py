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
PAPER_ENABLE_EMOS = True  # use LiveEMOSModel prob for CORE_HGEFS_EMOS sleeve
PAPER_USE_RESEARCH_WEIGHTS = True
PAPER_USE_WING_CENTRAL_SPLIT = True
PAPER_TAIL_NO_ENABLED = False
PAPER_DEEP_TAIL_NO_ENABLED = True
PAPER_REQUIRE_EXECUTION_MARGIN = True
PAPER_USE_SEASONAL_SCALING = True
PAPER_USE_REGIME_SCALING = True
PAPER_USE_CALIBRATED_PROBS = False
PAPER_SUSPEND_LOWER_WING = True

# TradingAgents-inspired features (Priority 1–3 from May 2026 integration).
# Both require ANTHROPIC_API_KEY in env; gracefully degrade when absent.
PAPER_WEATHER_MEMORY_ENABLED = True  # deferred reflection memory log
PAPER_LLM_SYNTHESIS_ENABLED = True  # post-gate LLM synthesis (Claude Haiku)


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
# Backtest shows 25–55c entry range loses money; 55–75c wins 78.6% with 3.5× Sharpe.
# This filter applies only to paper CORE entries, not live or tail sleeves.
PAPER_CORE_MIN_ENTRY_PRICE = 0.55
# YES trades are only profitable in the 30–35pp gap window (100% WR in leakage-safe backtest).
# Below 30pp: EMOS edge too small vs market noise (26% WR). Above 35pp: market strongly
# disagrees with the model and is usually right (38% WR). Cap applies to CORE and EMOS sleeves.
PAPER_YES_MIN_GAP_PP = 30.0
PAPER_YES_MAX_GAP_PP = 35.0
PAPER_CORE_STRESS_BUFFER_PP = 3.0
PAPER_DEEP_TAIL_STRESS_BUFFER_PP = 1.0
PAPER_WING_STRESS_BUFFER_PP = 1.0
PAPER_MIN_NET_EDGE_PP_LADDER = 1.0


# Soft sizing controls. No month or regime is forced to zero. Weak periods are
# scaled down for paper observation while preserving forward data collection.
PAPER_SEASONAL_MULTIPLIERS = {
    1: 0.50,
    2: 0.65,
    3: 0.50,
    4: 0.75,
    5: 0.75,
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
    "S3_BRACKET_LOCK_YES": "paper_only",  # Strategy 3 intraday high-confirmation YES
    "S1_FAR_BRACKET_NO_OVERLAY": "paper_only",  # Strategy 1 far wrong bracket NO overlay
    "LADDER_EVENT": "paper_only",  # Strategy 2 event-level YES/NO ladder sleeve
}

# Strategy 3: bracket-lock sleeve — intraday confirmed high entry (3:00–4:14 PM ET)
# Backtest (571 days, Oct 2024–Apr 2026): 78.4% WR, avg entry 64c, Sharpe 0.382
# Predexon 3PM executable-book sample (Jan–Apr 2026): 66.7% WR, positive but thin sample.
PAPER_BRACKET_LOCK_ENABLED = True
PAPER_BRACKET_LOCK_ENTRY_ET = "15:00"  # start of entry window
PAPER_BRACKET_LOCK_MIN_MARGIN_F = 1.0  # running max must be ≥1°F below upper bracket boundary
PAPER_BRACKET_LOCK_MIN_PRICE = 0.20  # don't enter if price already too cheap (bracket unlikely)
PAPER_BRACKET_LOCK_MAX_PRICE = 0.90  # don't enter if already repriced near certainty
PAPER_BRACKET_LOCK_NWS_BUFFER_F = 1.0  # skip if NWS remaining max > running_max + buffer
PAPER_BRACKET_LOCK_SIZE = 50  # contracts per trade (conservative start)
PAPER_BRACKET_LOCK_TARGET_PRICE = 0.95  # paper exit target for Strategy 3 research
# Per-sleeve stop loss overrides.
# DEEP_TAIL_NO: stops disabled — backtests show removing stop improves win rate
# from 55% to 95% because intraday NO price swings trigger stops on correct trades.
# Exits are handled by DSM_CANCEL and TIME_LIMIT instead.
# CORE/EMOS: widened to 0.35 (was 0.20) to absorb normal intraday volatility.
PAPER_DEEP_TAIL_NO_STOP_DISABLED = True
PAPER_CORE_STOP_DIFF = 0.35

PAPER_BRACKET_LOCK_STOP_DIFF = 0.20

# Strategy 1: far-bracket NO overlay after Strategy 3 confirms the observed-high bracket.
# Predexon 3PM executable-book sample: 7/7 wins, +$20.63 per 100-contract legs.
PAPER_FAR_BRACKET_NO_OVERLAY_ENABLED = True
PAPER_FAR_BRACKET_NO_MIN_DISTANCE_F = 4.0  # central brackets at least 4°F away from predicted floor
PAPER_FAR_BRACKET_NO_MIN_PRICE = 0.85
PAPER_FAR_BRACKET_NO_MAX_PRICE = 0.99
PAPER_FAR_BRACKET_NO_SIZE = 25  # smaller overlay than the main YES sleeve
PAPER_FAR_BRACKET_NO_TARGET_PRICE = 0.99
PAPER_FAR_BRACKET_NO_STOP_DIFF = 0.20
PAPER_FIXED_SIZE_SLEEVES = {"S3_BRACKET_LOCK_YES", "S1_FAR_BRACKET_NO_OVERLAY"}
PAPER_ALLOW_HIGH_ENTRY_SLEEVES = {"S3_BRACKET_LOCK_YES", "S1_FAR_BRACKET_NO_OVERLAY", "DEEP_TAIL_NO"}


# Strategy 2 — event-level ladder sleeve (morning window)
# Builds a small event portfolio: 1-2 YES legs where model probability is well
# above market, plus up to 3 NO legs on clearly wrong central brackets.
PAPER_LADDER_EVENT_ENABLED = True
PAPER_LADDER_ENTRY_START_ET = "09:00"
PAPER_LADDER_ENTRY_END_ET = "10:30"
PAPER_LADDER_TODAY_ONLY = True
PAPER_LADDER_MAX_YES_LEGS = 2
PAPER_LADDER_MAX_NO_LEGS = 3
PAPER_LADDER_YES_MIN_PROB = 0.15
PAPER_LADDER_YES_MIN_EDGE_PP = 12.0
PAPER_LADDER_NO_MAX_MODEL_PROB = 0.05
PAPER_LADDER_NO_MIN_ENTRY_PRICE = 0.86
PAPER_LADDER_NO_MAX_ENTRY_PRICE = 0.93
PAPER_LADDER_NO_MIN_DISTANCE_F = 4.0
PAPER_LADDER_CONFIDENCE = 45.0


# Paper-only defaults that can be reported by dashboard/daily_report.py in later
# phases. Use Decimal for price-like values to stay consistent with Kalshi price
# handling.
PAPER_ASSUMED_MAKER_ONLY = True
PAPER_CORE_STRESS_WARNING = "CORE negative under +3c stress in cached backtest"
PAPER_DEEP_TAIL_STRESS_WARNING = "DEEP_TAIL_NO survived +3c stress but with thin residual edge"
PAPER_MAX_TRADE_PCT = Decimal(str(config.MAX_TRADE_PCT))
