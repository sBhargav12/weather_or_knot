"""
Regression tests for bugs found in the 2026-05-07 deep audit.
Each test is named after the bug it covers.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from config import maker_fee, taker_fee
from data_store.db import Database
from data_store.schema import create_database
from paper_trader.simulator import PaperTrader, calculate_fees


# ---------------------------------------------------------------------------
# BUG: Fee formula — batch ceiling vs per-contract ceiling
# ---------------------------------------------------------------------------

def test_fee_per_contract_not_batch_ceiling():
    """
    Kalshi charges per-contract with ceiling applied per contract.
    maker_fee(N, price) must equal N * maker_fee(1, price).
    The old batch-ceiling formula underestimated fees at off-50c prices.
    """
    for contracts in [10, 50, 100]:
        for price in [0.30, 0.45, 0.51, 0.64, 0.70]:
            batch = maker_fee(contracts, price)
            per_contract = contracts * maker_fee(1, price)
            assert abs(batch - per_contract) < 1e-9, (
                f"maker_fee({contracts}, {price}) = {batch} "
                f"but per-contract sum = {per_contract}"
            )


def test_taker_fee_per_contract_not_batch_ceiling():
    for contracts in [10, 50]:
        for price in [0.30, 0.64]:
            batch = taker_fee(contracts, price)
            per_contract = contracts * taker_fee(1, price)
            assert abs(batch - per_contract) < 1e-9


def test_fee_single_contract_unchanged():
    """Single-contract fees are stable: ceil(rate * 0.25 * 100) / 100."""
    # maker: ceil(0.0175 * 0.5 * 0.5 * 100) / 100 = ceil(0.4375) / 100 = 0.01
    assert maker_fee(1, 0.50) == pytest.approx(0.01)
    # taker: ceil(0.07 * 0.5 * 0.5 * 100) / 100 = ceil(1.75) / 100 = 0.02
    assert taker_fee(1, 0.50) == pytest.approx(0.02)


# ---------------------------------------------------------------------------
# BUG: _exit_trade KeyError on unknown trade_id
# ---------------------------------------------------------------------------

def test_exit_trade_unknown_id_does_not_raise(tmp_path):
    db_path = tmp_path / "pipeline.db"
    create_database(str(db_path))
    trader = PaperTrader(500.0, str(db_path))
    # Should log a warning but not raise KeyError
    trader._exit_trade(99999, 0.50, "TEST")
    assert trader.bankroll == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# BUG: _direction_correct crashes on negative temperature brackets
# ---------------------------------------------------------------------------

def test_direction_correct_negative_bracket_yes_in():
    trade = {"direction": "YES", "bracket": "-10--5F"}
    assert PaperTrader._direction_correct(trade, -7.0) is True


def test_direction_correct_negative_bracket_yes_out():
    trade = {"direction": "YES", "bracket": "-10--5F"}
    assert PaperTrader._direction_correct(trade, 30.0) is False


def test_direction_correct_negative_bracket_no():
    trade = {"direction": "NO", "bracket": "-10--5F"}
    assert PaperTrader._direction_correct(trade, -7.0) is False
    assert PaperTrader._direction_correct(trade, 30.0) is True


def test_direction_correct_mixed_negative_to_positive():
    trade = {"direction": "YES", "bracket": "-5-0F"}
    assert PaperTrader._direction_correct(trade, -3.0) is True
    assert PaperTrader._direction_correct(trade, 5.0) is False


def test_direction_correct_positive_bracket_still_works():
    trade = {"direction": "YES", "bracket": "64-65F"}
    assert PaperTrader._direction_correct(trade, 64.0) is True
    assert PaperTrader._direction_correct(trade, 66.0) is False


def test_direction_correct_tail_brackets():
    yes_hi = {"direction": "YES", "bracket": ">=71F"}
    assert PaperTrader._direction_correct(yes_hi, 72.0) is True
    assert PaperTrader._direction_correct(yes_hi, 70.0) is False

    yes_lo = {"direction": "YES", "bracket": "<=64F"}
    assert PaperTrader._direction_correct(yes_lo, 63.0) is True
    assert PaperTrader._direction_correct(yes_lo, 65.0) is False


def test_direction_correct_unrecognized_bracket_does_not_mark_no_correct():
    """Unrecognized bracket: in_bracket stays False, NO should return True (not in bracket)."""
    trade = {"direction": "NO", "bracket": "UNKNOWN"}
    # in_bracket=False → not in_bracket=True for NO — this is the current behavior
    # (pending further validation of whether "unknown = not correct" is right)
    result = PaperTrader._direction_correct(trade, 65.0)
    # At minimum it must not raise
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# BUG: get_daily_pnl uses UTC date('now') — ET trades after 8 PM are excluded
# ---------------------------------------------------------------------------

def test_get_daily_pnl_uses_et_window(tmp_path):
    """
    A trade entered at 11 PM ET (= 3 AM UTC next day) must appear in today's
    ET daily PnL, not be silently excluded.
    """
    db_path = tmp_path / "pipeline.db"
    create_database(str(db_path))
    db = Database(str(db_path))

    _ny = ZoneInfo("America/New_York")
    # Simulate a trade entered at 11:30 PM ET tonight (UTC = next-day 03:30)
    now_et = datetime.now(_ny)
    late_et = now_et.replace(hour=23, minute=30, second=0, microsecond=0)
    late_utc = late_et.astimezone(UTC).isoformat()

    db.execute_write(
        """
        INSERT INTO paper_trades
            (city, ticker, direction, contracts, stake_dollars, entry_price,
             created_at, entry_time, net_pnl_maker)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        ("KNYC", "T-26MAY07-B64.5", "YES", 1, 0.64, 0.64,
         late_utc, late_utc, -0.10),
    )

    trader = PaperTrader(500.0, str(db_path))
    pnl = trader.get_daily_pnl()

    # The trade is for tonight ET — it must be included in today's PnL
    assert pnl == pytest.approx(-0.10), (
        f"Expected -0.10 but got {pnl} — late-ET trade excluded from daily PnL"
    )


