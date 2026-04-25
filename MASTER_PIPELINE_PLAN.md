# KALSHI WEATHER TRADING PIPELINE — MASTER PLAN
**Version: 1.0 | Date: April 25, 2026**
**Author: Bhargav Sukhavasi**
**Status: All APIs confirmed working. Ready to build.**

---

## DOCUMENT PURPOSE

This document is the single source of truth for building a live 30-day paper trading pipeline for Kalshi weather temperature markets. It contains every detail needed — credentials, architecture, data sources, API formats, strategy rules, database schema, module specifications, and build order — so that any coding agent can build the complete system from scratch without needing any additional context.

Read this document completely before writing a single line of code.

---

## TABLE OF CONTENTS

1. What We Are Building
2. Project Goal
3. Confirmed Credentials and API Keys
4. Project Folder Structure
5. Technology Stack
6. Architecture Overview
7. Data Sources (Every Source, Fully Documented)
8. Strategy Rules (Every Parameter Confirmed)
9. The 6-Gate Signal System (Complete Code)
10. Database Schema (All 10 Tables, Full SQL)
11. Module Specifications (Every File, Every Function)
12. Polling Schedule
13. Signal Generation Flow
14. Paper Trading Simulator
15. Dashboard and Reporting
16. Build Order (Step by Step)
17. Configuration File (config.py — Complete)
18. Known Failure Modes
19. Risk Management Rules
20. Testing Requirements

---

## SECTION 1: WHAT WE ARE BUILDING

A fully automated, continuously running Python pipeline that:

1. **Collects data continuously** from all weather models, observations, and Kalshi market prices — every minute, every hour, every day — and stores everything in a SQLite database.

2. **Generates event-driven entry signals** when all 6 trading gates pass simultaneously. Signals include exact entry price, exit target, stop loss, confidence score, and reasoning.

3. **Simulates paper trades** as if real money is being placed. Tracks P&L with realistic fees, slippage, and timing. Starting bankroll: $500.

4. **Monitors Kalshi in real time** via WebSocket orderbook streaming and REST price polling. Compares our model probabilities against Kalshi market prices continuously.

5. **Produces daily reports** showing signals generated, trades simulated, win rate, P&L, Sharpe ratio, and model accuracy.

6. **Runs for 30 days** collecting as much data as possible so we can analyze strategy performance, improve the model, and make an informed decision about deploying real money.

**This is NOT a backtest. This is a live forward-running paper trading system.**

---

## SECTION 2: PROJECT GOAL

**Primary goal:** Demonstrate that our strategy generates positive risk-adjusted returns in real market conditions before committing real money.

**Secondary goal:** Collect comprehensive data on every aspect of the market — model accuracy, Kalshi price behavior, DSM timing, temperature patterns — so we can continuously improve the strategy.

**Target performance for real money deployment:**
- Win rate > 55% across 30+ paper trades
- Positive net P&L after all simulated fees
- No single day losing more than 10% of simulated bankroll
- Sharpe ratio > 2.0 annualized

**Market being traded:**
- Primary: KXHIGHNY — NYC Central Park (KNYC) daily high temperature on Kalshi
- Secondary: KXHIGHPHL — Philadelphia daily high temperature on Kalshi
- Settlement source: NWS Daily Climate Report (CLI)

---

## SECTION 3: CONFIRMED CREDENTIALS AND API KEYS

### Environment Variables (set in ~/.zshrc on Mac)
```bash
KALSHI_API_KEY="7f460be7-3df7-4e4b-86c4-9c92fbfd675e"
KALSHI_KEY_PATH="$HOME/prediction-market-analysis/keys/kalshi_private.pem"
WETHR_API_KEY="<user's wethr.net Pro key — in their ~/.zshrc>"
```

### Kalshi Account
- **Balance:** $10.00 cash (1000 internal units)
- **RSA Key ID:** 7f460be7-3df7-4e4b-86c4-9c92fbfd675e
- **Private key path:** ~/prediction-market-analysis/keys/kalshi_private.pem
- **Public key path:** ~/prediction-market-analysis/keys/kalshi_public.pem
- **Confirmed working:** Status 200 on April 25, 2026
- **Old simple key:** out_of_thin_air (936df4c8-5a32-4793-aecb-bf970b19d189) — keep as fallback REST key

### wethr.net Pro
- **Tier:** Professional ($24.99/month)
- **Rate limits:** 60 requests/minute, 5,000 requests/day
- **Push API:** NOT deployed yet (BETA) — use REST polling
- **Confirmed working endpoints:** All tested April 25, 2026

### Free Data Sources (no credentials needed)
- NOAA NOMADS HTTPS — public, no auth required
- NBM text bulletins — public
- BoM MJO RMM — public
- CPC teleconnection indices — public
- IEM ASOS — public fallback

---

## SECTION 4: PROJECT FOLDER STRUCTURE

```
prediction-market-analysis/
│
├── CLAUDE.md                          # Strategy rules for Claude Code
├── kalshi_weather_strategy_complete.md # Complete strategy reference
├── MASTER_PIPELINE_PLAN.md            # This document
├── main.py                            # Main orchestrator — runs forever
├── config.py                          # All constants and configuration
│
├── data_ingest/
│   ├── __init__.py
│   ├── wethr_client.py                # wethr.net Pro REST API client
│   ├── kalshi_client.py               # Kalshi REST + WebSocket client
│   ├── model_fetcher.py               # HGEFS NOMADS + NBM bulletin
│   └── teleconn_fetcher.py            # CPC indices + BoM MJO
│
├── signal_engine/
│   ├── __init__.py
│   ├── gumbel_model.py                # Probability model
│   ├── gate_checker.py                # All 6 gates
│   └── event_triggers.py             # Polling loop + trigger detection
│
├── kalshi_watcher/
│   ├── __init__.py
│   └── orderbook.py                   # WebSocket orderbook manager
│
├── paper_trader/
│   ├── __init__.py
│   └── simulator.py                   # Trade simulation + P&L tracking
│
├── data_store/
│   ├── __init__.py
│   ├── schema.py                      # Creates all database tables
│   └── db.py                          # Connection manager + helpers
│
├── dashboard/
│   ├── __init__.py
│   └── daily_report.py                # Daily summary generation
│
├── keys/
│   ├── kalshi_private.pem             # RSA private key (chmod 600)
│   └── kalshi_public.pem              # RSA public key
│
├── data/
│   └── pipeline.db                    # SQLite database (created on first run)
│
├── logs/
│   └── pipeline.log                   # Rotating log file
│
└── tests/
    ├── test_wethr.py                  # wethr.net API tests
    ├── test_kalshi.py                 # Kalshi API tests
    └── test_gates.py                  # Gate logic tests
```

---

## SECTION 5: TECHNOLOGY STACK

### Language
Python 3.11+ (already installed on Mac)

### Required Python Packages
```
requests          # HTTP calls to all REST APIs
websockets        # Kalshi WebSocket orderbook
cryptography      # RSA-PSS signing for Kalshi auth
scipy             # Gumbel distribution calculations
numpy             # Numerical operations
pandas            # Data manipulation
scikit-learn      # Isotonic regression calibration
schedule          # Polling scheduler
sqlite3           # Database (built into Python stdlib)
cfgrib            # GRIB2 parsing for HGEFS
xarray            # GRIB2 data handling
eccodes           # GRIB2 binary library (cfgrib dependency)
pytz              # Timezone handling
python-dotenv     # Environment variable loading
asyncio           # Async WebSocket handling
aiohttp           # Async HTTP (optional, for parallel model fetching)
```

### Install command
```bash
pip3 install requests websockets cryptography scipy numpy pandas scikit-learn schedule cfgrib xarray eccodes pytz python-dotenv aiohttp
```

### Database
SQLite — file at `data/pipeline.db`. No server needed. Built into Python.

### Scheduling
Python `schedule` library for polling. `asyncio` for WebSocket.

---

## SECTION 6: ARCHITECTURE OVERVIEW

```
┌─────────────────────────────────────────────────────────────────────┐
│                     PIPELINE ARCHITECTURE                            │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              DATA INGEST LAYER (runs continuously)            │   │
│  │                                                               │   │
│  │  wethr_client.py        kalshi_client.py    model_fetcher.py │   │
│  │  ─────────────────       ─────────────────   ──────────────── │   │
│  │  • Latest obs (60s)     • REST price poll   • HGEFS NOMADS   │   │
│  │  • Wethr High (60s)       (30min)           • NBM bulletin    │   │
│  │  • DSM filter (60s)     • WebSocket         • HRRR from       │   │
│  │  • CLI filter (60s)       orderbook         • wethr.net API   │   │
│  │  • HRRR latest (5min)     (continuous)                        │   │
│  │  • NBM latest (5min)    teleconn_fetcher.py                   │   │
│  │  • NWS version (5min)   ──────────────────                    │   │
│  │  • All models (30min)   • BoM MJO (daily)                     │   │
│  │  • History (daily)      • CPC AO/NAO/PNA                      │   │
│  │                         • ONI monthly                          │   │
│  └────────────────────────────┬─────────────────────────────────┘   │
│                                │ All data → SQLite database          │
│                                ▼                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    DATA STORE (pipeline.db)                   │    │
│  │  model_runs | metar_observations | kalshi_prices |            │    │
│  │  gate_checks | signals | paper_trades | teleconnections |     │    │
│  │  dsm_reports | cli_reports | performance_daily               │    │
│  └────────────────────────────┬────────────────────────────────┘    │
│                                │                                      │
│                                ▼                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │              SIGNAL ENGINE (event-driven)                     │    │
│  │                                                               │    │
│  │  event_triggers.py detects when to run gates:                │    │
│  │  • New HRRR run detected                                      │    │
│  │  • New HGEFS cycle available                                  │    │
│  │  • NWS forecast version increments                            │    │
│  │  • Temperature anomaly > 1.5°F from trajectory                │    │
│  │  • Kalshi price moves > 5¢ in 30 minutes                     │    │
│  │  • DSM detected                                               │    │
│  │  • Fallback: 11 AM ET if no trigger fired                     │    │
│  │                                                               │    │
│  │  gate_checker.py runs all 6 gates:                           │    │
│  │  Gate 1: HGEFS physics vs AI ≤ 1.5°F                        │    │
│  │  Gate 2: Gumbel gap > 20pp (not in 35-40pp dead zone)       │    │
│  │  Gate 3: Price 25¢-75¢                                       │    │
│  │  Gate 4: Dead zone exclusion                                  │    │
│  │  Gate 5: METAR at 9:51 AM within threshold                   │    │
│  │  Gate 6: No evening reversal pattern                          │    │
│  │                                                               │    │
│  │  gumbel_model.py computes probabilities:                     │    │
│  │  • NBM p50 as Bayesian prior                                  │    │
│  │  • HGEFS consensus as likelihood update                       │    │
│  │  • Gumbel distribution (mu = consensus - 0.45, beta = 0.742) │    │
│  │  • Isotonic regression calibration (rolling 90-day)          │    │
│  └────────────────────────────┬────────────────────────────────┘    │
│                                │ Signals → database                   │
│                                ▼                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │              PAPER TRADER (simulator.py)                      │    │
│  │                                                               │    │
│  │  On signal:                                                   │    │
│  │  • Calculate position size (Quarter-Kelly, max 5% bankroll)   │    │
│  │  • Simulate limit order entry at current Kalshi price         │    │
│  │  • Place simulated 68¢ limit sell                             │    │
│  │  • Monitor exit conditions every 60 seconds                   │    │
│  │  • Calculate P&L with ceiling-rounded maker fees              │    │
│  │  • Cancel all orders at 4:15 PM ET                            │    │
│  │  • Record settlement vs CLI next morning                      │    │
│  └────────────────────────────┬────────────────────────────────┘    │
│                                │                                      │
│                                ▼                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │              DASHBOARD (daily_report.py)                      │    │
│  │  • Prints daily summary at 8 AM ET                            │    │
│  │  • Signals generated, trades taken, wins, losses             │    │
│  │  • Net P&L, win rate, Sharpe, max drawdown                   │    │
│  │  • Model accuracy (Brier score, CRPS)                         │    │
│  │  • Bankroll remaining                                          │    │
│  └─────────────────────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────────────────┘
```

---

## SECTION 7: DATA SOURCES (EVERY SOURCE, FULLY DOCUMENTED)

### 7.1 wethr.net Pro REST API (Primary Hub)

**Base URL:** `https://wethr.net/api/v2/`
**Authentication:** `Authorization: Bearer {WETHR_API_KEY}` in HTTP header
**Rate limits:** 60 requests/minute, 5,000 requests/day
**Tier:** Professional ($24.99/month)
**Push API:** BETA — NOT deployed as of April 25, 2026. Do NOT attempt WebSocket connection.

#### Endpoint 1: Latest Observation
```
GET https://wethr.net/api/v2/observations.php?station_code=KNYC&mode=latest

Confirmed response format (April 25, 2026):
{
  "id": 337441745,
  "station_code": "KNYC",
  "observation_time": "2026-04-25 06:51:00",    # UTC
  "temperature": 9.4,                             # CELSIUS
  "six_hour_high": null,                          # null until 6hr period closes
  "six_hour_low": null,
  "twentyfour_hour_high": null,
  "twentyfour_hour_low": null,
  "dew_point": 5.6,                              # Celsius
  "wind_direction": "090",
  "wind_speed": "7.00",
  "wind_gust": null,
  "visibility": ...,
  "relative_humidity": ...,
  "units": "fahrenheit"                           # Note: temp is still in Celsius despite this
}

IMPORTANT: temperature field is in CELSIUS. Convert: temp_f = temp_c * 9/5 + 32
```

