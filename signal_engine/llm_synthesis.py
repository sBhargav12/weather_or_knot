"""LLM synthesis layer — post-gate trade decision using Claude Haiku.

Called once per bracket after all 6 gates pass. Receives gate outputs, model
probabilities, and the city's past-trade reflections, then outputs a structured
WeatherTradeDecision (action + sizing_fraction + reasoning + key_risk).

Falls back to a pass-through decision (full size, BUY_<direction>) when:
  - ANTHROPIC_API_KEY is not set
  - The LLM call fails for any reason

This layer never hard-blocks a trade on its own; it can only set sizing_fraction
to 0.0 (PASS) when signals are contradictory despite gates passing.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from signal_engine.schemas import GateCheckResult, WeatherTradeDecision

logger = logging.getLogger(__name__)


def _fallback(gate: GateCheckResult) -> WeatherTradeDecision:
    return WeatherTradeDecision(
        action=f"BUY_{gate.direction}",  # type: ignore[arg-type]
        sizing_fraction=1.0,
        reasoning="LLM synthesis unavailable; arithmetic gate result used.",
        key_risk="No LLM risk assessment available.",
        past_context_used=False,
    )


def synthesize_trade_decision(
    city: str,
    ticker: str,
    gate: GateCheckResult,
    emos_prob: Optional[float],
    gumbel_prob: float,
    market_price: float,
    past_context: str,
    bracket_label: str = "",
) -> WeatherTradeDecision:
    """Call Claude Haiku to synthesize a final trade decision after all gates pass.

    Returns a WeatherTradeDecision. Never raises — any error returns the fallback.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.debug("ANTHROPIC_API_KEY not set; skipping LLM synthesis for %s", ticker)
        return _fallback(gate)

    try:
        import anthropic

        g1 = gate.gate1
        g5 = gate.gate5
        g6 = gate.gate6

        physics_str = (
            f"{g1.physics_mean:.1f}°F spread={g1.physics_spread:.2f}°F"
            if g1.physics_mean is not None else "N/A"
        )
        metar_str = (
            f"{g5.effective_temp_f:.1f}°F vs center {g5.bracket_center_f:.1f}°F ({g5.reason})"
            if g5.effective_temp_f is not None else f"unavailable ({g5.reason})"
        )
        past_section = past_context.strip() if past_context else "No prior history for this city."
        emos_str = f"{emos_prob:.3f}" if emos_prob is not None else "N/A"

        prompt = f"""You are a weather prediction market analyst for Kalshi temperature bracket contracts.
All 6 signal gates have passed. Decide whether to execute and at what size.

## City: {city} | Bracket: {bracket_label} | Ticker: {ticker}
Market price: {market_price:.2f}

## Model signals
- EMOS probability: {emos_str}
- Gumbel probability: {gumbel_prob:.3f}
- Gap vs market: {gate.gap_pp:.1f}pp ({gate.direction})
- Confidence score: {gate.confidence_score:.0f}/100

## Gate diagnostics
- Gate 1 (Ensemble convergence): {g1.reason} | {physics_str}
- Gate 5 (METAR observation): {metar_str}
- Gate 6 (Evening reversal): {g6.reason} | cold_bracket={g6.is_cold_bracket}

## Past {city} resolved trades
{past_section}

---
Consider: (1) Are model signals consistent and does the gap justify a trade?
(2) Does the METAR reading support or undermine the probability?
(3) What does past city-specific experience suggest about similar setups?

Output ONLY valid JSON — no markdown, no explanation:
{{"action": "BUY_YES" | "BUY_NO" | "PASS", "sizing_fraction": 0.0-1.0, "reasoning": "1-2 sentences", "key_risk": "1 sentence", "past_context_used": true | false}}

sizing_fraction: 1.0 = full gate-computed size, 0.5 = half, 0.0 = PASS.
Use PASS only if signals are genuinely contradictory despite gates passing."""

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=220,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        # Strip accidental markdown fences
        if raw.startswith("```"):
            raw = "\n".join(
                line for line in raw.splitlines()
                if not line.strip().startswith("```")
            ).strip()

        data = json.loads(raw)
        decision = WeatherTradeDecision(**data)

        logger.info(
            "LLM synthesis %s %s: action=%s sizing=%.2f | %s",
            city, ticker, decision.action, decision.sizing_fraction, decision.reasoning,
        )
        return decision

    except Exception as exc:
        logger.warning("LLM synthesis failed for %s (%s): %s", ticker, city, exc)
        return _fallback(gate)
