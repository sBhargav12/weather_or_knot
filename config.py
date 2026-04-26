from __future__ import annotations

import math
import os
from decimal import Decimal

# API credentials are intentionally read from the environment only.
KALSHI_API_KEY = os.environ.get("KALSHI_API_KEY", "")
KALSHI_KEY_PATH = os.environ.get("KALSHI_KEY_PATH", "")
WETHR_API_KEY = os.environ.get("WETHR_API_KEY", "")

# API endpoints
KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"
WETHR_BASE_URL = "https://wethr.net/api/v2"
NOMADS_HGEFS_BASE = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/hgefs/prod"
NOMADS_NBM_BASE = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod"

BOM_MJO_URL = "https://www.bom.gov.au/climate/mjo/graphics/rmm.74toRealtime.txt"
CPC_ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
CPC_TELE_URL = "https://ftp.cpc.ncep.noaa.gov/wd52dg/data/indices/tele_index.nh"

IEM_ASOS_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
NWS_DSM_NYC_URL = "https://mesonet.agron.iastate.edu/wx/afos/p.php?pil=DSMNYC"
NWS_CLI_NYC_URL = "https://forecast.weather.gov/product.php?site=OKX&product=CLI&issuedby=NYC"

DB_PATH = "data/pipeline.db"

# Trading parameters
TARGET_EXIT_PRICE = Decimal("0.68")
STOP_LOSS_DIFF = Decimal("0.20")
MIN_YES_PRICE = Decimal("0.25")
MAX_YES_PRICE = Decimal("0.75")
NEVER_HOLD_ABOVE = Decimal("0.70")
# Canonical live Gate 2 edge threshold. Keep the 35-40pp dead zone below as a
# separate hard block.
MIN_GAP_PP = 20.0
DEAD_ZONE_LO = 35.0
DEAD_ZONE_HI = 40.0

# Research sleeves from scripts/backtest.py. TAIL_NO is logged for research only
# until it survives stricter walk-forward/slippage tests; DEEP_TAIL_NO remains
# paper-traded because it held up best in the exchange-settlement backtest.
TAIL_NO_PROB_MAX = 0.30
TAIL_NO_YES_PRICE_MIN = Decimal("0.55")
ENABLE_TAIL_NO_TRADES = False
DEEP_TAIL_NO_PROB_MAX = 0.02
DEEP_TAIL_NO_YES_PRICE_MIN = Decimal("0.05")
ENABLE_DEEP_TAIL_NO_TRADES = True

# Gumbel parameters
GUMBEL_MU_CORRECTION = -0.45
GUMBEL_BETA = 0.742
ECMWF_MAE = 0.95
ECMWF_BIAS = -0.42
GFS_MAE = 1.58
GFS_BIAS = 0.47
HRRR_SUMMER_BIAS = -1.5

# Fallback-only Open-Meteo/wethr weights learned from the exchange-settlement
# KXHIGHNY backtest. Real HGEFS remains the primary model whenever available.
FALLBACK_ENSEMBLE_WEIGHTS = {
    "GFS": 0.3575441093,
    "ECMWF": 0.2121428382,
    "UKMO": 0.1938071607,
    "NBM": 0.2365058918,
}

# Gate thresholds
HGEFS_MAX_SPREAD_BETWEEN = 1.5
HGEFS_MAX_SUBSET_SPREAD = 3.0
METAR_YES_MAX_DISTANCE = 8.0
METAR_NO_MIN_DISTANCE = 3.0
REVERSAL_THRESHOLD = Decimal("0.10")
COLD_BRACKET_MAX_TEMP = 52.0
LIQUIDITY_CENTRAL_MAX = Decimal("0.04")
LIQUIDITY_WING_MAX = Decimal("0.06")

# Position sizing
STARTING_BANKROLL = 500.00
MAX_TRADE_PCT = 0.05
MAX_TOTAL_EXPOSURE = 0.15
POSITION_SIZING = "quarter_kelly"

# Fees
TAKER_FEE_RATE = 0.07
MAKER_FEE_RATE = 0.0175