#### Endpoint 2: Wethr High (Most Important)
```
GET https://wethr.net/api/v2/observations.php?station_code=KNYC&mode=wethr_high&logic=nws

Confirmed response format:
{
  "station_code": "KNYC",
  "date": "2026-04-25",
  "wethr_high": 50,           # INTEGER °F — confirmed high for the day
  "wethr_low": 49,            # INTEGER °F
  "time_of_high_utc": "2026-04-25 05:51:00",
  "time_of_low_utc": "2026-04-25 06:51:00",
  "calculation_logic": "nws",
  "units": "fahrenheit"
}

logic=nws: Uses Standard Time year-round. Includes DSM, CLI, 6-hour highs, AND OMO data.
logic=wu: Uses Local Time. Weather Underground/Polymarket logic.
ALWAYS use logic=nws for Kalshi settlement prediction.
wethr_high already incorporates OMO data (1-minute obs). OMO raw API not available until Q3 2026.
Caution flag: if DSM is potentially erroneous, response may include caution_flag=true. Treat as elevated risk.
```

#### Endpoint 3: DSM Detection
```
GET https://wethr.net/api/v2/observations.php?station_code=KNYC&mode=latest&observation_type=dsm_high

Confirmed response (when DSM has fired):
{
  "id": 336089154,
  "station_code": "KNYC",
  "observation_time": "2026-04-24 19:23:00",   # UTC when DSM was recorded
  "temperature": 20,                              # Celsius DSM high
  "dsm_high": 20,
  "dsm_high_display": 68,                        # Fahrenheit display value
  ...
}

DSM for NYC fires at approximately:
  4:21 PM ET (20:21 UTC during DST)
  5:21 PM ET (21:21 UTC during DST)
  1:17 AM ET (05:17 UTC during DST)

Poll this endpoint every 60 seconds. When observation_type=dsm_high returns
a new dsm_high value with today's date, DSM has fired. This triggers:
  1. Log to dsm_reports table
  2. Cancel any unfilled paper trade orders
  3. Update Wethr High
```

#### Endpoint 4: CLI Detection
```
GET https://wethr.net/api/v2/observations.php?station_code=KNYC&mode=latest&observation_type=cli_high

Same format as DSM. CLI releases next morning ~7-8 AM ET.
When CLI fires: record official settlement temperature to cli_reports table.
This is the final P&L settlement for previous day's paper trades.
```

#### Endpoint 5: History
```
GET https://wethr.net/api/v2/observations.php?station_code=KNYC&mode=history&start_time=2026-04-24 00:00:00&end_time=2026-04-24 23:59:59

CRITICAL: Must provide BOTH start_time AND end_time (not just date).
Confirmed working. Returns list of 25 hourly observations.
Use for calibration and model training.
```

#### Endpoint 6: HRRR Forecast
```
GET https://wethr.net/api/v2/forecasts.php?location_name=KNYC&model=HRRR&run=latest

Confirmed response format:
[
  {
    "id": 132965707,
    "model": "HRRR",
    "location_name": "KNYC",
    "latitude": "40.779167",
    "longitude": "-73.969167",
    "run_time": "2026-04-25 05:00:00",      # UTC — when this model run initialized
    "valid_time": "2026-04-25 05:00:00",    # UTC — when forecast is valid
    "forecast_hour": 0,                      # Hours from run_time
    "temperature_k": "282.45",              # Kelvin
    "temperature_f": "48.75",               # Fahrenheit (use this)
    "temperature_c": "9.30",               # Celsius
    "inserted_at": "2026-04-25 ..."
  },
  ... (one record per forecast hour)
]

X-Run-Time response header: the resolved run cycle (e.g., "2026-04-25 05:00:00")
HRRR runs every hour. Always has fresh data.
TRIGGER: when run_time changes → new HRRR run → check gates.

To get MaxT for a calendar day:
1. Filter forecast hours to those valid between 00:00 and 24:00 ET on target date
2. Take max of temperature_f across those hours
3. This is the HRRR MaxT forecast for that day
```

#### Endpoint 7: All Other Models
```
GET https://wethr.net/api/v2/forecasts.php?location_name=KNYC&model={MODEL}&run=latest

Confirmed available for KNYC (tested April 25, 2026 ~2AM ET):
  Always live (hourly models): HRRR, NBM
  Available during trading hours: GFS, ECMWF, NAM, ICON, UKMO, ARPEGE, JMA

Models confirmed empty at 2AM ET (timing, not broken): GFS, NAM, ECMWF, GEM, RAP
These will return data when their cycle runs (GFS: 00Z/06Z/12Z/18Z = 7PM/1AM/7AM/1PM ET)

Handle empty arrays gracefully: if response is [], skip and use available models only.
```

#### Endpoint 8: NWS Forecast Evolution
```
GET https://wethr.net/api/v2/nws_forecasts.php?station_code=KNYC

Confirmed response format:
{
  "station_code": "KNYC",
  "station_name": "New York (Central Park)",
  "timezone": "America/New_York",
  "timezone_offset_hours": -5,
  "forecast_date": "2026-04-25",
  "version": 6,                               # NWS has updated 6 times today
  "hourly_temps": [null, 51, 51, 50, 50, 49, 50, 49, 49, 48, 49, 49, 50, 49, 51, 48, 48, 47, 46, 45, 45, 44, 45, 45, 45],
  "high": ...                                 # truncated in test
}

version field: increment = NWS issued new forecast.
TRIGGER: poll every 5 minutes. If version > last_seen_version → run all gates.
hourly_temps: array of 25 values (midnight=0 through midnight=24), each is °F or null.
Index 0 = midnight, index 13 = 1 PM, etc.
Note: KNYC shows 11:51 AM observation at the 12 PM slot (confirmed in wethr.net update log).
```

### 7.2 Kalshi API

**REST Base URL:** `https://api.elections.kalshi.com/trade-api/v2`
**WebSocket URL:** `wss://api.elections.kalshi.com/trade-api/v2/ws`
**Authentication:** RSA-PSS signing — REQUIRED for ALL endpoints including WebSocket

#### RSA Authentication Implementation
```python
import time
import base64
import os
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

def get_kalshi_headers(method: str, path: str) -> dict:
    """Generate RSA-PSS signed headers for Kalshi API."""
    key_path = os.environ['KALSHI_KEY_PATH']
    key_id = os.environ['KALSHI_API_KEY']

    with open(key_path, 'rb') as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)

    ts = str(int(time.time() * 1000))  # MILLISECONDS — not seconds
    msg = f"{ts}{method}{path}".encode()

    sig = private_key.sign(
        msg,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH
        ),
        hashes.SHA256()
    )

    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        "Content-Type": "application/json"
    }

# Usage:
headers = get_kalshi_headers("GET", "/trade-api/v2/portfolio/balance")
r = requests.get("https://api.elections.kalshi.com/trade-api/v2/portfolio/balance",
                 headers=headers)
```

#### Key REST Endpoints
```python
# Balance (confirmed working)
GET /trade-api/v2/portfolio/balance
Response: {"balance": 1000, "portfolio_value": 0, "updated_ts": 1777099371}
# balance = cents * 10. 1000 = $10.00

# Get active weather markets for NYC
GET /trade-api/v2/markets?series_ticker=KXHIGHNY&status=active
Response: {"markets": [{
    "ticker": "KXHIGHNY-26APR25-B68",
    "series_ticker": "KXHIGHNY",
    "status": "active",
    "yes_bid": 23,        # cents
    "yes_ask": 25,
    "no_bid": 75,
    "no_ask": 77,
    "last_price": 24,
    "volume": 1250,
    "expiration_time": "2026-04-25T23:59:59Z",
    "strike_type": "greater",    # or "between" for range brackets
    "floor_strike": 68,
    "cap_strike": null,          # null for tail brackets
    "fee_type": "quadratic",
    "fee_multiplier": 1
}]}

# Market orderbook
GET /trade-api/v2/markets/{ticker}/orderbook
Response: {
    "orderbook": {
        "yes": [[price_cents, quantity], ...],   # bid ladder
        "no": [[price_cents, quantity], ...]     # bid ladder
    }
}
# Implied YES ask = 100 - best_no_bid (in cents)
# Implied NO ask = 100 - best_yes_bid (in cents)
# NEVER use float — use decimal.Decimal for ALL price arithmetic
```

#### WebSocket Implementation
```python
import asyncio
import json
import websockets
from decimal import Decimal

class KalshiOrderBook:
    def __init__(self, ticker: str):
        self.ticker = ticker
        self.yes_bids = {}  # price (Decimal) -> quantity (Decimal)
        self.no_bids = {}
        self.last_seq = None
        self.connected = False

    def apply_snapshot(self, msg: dict):
        """Apply full orderbook snapshot."""
        data = msg['msg']
        self.yes_bids = {}
        self.no_bids = {}
        for price_str, qty_str in data.get('yes_dollars_fp', []):
            price = Decimal(price_str)
            qty = Decimal(qty_str)
            if qty > 0:
                self.yes_bids[price] = qty
        for price_str, qty_str in data.get('no_dollars_fp', []):
            price = Decimal(price_str)
            qty = Decimal(qty_str)
            if qty > 0:
                self.no_bids[price] = qty
        self.last_seq = msg['seq']

    def apply_delta(self, msg: dict):
        """Apply incremental delta."""
        if self.last_seq and msg['seq'] > self.last_seq + 1:
            raise Exception(f"Sequence gap: expected {self.last_seq + 1}, got {msg['seq']}")
        data = msg['msg']
        price = Decimal(data['price_dollars'])
        delta = Decimal(data['delta_fp'])
        side = data['side']
        book = self.yes_bids if side == 'yes' else self.no_bids
        current = book.get(price, Decimal('0'))
        new_qty = current + delta
        if new_qty <= 0:
            book.pop(price, None)
        else:
            book[price] = new_qty
        self.last_seq = msg['seq']

    @property
    def best_yes_bid(self) -> Decimal:
        if not self.yes_bids:
            return Decimal('0')
        return max(self.yes_bids.keys())

    @property
    def best_no_bid(self) -> Decimal:
        if not self.no_bids:
            return Decimal('0')
        return max(self.no_bids.keys())

    @property
    def yes_ask(self) -> Decimal:
        """Implied YES ask = 1.00 - best NO bid."""
        return Decimal('1.00') - self.best_no_bid

    @property
    def spread(self) -> Decimal:
        return self.yes_ask - self.best_yes_bid


async def run_kalshi_websocket(tickers: list, key_id: str, key_path: str):
    """Run Kalshi WebSocket orderbook with auto-reconnect."""
    books = {ticker: KalshiOrderBook(ticker) for ticker in tickers}
    backoff = 1

    while True:
        try:
            headers = get_kalshi_headers("GET", "/trade-api/v2/ws")
            url = "wss://api.elections.kalshi.com/trade-api/v2/ws"

            async with websockets.connect(url, additional_headers=headers,
                                          ping_interval=20) as ws:
                backoff = 1
                # Subscribe to all tickers
                await ws.send(json.dumps({
                    "id": 1,
                    "cmd": "subscribe",
                    "params": {
                        "channels": ["orderbook_delta"],
                        "market_tickers": tickers
                    }
                }))

                async for raw in ws:
                    msg = json.loads(raw)
                    t = msg.get('type')
                    ticker = msg.get('msg', {}).get('market_ticker')

                    if ticker not in books:
                        continue

                    if t == 'orderbook_snapshot':
                        books[ticker].apply_snapshot(msg)
                    elif t == 'orderbook_delta':
                        try:
                            books[ticker].apply_delta(msg)
                        except Exception as e:
                            # Sequence gap — resubscribe
                            await ws.send(json.dumps({
                                "id": 2, "cmd": "subscribe",
                                "params": {"channels": ["orderbook_delta"],
                                           "market_tickers": [ticker]}
                            }))
                    # Save to database every update
                    yield ticker, books[ticker]

        except Exception as e:
            print(f"WebSocket error: {e}. Reconnecting in {backoff}s")
            await asyncio.sleep(min(backoff, 60))
            backoff = min(backoff * 2, 60)
```

### 7.3 HGEFS via NOMADS HTTPS

**CRITICAL:** S3 bucket `noaa-hgefs-pds` does NOT exist as of April 25, 2026.
Must use NOMADS HTTPS with `.idx` byte-range subsetting.

