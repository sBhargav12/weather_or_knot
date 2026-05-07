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
        markets: list = []
        cursor: str | None = None
        while True:
            params = {"series_ticker": series, "status": "open", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            data = self._get("/markets", params)
            markets.extend(data.get("markets", []))
            cursor = data.get("cursor")
            if not cursor:
                return markets

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

    def _post(self, path: str, body: dict) -> dict:
        sign_path = path if path.startswith("/trade-api/v2") else f"/trade-api/v2{path}"
        headers = self._sign_request("POST", sign_path)
        url = f"{self.base_url}{path}"
        response = self.session.post(url, headers=headers, json=body, timeout=30)
        response.raise_for_status()
        return response.json()

    def _delete(self, path: str) -> dict:
        sign_path = path if path.startswith("/trade-api/v2") else f"/trade-api/v2{path}"
        headers = self._sign_request("DELETE", sign_path)
        url = f"{self.base_url}{path}"
        response = self.session.delete(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def place_order(
        self,
        ticker: str,
        side: str,
        count: int,
        yes_price_cents: int,
        action: str = "buy",
        client_order_id: str | None = None,
    ) -> dict:
        """Place a limit order. yes_price_cents is 1-99 (always the YES side price)."""
        body: dict = {
            "ticker": ticker,
            "type": "limit",
            "action": action,
            "side": side.lower(),
            "count": count,
            "yes_price": yes_price_cents,
            "expiration_ts": 0,
        }
        if client_order_id:
            body["client_order_id"] = client_order_id
        data = self._post("/portfolio/orders", body)
        return data.get("order", data)

    def cancel_order(self, order_id: str) -> dict:
        data = self._delete(f"/portfolio/orders/{order_id}")
        return data.get("order", data)

    def get_order(self, order_id: str) -> dict:
        data = self._get(f"/portfolio/orders/{order_id}")
        return data.get("order", data)

    def get_open_orders(self, ticker: str | None = None) -> list:
        params: dict = {"status": "resting"}
        if ticker:
            params["ticker"] = ticker
        data = self._get("/portfolio/orders", params)
        return data.get("orders", [])

    def parse_brackets(self, markets: list) -> list:
        brackets = []
        for market in markets:
            # Use explicit None-check instead of `or` so that Decimal("0") (empty book,
            # bid=0) is not treated as falsy and incorrectly replaced with the _dollars field.
            def _coalesce(cents_val: Any, dollars_val: Any) -> Optional[Decimal]:
                v = cents_to_decimal(cents_val)
                return v if v is not None else dollars_to_decimal(dollars_val)

            yes_bid = _coalesce(market.get("yes_bid"), market.get("yes_bid_dollars"))
            no_bid = _coalesce(market.get("no_bid"), market.get("no_bid_dollars"))
            yes_last = _coalesce(market.get("last_price"), market.get("last_price_dollars"))
            yes_ask = _coalesce(market.get("yes_ask"), market.get("yes_ask_dollars"))
            no_ask = _coalesce(market.get("no_ask"), market.get("no_ask_dollars"))
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
            return f"<{strike_hi}F"  # Kalshi settles strictly less than cap_strike
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
        """Run the WebSocket loop with automatic reconnect on any error."""
        backoff = 1
        while True:
            try:
                if self.ws is None:
                    await self.connect()
                async for raw in self.ws:
                    msg = json.loads(raw)
                    result = callback(msg)
                    if asyncio.iscoroutine(result):
                        await result
                # Clean server-side close — reconnect
                logger.info("KalshiWebSocket: server closed connection, reconnecting in %ss", backoff)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("KalshiWebSocket error: %s. Reconnecting in %ss", exc, backoff)
            finally:
                self.ws = None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
