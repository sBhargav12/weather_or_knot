from __future__ import annotations

import io
import logging
from typing import Optional

import pandas as pd
import requests

import config
from data_store.db import Database

logger = logging.getLogger(__name__)


class TeleconnFetcher:
    """Download and shape MJO, ONI, and monthly NH teleconnection indices."""

    def __init__(self, db_path: Optional[str] = None):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})
        self.db_path = db_path or config.DB_PATH

    def fetch_mjo_rmm(self) -> pd.DataFrame:
        text = self.session.get(config.BOM_MJO_URL, timeout=30).text
        if text.lstrip().startswith("<"):
            raise RuntimeError("BoM MJO response was HTML instead of text data")
        df = pd.read_csv(
            io.StringIO(text),
            skiprows=2,
            sep=r"\s+",
            names=["year", "month", "day", "RMM1", "RMM2", "phase", "amplitude", "missing"],
        )
        df = df[df["amplitude"] < 999].copy()
        df["date"] = pd.to_datetime(df[["year", "month", "day"]])
        return df.set_index("date")[["RMM1", "RMM2", "phase", "amplitude"]]

    def fetch_oni(self) -> pd.DataFrame:
        text = self.session.get(config.CPC_ONI_URL, timeout=30).text
        return pd.read_csv(io.StringIO(text), sep=r"\s+")

    def fetch_tele_monthly(self) -> pd.DataFrame:
        text = self.session.get(config.CPC_TELE_URL, timeout=30).text
        df = pd.read_fwf(
            io.StringIO(text),
            skiprows=18,
            header=None,
            names=[
                "year",
                "month",
                "NAO",
                "EA",
                "EAJET",
                "WP",
                "EP",
                "NP",
                "PNA",
                "EAWR",
                "SCA",
                "TNH",
                "POL",
                "PT",
                "SZ",
                "ASU",
            ],
        )
        for col in df.columns:
            if col not in ("year", "month"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df[df["NAO"].notna() & (df["NAO"] != -9.9)].copy()
        df["date"] = pd.to_datetime(df[["year", "month"]].assign(day=1))
        return df.set_index("date")

    def build_daily_features(self, date: str) -> dict:
        target = pd.Timestamp(date)
        features = {"date": target.strftime("%Y-%m-%d"), "source": "bom_cpc"}

        try:
            rmm = self.fetch_mjo_rmm()
            latest = rmm[rmm.index <= target].iloc[-1]
            features.update(
                {
                    "mjo_rmm1": float(latest["RMM1"]),
                    "mjo_rmm2": float(latest["RMM2"]),
                    "mjo_phase": int(latest["phase"]),
                    "mjo_amplitude": float(latest["amplitude"]),
                }
            )
            for lag in [7, 14]:
                lag_target = target - pd.Timedelta(days=lag)
                lag_rows = rmm[rmm.index <= lag_target]
                if not lag_rows.empty:
                    lag_row = lag_rows.iloc[-1]
                    features[f"mjo_amplitude_lag{lag}"] = float(lag_row["amplitude"])
                    features[f"mjo_phase_lag{lag}"] = int(lag_row["phase"])
        except Exception as exc:
            logger.warning("MJO features unavailable: %s", exc)

        try:
            tele = self.fetch_tele_monthly()
            latest_tele = tele[tele.index <= target].iloc[-1]
            for src, dest in [("NAO", "nao"), ("PNA", "pna"), ("TNH", "tnh"), ("POL", "pol")]:
                if src in latest_tele:
                    features[dest] = float(latest_tele[src])
        except Exception as exc:
            logger.warning("Monthly teleconnection features unavailable: %s", exc)

        try:
            oni = self.fetch_oni()
            if "ANOM" in oni.columns:
                features["oni"] = float(oni.iloc[-1]["ANOM"])
            elif "anomaly" in oni.columns:
                features["oni"] = float(oni.iloc[-1]["anomaly"])
        except Exception as exc:
            logger.warning("ONI unavailable: %s", exc)

        return features

    def save_to_db(self, date: str, features: dict) -> int:
        db = Database(self.db_path)
        payload = {"date": date, **features}
        return db.insert_teleconnection(payload)
