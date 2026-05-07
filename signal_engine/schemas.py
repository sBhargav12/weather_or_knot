from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel


class _GateBase(BaseModel):
    """Pydantic base that supports legacy dict-style access so existing callers
    and tests that use gate["key"] or gate.get("key") continue to work."""

    def __getitem__(self, key: str) -> Any:
        # "pass" is a Python keyword; the old dict used that key for pass/fail.
        if key == "pass":
            return self.passed  # type: ignore[attr-defined]
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except AttributeError:
            return default


class Gate1Result(_GateBase):
    physics_mean: Optional[float] = None
    physics_spread: Optional[float] = None
    ai_mean: Optional[float] = None
    ai_spread: Optional[float] = None
    spread_between: Optional[float] = None
    nbm_p50: Optional[float] = None
    nbm_hgefs_gap_f: Optional[float] = None
    passed: bool = False
    hgefs_real: bool = False
    confidence_add: float = 0.0
    reason: str = "insufficient_model_data"


class Gate2Result(_GateBase):
    model_prob: float
    market_price: float
    gap_pp: float
    direction: Literal["YES", "NO"]
    in_dead_zone: bool
    passed: bool
    confidence_add: float


class Gate3Result(_GateBase):
    yes_price: float
    entry_price: float
    direction: str
    passed: bool
    reason: str


class Gate4Result(_GateBase):
    gap_pp: float
    in_dead_zone: bool
    passed: bool = True
    confidence_delta: float


class Gate5Result(_GateBase):
    metar_temp_f: Optional[float] = None
    six_hour_high_f: Optional[float] = None
    effective_temp_f: Optional[float] = None
    bracket_center_f: float
    distance: Optional[float] = None
    direction: str
    passed: bool = True
    metar_confirms: Optional[bool] = None
    confidence_delta: float
    reason: str


class Gate6Result(_GateBase):
    ticker: str
    is_cold_bracket: bool
    reversal_detected: bool = False
    max_price: Optional[float] = None
    current_price: Optional[float] = None
    passed: bool = True
    confidence_delta: float
    reason: str


class GateCheckResult(BaseModel):
    """Typed result from run_all_gates(). Supports legacy dict-style access."""

    all_pass: bool
    direction: Literal["YES", "NO"]
    requested_direction: str
    gap_pp: float
    gate1: Gate1Result
    gate2: Gate2Result
    gate3: Gate3Result
    gate4: Gate4Result
    gate5: Gate5Result
    gate6: Gate6Result
    confidence_score: float = 0.0
    skip_reason: Optional[str] = None

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class WeatherTradeDecision(BaseModel):
    """Structured decision output from the LLM synthesis layer."""

    action: Literal["BUY_YES", "BUY_NO", "PASS"]
    sizing_fraction: float  # 0.0–1.0 multiplier on the gate-computed position size
    reasoning: str
    key_risk: str
    past_context_used: bool = False
