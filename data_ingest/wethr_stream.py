from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable, Optional

import aiohttp

logger = logging.getLogger(__name__)

_STREAM_URL = "https://wethr.net:3443/api/v2/stream"
_RECONNECT_DELAY_S = 30
_REFRESH_HINT_DEFAULT_S = 400


class WethrStreamClient:
    """SSE Push API client for wethr.net Pro tier.

    Subscribes to new_high, new_low, cli, dsm, and observation events.
    Reconnects automatically on disconnect. maxConnections=1 on Pro tier —
    subscribe all active stations in a single connection.
    """

    def __init__(self, api_key: str, stations: list[str]):
        self.api_key = api_key
        self.stations = stations
        self._on_new_high: Optional[Callable] = None
        self._on_new_low: Optional[Callable] = None
        self._on_cli: Optional[Callable] = None
        self._on_dsm: Optional[Callable] = None
        self._on_observation: Optional[Callable] = None
        self._last_event_id: Optional[str] = None
        self._refresh_hint_s: int = _REFRESH_HINT_DEFAULT_S
        self._connected = False

    def register_new_high(self, callback: Callable) -> None:
        self._on_new_high = callback

    def register_new_low(self, callback: Callable) -> None:
        self._on_new_low = callback

    def register_cli(self, callback: Callable) -> None:
        self._on_cli = callback

    def register_dsm(self, callback: Callable) -> None:
        self._on_dsm = callback

    def register_observation(self, callback: Callable) -> None:
        self._on_observation = callback

    def is_connected(self) -> bool:
        return self._connected

    async def run_forever(self) -> None:
        while True:
            try:
                await self._stream_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("WethrStream disconnected: %s — reconnecting in %ds", exc, _RECONNECT_DELAY_S)
            self._connected = False
            await asyncio.sleep(_RECONNECT_DELAY_S)

    async def _stream_once(self) -> None:
        params: dict = {
            "api_key": self.api_key,
            "stations": ",".join(self.stations),
        }
        if self._last_event_id:
            params["last_event_id"] = self._last_event_id

        timeout = aiohttp.ClientTimeout(connect=15, sock_read=self._refresh_hint_s + 60)
        connector = aiohttp.TCPConnector(ssl=True)
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with session.get(_STREAM_URL, params=params) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"Push API returned {resp.status}: {body[:200]}")

                logger.info("WethrStream connected (stations=%s)", self.stations)
                self._connected = True

                event_type = "message"
                data_lines: list[str] = []

                async for raw in resp.content:
                    line = raw.decode().rstrip("\r\n")

                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                    elif line.startswith("id:"):
                        self._last_event_id = line[3:].strip()
                    elif line == "":
                        # End of event block
                        if data_lines:
                            raw_data = " ".join(data_lines)
                            try:
                                payload = json.loads(raw_data)
                            except json.JSONDecodeError:
                                payload = {"raw": raw_data}
                            await self._dispatch(event_type, payload)
                        event_type = "message"
                        data_lines = []

    async def _dispatch(self, event_type: str, payload: dict) -> None:
        try:
            if event_type == "connected":
                hint = payload.get("refreshHint")
                if hint:
                    self._refresh_hint_s = int(hint) // 1000
                logger.info(
                    "WethrStream handshake: tier=%s stations=%s maxConn=%s",
                    payload.get("tier"),
                    payload.get("stations"),
                    payload.get("maxConnections"),
                )

            elif event_type == "heartbeat":
                logger.debug("WethrStream heartbeat %s", payload.get("timestamp"))

            elif event_type == "new_high" and self._on_new_high:
                station = payload.get("station_code") or payload.get("station")
                high_f = payload.get("high_f") or payload.get("wethr_high") or payload.get("value")
                ts = payload.get("timestamp") or payload.get("observation_time")
                if station and high_f is not None:
                    logger.info("WethrStream new_high %s=%.1f°F", station, float(high_f))
                    await self._maybe_await(self._on_new_high, station, float(high_f), ts, payload)

            elif event_type == "new_low" and self._on_new_low:
                station = payload.get("station_code") or payload.get("station")
                low_f = payload.get("low_f") or payload.get("wethr_low") or payload.get("value")
                ts = payload.get("timestamp") or payload.get("observation_time")
                if station and low_f is not None:
                    await self._maybe_await(self._on_new_low, station, float(low_f), ts, payload)

            elif event_type == "cli" and self._on_cli:
                station = payload.get("station_code") or payload.get("station")
                cli_high = payload.get("cli_high_f") or payload.get("cli_high")
                cli_low = payload.get("cli_low_f") or payload.get("cli_low")
                ts = payload.get("timestamp") or payload.get("observation_time")
                logger.info("WethrStream CLI %s: high=%s low=%s", station, cli_high, cli_low)
                await self._maybe_await(self._on_cli, station, cli_high, cli_low, ts, payload)

            elif event_type == "dsm" and self._on_dsm:
                station = payload.get("station_code") or payload.get("station")
                dsm_high = payload.get("dsm_high_f") or payload.get("dsm_high")
                ts = payload.get("timestamp") or payload.get("dsm_received_at")
                logger.info("WethrStream DSM %s: high=%s", station, dsm_high)
                await self._maybe_await(self._on_dsm, station, dsm_high, ts, payload)

            elif event_type == "observation" and self._on_observation:
                station = payload.get("station_code") or payload.get("station")
                await self._maybe_await(self._on_observation, station, payload)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("WethrStream dispatch error for %s: %s", event_type, exc)

    @staticmethod
    async def _maybe_await(fn: Optional[Callable], *args) -> None:
        if fn is None:
            return
        import inspect
        if inspect.iscoroutinefunction(fn):
            await fn(*args)
        else:
            fn(*args)