```python
import requests

NOMADS_BASE = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/hgefs/prod"
CENTRAL_PARK_LAT = 40.7789
CENTRAL_PARK_LON = 286.0308  # 360-degree grid: -73.9692 + 360 = 286.0308

def get_hgefs_file_url(date_str: str, cycle: str, member: str, fhr: int) -> str:
    """
    date_str: "20260425"
    cycle: "00", "06", "12", "18"
    member: "c00" or "p01" through "p61"
    fhr: forecast hour (0-384)
    """
    return f"{NOMADS_BASE}/hgefs.{date_str}/{cycle}/hgefs{member}.t{cycle}z.pgrb2.0p25.f{fhr:03d}"

def get_maxt_bytes(url: str) -> bytes:
    """Download only the tmax bytes using .idx byte-range subsetting."""
    idx_url = url + ".idx"
    idx_content = requests.get(idx_url, timeout=30).text.splitlines()

    start_byte = None
    end_byte = None
    for i, line in enumerate(idx_content):
        if ':TMAX:2 m above ground:' in line and ':max fcst:' in line:
            start_byte = int(line.split(':')[1])
            if i + 1 < len(idx_content):
                end_byte = int(idx_content[i+1].split(':')[1]) - 1
            break

    if start_byte is None:
        return None  # Field not found

    headers = {"Range": f"bytes={start_byte}-{end_byte}" if end_byte else f"bytes={start_byte}-"}
    return requests.get(url, headers=headers, timeout=60).content

def extract_maxt_at_point(grib_bytes: bytes, lat: float, lon: float) -> float:
    """Extract MaxT for a specific lat/lon from GRIB2 bytes."""
    import xarray as xr
    import tempfile, os

    with tempfile.NamedTemporaryFile(suffix='.grib2', delete=False) as f:
        f.write(grib_bytes)
        tmp_path = f.name

    try:
        ds = xr.open_dataset(tmp_path, engine='cfgrib',
            backend_kwargs={'filter_by_keys': {
                'shortName': 'tmax',
                'typeOfLevel': 'heightAboveGround',
                'level': 2,
                'stepType': 'max'
            },
            'indexpath': ''})  # disable cache on read-only fs
        val_K = ds['tmax'].interp(latitude=lat, longitude=lon).values.item()
        return (val_K - 273.15) * 9/5 + 32  # Convert K → °F
    finally:
        os.unlink(tmp_path)

def get_all_hgefs_members_maxt(date_str: str, cycle: str,
                                 target_date_et: str) -> dict:
    """
    Get MaxT from all 62 HGEFS members for a target date.
    Returns: {
        'physics_members': {'c00': 68.5, 'p01': 67.2, ...},
        'ai_members': {'p31': 69.1, 'p32': 68.8, ...},
        'physics_mean': 68.1,
        'physics_spread': 2.1,
        'ai_mean': 69.0,
        'ai_spread': 1.8
    }
    """
    import numpy as np

    # Members: c00 + p01-p30 = physics (31)
    #          p31-p61 = AI (31)
    all_members = ['c00'] + [f'p{i:02d}' for i in range(1, 62)]
    physics_members = ['c00'] + [f'p{i:02d}' for i in range(1, 31)]
    ai_members = [f'p{i:02d}' for i in range(31, 62)]

    # Forecast hours covering target date ET (rough approximation)
    # 12Z cycle: f12-f36 covers next local day
    fhrs = [12, 15, 18, 21, 24, 27, 30, 33, 36]

    member_maxt = {}
    for member in all_members:
        member_max = -9999
        for fhr in fhrs:
            try:
                url = get_hgefs_file_url(date_str, cycle, member, fhr)
                grib_bytes = get_maxt_bytes(url)
                if grib_bytes:
                    t = extract_maxt_at_point(grib_bytes,
                                               CENTRAL_PARK_LAT,
                                               CENTRAL_PARK_LON)
                    member_max = max(member_max, t)
            except Exception as e:
                print(f"HGEFS {member} f{fhr}: {e}")
        if member_max > -9999:
            member_maxt[member] = member_max

    physics = [member_maxt[m] for m in physics_members if m in member_maxt]
    ai = [member_maxt[m] for m in ai_members if m in member_maxt]

    return {
        'physics_members': {m: member_maxt[m] for m in physics_members if m in member_maxt},
        'ai_members': {m: member_maxt[m] for m in ai_members if m in member_maxt},
        'physics_mean': np.mean(physics) if physics else None,
        'physics_spread': np.std(physics) if physics else None,
        'ai_mean': np.mean(ai) if ai else None,
        'ai_spread': np.std(ai) if ai else None,
    }
```

### 7.4 NBM Text Bulletin (Bayesian Prior)

```python
import requests

def get_nbm_maxt_percentiles(date_str: str, cycle: str, station: str = 'KNYC') -> dict:
    """
    Get NBM probabilistic MaxT percentiles for a station.
    date_str: "20260425"
    cycle: "00" through "23"
    station: "KNYC"

    Returns:
    {
        'p10': 62.0, 'p25': 65.0, 'p50': 68.0,
        'p75': 71.0, 'p90': 74.0,
        'run_time': '2026-04-25 00:00:00'
    }
    """
    url = (f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/"
           f"blend.{date_str}/{cycle}/text/blend_nbptx.t{cycle}z")

    try:
        text = requests.get(url, timeout=30).text
    except Exception as e:
        return None

    # Parse the station block
    lines = text.split('\n')
    station_block = None
    for i, line in enumerate(lines):
        if line.strip().startswith(station):
            station_block = lines[i:i+50]
            break

    if not station_block:
        return None

    # Parse percentile fields
    result = {'run_time': f"2026-{date_str[4:6]}-{date_str[6:8]} {cycle}:00:00"}
    for line in station_block:
        if 'TXNP1' in line:
            result['p10'] = float(line.split()[-1])
        elif 'TXNP2' in line:
            result['p25'] = float(line.split()[-1])
        elif 'TXNP5' in line:
            result['p50'] = float(line.split()[-1])
        elif 'TXNP7' in line:
            result['p75'] = float(line.split()[-1])
        elif 'TXNP9' in line:
            result['p90'] = float(line.split()[-1])

    return result if 'p50' in result else None

# NBM v5.0 went operational April 15, 2026
# Treat this as a calibration reset point for isotonic regression
# NBM updates every hour — always fresh data available
```

### 7.5 CPC Teleconnection Indices

```python
import requests
import pandas as pd
import io

def fetch_mjo_rmm() -> pd.DataFrame:
    """
    BoM Wheeler-Hendon RMM index — daily, stable URL.
    Returns DataFrame with columns: year, month, day, RMM1, RMM2, phase, amplitude
    Filter out rows where amplitude == 999 (missing data sentinel)
    """
    url = "http://www.bom.gov.au/climate/mjo/graphics/rmm.74toRealtime.txt"
    text = requests.get(url, timeout=30).text
    df = pd.read_csv(io.StringIO(text), skiprows=2, sep=r'\s+',
                     names=['year','month','day','RMM1','RMM2','phase','amplitude','missing'])
    df = df[df['amplitude'] < 999]  # Remove missing sentinels
    df['date'] = pd.to_datetime(df[['year','month','day']])
    df = df.set_index('date')
    return df[['RMM1','RMM2','phase','amplitude']]

def fetch_oni() -> pd.DataFrame:
    """
    CPC Oceanic Nino Index — monthly.
    Returns DataFrame with columns: season, year, total, anomaly
    """
    url = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
    text = requests.get(url, timeout=30).text
    df = pd.read_csv(io.StringIO(text), sep=r'\s+')
    df.columns = [c.strip() for c in df.columns]
    return df

def fetch_teleconnections_monthly() -> pd.DataFrame:
    """
    CPC NH teleconnection indices — monthly.
    Columns include: NAO, EA, WP, EP, PNA, EAWR, SCA, TNH, POL
    """
    url = "https://ftp.cpc.ncep.noaa.gov/wd52dg/data/indices/tele_index.nh"
    try:
        text = requests.get(url, timeout=30).text
        df = pd.read_fwf(io.StringIO(text), skiprows=18, header=None,
                         names=['year','month','NAO','EA','EAJET','WP','EP','NP',
                                'PNA','EAWR','SCA','TNH','POL','PT','SZ','ASU'])
        df = df[df['NAO'] != -9.9]  # Remove sentinels
        df['date'] = pd.to_datetime(df[['year','month']].assign(day=1))
        return df.set_index('date')
    except Exception as e:
        print(f"Teleconnection fetch error: {e}")
        return None

def build_teleconn_features(target_date: str) -> dict:
    """Build teleconnection feature dict for a target date."""
    target = pd.Timestamp(target_date)
    features = {}

    try:
        rmm = fetch_mjo_rmm()
        for lag in [0, 7, 10, 14]:
            d = target - pd.Timedelta(days=lag)
            if d in rmm.index:
                features[f'mjo_rmm1_lag{lag}'] = float(rmm.loc[d, 'RMM1'])
                features[f'mjo_rmm2_lag{lag}'] = float(rmm.loc[d, 'RMM2'])
                features[f'mjo_amplitude_lag{lag}'] = float(rmm.loc[d, 'amplitude'])
                features[f'mjo_phase_lag{lag}'] = int(rmm.loc[d, 'phase'])
    except Exception as e:
        print(f"MJO fetch error: {e}")

    try:
        tele = fetch_teleconnections_monthly()
        if tele is not None:
            last = tele.iloc[-1]
            for v in ['NAO','PNA','WP','EP','TNH','POL']:
                if v in last:
                    features[f'{v.lower()}_monthly'] = float(last[v])
    except Exception as e:
        print(f"Teleconn fetch error: {e}")

    try:
        oni = fetch_oni()
        features['oni_monthly'] = float(oni.iloc[-1]['ANOM'])
    except Exception as e:
        print(f"ONI fetch error: {e}")

    return features

# Update schedule: once daily at 6 AM ET
# CPC daily AO/NAO/PNA URLs are unstable — wrap in try/except
# Cache last known values locally in database as fallback
```

---

## SECTION 8: STRATEGY RULES (ALL PARAMETERS CONFIRMED)

### Market Being Traded
- **Primary:** KXHIGHNY — NYC Central Park daily high temperature on Kalshi
- **Settlement:** NWS Daily Climate Report (CLI) for KNYC station
- **Brackets:** 6 per day — 4 narrow 2°F range brackets + 2 wide tail brackets

### Entry Parameters (All Confirmed in Backtest)
```
Strategy type:     Event-driven (trigger-based, not fixed time)
Fallback time:     11 AM ET if no trigger fires
Entry order type:  Limit order (maker fee = 4x cheaper than taker)
Exit target:       68¢ — place limit sell IMMEDIATELY at entry
Stop loss:         Entry price - 20¢
Max hold time:     11:00 PM ET
DSM cancel time:   4:15 PM ET (before 4:21 PM DSM bot)
Never hold above:  70¢ (NWS error risk)
```

### Gap Thresholds (Confirmed in Backtest on 806,295 Trades)
```
Required gap:  > 20 percentage points
Dead zone:     35-40pp (confirmed negative P&L — SKIP)
Sweet spots:   20-25pp and 40pp+
Positive gap:  YES trade (model says more likely than market)
Negative gap:  NO trade (model says less likely than market)
```

### Price Band (Confirmed)
```
YES entry min: 25¢ (below this = longshot trap — 60%+ capital loss per UCD paper)
YES entry max: 75¢ (above this = NWS error risk)
```

### Gumbel Parameters (Confirmed Optimal)
```
mu   = consensus_temp_f - 0.45   (NOT -0.5)
beta = 0.742                       (= 0.95/1.28 ECMWF MAE / Gumbel scale factor)

Model biases (apply before computing consensus):
ECMWF: MAE = 0.95°F, bias = -0.42°F (runs cold) → add 0.42 to ECMWF forecast
GFS:   MAE = 1.58°F, bias = +0.47°F (runs warm) → subtract 0.47 from GFS forecast
HRRR:  summer warm bias ~1.5°F → subtract 1.5 in June-August
```

### Backtest Results (806,295 Kalshi Trades, Oct 2024 - Nov 2025)
```
Total trades:    260
Win rate:        60.0%
Net P&L:         +$427
Sharpe:          4.72 (NYC)
Max drawdown:    -$46

City Sharpe ratios:
  NYC (KNYC):  4.72  ← Trade this
  PHL (KPHL):  2.83  ← Trade as secondary
  Denver:      1.58  ← Only when above are unavailable
  Austin:      -1.57 ← NEVER TRADE

Seasonal P&L:
  Oct 2024 - Jul 2025: +$52 (nearly flat, 10 months)
  Aug 2025:  +$42
  Sep 2025:  +$53 (best month)
  Oct 2025:  +$23
  Nov 2025:  +$33
  93% of profit in Aug-Nov shoulder season

Gap performance:
  20-25pp: profitable
  25-35pp: profitable
  35-40pp: NEGATIVE ← dead zone
  40pp+:   profitable
```

### Settlement Rules
```
DST: During Daylight Saving Time, Kalshi CLI measures 1 AM to 1 AM ET (not midnight)
     This is because CLI uses Local Standard Time (LST) year-round.
     Check dst_active flag when calculating settlement window.

Finality: CFTC rule — revisions to NWS after Expiration NOT counted.
          Once Kalshi's snapshot is taken, even corrected NWS data doesn't change settlement.

Review delays: Settlement delayed when preliminary high inconsistent with 6-hr METAR.
```

---

## SECTION 9: THE 6-GATE SIGNAL SYSTEM (COMPLETE)

### Gate 1 — HGEFS Convergence Check

**Purpose:** Ensure physics and AI ensemble members agree. When they disagree, genuine atmospheric uncertainty exists and edge collapses.

```python
def check_gate_1(physics_mean: float, physics_spread: float,
                  ai_mean: float, ai_spread: float) -> tuple[bool, dict]:
    """
    Returns (pass: bool, details: dict)
    """
    spread_between = abs(physics_mean - ai_mean)
    gate_pass = (
        spread_between <= 1.5 and
        physics_spread < 3.0 and
        ai_spread < 3.0
    )
    return gate_pass, {
        'physics_mean': physics_mean,
        'physics_spread': physics_spread,
        'ai_mean': ai_mean,
        'ai_spread': ai_spread,
        'spread_between': spread_between,
        'pass': gate_pass,
        'reason': 'pass' if gate_pass else f'spread {spread_between:.2f}°F exceeds threshold'
    }

# Fallback for when HGEFS is unavailable:
# Use wethr.net model comparison: require 4 of 6 models within 2°F
# Models: HRRR, NBM, GFS, ECMWF, ICON, NAM
# Count models within 2°F of median. Pass if count >= 4.
```

### Gate 2 — Gumbel Gap Filter

**Purpose:** Ensure our probability estimate differs from market price by enough to cover fees and uncertainty.

