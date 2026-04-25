from __future__ import annotations

import logging
import os
import tempfile
from datetime import UTC, datetime
from typing import Dict, Optional

import numpy as np
import requests

import config

logger = logging.getLogger(__name__)


class ModelFetcher:
    """Fetch HGEFS GRIB slices and NBM probabilistic text bulletins."""

    def __init__(self, hgefs_base: str = config.NOMADS_HGEFS_BASE, nbm_base: str = config.NOMADS_NBM_BASE):
        self.hgefs_base = hgefs_base.rstrip("/")
        self.nbm_base = nbm_base.rstrip("/")
        self.session = requests.Session()

    def check_new_hgefs_cycle(self, current_cycle: Optional[str] = None, date_str: Optional[str] = None) -> Optional[str]:
        if date_str is None:
            date_str = datetime.now(UTC).strftime("%Y%m%d")
        for cycle in ["18", "12", "06", "00"]:
            if cycle == current_cycle:
                return None
            url = f"{self.hgefs_base}/hgefs.{date_str}/{cycle}/"
            try:
                response = self.session.get(url, timeout=20)
                if response.status_code == 200 and "hgefs" in response.text:
                    return cycle
            except Exception as exc:
                logger.debug("HGEFS cycle check failed for %s: %s", url, exc)
        return None

    def get_hgefs_file_url(self, date_str: str, cycle: str, member: str, fhr: int) -> str:
        return f"{self.hgefs_base}/hgefs.{date_str}/{cycle}/ensstat/products/atmos/grib2/hgefs.t{cycle}z.sfc.avg.f{fhr:03d}.grib2"

    def get_gefs_file_url(self, date_str: str, cycle: str, member: str, fhr: int) -> str:
        gefs_base = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/gefs/prod"
        gefs_member = "gec00" if member == "c00" else f"gep{int(member[1:]):02d}"
        return (
            f"{gefs_base}/gefs.{date_str}/{cycle}/atmos/pgrb2sp25/"
            f"{gefs_member}.t{cycle}z.pgrb2s.0p25.f{fhr:03d}"
        )

    def get_aigefs_file_url(self, date_str: str, cycle: str, member_index: int, fhr: int) -> str:
        aigefs_base = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/aigefs/prod"
        return (
            f"{aigefs_base}/aigefs.{date_str}/{cycle}/mem{member_index:03d}/model/atmos/grib2/"
            f"aigefs.t{cycle}z.sfc.f{fhr:03d}.grib2"
        )

    def get_byte_range(self, url: str, variable: str = "TMAX") -> Optional[bytes]:
        idx_url = f"{url}.idx"
        idx_response = self.session.get(idx_url, timeout=30)
        idx_response.raise_for_status()
        idx_lines = idx_response.text.splitlines()
        start_byte = None
        end_byte = None
        for i, line in enumerate(idx_lines):
            if f":{variable}:" in line and ":2 m above ground:" in line and ":max fcst:" in line:
                start_byte = int(line.split(":")[1])
                if i + 1 < len(idx_lines):
                    end_byte = int(idx_lines[i + 1].split(":")[1]) - 1
                break
        if start_byte is None:
            return None
        range_header = f"bytes={start_byte}-{end_byte}" if end_byte else f"bytes={start_byte}-"
        response = self.session.get(url, headers={"Range": range_header}, timeout=60)
        response.raise_for_status()
        return response.content

    def extract_maxt_at_point(self, grib_bytes: bytes, lat: float, lon_360: float) -> float:
        try:
            import xarray as xr
        except ImportError as exc:
            raise RuntimeError("xarray/cfgrib/eccodes are required for HGEFS extraction") from exc

        with tempfile.NamedTemporaryFile(suffix=".grib2", delete=False) as f:
            f.write(grib_bytes)
            tmp_path = f.name
        try:
            ds = xr.open_dataset(
                tmp_path,
                engine="cfgrib",
                backend_kwargs={
                    "filter_by_keys": {
                        "shortName": "tmax",
                        "typeOfLevel": "heightAboveGround",
                        "level": 2,
                        "stepType": "max",
                    },
                    "indexpath": "",
                },
            )
            val_k = ds["tmax"].interp(latitude=lat, longitude=lon_360).values.item()
            return (val_k - 273.15) * 9 / 5 + 32
        finally:
            os.unlink(tmp_path)

    def fetch_hgefs_member_maxt(self, date_str: str, cycle: str, member: str, city_config: dict) -> Optional[float]:
        fhrs = [12, 15, 18, 21, 24, 27, 30, 33, 36]
        values = []
        for fhr in fhrs:
            try:
                url = self.get_gefs_file_url(date_str, cycle, member, fhr)
                grib_bytes = self.get_byte_range(url, "TMAX")
                if grib_bytes:
                    values.append(
                        self.extract_maxt_at_point(
                            grib_bytes,
                            float(city_config["lat"]),
                            float(city_config["lon_360"]),
                        )
                    )
            except Exception as exc:
                logger.debug("HGEFS %s f%03d unavailable: %s", member, fhr, exc)
        return max(values) if values else None

    def fetch_aigefs_member_maxt(self, date_str: str, cycle: str, member_index: int, city_config: dict) -> Optional[float]:
        fhrs = [12, 15, 18, 21, 24, 27, 30, 33, 36]
        values = []
        for fhr in fhrs:
            try:
                url = self.get_aigefs_file_url(date_str, cycle, member_index, fhr)
                grib_bytes = self.get_byte_range(url, "TMAX")
                if grib_bytes:
                    values.append(
                        self.extract_maxt_at_point(
                            grib_bytes,
                            float(city_config["lat"]),
                            float(city_config["lon_360"]),
                        )
                    )
            except Exception as exc:
                logger.debug("AIGEFS mem%03d f%03d unavailable: %s", member_index, fhr, exc)
        return max(values) if values else None

    def fetch_all_hgefs_members(self, date_str: str, cycle: str, city_config: dict) -> dict:
        physics_members = ["c00"] + [f"p{i:02d}" for i in range(1, 31)]

        member_maxt: Dict[str, float] = {}
        for member in physics_members:
            value = self.fetch_hgefs_member_maxt(date_str, cycle, member, city_config)
            if value is not None:
                member_maxt[member] = value
        for member_index in range(1, 32):
            member_name = f"ai{member_index:03d}"
            value = self.fetch_aigefs_member_maxt(date_str, cycle, member_index, city_config)
            if value is not None:
                member_maxt[member_name] = value

        physics = [member_maxt[m] for m in physics_members if m in member_maxt]
        ai_member_names = [f"ai{i:03d}" for i in range(1, 32)]
        ai = [member_maxt[m] for m in ai_member_names if m in member_maxt]
        return {
            "physics_members": {m: member_maxt[m] for m in physics_members if m in member_maxt},
            "ai_members": {m: member_maxt[m] for m in ai_member_names if m in member_maxt},
            "physics_mean": float(np.mean(physics)) if physics else None,
            "physics_spread": float(np.std(physics)) if physics else None,
            "ai_mean": float(np.mean(ai)) if ai else None,
            "ai_spread": float(np.std(ai)) if ai else None,
        }

    def fetch_nbm_bulletin(self, date_str: str, cycle: str, station: str) -> Optional[dict]:
        """Fetch NBM MaxT guidance.

        The master plan names blend_nbptx and TXNP percentile rows. NOMADS
        currently exposes KNYC MaxT guidance in blend_nbetx/blend_nbstx with
        TXN rows and XND spread rows, so this parser first honors TXNP rows if
        NOAA adds them and then falls back to TXN-derived percentile proxies.
        """
        filenames = [f"blend_nbptx.t{cycle}z", f"blend_nbetx.t{cycle}z", f"blend_nbstx.t{cycle}z"]
        for filename in filenames:
            result = self._fetch_nbm_file(date_str, cycle, station, filename)
            if result:
                return result
        return None

    def _fetch_nbm_file(self, date_str: str, cycle: str, station: str, filename: str) -> Optional[dict]:
        url = f"{self.nbm_base}/blend.{date_str}/{cycle}/text/{filename}"
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
        except Exception as exc:
            logger.warning("NBM bulletin unavailable: %s", exc)
            return None

        lines = response.text.splitlines()
        station_block = None
        for i, line in enumerate(lines):
            if line.strip().startswith(station):
                station_block = lines[i : i + 80]
                break
        if not station_block:
            return None

        result = {
            "run_time": f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {cycle}:00:00",
            "source_file": filename,
        }
        mapping = {"TXNP1": "p10", "TXNP2": "p25", "TXNP5": "p50", "TXNP7": "p75", "TXNP9": "p90"}
        for line in station_block:
            parts = line.split()
            if not parts:
                continue
            for token, key in mapping.items():
                if token in parts or line.strip().startswith(token):
                    try:
                        result[key] = float(parts[-1])
                    except ValueError:
                        pass
        if "p50" in result:
            result["percentiles_real"] = True
            return result

        txn_values = self._first_numeric_values(station_block, "TXN")
        xnd_values = self._first_numeric_values(station_block, "XND")
        if txn_values:
            p50 = float(txn_values[0])
            spread = float(xnd_values[0]) if xnd_values else 2.0
            result.update(
                {
                    "p10": p50 - 2 * spread,
                    "p25": p50 - spread,
                    "p50": p50,
                    "p75": p50 + spread,
                    "p90": p50 + 2 * spread,
                    "derived_from": "TXN_XND",
                    "percentiles_real": False,
                }
            )
            return result
        return None

    @staticmethod
    def _first_numeric_values(lines: list, token: str) -> list:
        for line in lines:
            parts = line.replace("|", " ").split()
            if parts and parts[0] == token:
                values = []
                for part in parts[1:]:
                    try:
                        values.append(float(part))
                    except ValueError:
                        continue
                return values
        return []
