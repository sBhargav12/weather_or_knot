from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Dict, Optional
from zoneinfo import ZoneInfo

import config
from data_store.db import Database


def calculate_fees(contracts: int, price: float, order_type: str = "maker") -> float:
    if order_type == "maker":
        return config.maker_fee(contracts, price)
    return config.taker_fee(contracts, price)


class PaperTrader:
    def __init__(self, starting_bankroll: float, db_path: str):
        self.bankroll = float(starting_bankroll)
        self.starting_bankroll = float(starting_bankroll)
        self.db = Database(db_path)
        self.open_trades: Dict[int, dict] = {}

    def on_signal(self, signal: dict) -> Optional[dict]:
        direction = signal.get("direction", "YES")
        yes_price = float(signal.get("market_price", signal.get("entry_price", 0)))
        side_price = yes_price if direction == "YES" else 1.0 - yes_price
        model_prob_yes = float(signal.get("model_prob", 0.0))
        side_prob = model_prob_yes if direction == "YES" else 1.0 - model_prob_yes
        sizing = self.calculate_position_size(self.bankroll, side_prob, side_price)
        if sizing["contracts"] <= 0:
            return None
        trade = self.simulate_entry(
            signal=signal,
            current_price=Decimal(str(side_price)),
            spread=Decimal(str(signal.get("spread", "0"))),
        )
        return trade

    def calculate_position_size(self, bankroll: float, prob: float, price: float) -> dict:
        if price <= 0 or price >= 1:
            return {
                "kelly_f": 0.0,
                "quarter_kelly_f": 0.0,
                "stake": 0.0,
                "contracts": 0,
                "max_allowed": False,
            }
        b = (1 - price) / price
        p = prob
        q = 1 - p
        full_kelly = (b * p - q) / b
        quarter_kelly = max(0.0, full_kelly * 0.25)
        desired_stake = quarter_kelly * bankroll
        max_stake = bankroll * config.MAX_TRADE_PCT
        stake = min(desired_stake, max_stake)
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
        }

    def simulate_entry(self, signal: dict, current_price: Decimal, spread: Decimal) -> dict:
        slippage = spread / Decimal("2") if config.SLIPPAGE_HALF_SPREAD else Decimal("0")
        effective_entry = current_price + slippage
        direction = signal.get("direction", "YES")
        model_prob_yes = float(signal.get("model_prob", 0.0))
        side_prob = model_prob_yes if direction == "YES" else 1.0 - model_prob_yes
        sizing = self.calculate_position_size(self.bankroll, side_prob, float(effective_entry))
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
        }
        trade_id = self.db.insert_paper_trade(trade)
        trade["id"] = trade_id
        self.open_trades[trade_id] = trade
        self.bankroll -= sizing["stake"] + maker_fee_entry
        return trade

    def check_exits(self, current_prices: dict, dsm_detected: bool = False) -> None:
        for trade_id, trade in list(self.open_trades.items()):
            current = current_prices.get(trade["ticker"])
            if current is None:
                continue
            current_price = float(current)
            entry = float(trade["entry_price"])
            reason = None
            exit_price = current_price
            if dsm_detected:
                reason = "DSM_CANCEL"
            elif current_price >= float(config.TARGET_EXIT_PRICE):
                reason = "TARGET"
                exit_price = float(config.TARGET_EXIT_PRICE)
            elif current_price <= max(0.0, entry - float(config.STOP_LOSS_DIFF)):
                reason = "STOP"
            elif self._past_max_hold_time():
                reason = "TIME_LIMIT"
            if reason:
                self._exit_trade(trade_id, exit_price, reason)

    def _past_max_hold_time(self) -> bool:
        now = datetime.now(ZoneInfo("America/New_York")).time()
        hour, minute = [int(x) for x in config.MAX_HOLD_TIME_ET.split(":")]
        return now.hour > hour or (now.hour == hour and now.minute >= minute)

    def _exit_trade(self, trade_id: int, exit_price: float, reason: str) -> None:
        trade = self.open_trades.pop(trade_id)
        contracts = int(trade["contracts"])
        entry = float(trade["entry_price"])
        gross_pnl = (exit_price - entry) * contracts
        maker_fee_exit = calculate_fees(contracts, exit_price, "maker")
        taker_fee_exit = calculate_fees(contracts, exit_price, "taker")
        maker_total = float(trade.get("maker_fee_entry", 0.0)) + maker_fee_exit
        taker_total = float(trade.get("taker_fee_entry", 0.0)) + taker_fee_exit
        net_maker = gross_pnl - maker_fee_exit
        net_taker = gross_pnl - taker_fee_exit
        self.bankroll += contracts * exit_price + net_maker
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
                gross_pnl - maker_total,
                gross_pnl - taker_total,
                trade_id,
            ),
        )

    def settle_trade(self, trade: dict, settlement_temp_f: float) -> None:
        correct = self._direction_correct(trade, settlement_temp_f)
        self.db.execute_write(
            "UPDATE paper_trades SET settlement_temp_f = ?, settled_correct = ? WHERE id = ?",
            (settlement_temp_f, int(correct), trade["id"]),
        )

    @staticmethod
    def _direction_correct(trade: dict, settlement_temp_f: float) -> bool:
        bracket = str(trade.get("bracket") or "")
        in_bracket = False
        if bracket.startswith(">="):
            in_bracket = settlement_temp_f >= float(bracket[2:].replace("F", ""))
        elif bracket.startswith("<="):
            in_bracket = settlement_temp_f <= float(bracket[2:].replace("F", ""))
        elif "-" in bracket:
            lo, hi = bracket.replace("F", "").split("-", 1)
            in_bracket = float(lo) <= settlement_temp_f <= float(hi)
        return in_bracket if trade.get("direction") == "YES" else not in_bracket

    def get_daily_pnl(self) -> float:
        rows = self.db.execute(
            """
            SELECT COALESCE(SUM(net_pnl_maker), 0) AS pnl
            FROM paper_trades
            WHERE date(created_at) = date('now')
            """
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
        return daily_loss <= self.starting_bankroll * config.MAX_DAILY_LOSS_PCT and weekly_loss <= self.starting_bankroll * config.MAX_WEEKLY_LOSS_PCT