```python
from scipy.stats import gumbel_r

def compute_gumbel_probability(bracket_lo: float, bracket_hi: float,
                                 consensus_temp_f: float,
                                 bracket_type: str = 'range') -> float:
    """
    Compute P(temperature in bracket) using Gumbel distribution.

    bracket_lo, bracket_hi: bracket boundaries in °F
    consensus_temp_f: model consensus temperature in °F
    bracket_type: 'range', 'lower_tail', 'upper_tail'

    Returns: probability 0.0 to 1.0
    """
    mu = consensus_temp_f - 0.45
    beta = 0.742

    if bracket_type == 'range':
        return gumbel_r.cdf(bracket_hi + 0.5, mu, beta) - \
               gumbel_r.cdf(bracket_lo - 0.5, mu, beta)
    elif bracket_type == 'lower_tail':
        return gumbel_r.cdf(bracket_lo - 0.5, mu, beta)
    elif bracket_type == 'upper_tail':
        return 1 - gumbel_r.cdf(bracket_hi + 0.5, mu, beta)

def apply_bayesian_update(gumbel_prob: float, nbm_p50: float,
                           nbm_p10: float, nbm_p90: float,
                           bracket_lo: float, bracket_hi: float) -> float:
    """
    Update Gumbel probability with NBM probabilistic prior.
    Returns calibrated probability.
    """
    # Simple weighted blend: 60% HGEFS Gumbel, 40% NBM
    mu_nbm = nbm_p50 - 0.45
    beta_nbm = (nbm_p90 - nbm_p10) / 4.0  # rough sigma from IQR

    nbm_prob = gumbel_r.cdf(bracket_hi + 0.5, mu_nbm, beta_nbm) - \
               gumbel_r.cdf(bracket_lo - 0.5, mu_nbm, beta_nbm)

    return 0.6 * gumbel_prob + 0.4 * nbm_prob

def apply_isotonic_calibration(raw_prob: float, calibrator) -> float:
    """Apply fitted isotonic regression calibrator."""
    if calibrator is None:
        return raw_prob
    import numpy as np
    return float(calibrator.predict(np.array([raw_prob]).reshape(-1, 1))[0])

def check_gate_2(model_prob: float, market_price: float) -> tuple[bool, dict]:
    """
    model_prob: our calibrated probability (0.0 to 1.0)
    market_price: Kalshi YES price in cents divided by 100 (0.25 to 0.75)
    """
    gap_pp = (model_prob - market_price) * 100
    gate_pass = abs(gap_pp) > 20.0

    if gap_pp > 0:
        direction = 'YES'
    else:
        direction = 'NO'

    return gate_pass, {
        'model_prob': model_prob,
        'market_price': market_price,
        'gap_pp': gap_pp,
        'direction': direction,
        'pass': gate_pass
    }
```

### Gate 3 — Price Band Filter

```python
def check_gate_3(yes_price: float) -> tuple[bool, dict]:
    """
    yes_price: Kalshi YES price as decimal (0.25 to 0.75)
    """
    gate_pass = 0.25 <= yes_price <= 0.75
    return gate_pass, {
        'yes_price': yes_price,
        'pass': gate_pass,
        'reason': 'pass' if gate_pass else
                  ('longshot_trap' if yes_price < 0.25 else 'nws_error_risk')
    }
```

### Gate 4 — Dead Zone Exclusion

```python
def check_gate_4(gap_pp: float) -> tuple[bool, dict]:
    """
    Skip if gap is in the 35-40pp dead zone.
    Confirmed negative P&L in every backtest configuration for this range.
    """
    in_dead_zone = 35.0 <= abs(gap_pp) <= 40.0
    gate_pass = not in_dead_zone
    return gate_pass, {
        'gap_pp': gap_pp,
        'in_dead_zone': in_dead_zone,
        'pass': gate_pass
    }
```

### Gate 5 — METAR Confirmation (9:51 AM ET)

```python
def check_gate_5(metar_temp_f: float, bracket_center_f: float,
                  direction: str) -> tuple[bool, dict]:
    """
    metar_temp_f: 9:51 AM ET temperature reading from wethr.net
    bracket_center_f: midpoint of the target bracket in °F
    direction: 'YES' or 'NO'

    Observation priority (use highest available):
    1. SPECI (obs_type='SPECI')
    2. Hourly XX:51-XX:54 (obs_type='hourly')
    3. 6-hourly METAR (obs_type='6hour')
    4. 5-minute reading (obs_type='5min') — use cautiously
    """
    distance = abs(metar_temp_f - bracket_center_f)

    if direction == 'YES':
        gate_pass = distance <= 8.0
    else:  # NO trade
        gate_pass = distance > 3.0

    return gate_pass, {
        'metar_temp_f': metar_temp_f,
        'bracket_center_f': bracket_center_f,
        'distance': distance,
        'direction': direction,
        'pass': gate_pass
    }
```

### Gate 6 — Evening Reversal Check

```python
def check_gate_6(ticker: str, bracket_low_f: float,
                  price_history: list) -> tuple[bool, dict]:
    """
    Check for evening reversal pattern on cold brackets.
    price_history: list of (timestamp, yes_price) tuples since 3 PM ET

    Historical base rate from 806,295 trades:
    Cold brackets (<=52°F): 94 reversals → 0 YES, 92 NO = 98% NO rate
    """
    is_cold_bracket = bracket_low_f <= 52.0

    if not price_history or len(price_history) < 2:
        return True, {'pass': True, 'reversal_detected': False, 'reason': 'no_history'}

    prices = [p for _, p in price_history]
    max_price = max(prices)
    current_price = prices[-1]

    rose_10 = any(prices[i] >= prices[0] + 0.10 for i in range(len(prices)))
    fell_10 = rose_10 and (max_price - current_price >= 0.10)
    reversal_detected = rose_10 and fell_10

    if reversal_detected and is_cold_bracket:
        gate_pass = False
    else:
        gate_pass = True

    return gate_pass, {
        'is_cold_bracket': is_cold_bracket,
        'reversal_detected': reversal_detected,
        'max_price': max_price,
        'current_price': current_price,
        'pass': gate_pass,
        'reason': '98pct_no_rate_cold_bracket' if (not gate_pass) else 'pass'
    }
```

### Master Gate Checker

```python
def run_all_gates(physics_mean, physics_spread, ai_mean, ai_spread,
                   model_prob, market_price, yes_price,
                   metar_temp_f, bracket_center_f, bracket_low_f,
                   direction, price_history, ticker) -> dict:
    """Run all 6 gates and return complete result."""

    g1_pass, g1 = check_gate_1(physics_mean, physics_spread, ai_mean, ai_spread)
    g2_pass, g2 = check_gate_2(model_prob, market_price)
    g3_pass, g3 = check_gate_3(yes_price)
    g4_pass, g4 = check_gate_4(g2['gap_pp'])
    g5_pass, g5 = check_gate_5(metar_temp_f, bracket_center_f, direction)
    g6_pass, g6 = check_gate_6(ticker, bracket_low_f, price_history)

    all_pass = all([g1_pass, g2_pass, g3_pass, g4_pass, g5_pass, g6_pass])

    return {
        'all_pass': all_pass,
        'direction': g2['direction'],
        'gap_pp': g2['gap_pp'],
        'gate1': g1, 'gate2': g2, 'gate3': g3,
        'gate4': g4, 'gate5': g5, 'gate6': g6,
        'skip_reason': None if all_pass else
            next(f"gate{i+1}_fail" for i, g in enumerate(
                [g1_pass, g2_pass, g3_pass, g4_pass, g5_pass, g6_pass]
            ) if not g)
    }
```

---

## SECTION 10: DATABASE SCHEMA (ALL 10 TABLES)

**Database file:** `data/pipeline.db`
**Engine:** SQLite (built into Python)

```python
# data_store/schema.py

import sqlite3
import os

def create_database(db_path: str = 'data/pipeline.db'):
    """Create all database tables. Safe to call multiple times (IF NOT EXISTS)."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.executescript("""

    -- TABLE 1: Every weather model data pull
    CREATE TABLE IF NOT EXISTS model_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        run_time TEXT,                    -- model initialization time (UTC)
        model TEXT NOT NULL,             -- HGEFS, HRRR, NBM, GFS, ECMWF, etc.
        city TEXT NOT NULL,              -- KNYC, KPHL
        target_date TEXT,                -- date this forecast is for (YYYY-MM-DD)
        physics_mean REAL,               -- HGEFS: mean of physics members (°F)
        physics_spread REAL,             -- HGEFS: std dev of physics members
        ai_mean REAL,                    -- HGEFS: mean of AI members
        ai_spread REAL,                  -- HGEFS: std dev of AI members
        consensus_temp_f REAL,           -- final weighted consensus (°F)
        nbm_p10 REAL,                    -- NBM 10th percentile MaxT
        nbm_p25 REAL,                    -- NBM 25th percentile MaxT
        nbm_p50 REAL,                    -- NBM 50th percentile MaxT (primary prior)
        nbm_p75 REAL,                    -- NBM 75th percentile MaxT
        nbm_p90 REAL,                    -- NBM 90th percentile MaxT
        hrrr_maxt_f REAL,               -- HRRR forecast MaxT for target date
        gfs_maxt_f REAL,                -- GFS forecast MaxT
        ecmwf_maxt_f REAL,             -- ECMWF forecast MaxT
        raw_data_json TEXT,             -- Full API response
        source TEXT                     -- wethr_api, nomads, nbm_bulletin
    );

    -- TABLE 2: Every observation from wethr.net
    CREATE TABLE IF NOT EXISTS metar_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        station TEXT NOT NULL,           -- KNYC, KPHL
        observation_time TEXT,           -- observation timestamp (UTC from API)
        temp_c REAL,                     -- raw Celsius from API
        temp_f REAL,                     -- converted Fahrenheit
        obs_type TEXT,                   -- METAR, SPECI, DSM_HIGH, CLI_HIGH, WETHR_HIGH, 6HR_HIGH
        six_hour_high_f REAL,
        six_hour_low_f REAL,
        wethr_high_f REAL,               -- confirmed day high (from wethr_high mode)
        wethr_low_f REAL,
        dew_point_c REAL,
        wind_speed REAL,
        relative_humidity REAL,
        dsm_high_f REAL,                 -- present if DSM has fired
        cli_high_f REAL,                 -- present if CLI has fired
        caution_flag INTEGER DEFAULT 0, -- 1 if wethr.net flagged potential DSM error
        raw_json TEXT
    );

    -- TABLE 3: Every Kalshi price poll
    CREATE TABLE IF NOT EXISTS kalshi_prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        ticker TEXT NOT NULL,            -- KXHIGHNY-26APR25-T70
        city TEXT NOT NULL,
        target_date TEXT,                -- date this market is for
        bracket_label TEXT,              -- "68-70°F" or ">75°F"
        strike_lo REAL,                 -- lower bracket boundary
        strike_hi REAL,                 -- upper bracket boundary
        bracket_type TEXT,              -- central, wing_low, wing_high
        yes_bid TEXT,                   -- Decimal string (NEVER float)
        yes_ask TEXT,                   -- 1.00 - best_no_bid
        yes_last TEXT,
        no_bid TEXT,
        no_ask TEXT,
        spread TEXT,                    -- yes_ask - yes_bid
        spread_cents REAL,             -- spread in cents for filtering
        volume INTEGER,
        open_interest INTEGER,
        source TEXT                    -- websocket, rest_poll
    );

    -- TABLE 4: Every gate evaluation
    CREATE TABLE IF NOT EXISTS gate_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        city TEXT NOT NULL,
        ticker TEXT,
        target_date TEXT,
        trigger_reason TEXT,             -- new_hrrr, new_hgefs, nws_version, temp_anomaly, price_move, fallback_11am
        -- Gate 1
        gate1_pass INTEGER,
        gate1_physics_mean REAL,
        gate1_ai_mean REAL,
        gate1_spread_between REAL,
        gate1_physics_spread REAL,
        gate1_ai_spread REAL,
        -- Gate 2
        gate2_pass INTEGER,
        gate2_model_prob REAL,
        gate2_market_price REAL,
        gate2_gap_pp REAL,
        gate2_direction TEXT,
        -- Gate 3
        gate3_pass INTEGER,
        gate3_yes_price REAL,
        -- Gate 4
        gate4_pass INTEGER,
        gate4_in_dead_zone INTEGER,
        -- Gate 5
        gate5_pass INTEGER,
        gate5_metar_temp_f REAL,
        gate5_bracket_center_f REAL,
        gate5_distance REAL,
        -- Gate 6
        gate6_pass INTEGER,
        gate6_reversal_detected INTEGER,
        gate6_is_cold_bracket INTEGER,
        -- Overall
        all_pass INTEGER,
        signal_generated INTEGER,
        skip_reason TEXT
    );

    -- TABLE 5: Every entry signal generated
    CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        city TEXT NOT NULL,
        ticker TEXT NOT NULL,
        target_date TEXT,
        bracket TEXT,                   -- "68-70°F"
        bracket_lo REAL,
        bracket_hi REAL,
        direction TEXT,                 -- YES or NO
        entry_price REAL,              -- recommended entry (decimal)
        target_price REAL DEFAULT 0.68,
        stop_price REAL,               -- entry - 0.20
        model_prob REAL,               -- calibrated probability
        market_price REAL,             -- Kalshi YES price at signal time
        gap_pp REAL,
        confidence_score REAL,         -- 0-100 composite score
        physics_mean REAL,
        ai_mean REAL,
        nbm_p50 REAL,
        metar_temp_f REAL,
        nws_version INTEGER,
        trigger_reason TEXT,
        reasoning TEXT,                -- human-readable explanation
        status TEXT DEFAULT 'ACTIVE'   -- ACTIVE, HIT_TARGET, HIT_STOP, EXPIRED, CANCELLED
    );

    -- TABLE 6: Every simulated paper trade
    CREATE TABLE IF NOT EXISTS paper_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        signal_id INTEGER,
        city TEXT NOT NULL,
        ticker TEXT NOT NULL,
        target_date TEXT,
        bracket TEXT,
        direction TEXT,
        contracts INTEGER DEFAULT 1,
        stake_dollars REAL,            -- total capital at risk
        entry_time TEXT,
        entry_price REAL,
        exit_time TEXT,
        exit_price REAL,
        exit_reason TEXT,              -- TARGET, STOP, EXPIRED, DSM_CANCEL, TIME_LIMIT
        gross_pnl REAL,
        taker_fee_entry REAL,          -- ceil(0.07 * C * P * (1-P) * 100) / 100
        maker_fee_entry REAL,          -- ceil(0.0175 * C * P * (1-P) * 100) / 100
        taker_fee_exit REAL,
        maker_fee_exit REAL,
        net_pnl_maker REAL,           -- P&L using maker fees (our assumption)
        net_pnl_taker REAL,           -- P&L using taker fees (stress test)
        slippage_estimate REAL,       -- half-spread + 1 tick
        settlement_temp_f REAL,       -- actual CLI settlement temperature
        settled_correct INTEGER,      -- 1 if our direction was correct
        FOREIGN KEY (signal_id) REFERENCES signals(id)
    );

    -- TABLE 7: Daily teleconnection indices
    CREATE TABLE IF NOT EXISTS teleconnections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT UNIQUE NOT NULL,
        -- MJO
        mjo_rmm1 REAL, mjo_rmm2 REAL,
        mjo_phase INTEGER, mjo_amplitude REAL,
        -- Monthly indices (same value repeated for each day of month)
        nao REAL, pna REAL, ao REAL,
        epo REAL, wpo REAL, tnh REAL, pol REAL,
        -- ENSO
        oni REAL,
        -- Lag features (pre-computed for XGBoost)
        nao_lag1 REAL, pna_lag1 REAL, ao_lag1 REAL,
        nao_lag3 REAL, pna_lag3 REAL, ao_lag3 REAL,
        nao_lag7 REAL, pna_lag7 REAL, ao_lag7 REAL,
        mjo_amplitude_lag7 REAL, mjo_phase_lag7 INTEGER,
        mjo_amplitude_lag14 REAL, mjo_phase_lag14 INTEGER,
        source TEXT,
        updated_at TEXT DEFAULT (datetime('now'))
    );

    -- TABLE 8: DSM reports
    CREATE TABLE IF NOT EXISTS dsm_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        city TEXT NOT NULL,
        station TEXT,
        dsm_date TEXT,                  -- date DSM is reporting for
        dsm_fire_time_utc TEXT,         -- when DSM was detected
        max_temp_c REAL,               -- raw Celsius from API
        max_temp_f REAL,               -- converted Fahrenheit
        min_temp_c REAL,
        min_temp_f REAL,
        caution_flag INTEGER DEFAULT 0,
        raw_json TEXT
    );

    -- TABLE 9: CLI settlements
    CREATE TABLE IF NOT EXISTS cli_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        city TEXT NOT NULL,
        station TEXT,
        settlement_date TEXT,           -- date CLI is settling
        cli_fire_time_utc TEXT,         -- when CLI was detected
        official_high_f REAL,          -- THE settlement temperature
        official_low_f REAL,
        raw_json TEXT
    );

    -- TABLE 10: Daily performance summary
    CREATE TABLE IF NOT EXISTS performance_daily (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT UNIQUE NOT NULL,
        signals_generated INTEGER DEFAULT 0,
        trades_taken INTEGER DEFAULT 0,
        trades_skipped INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        cancelled INTEGER DEFAULT 0,
        gross_pnl REAL DEFAULT 0,
        total_maker_fees REAL DEFAULT 0,
        net_pnl_maker REAL DEFAULT 0,
        win_rate REAL,
        sharpe_daily REAL,
        max_dd_daily REAL,
        bankroll_start REAL,
        bankroll_end REAL,
        best_trade_pnl REAL,
        worst_trade_pnl REAL,
        -- Model accuracy metrics
        avg_brier_score REAL,
        avg_calibration_error REAL,
        -- System health
        api_errors INTEGER DEFAULT 0,
        gate1_failures INTEGER DEFAULT 0,
        gate2_failures INTEGER DEFAULT 0,
        gate5_failures INTEGER DEFAULT 0,
        gate6_failures INTEGER DEFAULT 0,
        notes TEXT,
        updated_at TEXT DEFAULT (datetime('now'))
    );

    """)

    # Create indexes for common queries
    c.executescript("""
    CREATE INDEX IF NOT EXISTS idx_model_runs_city_date ON model_runs(city, target_date);
    CREATE INDEX IF NOT EXISTS idx_metar_station_time ON metar_observations(station, observation_time);
    CREATE INDEX IF NOT EXISTS idx_kalshi_ticker_time ON kalshi_prices(ticker, created_at);
    CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status, created_at);
    CREATE INDEX IF NOT EXISTS idx_paper_trades_date ON paper_trades(target_date);
    CREATE INDEX IF NOT EXISTS idx_teleconn_date ON teleconnections(date);
    CREATE INDEX IF NOT EXISTS idx_dsm_city_date ON dsm_reports(city, dsm_date);
    CREATE INDEX IF NOT EXISTS idx_cli_city_date ON cli_reports(city, settlement_date);
    """)

    conn.commit()
    conn.close()
    print(f"Database created/verified at {db_path}")
```

