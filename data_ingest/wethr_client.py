from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests

import config

logger = logging.getLogger(__name__)


class WethrClient:
    """wethr.net Pro REST API client."""

    def __init__(self, api_key: str, base_url: str = config.WETHR_BASE_URL):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        if api_key:
            self.session.headers.update({"Authorization": f"Bearer {api_key}"})
        self._last_nws_versions: Dict[str, int] = {}
        self._last_request_at = 0.0

    def _get(self, endpoint: str, params: Optional[dict] = None) -> Any:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        last_exc: Optional[Exception] = None
        for attempt in range(3):
            try:
                elapsed = time.monotonic() - self._last_request_at
                if elapsed < 1.05:
                    time.sleep(1.05 - elapsed)
                logger.debug("wethr GET %s params=%s", url, params)
                response = self.session.get(url, params=params, timeout=30)
                self._last_request_at = time.monotonic()
                if response.status_code == 429 and attempt < 2:
                    retry_after = float(response.headers.get("Retry-After", "5"))
                    time.sleep(max(retry_after, 5.0))
                    continue
                response.raise_for_status()
                data = response.json()
                logger.debug("wethr response %s", data)
                return data
            except Exception as exc:  # requests exceptions plus JSON decode
                last_exc = exc
                if attempt < 2:
                    time.sleep(5)
        raise RuntimeError(f"wethr request failed for {url}: {last_exc}")

    @staticmethod
    def celsius_to_fahrenheit(c: Optional[float]) -> Optional[float]:
        if c is None:
            return None
        return float(c) * 9 / 5 + 32

    def _add_temp_f(self, payload: dict) -> dict:
        if "temperature" in payload and payload.get("temperature") is not None:
            payload = dict(payload)
            payload["temperature_f"] = self.celsius_to_fahrenheit(float(payload["temperature"]))
        return payload

    def get_latest_obs(self, station: str) -> dict:
        data = self._get("observations.php", {"station_code": station, "mode": "latest"})
        return self._add_temp_f(data) if isinstance(data, dict) else data

    def get_wethr_high(self, station: str, logic: str = "nws") -> dict:
        return self._get(
            "observations.php",
            {"station_code": station, "mode": "wethr_high", "logic": logic},
        )

    def get_dsm_high(self, station: str) -> dict:
        return self._get(
            "observations.php",
            {"station_code": station, "mode": "latest", "observation_type": "dsm_high"},
        )

    def get_cli_high(self, station: str) -> dict:
        return self._get(
            "observations.php",
            {"station_code": station, "mode": "latest", "observation_type": "cli_high"},
        )

    def get_history(self, station: str, start_time: str, end_time: str) -> list:
        if not start_time or not end_time:
            raise ValueError("wethr history requires both start_time and end_time")
        data = self._get(
            "observations.php",
            {
                "station_code": station,
                "mode": "history",
                "start_time": start_time,
                "end_time": end_time,
            },
        )
        return data if isinstance(data, list) else []

    def get_forecast(self, station: str, model: str, run: str = "latest") -> list:
        data = self._get(
            "forecasts.php",
            {"location_name": station, "model": model, "run": run},
        )
        return data if isinstance(data, list) else []

    def get_forecast_maxt(self, station: str, model: str, target_date_et: str) -> Optional[float]:
        rows = self.get_forecast(station, model, run="latest")
        if not rows:
            return None
        city_cfg = config.CITIES.get(station, {})
        tz = ZoneInfo(city_cfg.get("timezone", "America/New_York"))
        target_date = datetime.strptime(target_date_et, "%Y-%m-%d").date()
        values: List[float] = []
        for row in rows:
            valid_raw = row.get("valid_time")
            temp_raw = row.get("temperature_f")
            if not valid_raw or temp_raw in (None, ""):
                continue
            valid_utc = datetime.fromisoformat(str(valid_raw).replace("Z", "+00:00"))
            if valid_utc.tzinfo is None:
                valid_utc = valid_utc.replace(tzinfo=ZoneInfo("UTC"))
            valid_local = valid_utc.astimezone(tz)
            if valid_local.date() == target_date:
                values.append(float(temp_raw))
        return max(values) if values else None

    def get_nws_evolution(self, station: str) -> dict:
        data = self._get("nws_forecasts.php", {"station_code": station})
        if isinstance(data, dict) and "version" in data:
            self._last_nws_versions[station] = int(data["version"])
        return data

    def nws_version_incremented(self, station: str, version: int) -> bool:
        old = self._last_nws_versions.get(station)
        self._last_nws_versions[station] = version
        return old is not None and version > old

    def get_all_models_maxt(self, station: str, target_date_et: str) -> dict:
        result = {}
        for model in ["HRRR", "NBM", "GFS", "ECMWF", "NAM", "ICON", "UKMO", "ARPEGE", "JMA"]:
            try:
                maxt = self.get_forecast_maxt(station, model, target_date_et)
                if maxt is not None:
                    result[model] = maxt
            except Exception as exc:
                logger.warning("wethr %s MaxT unavailable for %s: %s", model, station, exc)
        return result