def taker_fee(contracts: int, price: float) -> float:
    return math.ceil(TAKER_FEE_RATE * contracts * price * (1 - price) * 100) / 100


def maker_fee(contracts: int, price: float) -> float:
    return math.ceil(MAKER_FEE_RATE * contracts * price * (1 - price) * 100) / 100


CITIES = {
    "KNYC": {
        "name": "New York City (Central Park)",
        "series_ticker": "KXHIGHNY",
        "timezone": "America/New_York",
        "lat": 40.7789,
        "lon": -73.9692,
        "lon_360": 286.0308,
        "dsm_times_utc": ["20:21", "21:21", "05:17"],
        "sharpe_backtest": 4.72,
        "active": True,
        "wethr_station": "KNYC",
    },
    "KPHL": {
        "name": "Philadelphia",
        "series_ticker": "KXHIGHPHL",
        "timezone": "America/New_York",
        "lat": 39.8729,
        "lon": -75.2408,
        "lon_360": 284.7592,
        "dsm_times_utc": ["20:21", "21:21"],
        "sharpe_backtest": 2.83,
        "active": True,
        "wethr_station": "KPHL",
    },
    "KMDW": {
        "name": "Chicago Midway",
        "series_ticker": "KXHIGHCHI",
        "timezone": "America/Chicago",
        "lat": 41.7868,
        "lon": -87.7522,
        "lon_360": 272.2478,
        "dsm_times_utc": ["21:17", "22:17", "06:17"],
        "sharpe_backtest": 1.58,
        "active": False,
        "wethr_station": "KMDW",
    },
}

DSM_CANCEL_TIME_ET = "16:15"
MAX_HOLD_TIME_ET = "23:00"
METAR_GATE_TIME_ET = "09:51"
FALLBACK_ENTRY_ET = "11:00"
DAILY_REPORT_TIME_ET = "08:00"
CLI_CHECK_TIME_ET = "07:00"
TELECONN_UPDATE_ET = "06:00"

POLL_INTERVAL_60S = 60
POLL_INTERVAL_5MIN = 300
POLL_INTERVAL_30MIN = 1800
POLL_INTERVAL_DAILY = 86400

MODEL_RUN_SCHEDULE_ET = {
    "GFS":  ["00:40", "06:40", "12:40", "18:40"],
    "ECMWF": ["03:00", "15:00"],
    "HRRR": "hourly",
    "NAM":  ["04:35", "10:35", "16:35", "22:35"],
    "NBM":  "hourly",
    "UKMO": ["05:00", "17:00"],
}

# 12Z GFS run (~12:40 PM ET) is the most important trigger for afternoon trading.
PEAK_MODEL_RUN_ET = "12:40"

TEMP_ANOMALY_TRIGGER = 1.5
PRICE_MOVE_TRIGGER = Decimal("0.05")
NWS_VERSION_CHECK = True

SIMULATION_DAYS = 30
TARGET_WIN_RATE = 0.55
MIN_PAPER_TRADES = 30
SLIPPAGE_HALF_SPREAD = True

WEIGHT_HGEFS = 0.60
WEIGHT_NBM = 0.40
USE_DERIVED_NBM_PRIOR = False
HGEFS_MIN_PHYSICS_MEMBERS = 20
HGEFS_MIN_AI_MEMBERS = 20
REQUIRE_HGEFS_FOR_SIGNALS = True

FALLBACK_MODELS = ["HRRR", "NBM", "GFS", "ECMWF", "ICON", "NAM"]
FALLBACK_MIN_AGREEMENT = 4
FALLBACK_AGREEMENT_BAND = 2.0

CALIBRATION_WINDOW_DAYS = 90
CALIBRATION_UPDATE_DAYS = 7
NBM_V5_CUTOVER = "2026-04-15"

MAX_DAILY_LOSS_PCT = 0.10
MAX_WEEKLY_LOSS_PCT = 0.20
MIN_BRIER_SKILL_SCORE = 0.0
