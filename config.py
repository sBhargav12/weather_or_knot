from __future__ import annotations

import math
import os
from decimal import Decimal

# API credentials are intentionally read from the environment only.
KALSHI_API_KEY = os.environ.get("KALSHI_API_KEY", "")
KALSHI_KEY_PATH = os.environ.get("KALSHI_KEY_PATH", "")
WETHR_API_KEY = os.environ.get("WETHR_API_KEY", "")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_URL = os.environ.get("NTFY_URL", "https://ntfy.sh")

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
# NBM vs HGEFS disagreement: >15°F = hard block (Gate 1 fail); 8–15°F = -30 confidence penalty.
# Today (2026-05-03) was a 20°F gap; HGEFS was 15°F wrong, NBM was 5°F wrong.
NBM_HGEFS_HARD_BLOCK_GAP_F = 15.0
NBM_HGEFS_PENALTY_GAP_F = 8.0
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
    # Kalshi charges per-contract; ceiling must be applied per contract, not on the batch total.
    return contracts * (math.ceil(TAKER_FEE_RATE * price * (1 - price) * 100) / 100)


def maker_fee(contracts: int, price: float) -> float:
    return contracts * (math.ceil(MAKER_FEE_RATE * price * (1 - price) * 100) / 100)


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
        "series_ticker": "KXHIGHPHIL",
        "timezone": "America/New_York",
        "lat": 39.8729,
        "lon": -75.2408,
        "lon_360": 284.7592,
        "dsm_times_utc": ["20:21", "21:21", "05:17"],
        "sharpe_backtest": 2.83,
        "active": False,
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
        "active": True,
        "wethr_station": "KMDW",
    },
    "KMIA": {
        "name": "Miami International",
        "series_ticker": "KXHIGHMIA",
        "timezone": "America/New_York",
        "lat": 25.7959,
        "lon": -80.2870,
        "lon_360": 279.7130,
        "dsm_times_utc": ["20:21", "21:21", "05:17"],
        "sharpe_backtest": 0.384,
        "active": True,
        "wethr_station": "KMIA",
    },
    "KAUS": {
        "name": "Austin-Bergstrom International",
        "series_ticker": "KXHIGHAUS",
        "timezone": "America/Chicago",
        "lat": 30.1944,
        "lon": -97.6699,
        "lon_360": 262.3301,
        "dsm_times_utc": ["21:17", "22:17", "06:17"],
        "sharpe_backtest": None,
        "active": False,
        "wethr_station": "KAUS",
    },
    "KLAX": {
        "name": "Los Angeles International",
        "series_ticker": "KXHIGHLAX",
        "timezone": "America/Los_Angeles",
        "lat": 33.9425,
        "lon": -118.4081,
        "lon_360": 241.5919,
        "dsm_times_utc": ["23:17", "00:17", "08:17"],
        "sharpe_backtest": None,
        "active": False,
        "wethr_station": "KLAX",
    },
    "KDEN": {
        "name": "Denver International",
        "series_ticker": "KXHIGHDEN",
        "timezone": "America/Denver",
        "lat": 39.8561,
        "lon": -104.6737,
        "lon_360": 255.3263,
        "dsm_times_utc": ["22:17", "23:17", "07:17"],
        "sharpe_backtest": None,
        "active": False,
        "wethr_station": "KDEN",
    },
    "KXLOWTNYC": {
        "name": "New York City Low (Central Park)",
        "series_ticker": "KXLOWTNYC",
        "settlement_type": "low",
        "timezone": "America/New_York",
        "lat": 40.7789,
        "lon": -73.9692,
        "lon_360": 286.0308,
        "dsm_times_utc": ["20:21", "21:21", "05:17"],
        "sharpe_backtest": None,
        "active": False,
        "wethr_station": "KNYC",
    },
    "KXLOWTCHI": {
        "name": "Chicago Midway Low",
        "series_ticker": "KXLOWTCHI",
        "settlement_type": "low",
        "timezone": "America/Chicago",
        "lat": 41.7868,
        "lon": -87.7522,
        "lon_360": 272.2478,
        "dsm_times_utc": ["21:17", "22:17", "06:17"],
        "sharpe_backtest": 0.714,
        "active": True,
        "wethr_station": "KMDW",
    },
    "KXLOWTMIA": {
        "name": "Miami International Low",
        "series_ticker": "KXLOWTMIA",
        "settlement_type": "low",
        "timezone": "America/New_York",
        "lat": 25.7959,
        "lon": -80.2870,
        "lon_360": 279.7130,
        "dsm_times_utc": ["20:21", "21:21", "05:17"],
        "sharpe_backtest": None,
        "active": False,
        "wethr_station": "KMIA",
    },
    "KXLOWTAUS": {
        "name": "Austin-Bergstrom International Low",
        "series_ticker": "KXLOWTAUS",
        "settlement_type": "low",
        "timezone": "America/Chicago",
        "lat": 30.1944,
        "lon": -97.6699,
        "lon_360": 262.3301,
        "dsm_times_utc": ["21:17", "22:17", "06:17"],
        "sharpe_backtest": None,
        "active": False,
        "wethr_station": "KAUS",
    },
    "KXLOWTLAX": {
        "name": "Los Angeles International Low",
        "series_ticker": "KXLOWTLAX",
        "settlement_type": "low",
        "timezone": "America/Los_Angeles",
        "lat": 33.9425,
        "lon": -118.4081,
        "lon_360": 241.5919,
        "dsm_times_utc": ["23:17", "00:17", "08:17"],
        "sharpe_backtest": None,
        "active": False,
        "wethr_station": "KLAX",
    },
    "KXLOWTDEN": {
        "name": "Denver International Low",
        "series_ticker": "KXLOWTDEN",
        "settlement_type": "low",
        "timezone": "America/Denver",
        "lat": 39.8561,
        "lon": -104.6737,
        "lon_360": 255.3263,
        "dsm_times_utc": ["22:17", "23:17", "07:17"],
        "sharpe_backtest": 0.628,
        "active": True,
        "wethr_station": "KDEN",
    },
    "KXLOWTPHIL": {
        "name": "Philadelphia International Low",
        "series_ticker": "KXLOWTPHIL",
        "settlement_type": "low",
        "timezone": "America/New_York",
        "lat": 39.8729,
        "lon": -75.2408,
        "lon_360": 284.7592,
        "dsm_times_utc": ["20:21", "21:21", "05:17"],
        "sharpe_backtest": None,
        "active": False,
        "wethr_station": "KPHL",
    },
}