---

## SECTION 11: MODULE SPECIFICATIONS

### 11.1 config.py — Complete Configuration

```python
# config.py
import os
from decimal import Decimal

# ─── API CREDENTIALS ──────────────────────────────────────────────────────────
KALSHI_API_KEY    = os.environ.get('KALSHI_API_KEY', '')
KALSHI_KEY_PATH   = os.environ.get('KALSHI_KEY_PATH', '')
WETHR_API_KEY     = os.environ.get('WETHR_API_KEY', '')

# ─── API ENDPOINTS ────────────────────────────────────────────────────────────
KALSHI_BASE_URL   = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_WS_URL     = "wss://api.elections.kalshi.com/trade-api/v2/ws"
WETHR_BASE_URL    = "https://wethr.net/api/v2"
NOMADS_HGEFS_BASE = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/hgefs/prod"
NOMADS_NBM_BASE   = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod"

# ─── FREE DATA SOURCES ────────────────────────────────────────────────────────
BOM_MJO_URL       = "http://www.bom.gov.au/climate/mjo/graphics/rmm.74toRealtime.txt"
CPC_ONI_URL       = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
CPC_TELE_URL      = "https://ftp.cpc.ncep.noaa.gov/wd52dg/data/indices/tele_index.nh"

# Fallback (if wethr.net down)
IEM_ASOS_URL      = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
NWS_DSM_NYC_URL   = "https://mesonet.agron.iastate.edu/wx/afos/p.php?pil=DSMNYC"
NWS_CLI_NYC_URL   = "https://forecast.weather.gov/product.php?site=OKX&product=CLI&issuedby=NYC"

# ─── DATABASE ─────────────────────────────────────────────────────────────────
DB_PATH = "data/pipeline.db"

# ─── TRADING PARAMETERS (all confirmed in Becker backtest) ──────────────────
TARGET_EXIT_PRICE    = Decimal('0.68')     # 68¢ limit sell
STOP_LOSS_DIFF       = Decimal('0.20')     # 20¢ below entry
MIN_YES_PRICE        = Decimal('0.25')     # 25¢ minimum
MAX_YES_PRICE        = Decimal('0.75')     # 75¢ maximum
NEVER_HOLD_ABOVE     = Decimal('0.70')     # 70¢ absolute max
MIN_GAP_PP           = 20.0               # 20pp minimum gap
DEAD_ZONE_LO         = 35.0               # dead zone lower
DEAD_ZONE_HI         = 40.0               # dead zone upper

# ─── GUMBEL PARAMETERS ────────────────────────────────────────────────────────
GUMBEL_MU_CORRECTION = -0.45             # mode correction (NOT -0.5)
GUMBEL_BETA          = 0.742             # = ECMWF_MAE / 1.28
ECMWF_MAE            = 0.95             # °F
ECMWF_BIAS           = -0.42            # °F (runs cold)
GFS_MAE              = 1.58             # °F
GFS_BIAS             = +0.47            # °F (runs warm)
HRRR_SUMMER_BIAS     = -1.5             # subtract in Jun-Aug

# ─── GATE THRESHOLDS ──────────────────────────────────────────────────────────
HGEFS_MAX_SPREAD_BETWEEN  = 1.5        # °F max between physics and AI means
HGEFS_MAX_SUBSET_SPREAD   = 3.0        # °F max within each subset
METAR_YES_MAX_DISTANCE    = 8.0        # °F max distance for YES trades
METAR_NO_MIN_DISTANCE     = 3.0        # °F min distance for NO trades
REVERSAL_THRESHOLD        = 0.10       # 10¢ rise then 10¢ fall
COLD_BRACKET_MAX_TEMP     = 52.0       # °F threshold for "cold bracket"
LIQUIDITY_CENTRAL_MAX     = Decimal('0.04')   # 4¢ max spread central brackets
LIQUIDITY_WING_MAX        = Decimal('0.06')   # 6¢ max spread wing brackets

# ─── POSITION SIZING ──────────────────────────────────────────────────────────
STARTING_BANKROLL    = 500.00          # USD paper trading
MAX_TRADE_PCT        = 0.05            # 5% max per trade
MAX_TOTAL_EXPOSURE   = 0.15            # 15% max total open positions
POSITION_SIZING      = 'quarter_kelly'

# ─── FEES (ceiling-rounded) ───────────────────────────────────────────────────
TAKER_FEE_RATE = 0.07
MAKER_FEE_RATE = 0.0175

import math
def taker_fee(contracts: int, price: float) -> float:
    return math.ceil(TAKER_FEE_RATE * contracts * price * (1-price) * 100) / 100

def maker_fee(contracts: int, price: float) -> float:
    return math.ceil(MAKER_FEE_RATE * contracts * price * (1-price) * 100) / 100

# ─── CITY CONFIGURATIONS ─────────────────────────────────────────────────────
CITIES = {
    'KNYC': {
        'name': 'New York City (Central Park)',
        'series_ticker': 'KXHIGHNY',
        'timezone': 'America/New_York',
        'lat': 40.7789,
        'lon': -73.9692,
        'lon_360': 286.0308,          # 360-degree grid for HGEFS
        'dsm_times_utc': ['20:21', '21:21', '05:17'],  # DST: UTC = ET + 4
        'sharpe_backtest': 4.72,
        'active': True,
        'wethr_station': 'KNYC'
    },
    'KPHL': {
        'name': 'Philadelphia',
        'series_ticker': 'KXHIGHPHL',
        'timezone': 'America/New_York',
        'lat': 39.8729,
        'lon': -75.2408,
        'lon_360': 284.7592,
        'dsm_times_utc': ['20:21', '21:21'],
        'sharpe_backtest': 2.83,
        'active': True,
        'wethr_station': 'KPHL'
    },
    'KMDW': {
        'name': 'Chicago Midway',
        'series_ticker': 'KXHIGHCHI',
        'timezone': 'America/Chicago',
        'lat': 41.7868,
        'lon': -87.7522,
        'lon_360': 272.2478,
        'dsm_times_utc': ['21:17', '22:17', '06:17'],
        'sharpe_backtest': 1.58,
        'active': False,
        'wethr_station': 'KMDW'
    }
    # NEVER add KAUS (Austin) — Sharpe -1.57
}

# ─── TIMING ───────────────────────────────────────────────────────────────────
DSM_CANCEL_TIME_ET   = '16:15'          # 4:15 PM ET — cancel before 4:21 DSM
MAX_HOLD_TIME_ET     = '23:00'          # 11:00 PM ET
METAR_GATE_TIME_ET   = '09:51'          # 9:51 AM reading
FALLBACK_ENTRY_ET    = '11:00'          # fallback if no trigger by 11 AM
DAILY_REPORT_TIME_ET = '08:00'          # morning report time
CLI_CHECK_TIME_ET    = '07:00'          # when to poll for CLI
TELECONN_UPDATE_ET   = '06:00'          # teleconnection daily update

# ─── POLLING INTERVALS ────────────────────────────────────────────────────────
POLL_INTERVAL_60S    = 60               # seconds — observations, wethr_high, DSM
POLL_INTERVAL_5MIN   = 300              # seconds — NWS version, HRRR/NBM run check
POLL_INTERVAL_30MIN  = 1800             # seconds — Kalshi prices, HGEFS, other models
POLL_INTERVAL_DAILY  = 86400            # seconds — teleconnections, CLI

# ─── TRIGGER THRESHOLDS ───────────────────────────────────────────────────────
TEMP_ANOMALY_TRIGGER    = 1.5           # °F — if obs deviates this much from forecast
PRICE_MOVE_TRIGGER      = 0.05          # $0.05 — Kalshi price move in 30 min
NWS_VERSION_CHECK       = True          # check NWS forecast version every 5 min

# ─── PAPER TRADING ────────────────────────────────────────────────────────────
SIMULATION_DAYS         = 30
TARGET_WIN_RATE         = 0.55          # required before real money
MIN_PAPER_TRADES        = 30            # minimum before going live
SLIPPAGE_HALF_SPREAD    = True          # add half-spread to simulated entry cost

# ─── MODEL WEIGHTING ─────────────────────────────────────────────────────────
# When HGEFS is available:
WEIGHT_HGEFS  = 0.60
WEIGHT_NBM    = 0.40

# When HGEFS unavailable (fallback):
FALLBACK_MODELS         = ['HRRR', 'NBM', 'GFS', 'ECMWF', 'ICON', 'NAM']
FALLBACK_MIN_AGREEMENT  = 4             # of 6 models must agree
FALLBACK_AGREEMENT_BAND = 2.0           # °F

# ─── CALIBRATION ─────────────────────────────────────────────────────────────
CALIBRATION_WINDOW_DAYS = 90            # rolling window for isotonic regression
CALIBRATION_UPDATE_DAYS = 7             # refit every 7 days
NBM_V5_CUTOVER          = '2026-04-15'  # calibration reset point

# ─── RISK LIMITS ─────────────────────────────────────────────────────────────
MAX_DAILY_LOSS_PCT      = 0.10          # stop trading if bankroll drops 10% in a day
MAX_WEEKLY_LOSS_PCT     = 0.20          # stop trading if bankroll drops 20% in a week
MIN_BRIER_SKILL_SCORE   = 0.0           # kill city-bracket if BSS < 0 for 14 days
```

