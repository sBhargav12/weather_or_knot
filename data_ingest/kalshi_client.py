from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests
import websockets
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

import config

logger = logging.getLogger(__name__)


def cents_to_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    return Decimal(str(value)) / Decimal("100")


def dollars_to_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    return Decimal(str(value))


class KalshiClient:
    """Kalshi REST client with RSA-PSS authentication."""

    def __init__(
        self,
        key_id: str,
        key_path: str,
        base_url: str = config.KALSHI_BASE_URL,
    ):
        self.key_id = key_id
        self.key_path = key_path
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self._private_key = None

    def _load_private_key(self):
        if self._private_key is not None:
            return self._private_key
        if not self.key_path:
            raise ValueError("KALSHI_KEY_PATH is not set")
        with open(Path(self.key_path).expanduser(), "rb") as f:
            self._private_key = serialization.load_pem_private_key(f.read(), password=None)
        return self._private_key

    def _sign_request(self, method: str, path: str) -> dict:
        if not self.key_id:
            raise ValueError("KALSHI_API_KEY is not set")
        private_key = self._load_private_key()
        ts = str(int(time.time() * 1000))
        msg = f"{ts}{method.upper()}{path}".encode()
        sig = private_key.sign(
            msg,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        sign_path = path if path.startswith("/trade-api/v2") else f"/trade-api/v2{path}"
        headers = self._sign_request("GET", sign_path)
        url = f"{self.base_url}{path}"
        response = self.session.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_balance(self) -> float:
        data = self._get("/portfolio/balance")
        return float(data.get("balance", 0))

    def get_active_markets(self, series: str) -> list:
        # Kalshi's current API uses "open" for tradable markets; older docs called
        # this "active". Keep the method name aligned with the pipeline plan.
        data = self._get("/markets", {"series_ticker": series, "status": "open", "limit": 200})
        return data.get("markets", [])

    def get_orderbook(self, ticker: str) -> dict:
        data = self._get(f"/markets/{ticker}/orderbook")
        return data.get("orderbook", {})

    def get_market_info(self, ticker: str) -> dict:
        data = self._get(f"/markets/{ticker}")
        return data.get("market", data)

    def get_candlesticks(self, ticker: str, period: str) -> list:
        data = self._get(f"/markets/{ticker}/candlesticks", {"period_interval": period})
        return data.get("candlesticks", [])

    def get_trades(self, ticker: str, limit: int = 100) -> list:
        data = self._get("/markets/trades", {"ticker": ticker, "limit": limit})
        return data.get("trades", [])

    def parse_brackets(self, markets: list) -> list:
        brackets = []
        for market in markets:
            yes_bid = cents_to_decimal(market.get("yes_bid")) or dollars_to_decimal(market.get("yes_bid_dollars"))
            no_bid = cents_to_decimal(market.get("no_bid")) or dollars_to_decimal(market.get("no_bid_dollars"))
            yes_last = cents_to_decimal(market.get("last_price")) or dollars_to_decimal(market.get("last_price_dollars"))
            yes_ask = cents_to_decimal(market.get("yes_ask")) or dollars_to_decimal(market.get("yes_ask_dollars"))
            no_ask = cents_to_decimal(market.get("no_ask")) or dollars_to_decimal(market.get("no_ask_dollars"))
            if yes_ask is None and no_bid is not None:
                yes_ask = Decimal("1.00") - no_bid
            if no_ask is None and yes_bid is not None:
                no_ask = Decimal("1.00") - yes_bid
            strike_lo = market.get("floor_strike")
            strike_hi = market.get("cap_strike")
            bracket_type = self._bracket_type(strike_lo, strike_hi)
            bracket_label = self._bracket_label(strike_lo, strike_hi, bracket_type)
            spread = yes_ask - yes_bid if yes_ask is not None and yes_bid is not None else None
            brackets.append(
                {
                    "ticker": market.get("ticker"),
                    "series_ticker": market.get("series_ticker"),
                    "target_date": self._date_from_ticker(market.get("ticker", "")),
                    "strike_lo": float(strike_lo) if strike_lo is not None else None,
                    "strike_hi": float(strike_hi) if strike_hi is not None else None,
                    "bracket_type": bracket_type,
                    "bracket_label": bracket_label,
                    "yes_bid": yes_bid,
                    "yes_ask": yes_ask,
                    "yes_last": yes_last,
                    "no_bid": no_bid,
                    "no_ask": no_ask,
                    "spread": spread,
                    "spread_cents": float(spread * 100) if spread is not None else None,
                    "volume": self._int_field(market.get("volume"), market.get("volume_fp"), market.get("volume_24h_fp")),
                    "open_interest": self._int_field(market.get("open_interest"), market.get("open_interest_fp")),
                    "raw": market,
                }
            )
        return brackets

    @staticmethod
    def _bracket_type(strike_lo: Any, strike_hi: Any) -> str:
        if strike_lo is None:
            return "wing_low"
        if strike_hi is None:
            return "wing_high"
        return "central"

    @staticmethod
    def _bracket_label(strike_lo: Any, strike_hi: Any, bracket_type: str) -> str:
        if bracket_type == "wing_low":
            return f"<={strike_hi}F"
        if bracket_type == "wing_high":
            return f">={strike_lo}F"
        return f"{strike_lo}-{strike_hi}F"

    @staticmethod
    def _date_from_ticker(ticker: str) -> Optional[str]:
        # KXHIGHNY-26APR25-T70 -> 2026-04-25
        try:
            _, yymmdd, _ = ticker.split("-", 2)
            year = 2000 + int(yymmdd[:2])
            month = {
                "JAN": 1,
                "FEB": 2,
                "MAR": 3,
                "APR": 4,
                "MAY": 5,
                "JUN": 6,
                "JUL": 7,
                "AUG": 8,
                "SEP": 9,
                "OCT": 10,
                "NOV": 11,
                "DEC": 12,
            }[yymmdd[2:5].upper()]
            day = int(yymmdd[5:])
            return f"{year:04d}-{month:02d}-{day:02d}"
        except Exception:
            return None

    @staticmethod
    def _int_field(*values: Any) -> Optional[int]:
        for value in values:
            if value is not None:
                try:
                    return int(Decimal(str(value)))
                except Exception:
                    continue
        return None


class KalshiWebSocket:
    """Read-only Kalshi WebSocket wrapper."""

    def __init__(self, key_id: str, key_path: str):
        self.client = KalshiClient(key_id, key_path)
        self.ws = None

    async def connect(self):
        headers = self.client._sign_request("GET", "/trade-api/ws/v2")
        self.ws = await websockets.connect(
            config.KALSHI_WS_URL,
            additional_headers=headers,
            ping_interval=20,
        )
        return self.ws

    async def subscribe(self, tickers: list):
        if self.ws is None:
            await self.connect()
        await self.ws.send(
            json.dumps(
                {
                    "id": 1,
                    "cmd": "subscribe",
                    "params": {
                        "channels": ["orderbook_delta"],
                        "market_tickers": tickers,
                    },
                }
            )
        )

    async def run(self, callback: Callable[[dict], Any]):
        if self.ws is None:
            await self.connect()
        async for raw in self.ws:
            msg = json.loads(raw)
            result = callback(msg)
            if asyncio.iscoroutine(result):
                await result
