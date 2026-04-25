from __future__ import annotations

import logging
import os
import tempfile
from datetime import UTC, datetime
from typing import Dict, List, Optional

import numpy as np
import requests

import config

logger = logging.getLogger(__name__)

_GEFS_S3_BASE = "https://noaa-gefs-pds.s3.amazonaws.com"
_AIGEFS_NOMADS_BASE = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/aigefs/prod"
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "*/*",
}

# 1000mb TMP is instantaneous; TMAX at 2m is the period maximum.
# For a sea-level city like NYC in spring, 1000mb TMP underestimates
# the daytime max by roughly 4°F.  Applied to every AIGEFS member so
# the physics/AI comparison in Gate 1 remains on the same scale.
_AIGEFS_1000MB_BIAS_F = 4.0


class ModelFetcher:
    """Fetch GEFS (S3) and AIGEFS (NOMADS) GRIB slices plus NBM bulletins."""

    def __init__(self, hgefs_base: str = config.NOMADS_HGEFS_BASE, nbm_base: str = config.NOMADS_NBM_BASE):
        self.hgefs_base = hgefs_base.rstrip("/")
        self.nbm_base = nbm_base.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(_BROWSER_HEADERS)

    # ------------------------------------------------------------------
    # Cycle discovery — uses GEFS S3 (NOMADS always 403 for file access)
    # ------------------------------------------------------------------

    def check_new_hgefs_cycle(self, current_cycle: Optional[str] = None, date_str: Optional[str] = None) -> Optional[str]:
        """Return the newest available GEFS cycle on S3, or None if unchanged."""
        if date_str is None:
            date_str = datetime.now(UTC).strftime("%Y%m%d")
        for cycle in ["12", "06", "00"]:
            if cycle == current_cycle:
                return None
            url = (
                f"{_GEFS_S3_BASE}/gefs.{date_str}/{cycle}/atmos/pgrb2sp25/"
                f"gec00.t{cycle}z.pgrb2s.0p25.f024.idx"
            )
            try:
                response = self.session.get(url, timeout=15)
                if response.status_code == 200:
                    logger.debug("GEFS S3 cycle available: %s/%s", date_str, cycle)
                    return cycle
            except Exception as exc:
                logger.debug("GEFS S3 cycle check failed %s/%s: %s", date_str, cycle, exc)
        return None

    # ------------------------------------------------------------------
    # URL builders
    # ------------------------------------------------------------------

    def get_gefs_file_url(self, date_str: str, cycle: str, member: str, fhr: int) -> str:
        """GEFS physics member on S3 (NOMADS returns 403 for file downloads)."""
        gefs_member = "gec00" if member == "c00" else f"gep{int(member[1:]):02d}"
        return (
            f"{_GEFS_S3_BASE}/gefs.{date_str}/{cycle}/atmos/pgrb2sp25/"
            f"{gefs_member}.t{cycle}z.pgrb2s.0p25.f{fhr:03d}"
        )

    def get_aigefs_file_url(self, date_str: str, cycle: str, member_index: int, fhr: int) -> str:
        """AIGEFS AI member on NOMADS (downloads return 200, S3 bucket absent).

        Confirmed structure: mem000-mem030 / model/atmos/grib2/
        aigefs.t{cycle}z.pres.f{fhr:03d}.grib2  (6-hourly, pressure-level)
        """
        return (
            f"{_AIGEFS_NOMADS_BASE}/aigefs.{date_str}/{cycle}/"
            f"mem{member_index:03d}/model/atmos/grib2/"
            f"aigefs.t{cycle}z.pres.f{fhr:03d}.grib2"
        )

    # ------------------------------------------------------------------
    # GRIB byte-range helpers
    # ------------------------------------------------------------------

    def get_byte_range(self, url: str, idx_patterns: List[str]) -> Optional[bytes]:
        """Download only the GRIB record whose .idx line matches ALL patterns."""
        idx_url = f"{url}.idx"
        idx_response = self.session.get(idx_url, timeout=30)
        idx_response.raise_for_status()
        idx_lines = idx_response.text.splitlines()
        start_byte: Optional[int] = None
        end_byte: Optional[int] = None
        for i, line in enumerate(idx_lines):
            if all(p in line for p in idx_patterns):
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

    @staticmethod
    def _ensure_eccodes() -> None:
        """Auto-detect Homebrew eccodes if ECCODES_DIR is not set."""
        if os.environ.get("ECCODES_DIR"):
            return
        try:
            import subprocess
            prefix = subprocess.check_output(
                ["brew", "--prefix", "eccodes"], stderr=subprocess.DEVNULL, timeout=5
            ).decode().strip()
            if prefix:
                os.environ["ECCODES_DIR"] = prefix
        except Exception:
            pass  # eccodes will fail with its own error if missing

    def _extract_grib_temp_at_point(
        self,
        grib_bytes: bytes,
        lat: float,
        lon_360: float,
        filter_by_keys: dict,
        var_name: str,
    ) -> float:
        """Extract a temperature variable from GRIB2 bytes, return °F."""
        self._ensure_eccodes()
        try:
            import xarray as xr
        except ImportError as exc:
            raise RuntimeError("xarray/cfgrib/eccodes required for GRIB extraction") from exc

        with tempfile.NamedTemporaryFile(suffix=".grib2", delete=False) as f:
            f.write(grib_bytes)
            tmp_path = f.name
        try:
            ds = xr.open_dataset(
                tmp_path,
                engine="cfgrib",
                backend_kwargs={"filter_by_keys": filter_by_keys, "indexpath": ""},
            )
            val_k = ds[var_name].interp(latitude=lat, longitude=lon_360).values.item()
            return (val_k - 273.15) * 9 / 5 + 32
        finally:
            os.unlink(tmp_path)

    def extract_maxt_at_point(self, grib_bytes: bytes, lat: float, lon_360: float) -> float:
        """Extract TMAX at 2 m above ground (GEFS pgrb2s), return °F."""
        return self._extract_grib_temp_at_point(
            grib_bytes,
            lat,
            lon_360,
            filter_by_keys={
                "shortName": "tmax",
                "typeOfLevel": "heightAboveGround",
                "level": 2,
                "stepType": "max",
            },
            var_name="tmax",
        )

    def extract_tmp_1000mb_at_point(self, grib_bytes: bytes, lat: float, lon_360: float) -> tuple[float, float]:
        """Extract TMP at 1000 hPa (AIGEFS pres).

        Returns (raw_f, corrected_f) where corrected = raw + _AIGEFS_1000MB_BIAS_F.
        The correction is unvalidated — caller must log a warning and store both values.
        """
        raw_f = self._extract_grib_temp_at_point(
            grib_bytes,
            lat,
            lon_360,
            filter_by_keys={
                "shortName": "t",
                "typeOfLevel": "isobaricInhPa",
                "level": 1000,
            },
            var_name="t",
        )
        corrected_f = raw_f + _AIGEFS_1000MB_BIAS_F
        logger.warning(
            "Using unvalidated AIGEFS 1000mb proxy: raw=%.2f°F corrected=%.2f°F (bias=+%.1f°F, not yet validated)",
            raw_f, corrected_f, _AIGEFS_1000MB_BIAS_F,
        )
        return raw_f, corrected_f

    # ------------------------------------------------------------------
    # Per-member fetchers
    # ------------------------------------------------------------------

    def fetch_hgefs_member_maxt(self, date_str: str, cycle: str, member: str, city_config: dict) -> Optional[float]:
        """Fetch GEFS physics member TMAX from S3.  3-hourly steps f012-f036."""
        fhrs = [12, 15, 18, 21, 24, 27, 30, 33, 36]
        # Period label varies by fhr, e.g. "18-24 hour max fcst" — match suffix only.
        idx_patterns = [":TMAX:", ":2 m above ground:", "max fcst"]
        values = []
        for fhr in fhrs:
            try:
                url = self.get_gefs_file_url(date_str, cycle, member, fhr)
                grib_bytes = self.get_byte_range(url, idx_patterns)
                if grib_bytes:
                    values.append(
                        self.extract_maxt_at_point(
                            grib_bytes,
                            float(city_config["lat"]),
                            float(city_config["lon_360"]),
                        )
                    )
            except Exception as exc:
                logger.debug("GEFS physics %s f%03d unavailable: %s", member, fhr, exc)
        return max(values) if values else None

    def fetch_aigefs_member_maxt(self, date_str: str, cycle: str, member_index: int, city_config: dict) -> Optional[tuple[float, float]]:
        """Fetch AIGEFS AI member 1000mb TMP from NOMADS.  6-hourly steps f012-f036.

        Returns (raw_max_f, corrected_max_f) or None if unavailable.
        corrected = raw + _AIGEFS_1000MB_BIAS_F (unvalidated proxy for surface TMAX).
        """
        fhrs = [12, 18, 24, 30, 36]
        idx_patterns = [":TMP:", ":1000 mb:"]
        raw_values: list[float] = []
        corrected_values: list[float] = []
        for fhr in fhrs:
            try:
                url = self.get_aigefs_file_url(date_str, cycle, member_index, fhr)
                grib_bytes = self.get_byte_range(url, idx_patterns)
                if grib_bytes:
                    raw_f, corrected_f = self.extract_tmp_1000mb_at_point(
                        grib_bytes,
                        float(city_config["lat"]),
                        float(city_config["lon_360"]),
                    )
                    raw_values.append(raw_f)
                    corrected_values.append(corrected_f)
            except Exception as exc:
                logger.debug("AIGEFS mem%03d f%03d unavailable: %s", member_index, fhr, exc)
        if not corrected_values:
            return None
        return max(raw_values), max(corrected_values)

    # ------------------------------------------------------------------
    # Full ensemble fetch
    # ------------------------------------------------------------------

    def fetch_all_hgefs_members(self, date_str: str, cycle: str, city_config: dict) -> dict:
        """Fetch all 31 GEFS physics + up to 31 AIGEFS AI members."""
        physics_members = ["c00"] + [f"p{i:02d}" for i in range(1, 31)]

        member_maxt: Dict[str, float] = {}

        for member in physics_members:
            value = self.fetch_hgefs_member_maxt(date_str, cycle, member, city_config)
            if value is not None:
                member_maxt[member] = value

        # AIGEFS: mem000-mem030 (0-indexed, 31 members)
        # Stores corrected value in member_maxt for Gate 1; tracks raw separately.
        ai_raw_values: list[float] = []
        for member_index in range(0, 31):
            member_name = f"ai{member_index:03d}"
            result = self.fetch_aigefs_member_maxt(date_str, cycle, member_index, city_config)
            if result is not None:
                raw_f, corrected_f = result
                member_maxt[member_name] = corrected_f
                ai_raw_values.append(raw_f)

        physics = [member_maxt[m] for m in physics_members if m in member_maxt]
        ai_member_names = [f"ai{i:03d}" for i in range(0, 31)]
        ai_corrected = [member_maxt[m] for m in ai_member_names if m in member_maxt]

        return {
            "physics_members": {m: member_maxt[m] for m in physics_members if m in member_maxt},
            "ai_members": {m: member_maxt[m] for m in ai_member_names if m in member_maxt},
            "physics_mean": float(np.mean(physics)) if physics else None,
            "physics_spread": float(np.std(physics)) if physics else None,
            "ai_mean": float(np.mean(ai_corrected)) if ai_corrected else None,
            "ai_spread": float(np.std(ai_corrected)) if ai_corrected else None,
            "aigefs_temp_raw": float(np.mean(ai_raw_values)) if ai_raw_values else None,
            "aigefs_temp_corrected": float(np.mean(ai_corrected)) if ai_corrected else None,
        }

    # ------------------------------------------------------------------
    # NBM bulletin
    # ------------------------------------------------------------------

    def fetch_nbm_bulletin(self, date_str: str, cycle: str, station: str) -> Optional[dict]:
        """Fetch NBM MaxT guidance.

        blend_nbptx contains real TXNP percentiles when available.
        In practice KNYC blocks in blend_nbptx are often empty; the
        fallback blend_nbetx always has TXN (mean) and XND (spread).
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

        # Real probabilistic percentiles (blend_nbptx)
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

        # Fallback: TXN mean + XND spread proxy (blend_nbetx / blend_nbstx)
        txn_values = self._first_numeric_values(station_block, "TXN")
        xnd_values = self._first_numeric_values(station_block, "XND")
        if txn_values:
            # The first TXN value at 6-hourly cycle covers today's afternoon
            # high (FHR 18 from 06Z = 12Z–00Z local, i.e. 8am–8pm ET daytime max).
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