### 11.2 data_ingest/wethr_client.py

**Purpose:** All communication with wethr.net Pro REST API.

**Functions to implement:**
```python
class WethrClient:
    def __init__(self, api_key: str)
    def get_latest_obs(self, station: str) -> dict
    def get_wethr_high(self, station: str, logic: str = 'nws') -> dict
    def get_dsm_high(self, station: str) -> dict
    def get_cli_high(self, station: str) -> dict
    def get_history(self, station: str, start_time: str, end_time: str) -> list
    def get_forecast(self, station: str, model: str, run: str = 'latest') -> list
    def get_forecast_maxt(self, station: str, model: str, target_date_et: str) -> float
    # ^ extracts MaxT for a calendar day from hourly forecast data
    def get_nws_evolution(self, station: str) -> dict
    def get_all_models_maxt(self, station: str, target_date_et: str) -> dict
    # ^ returns {model: maxt_f} for all available models
    def celsius_to_fahrenheit(self, c: float) -> float
```

**Key implementation notes:**
- Temperature in API responses is in CELSIUS despite `units: fahrenheit` field
- Convert all temperatures: `temp_f = temp_c * 9/5 + 32`
- Handle empty list responses from models gracefully (return None, not error)
- Cache last known NWS version per station to detect increments
- Retry failed requests up to 3 times with 5-second backoff
- Log all API calls and responses to console (debug level)

### 11.3 data_ingest/kalshi_client.py

**Purpose:** Kalshi REST and WebSocket client with RSA-PSS authentication.

**Functions to implement:**
```python
class KalshiClient:
    def __init__(self, key_id: str, key_path: str)
    def _sign_request(self, method: str, path: str) -> dict  # returns headers
    def get_balance(self) -> float
    def get_active_markets(self, series: str) -> list
    def get_orderbook(self, ticker: str) -> dict
    def get_market_info(self, ticker: str) -> dict
    def get_candlesticks(self, ticker: str, period: str) -> list
    def get_trades(self, ticker: str, limit: int = 100) -> list
    def parse_brackets(self, markets: list) -> list
    # ^ converts API response to bracket objects with lo/hi/type/price

class KalshiWebSocket:
    def __init__(self, key_id: str, key_path: str)
    async def connect(self)
    async def subscribe(self, tickers: list)
    async def run(self, callback)  # calls callback(ticker, orderbook) on each update
```

**Critical rules:**
- ALL prices must be `decimal.Decimal` — never float
- Implied YES ask = `Decimal('1.00') - best_no_bid`
- Sequence gap detection: if `msg['seq'] > last_seq + 1` → resubscribe
- Exponential backoff: 1s → 2s → 4s → 8s → max 60s on disconnect
- WebSocket is read-only — orders via REST only

### 11.4 data_ingest/model_fetcher.py

**Purpose:** Fetch HGEFS data from NOMADS and NBM probabilistic text bulletin.

**Functions to implement:**
```python
class ModelFetcher:
    def __init__(self)

    # HGEFS
    def check_new_hgefs_cycle(self, current_cycle: str) -> str or None
    # ^ checks NOMADS directory for new cycle. Returns new cycle string or None.
    def fetch_hgefs_member_maxt(self, date_str: str, cycle: str,
                                 member: str, city_config: dict) -> float or None
    def fetch_all_hgefs_members(self, date_str: str, cycle: str,
                                 city_config: dict) -> dict
    # ^ returns physics_mean, physics_spread, ai_mean, ai_spread

    # NBM
    def fetch_nbm_bulletin(self, date_str: str, cycle: str, station: str) -> dict or None
    # ^ returns {p10, p25, p50, p75, p90}

    # Helper
    def get_byte_range(self, url: str, variable: str) -> bytes or None
    # ^ uses .idx file to download only the needed GRIB2 bytes
```

**HGEFS notes:**
- Physics members: c00 + p01 through p30 (31 members)
- AI members: p31 through p61 (31 members)
- Files available ~3-4 hours after cycle initialization on NOMADS
- Extract GRIB2 field: shortName=tmax, typeOfLevel=heightAboveGround, level=2, stepType=max
- Take max across forecast hours covering local day
- Bilinear interpolate to city lat/lon

### 11.5 data_ingest/teleconn_fetcher.py

**Purpose:** Download and process climate teleconnection indices.

**Functions to implement:**
```python
class TeleconnFetcher:
    def fetch_mjo_rmm(self) -> pd.DataFrame
    def fetch_oni(self) -> pd.DataFrame
    def fetch_tele_monthly(self) -> pd.DataFrame
    def build_daily_features(self, date: str) -> dict
    # ^ returns all features with lag structure for given date
    def save_to_db(self, date: str, features: dict)
```

### 11.6 signal_engine/gumbel_model.py

**Purpose:** Compute bracket probabilities using Gumbel distribution with NBM prior and isotonic calibration.

```python
class GumbelModel:
    def __init__(self)
    self.calibrator = None  # isotonic regression object
    self.calibration_data = []  # list of (raw_prob, outcome) tuples

    def compute_bracket_prob(self, bracket_lo: float, bracket_hi: float,
                              consensus_f: float, bracket_type: str) -> float

    def bayesian_update_with_nbm(self, gumbel_prob: float, nbm_p50: float,
                                   nbm_p10: float, nbm_p90: float,
                                   bracket_lo: float, bracket_hi: float) -> float

    def calibrate(self, outcomes: list)  # refit isotonic regression
    # outcomes: list of (raw_prob, actual_result_0_or_1)

    def apply_calibration(self, raw_prob: float) -> float

    def compute_consensus_from_wethr(self, model_forecasts: dict) -> float
    # ^ weighted average from {model: maxt_f} dict, applying bias corrections

    def compute_all_bracket_probs(self, city: str, target_date: str,
                                   hgefs_result: dict, nbm_result: dict,
                                   wethr_models: dict) -> dict
    # ^ returns {ticker: calibrated_prob} for all active brackets
```

### 11.7 signal_engine/gate_checker.py

**Purpose:** Run all 6 gates and return pass/fail with details.

Implementation is fully specified in Section 9 above. Additional notes:
- Always run all 6 gates even if an early gate fails (for logging purposes)
- Log every gate check to gate_checks table regardless of outcome
- Include confidence score: weighted sum of margin by which each gate passed

```python
def compute_confidence_score(gate_results: dict) -> float:
    """
    0-100 score based on how strongly each gate passed.
    Gate 1: 30 points — based on how far spread is below 1.5°F
    Gate 2: 30 points — based on how far gap exceeds 20pp
    Gate 5: 20 points — based on METAR alignment
    Gate 6: 20 points — no reversal = full 20, reversal detected = 0
    """
```

### 11.8 signal_engine/event_triggers.py

**Purpose:** Main polling loop that detects trigger conditions and fires gate checks.

```python
class EventTriggerEngine:
    def __init__(self, wethr: WethrClient, kalshi: KalshiClient,
                 model_fetcher: ModelFetcher, db_path: str)

    async def run_forever(self)
    # Main entry point. Runs all polling loops concurrently.

    async def poll_60s(self)
    # Every 60 seconds:
    # - Get latest obs for each active city
    # - Get Wethr High for each city
    # - Check DSM filter
    # - Check for temperature anomaly trigger
    # - Save observations to metar_observations table

    async def poll_5min(self)
    # Every 5 minutes:
    # - Check NWS forecast version for each city
    # - Check HRRR latest run_time (trigger if changed)
    # - Check NBM latest run_time (trigger if changed)
    # - Save forecast data to model_runs table

    async def poll_30min(self)
    # Every 30 minutes:
    # - Get all Kalshi prices for active markets
    # - Check for price move trigger (>5¢ in 30 min on any bracket)
    # - Check HGEFS NOMADS directory for new cycle
    # - Fetch GFS/ECMWF/ICON/NAM from wethr.net
    # - Save prices to kalshi_prices table

    async def poll_daily(self)
    # Once daily at 6 AM ET:
    # - Fetch teleconnection indices
    # - Check CLI for yesterday's settlement
    # - Update paper trade outcomes with CLI settlement
    # - Generate daily performance summary
    # - Refit isotonic calibration if needed

    async def fire_gate_check(self, city: str, trigger_reason: str)
    # Runs all data gathering and gate evaluation for a city.
    # If all gates pass: generate signal, save to signals table.
    # Always: save gate check to gate_checks table.

    async def run_fallback_11am(self)
    # If no trigger has fired by 11 AM ET: run gate check as fallback.
```

### 11.9 kalshi_watcher/orderbook.py

**Purpose:** Maintain real-time Kalshi orderbook for all active markets.

```python
class KalshiOrderbookManager:
    def __init__(self, key_id: str, key_path: str)
    self.books = {}  # ticker -> KalshiOrderBook
    self.price_history = {}  # ticker -> deque of (timestamp, yes_bid)

    async def run(self, tickers: list)
    # Connect to WebSocket, subscribe, maintain books, save to DB

    def get_current_price(self, ticker: str) -> Decimal
    def get_spread(self, ticker: str) -> Decimal
    def get_price_history(self, ticker: str, minutes: int) -> list
    def check_reversal_pattern(self, ticker: str) -> bool
    # True if price rose >10¢ then fell >10¢ in the last 8 hours
    def passes_liquidity_filter(self, ticker: str, bracket_type: str) -> bool
```

### 11.10 paper_trader/simulator.py

**Purpose:** Simulate trades from signals. Track P&L with realistic fees.

```python
class PaperTrader:
    def __init__(self, starting_bankroll: float, db_path: str)
    self.bankroll = starting_bankroll  # $500
    self.open_trades = {}  # signal_id -> trade details

    def on_signal(self, signal: dict) -> dict or None
    # Calculate position size and "enter" a paper trade.
    # Returns trade record or None if bankroll limits prevent entry.

    def calculate_position_size(self, bankroll: float, prob: float,
                                  price: float) -> dict
    # Returns: {contracts: int, stake: float, kelly_f: float}
    # Uses Quarter-Kelly with 5% hard cap

    def simulate_entry(self, signal: dict, current_price: Decimal,
                        spread: Decimal) -> dict
    # Simulates limit order fill at current_price.
    # Applies half-spread slippage. Records maker fee.
    # Returns trade record.

    def check_exits(self, current_prices: dict)
    # Called every 60 seconds. Checks all open trades for:
    # 1. Price >= target (0.68¢) → HIT_TARGET
    # 2. Price <= entry - 0.20 → HIT_STOP
    # 3. Time >= 11 PM ET → TIME_LIMIT
    # 4. DSM detected → DSM_CANCEL

    def settle_trade(self, trade: dict, settlement_temp_f: float)
    # Called next morning when CLI fires.
    # Records official settlement temperature and whether direction was correct.

    def get_daily_pnl(self) -> float
    def get_total_pnl(self) -> float
    def get_win_rate(self) -> float
    def get_sharpe(self) -> float

    def enforce_risk_limits(self) -> bool
    # Returns False if daily/weekly loss limits hit → stop trading
```

### 11.11 dashboard/daily_report.py

**Purpose:** Generate and print daily performance summary.

```python
def generate_daily_report(db_path: str, date: str) -> str:
    """
    Queries database and generates a formatted report string.

    Report includes:
    - Date and bankroll status
    - Signals generated today (with gate breakdown)
    - Trades taken (entries, exits, outcomes)
    - P&L: gross, fees, net (both maker and taker scenarios)
    - Win rate (today and rolling 30 days)
    - Sharpe ratio
    - Max drawdown
    - Model accuracy: Brier score per city
    - DSM events detected
    - API health (any errors or outages)
    - Top performing brackets
    - Tomorrow's outlook (model consensus for next day)
    """

def print_gate_summary(db_path: str, date: str) -> str:
    """
    Shows why trades were skipped:
    - Gate 1 failures: X (HGEFS spread too wide)
    - Gate 2 failures: X (gap below threshold)
    - Gate 3 failures: X (price out of band)
    - Gate 4 failures: X (dead zone)
    - Gate 5 failures: X (METAR gate)
    - Gate 6 failures: X (reversal pattern)
    """
```

### 11.12 data_store/db.py

**Purpose:** Database connection manager and helper functions.

```python
class Database:
    def __init__(self, db_path: str)

    def insert_model_run(self, data: dict) -> int
    def insert_observation(self, data: dict) -> int
    def insert_kalshi_price(self, data: dict) -> int
    def insert_gate_check(self, data: dict) -> int
    def insert_signal(self, data: dict) -> int
    def insert_paper_trade(self, data: dict) -> int
    def insert_teleconnection(self, data: dict) -> int
    def insert_dsm_report(self, data: dict) -> int
    def insert_cli_report(self, data: dict) -> int
    def update_daily_performance(self, date: str, data: dict)

    def get_latest_observation(self, station: str) -> dict or None
    def get_wethr_high_today(self, station: str) -> float or None
    def get_open_signals(self, city: str) -> list
    def get_open_trades(self) -> list
    def get_model_run_latest(self, city: str, model: str) -> dict or None
    def get_price_history(self, ticker: str, hours: int) -> list
    def get_performance_summary(self, days: int) -> dict

    def execute(self, sql: str, params: tuple = ()) -> list
    def execute_write(self, sql: str, params: tuple = ()) -> int
```

### 11.13 main.py — Orchestrator

