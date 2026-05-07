from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Dict, Optional
from zoneinfo import ZoneInfo

import config
from dashboard.notifications import format_trade_entry, format_trade_exit, notify_phone
from data_ingest.kalshi_client import KalshiClient
from data_store.db import Database
from live_trader import config_live
from paper_trader import config_paper as _cp
from paper_trader.policy import PaperPolicyDecision, paper_policy_allows_trade
from paper_trader.simulator import PaperTrader, calculate_fees

logger = logging.getLogger(__name__)


def _yes_price_cents(direction: str, side_price: float) -> int:
    """Convert side price to YES price in cents for the Kalshi order API.

    Kalshi always wants the YES price. For a NO buy at entry_price (NO cost),
    the YES price = 1 - entry_price.
    """
    if direction == "YES":
        return round(side_price * 100)
    return round((1.0 - side_price) * 100)


def _yes_price_cents_for_sell(direction: str, side_exit_price: float) -> int:
    """YES price in cents for a sell (close) order."""
    if direction == "YES":
        return round(side_exit_price * 100)
    # Selling NO: side_exit_price is the NO price we want to receive.
    # yes_price = 1 - no_price.
    return round((1.0 - side_exit_price) * 100)


class LiveTrader:
    """Places real Kalshi orders for CORE_HGEFS_EMOS signals.

    Sizing and policy reuse PaperTrader logic exactly. All live positions are
    tracked in the live_trades table alongside paper_trades for comparison.
    """

    def __init__(self, starting_bankroll: float, db_path: str, kalshi: KalshiClient):
        self.bankroll = float(starting_bankroll)
        self.starting_bankroll = float(starting_bankroll)
        self.db = Database(db_path)
        self.kalshi = kalshi
        # keyed by live_trade.id
        self.open_trades: Dict[int, dict] = {
            int(t["id"]): t for t in self.db.get_open_live_trades()
        }

    # ------------------------------------------------------------------
    # Entry
    # ------------------------------------------------------------------

    def on_signal(self, signal: dict) -> Optional[dict]:
        if config_live.LIVE_KILL_SWITCH:
            logger.warning("Live kill switch active — skipping signal %s", signal.get("ticker"))
            return None

        if signal.get("strategy_sleeve") != config_live.LIVE_SLEEVE:
            return None

        policy = paper_policy_allows_trade(signal)
        if not policy.allowed:
            return None

        if self._has_open_trade(signal):
            return None

        direction = signal.get("direction", "YES")
        side_price = float(signal.get("entry_price", signal.get("market_price", 0)))
        model_prob_yes = float(signal.get("model_prob", 0.0))
        side_prob = model_prob_yes if direction == "YES" else 1.0 - model_prob_yes
        confidence = float(signal.get("confidence_score", 50.0))

        # Apply same minimum confidence floor as CORE sleeve (EMOS is treated as CORE-equivalent for live).
        if confidence < float(_cp.PAPER_CORE_MIN_CONFIDENCE):
            return None

        sizing = PaperTrader.calculate_position_size(
            None,  # unbound call; doesn't use self
            self.bankroll,
            side_prob,
            side_price,
            confidence_score=confidence,
            size_multiplier=policy.final_size_mult,
        )
        if sizing["contracts"] <= 0:
            return None

        if side_price >= float(config.NEVER_HOLD_ABOVE):
            logger.warning(
                "Live signal %s rejected: entry %.2fc >= NEVER_HOLD_ABOVE %.2fc",
                signal.get("ticker"), side_price * 100, float(config.NEVER_HOLD_ABOVE) * 100,
            )
            return None

        return self._place_entry(signal, side_price, sizing, policy)

    def _place_entry(
        self,
        signal: dict,
        side_price: float,
        sizing: dict,
        policy: PaperPolicyDecision,
    ) -> Optional[dict]:
        direction = signal.get("direction", "YES")
        contracts = sizing["contracts"]
        yes_cents = _yes_price_cents(direction, side_price)
        client_id = str(uuid.uuid4())

        try:
            order = self.kalshi.place_order(
                ticker=signal["ticker"],
                side=direction.lower(),
                count=contracts,
                yes_price_cents=yes_cents,
                action="buy",
                client_order_id=client_id,
            )
        except Exception as exc:
            logger.error("Live order placement failed for %s: %s", signal.get("ticker"), exc)
            return None

        order_id = order.get("order_id") or order.get("id")
        order_status = order.get("status", "resting")
        filled_count = int(order.get("filled_count", 0) or 0)
        fill_price = float(order.get("yes_price", yes_cents) or yes_cents) / 100.0

        maker_fee_entry = calculate_fees(contracts, side_price, "maker")
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
            "entry_price": side_price,
            "order_id": order_id,
            "order_status": order_status,
            "filled_count": filled_count,
            "fill_price": fill_price if filled_count > 0 else None,
            "maker_fee_entry": maker_fee_entry,
            "slippage_estimate": 0.0,
            "strategy_sleeve": signal.get("strategy_sleeve", config_live.LIVE_SLEEVE),
            "candidate_status": policy.candidate_status,
            "policy_reason": policy.policy_reason,
            "raw_edge_pp": policy.raw_edge_pp,
            "est_net_edge_pp": policy.est_net_edge_pp,
            "seasonal_mult": policy.seasonal_mult,
            "regime_mult": policy.regime_mult,
            "final_size_mult": policy.final_size_mult,
        }

        trade_id = self.db.insert_live_trade(trade)
        trade["id"] = trade_id
        self.open_trades[trade_id] = trade

        logger.info(
            "Live order placed: %s %s x%d @ %.2fc (order_id=%s status=%s)",
            direction, signal["ticker"], contracts, yes_cents, order_id, order_status,
        )
        notify_phone(
            "Live order placed",
            format_trade_entry(trade),
            priority="high",
            tags="moneybag",
        )
        return trade

    # ------------------------------------------------------------------
    # Fill polling
    # ------------------------------------------------------------------

    def poll_fills(self) -> None:
        """Update fill status for all open live trades from Kalshi."""
        for trade_id, trade in list(self.open_trades.items()):
            order_id = trade.get("order_id")
            if not order_id:
                continue
            if trade.get("order_status") in ("filled", "canceled", "failed"):
                continue
            try:
                order = self.kalshi.get_order(order_id)
            except Exception as exc:
                logger.warning("Could not poll order %s: %s", order_id, exc)
                continue

            new_status = order.get("status", trade["order_status"])
            filled_count = int(order.get("filled_count", 0) or 0)
            avg_price = order.get("yes_price")
            fill_price = float(avg_price) / 100.0 if avg_price else trade.get("fill_price")

            updates: dict = {}
            if new_status != trade.get("order_status"):
                updates["order_status"] = new_status
            if filled_count != trade.get("filled_count", 0):
                updates["filled_count"] = filled_count
                if fill_price:
                    updates["fill_price"] = fill_price

            if updates:
                self.db.update_live_trade(trade_id, updates)
                trade.update(updates)
                logger.info(
                    "Fill update %s: status=%s filled=%d/%d",
                    trade["ticker"], new_status, filled_count, trade["contracts"],
                )

    # ------------------------------------------------------------------
    # Exits
    # ------------------------------------------------------------------

    def check_exits(self, current_prices: dict, dsm_detected: bool = False) -> None:
        for trade_id, trade in list(self.open_trades.items()):
            current_yes = current_prices.get(trade["ticker"])
            if current_yes is None:
                continue

            order_status = trade.get("order_status", "resting")
            filled_count = int(trade.get("filled_count", 0) or 0)
            entry = float(trade["entry_price"])
            direction = trade.get("direction", "YES")

            current_side = PaperTrader.current_side_price(trade, current_yes)

            reason = None
            exit_price = current_side

            if dsm_detected:
                reason = "DSM_CANCEL"
            elif current_side >= float(config.NEVER_HOLD_ABOVE):
                reason = "NEVER_HOLD_ABOVE"
                exit_price = float(config.NEVER_HOLD_ABOVE)
            elif current_side >= float(config.TARGET_EXIT_PRICE) and entry < float(config.TARGET_EXIT_PRICE):
                reason = "TARGET"
                exit_price = float(config.TARGET_EXIT_PRICE)
            elif current_side <= max(0.0, entry - float(config.STOP_LOSS_DIFF)):
                reason = "STOP"
            elif self._past_max_hold_time():
                reason = "TIME_LIMIT"

            if reason:
                self._exit_trade(trade_id, exit_price, reason, order_status, filled_count)

    def _exit_trade(
        self,
        trade_id: int,
        exit_price: float,
        reason: str,
        order_status: str,
        filled_count: int,
    ) -> None:
        trade = self.open_trades.pop(trade_id)
        direction = trade.get("direction", "YES")
        contracts = int(trade["contracts"])
        entry = float(trade["entry_price"])
        order_id = trade.get("order_id")

        # Cancel resting entry order if not yet filled.
        if order_id and order_status in ("resting", "pending", "partial"):
            try:
                self.kalshi.cancel_order(order_id)
                logger.info("Cancelled resting entry order %s (%s)", order_id, reason)
            except Exception as exc:
                logger.warning("Could not cancel order %s: %s", order_id, exc)

        actual_contracts = filled_count if filled_count > 0 else 0
        exit_order_id = None
        exit_order_status = "not_placed"

        # Place exit sell order for any filled contracts.
        if actual_contracts > 0:
            yes_cents = _yes_price_cents_for_sell(direction, exit_price)
            # Clamp to valid range.
            yes_cents = max(1, min(99, yes_cents))
            try:
                exit_order = self.kalshi.place_order(
                    ticker=trade["ticker"],
                    side=direction.lower(),
                    count=actual_contracts,
                    yes_price_cents=yes_cents,
                    action="sell",
                )
                exit_order_id = exit_order.get("order_id") or exit_order.get("id")
                exit_order_status = exit_order.get("status", "resting")
                logger.info(
                    "Exit sell order placed: %s x%d @ %.2fc (order_id=%s reason=%s)",
                    trade["ticker"], actual_contracts, yes_cents, exit_order_id, reason,
                )
            except Exception as exc:
                logger.error("Exit order failed for %s: %s", trade["ticker"], exc)
                exit_order_status = "failed"

        gross_pnl = (exit_price - entry) * actual_contracts if actual_contracts > 0 else 0.0
        maker_fee_exit = calculate_fees(actual_contracts, exit_price, "maker") if actual_contracts > 0 else 0.0
        maker_fee_entry = float(trade.get("maker_fee_entry", 0.0))
        net_pnl_maker = gross_pnl - maker_fee_entry - maker_fee_exit

        now = datetime.now(UTC).isoformat()
        self.db.update_live_trade(
            trade_id,
            {
                "exit_time": now,
                "exit_price": exit_price,
                "exit_reason": reason,
                "exit_order_id": exit_order_id,
                "exit_order_status": exit_order_status,
                "gross_pnl": gross_pnl,
                "maker_fee_exit": maker_fee_exit,
                "net_pnl_maker": net_pnl_maker,
                "order_status": "canceled" if actual_contracts == 0 else trade.get("order_status"),
            },
        )

        notify_phone(
            "Live trade exit",
            format_trade_exit(trade, exit_price, reason, net_pnl_maker),
            priority="high",
            tags="moneybag",
        )

    def cancel_all_open_orders(self) -> None:
        """Cancel all resting entry orders. Called at DSM cancel time."""
        for trade_id, trade in list(self.open_trades.items()):
            order_id = trade.get("order_id")
            if not order_id:
                continue
            if trade.get("order_status") not in ("resting", "pending"):
                continue
            try:
                self.kalshi.cancel_order(order_id)
                self.db.update_live_trade(trade_id, {"order_status": "canceled"})
                self.open_trades.pop(trade_id)
                logger.info("Cancelled open live order %s for %s", order_id, trade["ticker"])
            except Exception as exc:
                logger.warning("Could not cancel live order %s: %s", order_id, exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def current_side_price(trade: dict, current_yes_price: float) -> float:
        return PaperTrader.current_side_price(trade, current_yes_price)

    def _has_open_trade(self, signal: dict) -> bool:
        ticker = signal.get("ticker")
        direction = signal.get("direction", "YES")
        return any(
            t.get("ticker") == ticker and t.get("direction") == direction
            for t in self.open_trades.values()
        )

    @staticmethod
    def _past_max_hold_time() -> bool:
        now = datetime.now(ZoneInfo("America/New_York")).time()
        hour, minute = [int(x) for x in config.MAX_HOLD_TIME_ET.split(":")]
        return now.hour > hour or (now.hour == hour and now.minute >= minute)

    def settle_trade(self, trade: dict, settlement_temp_f: float) -> None:
        correct = PaperTrader._direction_correct(trade, settlement_temp_f)
        self.db.update_live_trade(
            int(trade["id"]),
            {"settlement_temp_f": settlement_temp_f, "settled_correct": int(correct)},
        )
