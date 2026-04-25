from __future__ import annotations

import os
from decimal import Decimal

import pytest

import config
from data_ingest.kalshi_client import KalshiClient, cents_to_decimal


def test_cents_to_decimal():
    assert cents_to_decimal(25) == Decimal("0.25")
    assert cents_to_decimal(None) is None


def test_auth_headers_when_key_available():
    if not (os.environ.get("KALSHI_API_KEY") and os.environ.get("KALSHI_KEY_PATH")):
        pytest.skip("Kalshi env vars not set")
    client = KalshiClient(os.environ["KALSHI_API_KEY"], os.environ["KALSHI_KEY_PATH"])
    headers = client._sign_request("GET", "/trade-api/v2/portfolio/balance")
    assert headers["KALSHI-ACCESS-KEY"] == os.environ["KALSHI_API_KEY"]
    assert headers["KALSHI-ACCESS-TIMESTAMP"].isdigit()
    assert headers["KALSHI-ACCESS-SIGNATURE"]


def test_parse_brackets_uses_decimal_and_implied_ask():
    client = KalshiClient("dummy", "dummy")
    brackets = client.parse_brackets(
        [
            {
                "ticker": "KXHIGHNY-26APR25-T70",
                "series_ticker": "KXHIGHNY",
                "yes_bid": 23,
                "no_bid": 74,
                "last_price": 24,
                "floor_strike": 70,
                "cap_strike": None,
                "volume": 100,
            }
        ]
    )
    bracket = brackets[0]
    assert bracket["yes_bid"] == Decimal("0.23")
    assert bracket["yes_ask"] == Decimal("0.26")
    assert bracket["spread"] == Decimal("0.03")
    assert bracket["target_date"] == "2026-04-25"


def test_fee_calculations_are_ceiling_rounded():
    assert config.maker_fee(1, 0.50) == 0.01
    assert config.taker_fee(1, 0.50) == 0.02
