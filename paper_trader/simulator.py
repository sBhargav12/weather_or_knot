from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, time as _time, timedelta as _timedelta
from decimal import Decimal
from typing import Dict, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

import config
from dashboard.notifications import format_trade_entry, format_trade_exit, notify_phone
from data_store.db import Database
from paper_trader import config_paper
from paper_trader.policy import PaperPolicyDecision, paper_policy_allows_trade


def calculate_fees(contracts: int, price: float, order_type: str = "maker") -> float:
    if order_type == "maker":
        return config.maker_fee(contracts, price)
    return config.taker_fee(contracts, price)


def _canonical_sleeve(signal_or_trade: dict) -> str:
    return str(signal_or_trade.get("strategy_sleeve") or signal_or_trade.get("sleeve") or "CORE_HGEFS_GUMBEL")


def _settlement_date_from_ticker(ticker: str) -> str | None:
    """Parse settlement date from ticker, e.g. KXHIGHNY-26APR29-B58.5 → '2026-04-29'."""
    try:
        _, yymmdd, _ = ticker.split("-", 2)
        year = 2000 + int(yymmdd[:2])
        month = {
            "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
            "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
        }[yymmdd[2:5].upper()]
        day = int(yymmdd[5:])
        from datetime import date
        return date(year, month, day).isoformat()
    except Exception:
        return None


def _fixed_contracts(signal: dict) -> int | None:
    if _canonical_sleeve(signal) not in getattr(config_paper, "PAPER_FIXED_SIZE_SLEEVES", set()):
        return None
    try:
        contracts = int(signal.get("n_contracts") or 0)
    except (TypeError, ValueError):
        return None
    return contracts if contracts > 0 else None