```python
#!/usr/bin/env python3
"""
Kalshi Weather Trading Pipeline
Runs continuously for 30-day paper trading simulation.
"""

import asyncio
import logging
import os
import sys
from data_store.schema import create_database
from data_store.db import Database
from data_ingest.wethr_client import WethrClient
from data_ingest.kalshi_client import KalshiClient, KalshiWebSocket
from data_ingest.model_fetcher import ModelFetcher
from data_ingest.teleconn_fetcher import TeleconnFetcher
from signal_engine.gumbel_model import GumbelModel
from signal_engine.gate_checker import run_all_gates
from signal_engine.event_triggers import EventTriggerEngine
from kalshi_watcher.orderbook import KalshiOrderbookManager
from paper_trader.simulator import PaperTrader
from dashboard.daily_report import generate_daily_report
import config

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
        handlers=[
            logging.FileHandler('logs/pipeline.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )

async def main():
    setup_logging()
    logger = logging.getLogger('main')

    # Validate credentials
    assert config.KALSHI_API_KEY, "KALSHI_API_KEY not set"
    assert config.WETHR_API_KEY, "WETHR_API_KEY not set"
    assert os.path.exists(config.KALSHI_KEY_PATH), f"Key not found: {config.KALSHI_KEY_PATH}"

    # Initialize database
    create_database(config.DB_PATH)
    db = Database(config.DB_PATH)

    # Initialize clients
    wethr = WethrClient(config.WETHR_API_KEY)
    kalshi = KalshiClient(config.KALSHI_API_KEY, config.KALSHI_KEY_PATH)
    model_fetcher = ModelFetcher()
    teleconn = TeleconnFetcher()
    gumbel = GumbelModel()
    paper_trader = PaperTrader(config.STARTING_BANKROLL, config.DB_PATH)

    logger.info("All clients initialized")
    logger.info(f"Starting paper trading simulation: ${config.STARTING_BANKROLL} bankroll")
    logger.info(f"Active cities: {[c for c,v in config.CITIES.items() if v['active']]}")

    # Get active Kalshi tickers
    active_tickers = []
    for city, cfg in config.CITIES.items():
        if cfg['active']:
            markets = kalshi.get_active_markets(cfg['series_ticker'])
            tickers = [m['ticker'] for m in markets]
            active_tickers.extend(tickers)

    logger.info(f"Active Kalshi tickers: {active_tickers}")

    # Initialize Kalshi orderbook manager
    orderbook_manager = KalshiOrderbookManager(
        config.KALSHI_API_KEY, config.KALSHI_KEY_PATH
    )

    # Initialize event trigger engine
    trigger_engine = EventTriggerEngine(
        wethr=wethr,
        kalshi=kalshi,
        model_fetcher=model_fetcher,
        gumbel=gumbel,
        paper_trader=paper_trader,
        orderbook_manager=orderbook_manager,
        db=db
    )

    # Run everything concurrently
    await asyncio.gather(
        orderbook_manager.run(active_tickers),    # WebSocket orderbook
        trigger_engine.run_forever(),              # Polling + signal generation
    )

if __name__ == '__main__':
    asyncio.run(main())
```

---

## SECTION 12: POLLING SCHEDULE (COMPLETE)

```
TIME          | ACTION                           | SOURCE              | DB TABLE
─────────────────────────────────────────────────────────────────────────────────
Every 60s     | Latest obs KNYC + KPHL          | wethr.net REST      | metar_observations
Every 60s     | Wethr High KNYC + KPHL          | wethr.net REST      | metar_observations
Every 60s     | DSM filter check KNYC + KPHL    | wethr.net REST      | dsm_reports (if new)
Every 60s     | Check temp anomaly trigger      | Compare obs vs HRRR | gate_checks (if trigger)
─────────────────────────────────────────────────────────────────────────────────
Every 5min    | NWS version check KNYC + KPHL   | wethr.net REST      | (trigger if increment)
Every 5min    | HRRR run_time check KNYC + KPHL | wethr.net REST      | model_runs (if new)
Every 5min    | NBM run_time check KNYC + KPHL  | wethr.net REST      | model_runs (if new)
─────────────────────────────────────────────────────────────────────────────────
Every 30min   | All Kalshi bracket prices       | Kalshi REST         | kalshi_prices
Every 30min   | Price move trigger check        | Compare vs 30min ago| gate_checks (if trigger)
Every 30min   | HGEFS NOMADS directory check    | NOMADS HTTPS        | model_runs (if new)
Every 30min   | GFS/ECMWF/ICON/NAM from wethr  | wethr.net REST      | model_runs
─────────────────────────────────────────────────────────────────────────────────
Continuous    | Kalshi WebSocket orderbook      | Kalshi WebSocket    | kalshi_prices
─────────────────────────────────────────────────────────────────────────────────
06:00 AM ET  | Teleconnection indices          | BoM + CPC           | teleconnections
07:00 AM ET  | CLI check for yesterday         | wethr.net REST      | cli_reports
07:30 AM ET  | Settle yesterday's paper trades | CLI result          | paper_trades
08:00 AM ET  | Daily performance report        | Database query      | performance_daily
11:00 AM ET  | Fallback gate check (if no      | All sources         | gate_checks + signals
             | trigger has fired today)        |                     |
─────────────────────────────────────────────────────────────────────────────────
Triggered    | Full gate check                 | All sources         | gate_checks + signals
(any event)  | Paper trade simulation          | Signal result       | paper_trades
─────────────────────────────────────────────────────────────────────────────────

Estimated API usage:
  wethr.net: ~350-450 calls/day (within 5,000/day limit)
  Kalshi REST: ~200-300 calls/day
  NOMADS: ~50 requests/day (byte-range, small)
  CPC/BoM: ~5 requests/day
```

---

## SECTION 13: SIGNAL GENERATION FLOW

```
TRIGGER DETECTED
       │
       ▼
GATHER DATA FOR CITY
  ├── HGEFS: latest available cycle from NOMADS
  │     → physics_mean, physics_spread, ai_mean, ai_spread
  ├── NBM: latest text bulletin
  │     → p10, p25, p50, p75, p90 percentiles
  ├── wethr.net: HRRR + NBM + GFS + ECMWF (if available)
  │     → per-model MaxT forecasts
  ├── wethr.net: Wethr High (current confirmed max)
  ├── wethr.net: Latest observation (current temp)
  ├── wethr.net: NWS forecast evolution (version + hourly temps)
  └── Kalshi: Current bracket prices + orderbook depth
       │
       ▼
COMPUTE CONSENSUS TEMPERATURE
  weighted average of available models with bias corrections:
  - ECMWF: add 0.42°F (cold bias)
  - GFS: subtract 0.47°F (warm bias)
  - HRRR: subtract 1.5°F in Jun-Aug (summer warm bias)
  - HGEFS: use mean of all 62 members
  - Final consensus = weighted blend
       │
       ▼
FOR EACH ACTIVE BRACKET:
  COMPUTE GUMBEL PROBABILITY
  ├── mu = consensus_temp_f - 0.45
  ├── beta = 0.742
  ├── Bayesian update with NBM p50 (40% weight)
  ├── Apply isotonic calibration
  └── calibrated_prob = final probability
       │
       ▼
  COMPUTE GAP
  gap_pp = (calibrated_prob - market_price) * 100
       │
       ▼
  RUN ALL 6 GATES
  ├── Gate 1: abs(physics_mean - ai_mean) <= 1.5°F
  ├── Gate 2: abs(gap_pp) > 20.0
  ├── Gate 3: 0.25 <= yes_price <= 0.75
  ├── Gate 4: NOT 35 <= abs(gap_pp) <= 40
  ├── Gate 5: METAR 9:51 AM within threshold
  └── Gate 6: No evening reversal pattern
       │
       ├── ANY GATE FAILS → log to gate_checks, try next bracket
       │
       └── ALL GATES PASS →
               │
               ▼
          CHECK LIQUIDITY
          ├── spread <= 4¢ (central) or 6¢ (wing)
          ├── FAIL → log skip, try next bracket
          └── PASS →
                  │
                  ▼
             GENERATE SIGNAL
             {
               city, ticker, bracket,
               direction (YES/NO),
               entry_price (current market price),
               target_price (0.68),
               stop_price (entry - 0.20),
               model_prob, market_price, gap_pp,
               confidence_score (0-100),
               physics_mean, ai_mean, nbm_p50, metar_temp_f,
               trigger_reason, reasoning
             }
                  │
                  ▼
             SAVE SIGNAL TO DB
                  │
                  ▼
             SIMULATE PAPER TRADE
             ├── Calculate position size (Quarter-Kelly, max 5%)
             ├── Record entry at current price + half-spread slippage
             ├── Place simulated 68¢ limit sell
             └── Monitor every 60 seconds for exits
```

---

## SECTION 14: PAPER TRADING SIMULATOR DETAIL

### Position Sizing (Quarter-Kelly)
```python
def calculate_position_size(bankroll: float, model_prob: float,
                              market_price: float) -> dict:
    """
    Quarter-Kelly position sizing with hard caps.

    For binary market:
    b = payout ratio = (1 - market_price) / market_price
    f* = (b * p - (1-p)) / b  (full Kelly fraction)
    quarter_kelly = f* * 0.25

    Args:
        bankroll: current bankroll in dollars
        model_prob: our calibrated probability (0.0 to 1.0)
        market_price: Kalshi YES price (0.25 to 0.75)

    Returns:
        {
            'kelly_f': full Kelly fraction,
            'quarter_kelly_f': quarter Kelly fraction,
            'stake': dollar amount to risk,
            'contracts': number of contracts,
            'max_allowed': True/False (was it capped?)
        }
    """
    b = (1 - market_price) / market_price
    p = model_prob
    q = 1 - p

    full_kelly = (b * p - q) / b
    quarter_kelly = max(0, full_kelly * 0.25)

    stake = min(quarter_kelly * bankroll, bankroll * 0.05)  # 5% hard cap
    contracts = max(1, int(stake / market_price))  # at least 1 contract

    return {
        'kelly_f': full_kelly,
        'quarter_kelly_f': quarter_kelly,
        'stake': stake,
        'contracts': contracts,
        'max_allowed': (quarter_kelly * bankroll > bankroll * 0.05)
    }
```

### Fee Calculation (Ceiling-Rounded)
```python
import math

def calculate_fees(contracts: int, price: float, order_type: str = 'maker') -> float:
    """
    Ceiling-rounded Kalshi fee.
    order_type: 'maker' (limit order) or 'taker' (market order)
    """
    if order_type == 'maker':
        return math.ceil(0.0175 * contracts * price * (1 - price) * 100) / 100
    else:
        return math.ceil(0.07 * contracts * price * (1 - price) * 100) / 100

# Example: 1 contract at 50¢
# Taker: ceil(0.07 * 1 * 0.50 * 0.50 * 100) / 100 = ceil(1.75) / 100 = 2/100 = $0.02
# Maker: ceil(0.0175 * 1 * 0.50 * 0.50 * 100) / 100 = ceil(0.4375) / 100 = 1/100 = $0.01

# Always use limit orders → maker fee
```

### Trade Lifecycle
```
SIGNAL GENERATED
       │
       ▼
ENTRY SIMULATION
  - entry_price = current yes_bid (or yes_ask if NO trade)
  - slippage = half_spread (half of yes_ask - yes_bid)
  - effective_entry = entry_price + slippage
  - entry_fee = maker_fee(contracts, effective_entry)
  - Record in paper_trades table with status='OPEN'
       │
       ▼
EVERY 60 SECONDS — CHECK EXITS
  Current price >= 0.68 → EXIT: HIT_TARGET
  Current price <= effective_entry - 0.20 → EXIT: HIT_STOP
  Time >= 11:00 PM ET → EXIT: TIME_LIMIT
  DSM detected + order unfilled → EXIT: DSM_CANCEL
       │
       ▼
ON EXIT
  - exit_fee = maker_fee(contracts, exit_price)
  - gross_pnl = (exit_price - effective_entry) * contracts * 100
    (if NO trade: gross_pnl = (effective_entry - exit_price) * contracts * 100)
  - net_pnl_maker = gross_pnl - entry_fee - exit_fee
  - Record exit details in paper_trades table
       │
       ▼
NEXT MORNING: CLI SETTLEMENT
  - settlement_temp_f from CLI report
  - settled_correct = 1 if direction correct
  - Update paper_trades table
  - Update performance_daily table
```

---

## SECTION 15: DAILY REPORT FORMAT

```
╔══════════════════════════════════════════════════════════╗
║     KALSHI WEATHER PIPELINE — DAILY REPORT               ║
║     Date: 2026-04-25                                      ║
╚══════════════════════════════════════════════════════════╝

BANKROLL
  Start of day:  $498.50
  End of day:    $501.23 (+$2.73)
  Total P&L:     +$1.23 (since day 1)

TODAY'S ACTIVITY
  Triggers fired:       7
  Gate checks run:      12
  Signals generated:    2
  Trades simulated:     2
  Trades settled:       1 (from yesterday)

GATE FAILURES TODAY
  Gate 1 (HGEFS spread): 3 failures
  Gate 2 (gap < 20pp):   4 failures
  Gate 3 (price band):   1 failure
  Gate 4 (dead zone):    0 failures
  Gate 5 (METAR):        1 failure
  Gate 6 (reversal):     0 failures

TRADE DETAILS
  Trade 1: KNYC KXHIGHNY-26APR25-T68 YES
    Entry: 0.52 | Target: 0.68 | Stop: 0.32
    Status: OPEN (current price: 0.58)
    Unrealized P&L: +$6.00

  Trade 2 (settled): KNYC KXHIGHNY-26APR24-T70 YES
    Entry: 0.48 | Exit: 0.68 (HIT_TARGET) | Settlement: 72°F ✓
    Net P&L (maker): +$19.65

MODEL ACCURACY (rolling 7 days)
  HGEFS gate pass rate: 67%
  Avg gap when passed: 28.3pp
  Brier score: 0.18 (good)
  Calibration error: 0.04

OBSERVATIONS TODAY
  9:51 AM KNYC: 58°F (gate 5 check)
  DSM fired: 4:21 PM — confirmed high 68°F
  CLI expected: tomorrow morning

DATA HEALTH
  wethr.net API: ✓ (0 errors)
  Kalshi WS: ✓ (1 reconnect)
  HGEFS: ✓ (12Z cycle processed)
  NBM: ✓ (hourly updates)

TOMORROW'S OUTLOOK
  HRRR MaxT consensus: 71°F
  NBM p50: 70°F
  physics_mean: 71.2°F | ai_mean: 70.8°F
  Spread: 0.4°F (NARROW — Gate 1 likely passes)
  Best bracket: 70-72°F (model 62%, market 45% → +17pp gap)
  Recommendation: WATCH — approaching 20pp threshold
```

