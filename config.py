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
MIN_GAP_PP = 20.0
DEAD_ZONE_LO = 35.0
DEAD_ZONE_HI = 40.0

# Gumbel parameters
GUMBEL_MU_CORRECTION = -0.45
GUMBEL_BETA = 0.742
ECMWF_MAE = 0.95
ECMWF_BIAS = -0.42
GFS_MAE = 1.58
GFS_BIAS = 0.47
HRRR_SUMMER_BIAS = -1.5

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