class PaperTrader:
    def __init__(self, starting_bankroll: float, db_path: str):
        self.bankroll = float(starting_bankroll)
        self.starting_bankroll = float(starting_bankroll)
        self.db = Database(db_path)
        self.open_trades: Dict[int, dict] = {int(trade["id"]): trade for trade in self.db.get_open_trades()}

    def on_signal(self, signal: dict) -> Optional[dict]:
        policy = paper_policy_allows_trade(signal)
        self._log_policy_candidate(signal, policy)
        if not policy.allowed:
            return None
        if self._has_matching_open_trade(signal):
            return None

        direction = signal.get("direction", "YES")
        # entry_price is already the correct executable price for both YES and NO.
        # For NO: entry_price = 1 - yes_bid (set by event_triggers._no_entry_price).
        side_price = float(signal.get("entry_price", signal.get("market_price", 0)))
        model_prob_yes = float(signal.get("model_prob", 0.0))
        side_prob = model_prob_yes if direction == "YES" else 1.0 - model_prob_yes

        confidence = float(signal.get("confidence_score", 50.0))
        if confidence < 40.0:
            return None  # too uncertain to trade
        sleeve = _canonical_sleeve(signal)
        if (
            direction == "YES"
            and side_price >= float(config.NEVER_HOLD_ABOVE)
            and sleeve not in config_paper.PAPER_ALLOW_HIGH_ENTRY_SLEEVES
        ):
            return None  # entry price already at or above the ceiling; skip

        fixed_contracts = _fixed_contracts(signal)
        if fixed_contracts is None:
            sizing = self.calculate_position_size(
                self.bankroll,
                side_prob,
                side_price,
                confidence_score=confidence,
                size_multiplier=policy.final_size_mult,
            )
            if sizing["contracts"] <= 0:
                return None
        trade = self.simulate_entry(
            signal=signal,
            current_price=Decimal(str(side_price)),
            spread=Decimal(str(signal.get("spread", "0"))),
            policy=policy,
        )
        return trade

    def _has_matching_open_trade(self, signal: dict) -> bool:
        ticker = signal.get("ticker")
        direction = signal.get("direction", "YES")
        # Block if already open in same ticker+direction.
        if any(
            trade.get("ticker") == ticker and trade.get("direction") == direction
            for trade in self.open_trades.values()
        ):
            return True
        # Block re-entry: if we already closed a position in this ticker+direction
        # today ET (any reason including STOP), do not re-enter the same day.
        # entry_time is stored as UTC; compare against ET day via UTC window.
        _ny = ZoneInfo("America/New_York")
        _today_et = datetime.now(UTC).astimezone(_ny).date()
        _start_utc = datetime.combine(_today_et, _time.min, tzinfo=_ny).astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
        _end_utc = (datetime.combine(_today_et, _time.min, tzinfo=_ny) + _timedelta(days=1)).astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
        rows = self.db.execute(
            """
            SELECT id FROM paper_trades
            WHERE ticker = ? AND direction = ?
              AND entry_time >= ? AND entry_time < ?
              AND exit_time IS NOT NULL
            LIMIT 1
            """,
            (ticker, direction, _start_utc, _end_utc),
        )
        return len(rows) > 0

    def calculate_position_size(
        self,
        bankroll: float,
        prob: float,
        price: float,
        confidence_score: float = 70.0,
        size_multiplier: float = 1.0,
    ) -> dict:
        if price <= 0 or price >= 1:
            return {
                "kelly_f": 0.0,
                "quarter_kelly_f": 0.0,
                "stake": 0.0,
                "contracts": 0,
                "max_allowed": False,
                "size_multiplier": size_multiplier,
            }
        b = (1 - price) / price
        p = prob
        q = 1 - p
        full_kelly = (b * p - q) / b
        quarter_kelly = max(0.0, full_kelly * 0.25)
        desired_stake = quarter_kelly * bankroll

        # Confidence-based cap: 80+ = full QK, 60-79 = half, 40-59 = quarter
        if confidence_score >= 80.0:
            cap_fraction = config.MAX_TRADE_PCT
        elif confidence_score >= 60.0:
            cap_fraction = config.MAX_TRADE_PCT * 0.5
        else:
            cap_fraction = config.MAX_TRADE_PCT * 0.25
        max_stake = bankroll * cap_fraction
        stake = min(desired_stake, max_stake) * max(0.0, float(size_multiplier))
        contracts = int((stake + 1e-9) / price)
        if contracts <= 0 and stake >= price:
            contracts = 1
        actual_stake = contracts * price
        return {
            "kelly_f": full_kelly,
            "quarter_kelly_f": quarter_kelly,
            "stake": actual_stake,
            "contracts": contracts,
            "max_allowed": desired_stake > max_stake,
            "size_multiplier": float(size_multiplier),
        }

    def simulate_entry(
        self,
        signal: dict,
        current_price: Decimal,
        spread: Decimal,
        policy: Optional[PaperPolicyDecision] = None,
    ) -> dict:
        # Paper-policy diagnostics are research-guided controls, not live-
        # approved controls. They must be revalidated with forward paper data.
        policy = policy or paper_policy_allows_trade(signal)
        slippage = spread / Decimal("2") if config.SLIPPAGE_HALF_SPREAD else Decimal("0")
        effective_entry = current_price + slippage
        direction = signal.get("direction", "YES")
        model_prob_yes = float(signal.get("model_prob", 0.0))
        side_prob = model_prob_yes if direction == "YES" else 1.0 - model_prob_yes
        confidence = float(signal.get("confidence_score", 70.0))
        fixed_contracts = _fixed_contracts(signal)
        if fixed_contracts is not None:
            sizing = {
                "kelly_f": 0.0,
                "quarter_kelly_f": 0.0,
                "stake": fixed_contracts * float(effective_entry),
                "contracts": fixed_contracts,
                "max_allowed": False,
                "size_multiplier": float(policy.final_size_mult),
            }
        else:
            sizing = self.calculate_position_size(
                self.bankroll,
                side_prob,
                float(effective_entry),
                confidence_score=confidence,
                size_multiplier=policy.final_size_mult,
            )
        contracts = sizing["contracts"]
        if contracts <= 0:
            raise ValueError("signal produced zero-contract paper trade")
        maker_fee_entry = calculate_fees(contracts, float(effective_entry), "maker")
        taker_fee_entry = calculate_fees(contracts, float(effective_entry), "taker")
        now = datetime.now(UTC).isoformat()
        trade = {
            "signal_id": signal.get("id"),
            "city": signal["city"],
            "ticker": signal["ticker"],
            "target_date": signal.get("target_date"),
            "bracket": signal.get("bracket"),
            "direction": direction,
            "contracts": contracts,
            "stake_dollars": sizing["stake"],
            "entry_time": now,
            "entry_price": float(effective_entry),
            "taker_fee_entry": taker_fee_entry,
            "maker_fee_entry": maker_fee_entry,
            "slippage_estimate": float(slippage),
            "strategy_sleeve": signal.get("strategy_sleeve", "CORE_HGEFS_GUMBEL"),
            "target_price": signal.get("target_price"),
            "stop_price": signal.get("stop_price"),
            "never_hold_above": signal.get("never_hold_above"),
            "candidate_status": policy.candidate_status,
            "policy_reason": policy.policy_reason,
            "bracket_family": policy.bracket_family,
            "raw_edge_pp": policy.raw_edge_pp,
            "est_execution_cost_pp": policy.est_execution_cost_pp,
            "execution_margin_pp": policy.fee_margin_pp,
            "est_net_edge_pp": policy.est_net_edge_pp,
            "seasonal_mult": policy.seasonal_mult,
            "regime_mult": policy.regime_mult,
            "final_size_mult": policy.final_size_mult,
        }
        trade_id = self.db.insert_paper_trade(trade)
        trade["id"] = trade_id
        self.open_trades[trade_id] = trade
        self.bankroll -= sizing["stake"] + maker_fee_entry
        notify_phone("Paper trade entered", format_trade_entry(trade), priority="high", tags="chart_with_upwards_trend")
        return trade

    def _log_policy_candidate(self, signal: dict, policy: PaperPolicyDecision) -> None:
        """Best-effort paper-policy observability without touching live flow."""
        try:
            self.db.insert_candidate_signal(
                {
                    "city": signal.get("city", ""),
                    "ticker": signal.get("ticker", ""),
                    "target_date": signal.get("target_date"),
                    "bracket": signal.get("bracket"),
                    "strategy_sleeve": signal.get("strategy_sleeve", "CORE_HGEFS_GUMBEL"),
                    "direction": signal.get("direction"),
                    "yes_price": signal.get("market_price"),
                    "model_prob": signal.get("model_prob"),
                    "edge_pp": signal.get("gap_pp", policy.raw_edge_pp),
                    "gap_pp": signal.get("gap_pp", policy.raw_edge_pp),
                    "confidence_score": signal.get("confidence_score"),
                    "would_pass_core": int(policy.allowed),
                    "candidate_status": policy.candidate_status,
                    "policy_reason": policy.policy_reason,
                    "bracket_family": policy.bracket_family,
                    "raw_edge_pp": policy.raw_edge_pp,
                    "est_execution_cost_pp": policy.est_execution_cost_pp,
                    "est_net_edge_pp": policy.est_net_edge_pp,
                    "seasonal_mult": policy.seasonal_mult,
                    "regime_mult": policy.regime_mult,
                    "final_size_mult": policy.final_size_mult,
                    "execution_margin_pp": policy.fee_margin_pp,
                }
            )
        except Exception:
            # Candidate logging must never break paper-trade simulation.
            return

    def check_exits(self, current_prices: dict, dsm_detected: bool = False) -> None:
        for trade_id, trade in list(self.open_trades.items()):
            current_yes = current_prices.get(trade["ticker"])
            if current_yes is None:
                continue
            current_price = self.current_side_price(trade, current_yes)
            entry = float(trade["entry_price"])
            target_price = float(trade.get("target_price") or config.TARGET_EXIT_PRICE)
            sleeve = _canonical_sleeve(trade)
            stop_price = trade.get("stop_price")
            if stop_price is None:
                # DEEP_TAIL_NO: stops disabled — intraday swings on extreme-price
                # NO contracts trigger stops on correct trades before resolution.
                if sleeve == "DEEP_TAIL_NO" and getattr(config_paper, "PAPER_DEEP_TAIL_NO_STOP_DISABLED", False):
                    stop_price = -1.0  # unreachable
                else:
                    core_diff = getattr(config_paper, "PAPER_CORE_STOP_DIFF", float(config.STOP_LOSS_DIFF))
                    stop_price = max(0.0, entry - core_diff)
            else:
                stop_price = float(stop_price)
            never_hold_above = float(trade.get("never_hold_above") or config.NEVER_HOLD_ABOVE)
            reason = None
            exit_price = current_price
            direction = trade.get("direction", "YES")
            # Sleeves designed to hold through CLI settlement — DSM_CANCEL would
            # exit them 6 min before the confirmation they were entered to capture.
            _DSM_EXEMPT_SLEEVES = {"S3_BRACKET_LOCK_YES"}
            sleeve = _canonical_sleeve(trade)
            if dsm_detected and direction != "NO" and sleeve not in _DSM_EXEMPT_SLEEVES:
                today_str = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
                settlement = _settlement_date_from_ticker(trade.get("ticker", ""))
                if settlement is None or settlement <= today_str:
                    reason = "DSM_CANCEL"
            elif direction == "YES" and current_price >= never_hold_above:
                reason = "NEVER_HOLD_ABOVE"
                exit_price = never_hold_above
            elif current_price >= target_price and entry < target_price:
                reason = "TARGET"
                exit_price = target_price
            elif current_price <= stop_price:
                reason = "STOP"
            elif self._past_max_hold_time():
                reason = "TIME_LIMIT"
            if reason:
                self._exit_trade(trade_id, exit_price, reason)

    @staticmethod
    def current_side_price(trade: dict, current_yes_price: float) -> float:
        """Convert latest YES price into the side price for the held paper leg."""
        current_yes = float(current_yes_price)
        if trade.get("direction") == "NO":
            return round(max(0.0, min(1.0, 1.0 - current_yes)), 4)
        return current_yes

    def _past_max_hold_time(self) -> bool:
        now = datetime.now(ZoneInfo("America/New_York")).time()
        hour, minute = [int(x) for x in config.MAX_HOLD_TIME_ET.split(":")]
        return now.hour > hour or (now.hour == hour and now.minute >= minute)

    def _exit_trade(self, trade_id: int, exit_price: float, reason: str) -> None:
        trade = self.open_trades.pop(trade_id, None)
        if trade is None:
            logger.warning("_exit_trade called for unknown trade_id=%s (already closed?)", trade_id)
            return
        contracts = int(trade["contracts"])
        entry = float(trade["entry_price"])
        gross_pnl = (exit_price - entry) * contracts
        maker_fee_exit = calculate_fees(contracts, exit_price, "maker")
        taker_fee_exit = calculate_fees(contracts, exit_price, "taker")
        maker_total = float(trade.get("maker_fee_entry", 0.0)) + maker_fee_exit
        taker_total = float(trade.get("taker_fee_entry", 0.0)) + taker_fee_exit
        net_maker = gross_pnl - maker_total
        net_taker = gross_pnl - taker_total
        # Entry deducted stake + maker_fee_entry. Exit credits proceeds minus exit fee.
        self.bankroll += contracts * exit_price - maker_fee_exit
        self.db.execute_write(
            """
            UPDATE paper_trades
            SET exit_time = ?, exit_price = ?, exit_reason = ?, gross_pnl = ?,
                maker_fee_exit = ?, taker_fee_exit = ?,
                net_pnl_maker = ?, net_pnl_taker = ?
            WHERE id = ?
            """,
            (
                datetime.now(UTC).isoformat(),
                exit_price,
                reason,
                gross_pnl,
                maker_fee_exit,
                taker_fee_exit,
                net_maker,
                net_taker,
                trade_id,
            ),
        )
        notify_phone(
            "Paper trade exited",
            format_trade_exit(trade, exit_price, reason, net_maker),
            priority="high",
            tags="moneybag",
        )

    def settle_trade(self, trade: dict, settlement_temp_f: float) -> None:
        correct = self._direction_correct(trade, settlement_temp_f)
        self.db.execute_write(
            "UPDATE paper_trades SET settlement_temp_f = ?, settled_correct = ? WHERE id = ?",
            (settlement_temp_f, int(correct), trade["id"]),
        )
        # Remove from in-memory dict so a subsequent check_exits cannot re-exit it.
        self.open_trades.pop(int(trade["id"]), None)

    @staticmethod
    def _direction_correct(trade: dict, settlement_temp_f: float) -> bool:
        bracket = str(trade.get("bracket") or "")
        in_bracket = False
        if bracket.startswith(">="):
            in_bracket = settlement_temp_f >= float(bracket[2:].replace("F", ""))
        elif bracket.startswith("<="):
            in_bracket = settlement_temp_f <= float(bracket[2:].replace("F", ""))
        elif "-" in bracket:
            # Regex handles negative bounds like "-10--5F": matches optional-minus + digits.
            m = re.match(r"^(-?[\d]+(?:\.\d+)?)-(-?[\d]+(?:\.\d+)?)F?$", bracket)
            if m:
                in_bracket = float(m.group(1)) <= settlement_temp_f <= float(m.group(2))
        return in_bracket if trade.get("direction") == "YES" else not in_bracket

    def get_daily_pnl(self) -> float:
        # Use an explicit UTC window for today ET so trades at 8–11 PM ET
        # (which are UTC next-day) are not excluded from the daily risk limit.
        _ny = ZoneInfo("America/New_York")
        _today_et = datetime.now(_ny).date()
        _start = datetime.combine(_today_et, _time.min, tzinfo=_ny).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        _end = (datetime.combine(_today_et, _time.min, tzinfo=_ny) + _timedelta(days=1)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        rows = self.db.execute(
            "SELECT COALESCE(SUM(net_pnl_maker), 0) AS pnl FROM paper_trades WHERE created_at >= ? AND created_at < ?",
            (_start, _end),
        )
        return float(rows[0]["pnl"] or 0)

    def get_total_pnl(self) -> float:
        rows = self.db.execute("SELECT COALESCE(SUM(net_pnl_maker), 0) AS pnl FROM paper_trades")
        return float(rows[0]["pnl"] or 0)

    def get_win_rate(self) -> float:
        rows = self.db.execute(
            """
            SELECT
                SUM(CASE WHEN net_pnl_maker > 0 THEN 1 ELSE 0 END) AS wins,
                COUNT(*) AS total
            FROM paper_trades
            WHERE exit_time IS NOT NULL
            """
        )
        total = rows[0]["total"] or 0
        return float(rows[0]["wins"] or 0) / total if total else 0.0

    def get_sharpe(self) -> float:
        rows = self.db.execute(
            """
            SELECT net_pnl_maker FROM paper_trades
            WHERE exit_time IS NOT NULL AND net_pnl_maker IS NOT NULL
            """
        )
        values = [float(row["net_pnl_maker"]) for row in rows]
        if len(values) < 2:
            return 0.0
        import numpy as np

        std = float(np.std(values, ddof=1))
        return 0.0 if std == 0 else float(np.mean(values) / std)

    def enforce_risk_limits(self) -> bool:
        daily_loss = -min(0.0, self.get_daily_pnl())
        weekly_rows = self.db.execute(
            """
            SELECT COALESCE(SUM(net_pnl_maker), 0) AS pnl
            FROM paper_trades
            WHERE date(created_at) >= date('now', '-7 days')
            """
        )
        weekly_pnl = float(weekly_rows[0]["pnl"] or 0)
        weekly_loss = -min(0.0, weekly_pnl)
        return (
            daily_loss <= self.starting_bankroll * config.MAX_DAILY_LOSS_PCT
            and weekly_loss <= self.starting_bankroll * config.MAX_WEEKLY_LOSS_PCT
        )