---

## SECTION 16: BUILD ORDER (STEP BY STEP)

Build in exactly this order. Test each component before moving to the next.

### Phase 1 — Foundation
```
Step 1: Create project structure (all directories)
Step 2: config.py — complete with all constants
Step 3: data_store/schema.py — create_database() function
Step 4: data_store/db.py — Database class
Step 5: TEST: python3 -c "from data_store.schema import create_database; create_database()"
        Expected: "Database created/verified at data/pipeline.db"
```

### Phase 2 — Data Ingest
```
Step 6: data_ingest/wethr_client.py — all 8 endpoints
Step 7: TEST wethr_client.py:
        - get_latest_obs('KNYC') → temp in Celsius
        - get_wethr_high('KNYC') → 50°F (today's confirmed high)
        - get_forecast('KNYC', 'HRRR') → hourly forecast list
        - get_nws_evolution('KNYC') → version + hourly temps
        All should return data matching our April 25 test results.

Step 8: data_ingest/kalshi_client.py — REST client
Step 9: TEST kalshi_client.py:
        - get_balance() → 1000 ($10.00)
        - get_active_markets('KXHIGHNY') → list of brackets

Step 10: data_ingest/model_fetcher.py — HGEFS + NBM
Step 11: TEST model_fetcher.py:
         - fetch_nbm_bulletin('20260425', '00', 'KNYC') → p50 value
         - check_new_hgefs_cycle() → returns cycle string

Step 12: data_ingest/teleconn_fetcher.py
Step 13: TEST teleconn_fetcher.py:
         - fetch_mjo_rmm() → DataFrame with recent MJO values
         - fetch_oni() → DataFrame with ONI values
```

### Phase 3 — Signal Engine
```
Step 14: signal_engine/gumbel_model.py
Step 15: TEST gumbel_model.py:
         - compute_bracket_prob(68, 70, 71.0, 'range') → ~0.48
         - bayesian_update_with_nbm(0.48, 70.0, 62.0, 78.0, 68, 70) → ~0.47

Step 16: signal_engine/gate_checker.py — all 6 gates
Step 17: TEST gate_checker.py:
         - run all gates with known good values → all_pass=True
         - run with bad HGEFS spread → gate1 fails
         - run with gap=37pp → gate4 fails (dead zone)

Step 18: kalshi_watcher/orderbook.py — WebSocket orderbook
Step 19: TEST orderbook.py:
         - Connect to Kalshi WebSocket → Connected (RSA confirmed working)
         - Subscribe to KXHIGHNY tickers → receive snapshots
```

### Phase 4 — Paper Trader
```
Step 20: paper_trader/simulator.py
Step 21: TEST simulator.py:
         - calculate_position_size(500, 0.60, 0.50) → ~$6.25 (5% cap applies)
         - calculate_fees(1, 0.50, 'maker') → $0.01
         - calculate_fees(1, 0.50, 'taker') → $0.02

Step 22: dashboard/daily_report.py
Step 23: TEST daily_report.py:
         - generate_daily_report(db_path, today) → formatted string
```

### Phase 5 — Integration
```
Step 24: signal_engine/event_triggers.py — polling loop
Step 25: main.py — orchestrator
Step 26: TEST full integration:
         - python3 main.py
         - Watch 60 seconds of output
         - Verify: observations saved to DB, Kalshi prices polled, no errors
```

### Phase 6 — 30-Day Run
```
Step 27: Start the pipeline:
         nohup python3 main.py > logs/pipeline.log 2>&1 &
Step 28: Monitor logs:
         tail -f logs/pipeline.log
Step 29: Check daily reports each morning
Step 30: After 30 days: analyze full database and decide on real money
```

---

## SECTION 17: KNOWN FAILURE MODES (DO NOT REPEAT)

| Failure | Impact | Correct Rule |
|---------|--------|-------------|
| Fixed 10 AM entry | -$116 vs event-driven | Use event-driven triggers |
| 65¢ exit target | Suboptimal | Use 68¢ |
| 15¢ stop loss | -$96 P&L | Use 20¢ |
| Gaussian distribution | -$75 P&L | Use Gumbel only |
| Trading 35-40pp gap | Negative P&L | Dead zone — skip |
| Holding past 4:15 PM | DSM bot destroys position | Cancel at 4:15 |
| Public weather apps | Wrong settlement source | NWS CLI only |
| Trading Austin (KAUS) | Sharpe -1.57 | Never trade |
| Contracts < 25¢ | 60%+ capital loss | Min 25¢ |
| Contracts > 75¢ | NWS error risk | Max 75¢ |
| Float for Kalshi prices | Corrupts orderbook | Use Decimal only |
| Single model (GFS only) | 29% win rate | Multi-model ensemble |
| S3 for HGEFS | Bucket doesn't exist | Use NOMADS HTTPS |
| Gumbel mu = -0.5 | Wrong | Use -0.45 |
| Using 10 AM METAR | Wrong gate | Use 9:51 AM |
| Max 85¢ not 75¢ | NWS error risk | Use 75¢ max |

---

## SECTION 18: RISK MANAGEMENT RULES

### Per-Trade Rules
- Maximum stake: 5% of bankroll ($25 at $500 start)
- Position sizing: Quarter-Kelly
- Stop loss: 20¢ below entry (hard, no override)
- Target exit: 68¢ (never remove this order)
- Cancel time: 4:15 PM ET every day

### Portfolio Rules
- Maximum simultaneous open positions: 3
- Maximum total exposure: 15% of bankroll
- Correlated cities (NYC + PHL): divide combined position by 1.4
- Never hold above 70¢ under any circumstances

### System-Level Rules
- Stop trading if bankroll drops 10%+ in a single day
- Stop trading if bankroll drops 20%+ in a week
- Kill any city-bracket with negative Brier Skill Score for 14+ consecutive days
- Recalibrate isotonic regression every 7 days
- Treat April 15, 2026 as calibration reset (NBM v5.0 cutover)

### Data Quality Rules
- If wethr.net API fails: fall back to IEM ASOS for observations
- If HGEFS unavailable: use 4-of-6 model agreement fallback
- If METAR unavailable at 9:51 AM: skip trade (never assume)
- Log every data error and API failure to performance_daily table

---

## SECTION 19: TESTING REQUIREMENTS

### Unit Tests (tests/ directory)

**test_wethr.py:**
- All 8 endpoints return expected data structure
- Temperature conversion (Celsius → Fahrenheit) is correct
- Empty model list handled gracefully
- History requires start_time + end_time (not just date)

**test_kalshi.py:**
- RSA authentication returns headers (not full API call)
- Fee calculations match hand calculations
- Implied ask derivation: yes_ask = 1.00 - best_no_bid
- Decimal prices don't round to float

**test_gates.py:**
- All 6 gates return (bool, dict) tuples
- Gate 1: spread 1.4°F → pass, spread 1.6°F → fail
- Gate 2: gap 21pp → pass, gap 19pp → fail
- Gate 3: price 0.24 → fail, 0.25 → pass, 0.75 → pass, 0.76 → fail
- Gate 4: gap 37pp → fail (dead zone), gap 34pp → pass
- Gate 5: YES trade, distance 7°F → pass, 9°F → fail
- Gate 6: no history → pass, reversal on cold bracket → fail

### Integration Test
Run `python3 main.py` for 60 seconds and verify:
- At least 1 observation saved to metar_observations
- At least 1 Kalshi price saved to kalshi_prices
- NWS version check ran and logged
- No unhandled exceptions

---

## SECTION 20: FREQUENTLY ASKED QUESTIONS

**Q: Why event-driven entry instead of fixed 11 AM?**
A: Sensitivity test B4 confirmed 11 AM is the optimal *fixed* time (+$117 vs 10 AM). But event-driven is better because some days the best opportunity comes earlier (clear signal at 10:30 AM) and some days later (12Z model run at 1 PM changes the picture). 11 AM is the fallback.

**Q: Why Gumbel distribution instead of Gaussian?**
A: Daily temperature maxima are extreme values — they follow an extreme value distribution. Gumbel is the appropriate distribution for the maximum of a series of random variables. Ablation test A2 confirmed -$75 P&L from using Gaussian.

**Q: Why not trade Austin (KAUS)?**
A: Austin's temperature market produced Sharpe -1.57 in the Becker dataset. The combination of volatile desert weather and poor model accuracy makes it unprofitable.

**Q: Why is the Push API not used?**
A: wethr.net's Push API is marked BETA and confirmed not deployed as of April 25, 2026 (all WebSocket URLs return HTTP 404). REST polling every 60 seconds is equivalent for our purposes since DSM detection is based on an observation appearing in the filtered API response.

**Q: Why NOMADS for HGEFS instead of S3?**
A: The S3 bucket `noaa-hgefs-pds` does not exist yet. HGEFS only went operational December 17, 2025. Subscribe to `nodd@noaa.gov` for bucket announcement. When it arrives, update `NOMADS_HGEFS_BASE` in config.py to the S3 URL and add `--no-sign-request` to boto3 calls.

**Q: What if both HGEFS data and wethr.net are unavailable simultaneously?**
A: This is extremely unlikely but the fallback is: use IEM ASOS for observations, use Open-Meteo ensemble API for models (https://ensemble-api.open-meteo.com/v1/ensemble), require 4-of-6 models within 2°F for gate 1. Log the outage.

**Q: When can real money be deployed?**
A: After ALL of: (1) 30 paper trades completed, (2) win rate > 55%, (3) DSO written guidance obtained, (4) CPA consultation on tax treatment, (5) no single paper trade exceeded bankroll limits.

**Q: What is the F-1 visa situation?**
A: UNRESOLVED. Must get written DSO guidance before depositing any real money. Kalshi weather contracts have no LPR-only restriction. The risk is USCIS treating high-frequency trading as unauthorized employment. Keep trade frequency low and document everything.

---

## APPENDIX A: CONFIRMED API TEST RESULTS (APRIL 25, 2026)

All tests run at approximately 2:00 AM ET on April 25, 2026.

```
wethr.net Pro API Results:
  Latest KNYC obs:      ✅ 200 — 9.4°C at 06:51 UTC
  Wethr High (NWS):     ✅ 200 — 50°F high, 49°F low
  DSM High filter:      ✅ 200 — yesterday's DSM: 20°C = 68°F (April 24 settlement)
  CLI High filter:      ✅ 200 — same as DSM (confirmed correct)
  HRRR forecast:        ✅ 200 — 48.75°F at f0, run 05:00 UTC
  NBM forecast:         ✅ 200 — 51.17°F at f1, run 04:00 UTC
  ICON forecast:        ✅ 200 — 36 forecast hours
  JMA forecast:         ✅ 200 — data returned
  UKMO forecast:        ✅ 200 — data returned
  ARPEGE forecast:      ✅ 200 — data returned
  GFS forecast:         ⚠️ 200 — empty list (timing — 2AM, GFS not cycled yet)
  ECMWF forecast:       ⚠️ 200 — empty list (timing)
  NAM forecast:         ⚠️ 200 — empty list (timing)
  NWS evolution KNYC:   ✅ 200 — version 6, hourly temps array
  History KNYC:         ✅ 200 — 25 obs (required start_time + end_time params)
  KPHL latest:          ✅ 200 — 11.1°C at 06:54 UTC
  Push API WebSocket:   ❌ 404 — NOT DEPLOYED (use REST polling)

Kalshi API Results:
  RSA Auth balance:     ✅ 200 — 1000 ($10.00), portfolio 0

Models confirmed live for KNYC during trading hours:
  HRRR, NBM, ICON, JMA, UKMO, ARPEGE, GFS, ECMWF, NAM
```

## APPENDIX B: KEY COMMUNITY FINDINGS

- **u/stfarm (wethr.net Discord):** "When the physics ensemble and AI ensemble agree, confidence is high. When they disagree, probability moves toward 50/50." → HGEFS gate design.
- **Gumby808 ($125k+ Kalshi):** NO positions at 50¢, exit 65-70¢. Market structure validation.
- **KevinLuWX (top earner):** "Never buy above 90¢." → our 75¢ max is even more conservative.
- **Atte (wethr.net Discord):** "NWS employees have access to resolution-affecting numbers hours before release." → Never trade the DSM window.
- **predictandprofit.io v1:** Lost money at <20¢ contracts. v2: profitable with min 40¢ + 3-of-4 models.
- **UCD Academic Paper (Jan 2026, 300k+ trades):** Contracts >50¢ earn positive returns. Maker beats Taker. Favorite-longshot bias confirmed.
- **Oalkhadra (GitHub, live since Feb 2026):** 923 trades, 38% total return, 3.16 Sharpe, 33.9% win rate, 3.01 W/L. Shows asymmetric payoff structure.

## APPENDIX C: IMPORTANT DATES

```
Oct 2024:     Becker dataset begins (806,295 trades through Nov 2025)
Dec 17, 2025: HGEFS goes operational at NOAA (62-member hybrid ensemble)
Jan 2026:     Synoptic HF-ASOS feed restored after 27-month outage
Feb 22, 2026: Oalkhadra system deployed live
Apr 15, 2026: NBM v5.0 goes operational (calibration reset point)
Apr 23, 2026: Live market observation — GEM +1.5°F reversal caught by Gate 1 + Gate 6
Apr 25, 2026: All APIs tested and confirmed. Pipeline build begins.
May-Jun 2026: 30-day paper trading run
Jul 2026:     Real money decision based on paper trading results
Q3 2026:      OMO (1-minute observations) expected to be added to wethr.net API
```