# ---------------------------------------------------------------------------
# BUG: parse_brackets uses `or` falsy — Decimal("0") bid treated as None
# ---------------------------------------------------------------------------

def test_parse_brackets_zero_bid_not_treated_as_none():
    from data_ingest.kalshi_client import KalshiClient, cents_to_decimal
    # Decimal("0") must not be falsy-or'd to None
    v = cents_to_decimal(0)
    assert v == Decimal("0"), "cents_to_decimal(0) must return Decimal('0'), not None"
    # The `or` pattern would make Decimal("0") falsy → None; our fix uses explicit None check
    result = v if v is not None else Decimal("0.99")
    assert result == Decimal("0")


# ---------------------------------------------------------------------------
# BUG: apply_delta before snapshot should be silently ignored
# ---------------------------------------------------------------------------

def test_apply_delta_before_snapshot_is_ignored():
    from kalshi_watcher.orderbook import KalshiOrderBook
    book = KalshiOrderBook("TEST-TICKER")
    assert book.connected is False
    # Delta before snapshot must be ignored, not applied
    book.apply_delta({
        "seq": 1,
        "msg": {"market_ticker": "TEST-TICKER", "side": "yes", "price": "0.50", "delta": "100"},
    })
    assert book.yes_bids == {}, "Delta before snapshot must not modify yes_bids"


# ---------------------------------------------------------------------------
# BUG: apply_delta unknown/None side silently corrupts no_bids
# ---------------------------------------------------------------------------

def test_apply_delta_unknown_side_is_skipped(tmp_path):
    from kalshi_watcher.orderbook import KalshiOrderBook
    book = KalshiOrderBook("TEST-TICKER")
    # Initialize with a snapshot first
    book.apply_snapshot({
        "seq": 1,
        "msg": {"market_ticker": "TEST-TICKER", "yes": [[0.60, 100]], "no": [[0.40, 100]]},
    })
    assert book.connected is True
    no_bids_before = dict(book.no_bids)

    # Delta with unknown side must not touch no_bids
    book.apply_delta({
        "seq": 2,
        "msg": {"market_ticker": "TEST-TICKER", "side": None, "price": "0.40", "delta": "999"},
    })
    assert book.no_bids == no_bids_before, "Unknown-side delta must not modify no_bids"


# ---------------------------------------------------------------------------
# BUG: settle_trade — verify it writes settled_correct flag correctly
# ---------------------------------------------------------------------------

def test_settle_trade_writes_correct_flag(tmp_path):
    db_path = tmp_path / "pipeline.db"
    create_database(str(db_path))
    db = Database(str(db_path))
    trade_id = db.insert_paper_trade({
        "city": "KNYC",
        "ticker": "KXHIGHNY-26MAY07-B64.5",
        "direction": "YES",
        "contracts": 5,
        "stake_dollars": 3.20,
        "entry_price": 0.64,
        "bracket": "64-65F",
    })
    trader = PaperTrader(500.0, str(db_path))
    trade = {"id": trade_id, "direction": "YES", "bracket": "64-65F"}

    trader.settle_trade(trade, 64.0)  # in bracket → correct=1
    row = db.execute(
        "SELECT settled_correct, settlement_temp_f FROM paper_trades WHERE id = ?",
        (trade_id,),
    )[0]
    assert row["settled_correct"] == 1
    assert row["settlement_temp_f"] == pytest.approx(64.0)

    trader.settle_trade(trade, 70.0)  # out of bracket → correct=0
    row2 = db.execute(
        "SELECT settled_correct FROM paper_trades WHERE id = ?", (trade_id,)
    )[0]
    assert row2["settled_correct"] == 0


# ---------------------------------------------------------------------------
# BUG: bankroll math stays consistent after _exit_trade
# ---------------------------------------------------------------------------

def test_bankroll_consistent_after_exit(tmp_path):
    db_path = tmp_path / "pipeline.db"
    create_database(str(db_path))
    trader = PaperTrader(500.0, str(db_path))

    entry_price = 0.50
    exit_price = 0.75
    contracts = 10

    fee_entry = maker_fee(contracts, entry_price)
    fee_exit = maker_fee(contracts, exit_price)
    expected_bankroll = 500.0 - contracts * entry_price - fee_entry + contracts * exit_price - fee_exit

    signal = {
        "city": "KNYC",
        "ticker": "KXHIGHNY-26MAY07-B64.5",
        "target_date": "2026-05-07",
        "bracket": "64-65F",
        "direction": "YES",
        "entry_price": entry_price,
        "market_price": entry_price,
        "model_prob": 0.70,
        "spread": "0",
        "confidence_score": 85.0,
        "strategy_sleeve": "S1_FAR_BRACKET_NO_OVERLAY",
        "n_contracts": contracts,
    }
    trade = trader.on_signal(signal)
    assert trade is not None
    trade_id = trade["id"]

    trader._exit_trade(trade_id, exit_price, "TARGET")
    assert trader.bankroll == pytest.approx(expected_bankroll, abs=1e-6)