DSM_CANCEL_TIME_ET = "16:15"
MAX_HOLD_TIME_ET = "23:00"
METAR_GATE_TIME_ET = "09:51"
DEEP_TAIL_EARLY_ET = "10:15"   # DEEP_TAIL_NO fires 15min after tomorrow market lists (~10AM ET)
LADDER_EVENT_RUN_ET = "10:00"  # Strategy 2 morning event-level ladder check
FALLBACK_ENTRY_ET = "11:00"
DAILY_REPORT_TIME_ET = "08:00"
EOD_REPORT_TIME_ET = "18:35"  # after DSM window (16:15–18:30 ET)
CLI_CHECK_TIME_ET = "07:00"
TELECONN_UPDATE_ET = "06:00"
TRADE_TARGET_DAYS_AHEAD = 1

# Market data collection is intentionally broader than live/paper trading.
# Trading gates use active=True cities; collection can follow every configured
# weather series so research/backtests have today's and tomorrow's full tape.
COLLECT_MARKET_DATA_FOR_INACTIVE_CITIES = True
KALSHI_COLLECT_TARGET_DAYS = 1
KALSHI_REST_COLLECTION_INTERVAL_SECONDS = 60
KALSHI_WS_REFRESH_INTERVAL_SECONDS = 300
KALSHI_STORE_FULL_ORDERBOOK_SNAPSHOTS = True

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
BRACKET_LOCK_RUN_ET = "15:00"  # 3:00 PM ET — intraday bracket confirmation window

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

# Live trading — controlled by live_trader/config_live.py and env vars.
# STARTING_BANKROLL above is for paper trading only.
LIVE_BANKROLL = float(os.environ.get("LIVE_BANKROLL", "25.0"))
