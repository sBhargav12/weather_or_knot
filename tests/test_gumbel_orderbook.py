from __future__ import annotations

from decimal import Decimal

from kalshi_watcher.orderbook import KalshiOrderBook
from signal_engine.gumbel_model import GumbelModel


def test_gumbel_probability_range_and_nbm_blend():
    model = GumbelModel()
    prob = model.compute_bracket_prob(68, 70, 71.0, "range")
    assert 0.30 < prob < 0.40
    blended = model.bayesian_update_with_nbm(prob, 70.0, 62.0, 78.0, 68, 70)
    assert 0.0 < blended < 1.0


def test_gumbel_tails_are_bounded():
    model = GumbelModel()
    assert 0.0 <= model.compute_bracket_prob(None, 53, 55, "lower_tail") <= 1.0
    assert 0.0 <= model.compute_bracket_prob(75, None, 72, "upper_tail") <= 1.0


def test_orderbook_implied_asks_and_spread_are_decimal():
    book = KalshiOrderBook("T")
    book.apply_snapshot(
        {
            "seq": 1,
            "msg": {
                "yes_dollars_fp": [["0.42", "10"]],
                "no_dollars_fp": [["0.55", "12"]],
            },
        }
    )
    assert book.best_yes_bid == Decimal("0.42")
    assert book.best_no_bid == Decimal("0.55")
    assert book.yes_ask == Decimal("0.45")
    assert book.spread == Decimal("0.03")


def test_orderbook_delta_updates_levels():
    book = KalshiOrderBook("T")
    book.apply_snapshot({"seq": 1, "msg": {"yes_dollars_fp": [["0.40", "10"]], "no_dollars_fp": []}})
    book.apply_delta({"seq": 2, "msg": {"side": "yes", "price_dollars": "0.41", "delta_fp": "5"}})
    assert book.best_yes_bid == Decimal("0.41")
