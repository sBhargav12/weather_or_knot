"""Deferred reflection memory log for weather prediction market trades.

Inspired by TradingAgents' TradingMemoryLog pattern. Each trade is stored as
"pending" when entered; on the next pipeline run after settlement is available,
the outcome is resolved and an LLM reflection is generated. Past reflections are
injected as context into future trade decisions for the same city.

Storage: data/weather_memory.json  (simple JSON, not a DB table, so it can be
inspected and cleared without touching the live SQLite).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from data_store.db import Database

logger = logging.getLogger(__name__)

_MEMORY_PATH = Path("data/weather_memory.json")
_MAX_RESOLVED = 30   # entries kept per city
_PAST_CONTEXT_N = 5  # entries shown to LLM per city


class WeatherMemoryLog:
    def __init__(self, db: "Database", memory_path: Path = _MEMORY_PATH) -> None:
        self.db = db
        self.path = memory_path
        self._data: dict[str, Any] = self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write_pending(self, city: str, entry: dict) -> None:
        """Record a newly-entered trade as pending settlement resolution."""
        entry = {**entry, "resolved": False, "written_at": datetime.now(UTC).isoformat()}
        self._city(city)["pending"].append(entry)
        self._save()

    def resolve_pending(self, city: str) -> None:
        """Attempt to resolve any pending entries using CLI data in the DB.

        Called at the start of each fire_gate_check so reflections are ready
        before the LLM synthesis layer reads past_context.
        """
        city_data = self._city(city)
        still_pending = []
        resolved_any = False

        for entry in city_data.get("pending", []):
            trade_date = entry.get("trade_date")
            if not trade_date:
                still_pending.append(entry)
                continue

            settlement_temp = self._fetch_settlement(city, trade_date)
            if settlement_temp is None:
                still_pending.append(entry)
                continue

            bracket_yes = _parse_bracket_outcome(entry.get("bracket"), settlement_temp)
            direction_correct = (entry.get("direction") == "YES") == bracket_yes
            net_pnl = self._fetch_pnl(entry.get("ticker"), trade_date)

            reflection = _generate_reflection(entry, settlement_temp, bracket_yes, direction_correct, net_pnl)

            city_data["resolved"].append({
                **entry,
                "resolved": True,
                "settlement_temp_f": settlement_temp,
                "bracket_resolved_yes": bracket_yes,
                "direction_correct": direction_correct,
                "net_pnl": net_pnl,
                "reflection": reflection,
                "resolved_at": datetime.now(UTC).isoformat(),
            })
            resolved_any = True
            logger.info(
                "WeatherMemory resolved %s %s: settled=%.1f°F %s pnl=%s",
                city, trade_date, settlement_temp,
                "✓" if direction_correct else "✗",
                f"${net_pnl:.2f}" if net_pnl is not None else "N/A",
            )

        city_data["pending"] = still_pending
        # Trim to keep only the last N resolved entries
        city_data["resolved"] = city_data["resolved"][-_MAX_RESOLVED:]
        if resolved_any:
            self._save()

    def get_past_context(self, city: str, n: int = _PAST_CONTEXT_N) -> str:
        """Return a formatted string of the last n resolved decisions for a city."""
        resolved = self._city(city).get("resolved", [])
        if not resolved:
            return ""

        recent = resolved[-n:]
        lines = [f"--- {city} Last {len(recent)} Resolved Trade(s) ---"]
        for e in recent:
            date = e.get("trade_date", "?")
            bracket = e.get("bracket", "?")
            direction = e.get("direction", "?")
            price = e.get("entry_price", 0.0)
            emos = e.get("emos_prob")
            gap = e.get("gap_pp", 0.0)
            gate5 = e.get("gate5_reason", "?")
            settled = "YES" if e.get("bracket_resolved_yes") else "NO"
            temp = e.get("settlement_temp_f", "?")
            pnl = e.get("net_pnl") or 0.0
            pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
            ok = "✓" if e.get("direction_correct") else "✗"
            emos_str = f"EMOS={emos:.2f} " if emos is not None else ""
            lines.append(
                f"{date} | {bracket} {direction} @{price:.2f} | "
                f"{emos_str}gap={gap:.0f}pp | METAR:{gate5} | "
                f"settled={settled}({temp}°F) {pnl_str} {ok}"
            )
            if e.get("reflection"):
                lines.append(f"  → {e['reflection']}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _city(self, city: str) -> dict:
        if city not in self._data:
            self._data[city] = {"pending": [], "resolved": []}
        return self._data[city]

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except Exception as exc:
                logger.warning("WeatherMemory: failed to load %s: %s", self.path, exc)
        return {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=2, default=str))
        except Exception as exc:
            logger.warning("WeatherMemory: failed to save: %s", exc)

    def _fetch_settlement(self, city: str, trade_date: str) -> Optional[float]:
        """Query cli_reports for the official settlement temp on trade_date."""
        try:
            rows = self.db.execute(
                "SELECT official_high_f, official_low_f FROM cli_reports "
                "WHERE city = ? AND settlement_date = ? LIMIT 1",
                (city, trade_date),
            )
            if rows:
                val = rows[0]["official_high_f"] or rows[0]["official_low_f"]
                return float(val) if val is not None else None
        except Exception as exc:
            logger.debug("WeatherMemory: CLI query failed for %s %s: %s", city, trade_date, exc)
        return None

    def _fetch_pnl(self, ticker: Optional[str], trade_date: str) -> Optional[float]:
        """Sum net_pnl_maker for closed trades on this ticker/date."""
        if not ticker:
            return None
        try:
            rows = self.db.execute(
                "SELECT SUM(net_pnl_maker) AS pnl FROM paper_trades "
                "WHERE ticker = ? AND target_date = ? AND exit_time IS NOT NULL",
                (ticker, trade_date),
            )
            if rows and rows[0]["pnl"] is not None:
                return float(rows[0]["pnl"])
        except Exception as exc:
            logger.debug("WeatherMemory: PnL query failed for %s %s: %s", ticker, trade_date, exc)
        return None


# ------------------------------------------------------------------
# Module-level helpers (no DB dependency)
# ------------------------------------------------------------------

def _parse_bracket_outcome(bracket: Optional[str], settlement_temp: float) -> bool:
    """Return True if the bracket resolves YES at the given settlement temperature."""
    if not bracket:
        return False
    b = str(bracket).replace("°", "").replace("F", "").strip()
    try:
        if b.startswith(">="):
            return settlement_temp >= float(b[2:].strip())
        if b.startswith("<="):
            return settlement_temp <= float(b[2:].strip())
        if "-" in b:
            lo, hi = b.split("-", 1)
            return float(lo) <= settlement_temp <= float(hi)
    except (ValueError, IndexError):
        pass
    return False


def _generate_reflection(
    entry: dict,
    settlement_temp: float,
    bracket_yes: bool,
    direction_correct: bool,
    net_pnl: Optional[float],
) -> str:
    """Generate a reflection string. Uses LLM when ANTHROPIC_API_KEY is set,
    falls back to a deterministic summary otherwise."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _simple_reflection(entry, settlement_temp, bracket_yes, direction_correct)

    try:
        import anthropic

        direction = entry.get("direction", "?")
        bracket = entry.get("bracket", "?")
        emos = entry.get("emos_prob")
        gap = entry.get("gap_pp", 0.0)
        gate5 = entry.get("gate5_reason", "unknown")
        gate6 = entry.get("gate6_reason", "unknown")
        llm_risk = entry.get("llm_key_risk") or "none noted"
        settled = "YES" if bracket_yes else "NO"
        outcome = "correct" if direction_correct else "WRONG"
        pnl_str = f"+${net_pnl:.2f}" if net_pnl and net_pnl >= 0 else f"-${abs(net_pnl or 0):.2f}"
        emos_str = f"EMOS={emos:.3f}" if emos is not None else "EMOS=N/A"

        prompt = f"""You are reviewing a past Kalshi weather temperature bracket trade for {entry.get('city', '?')}.

Trade: {bracket} {direction} | {emos_str} | Gap={gap:.1f}pp
Gate 5 (METAR): {gate5} | Gate 6 (Reversal): {gate6}
Risk flagged at entry: {llm_risk}
Outcome: settlement={settlement_temp:.1f}°F → bracket resolved {settled} → {outcome} | PnL={pnl_str}

Write exactly 2–3 sentences of plain prose. Cover:
1. Was the probability estimate well-calibrated?
2. Did METAR or reversal gate signal prove useful or misleading?
3. One concrete lesson for the next similar trade on this city.

No headers. No bullet points. Be specific."""

        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=160,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()

    except Exception as exc:
        logger.warning("WeatherMemory: LLM reflection failed: %s", exc)
        return _simple_reflection(entry, settlement_temp, bracket_yes, direction_correct)


def _simple_reflection(
    entry: dict,
    settlement_temp: float,
    bracket_yes: bool,
    direction_correct: bool,
) -> str:
    emos = entry.get("emos_prob")
    direction = entry.get("direction", "?")
    settled = "YES" if bracket_yes else "NO"
    outcome = "correct" if direction_correct else "incorrect"
    emos_str = f"EMOS={emos:.3f}" if emos is not None else "EMOS=N/A"
    gap = entry.get("gap_pp", 0.0)
    gate5 = entry.get("gate5_reason", "unknown")
    return (
        f"Settlement {settlement_temp:.1f}°F → bracket {settled}. "
        f"{direction} trade was {outcome}. {emos_str}, gap={gap:.1f}pp, METAR:{gate5}."
    )
