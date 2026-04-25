# Kalshi Weather Trading Pipeline — Claude Code Reference
**Last updated: April 25, 2026**
**Status: All APIs confirmed working. Ready to build.**

---

## CRITICAL RULES — READ BEFORE ANY CODE

1. HGEFS is the primary model — NEVER substitute 4-model approach
2. Gumbel distribution is MANDATORY — mu = consensus - 0.45, beta = 0.742
3. Entry is EVENT-DRIVEN — NOT fixed 11 AM (use 11 AM as fallback only)
4. Exit target is 68¢ — NOT 65¢
5. Stop loss is 20¢ below entry — NOT 15¢
6. METAR gate uses 9:51 AM reading — NOT 10 AM
7. Dead zone: NEVER trade gaps between 35-40pp
8. Gate 6 MUST be checked — evening reversal on cold brackets = 98% NO
9. Cancel ALL open orders by 4:15 PM ET (DSM fires at 4:21 PM)
10. NEVER hold above 70¢ under any circumstances
11. Fees are CEILING-ROUNDED — use math.ceil()
12. ALL prices from Kalshi are Decimal — NEVER float
13. HGEFS is on NOMADS HTTPS — S3 bucket does not exist yet
14. wethr.net Push API is not deployed yet — use REST polling only
15. DST: during Daylight Saving Time, CLI measures 1 AM to 1 AM ET

---

## PROJECT STRUCTURE

```
prediction-market-analysis/
├── config.py                    # All constants, URLs, thresholds
├── main.py                      # Orchestrator — runs indefinitely
├── data_ingest/
│   ├── wethr_client.py          # wethr.net Pro REST API (primary hub)
│   ├── kalshi_client.py         # Kalshi RSA auth + REST + WebSocket
│   ├── model_fetcher.py         # HGEFS NOMADS + NBM text bulletin
│   └── teleconn_fetcher.py      # CPC indices + BoM MJO
├── signal_engine/
│   ├── gumbel_model.py          # NBM prior + Gumbel + isotonic calibration
│   ├── gate_checker.py          # All 6 gates
│   └── event_triggers.py        # Polling loop + trigger detection
├── kalshi_watcher/
│   └── orderbook.py             # Kalshi WebSocket orderbook manager
├── paper_trader/
│   └── simulator.py             # Signal execution + P&L tracking
├── data_store/
│   ├── schema.py                # SQLite database creation
│   └── db.py                    # Connection manager + helpers
├── dashboard/
│   └── daily_report.py          # Daily summary printer
├── keys/
│   ├── kalshi_private.pem       # RSA private key (chmod 600)
│   └── kalshi_public.pem        # RSA public key
└── data/
    └── pipeline.db              # SQLite database
```

---

## CONFIRMED CREDENTIALS

```python
# Environment variables (set in ~/.zshrc)
KALSHI_API_KEY   = "7f460be7-3df7-4e4b-86c4-9c92fbfd675e"  # RSA key ID
KALSHI_KEY_PATH  = "$HOME/prediction-market-analysis/keys/kalshi_private.pem"
WETHR_API_KEY    = os.environ['WETHR_API_KEY']  # wethr.net Pro

# Confirmed working:
# Kalshi RSA auth → Status 200, balance 1000 ($10.00)
# wethr.net Pro → all REST endpoints confirmed
```

---

## WETHR.NET PRO API (PRIMARY DATA HUB)

**Base URL:** `https://wethr.net/api/v2/`
**Auth:** `Authorization: Bearer {WETHR_API_KEY}`
**Rate limits:** 60 calls/min, 5,000 calls/day
**Push API:** NOT deployed yet — use REST polling

### Confirmed Working Endpoints

```python
# 1. Latest observation
GET /observations.php?station_code=KNYC&mode=latest
# Returns: observation_time, temperature (Celsius), dew_point, wind_speed

# 2. Wethr High — most important endpoint
GET /observations.php?station_code=KNYC&mode=wethr_high&logic=nws
# Returns: wethr_high (°F int), wethr_low, time_of_high_utc,
#          calculation_logic, units
# logic=nws: Standard Time year-round, includes DSM/CLI/6hr + OMO data

# 3. DSM detection
GET /observations.php?station_code=KNYC&mode=latest&observation_type=dsm_high

# 4. CLI confirmation
GET /observations.php?station_code=KNYC&mode=latest&observation_type=cli_high

# 5. History (REQUIRES start_time AND end_time)
GET /observations.php?station_code=KNYC&mode=history&start_time=2026-04-24 00:00:00&end_time=2026-04-24 23:59:59
# Returns: list of observations, temperatures in Celsius

# 6. HRRR forecast (always live)
GET /forecasts.php?location_name=KNYC&model=HRRR&run=latest
# Returns: [{model, run_time, valid_time, forecast_hour,
#            temperature_k, temperature_f, temperature_c}]

# 7. NBM forecast (always live)
GET /forecasts.php?location_name=KNYC&model=NBM&run=latest

# 8. Other models (available during trading hours)
GET /forecasts.php?location_name=KNYC&model=GFS&run=latest
GET /forecasts.php?location_name=KNYC&model=ECMWF&run=latest
GET /forecasts.php?location_name=KNYC&model=NAM&run=latest
GET /forecasts.php?location_name=KNYC&model=ICON&run=latest
GET /forecasts.php?location_name=KNYC&model=UKMO&run=latest
GET /forecasts.php?location_name=KNYC&model=ARPEGE&run=latest
GET /forecasts.php?location_name=KNYC&model=JMA&run=latest

# 9. NWS Forecast Evolution
GET /nws_forecasts.php?station_code=KNYC
# Returns: version (int), hourly_temps[], high, low, forecast_date
# TRIGGER: when version increments → recheck all gates
```

### Models confirmed available for KNYC
```
Always live:        HRRR, NBM
During trading hrs: GFS, ECMWF, NAM, ICON, UKMO, ARPEGE, JMA
```

---

## KALSHI API

**Base URL:** `https://api.elections.kalshi.com/trade-api/v2`
**WebSocket:** `wss://api.elections.kalshi.com/trade-api/v2/ws`
**Auth:** RSA-PSS signing (mandatory for both REST and WebSocket)

### RSA Authentication

```python
import time, base64, os
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

def get_auth_headers(method: str, path: str) -> dict:
    with open(os.environ['KALSHI_KEY_PATH'], 'rb') as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)
    ts = str(int(time.time() * 1000))
    msg = f"{ts}{method}{path}".encode()
    sig = private_key.sign(msg,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256())
    return {
        "KALSHI-ACCESS-KEY": os.environ['KALSHI_API_KEY'],
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode()
    }
```

### Fee Formula (CEILING ROUNDED)

```python
import math

def taker_fee(contracts: int, price: float) -> float:
    return math.ceil(0.07 * contracts * price * (1 - price) * 100) / 100

def maker_fee(contracts: int, price: float) -> float:
    return math.ceil(0.0175 * contracts * price * (1 - price) * 100) / 100
```

### WebSocket Orderbook

```python
# Subscribe
{"id": 1, "cmd": "subscribe",
 "params": {"channels": ["orderbook_delta"],
            "market_tickers": ["KXHIGHNY-26APR25-T70"]}}

# Implied YES ask = 1.00 - best_no_bid
# Implied NO ask  = 1.00 - best_yes_bid
# ALL prices: decimal.Decimal — NEVER float
# Sequence gap → resubscribe immediately
# Backoff: 1s → 2s → 4s → 8s → max 60s
# WebSocket = READ ONLY — orders via REST only
```

---

## HGEFS (NOMADS — S3 DOES NOT EXIST YET)

```
Base: https://nomads.ncep.noaa.gov/pub/data/nccf/com/hgefs/prod/hgefs.YYYYMMDD/CC/
File: hgefs{member}.t{CC}z.pgrb2.0p25.f{FFF}
Members: c00 + p01-p61 (62 total)
Cycles: 00Z, 06Z, 12Z, 18Z — available ~3-4hr after initialization

GRIB2 field:
  shortName=tmax, typeOfLevel=heightAboveGround, level=2, stepType=max

Central Park: lat=40.7789, lon=286.0308 (0-360 grid)

Physics members: c00 + p01-p30
AI members: p31-p61
```

### Processing

```python
# 1. Pull all fhr hours covering 00-24 ET on target date
# 2. Per-member MAX across those hours
# 3. Bilinear interpolate to KNYC
# 4. physics_mean/spread from c00+p01-p30
# 5. ai_mean/spread from p31-p61
# Gate 1: abs(physics_mean - ai_mean) <= 1.5°F
#         physics_spread < 3.0°F AND ai_spread < 3.0°F
```

---

## NBM TEXT BULLETIN (BAYESIAN PRIOR)

```
URL: https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/blend.YYYYMMDD/CC/text/blend_nbptx.tCCz
Updates: Every hour
Fields: TXNP1=10th, TXNP2=25th, TXNP5=50th, TXNP7=75th, TXNP9=90th percentile MaxT (°F)
NBM v5.0 operational April 15, 2026 — treat as calibration reset
```

---

## TELECONNECTION INDICES

```python
# Daily MJO (stable URL)
BoM_RMM = "http://www.bom.gov.au/climate/mjo/graphics/rmm.74toRealtime.txt"
# Columns: year month day RMM1 RMM2 phase amplitude missing
# Filter: missing != 999

# Monthly ENSO
ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"

# Monthly NH teleconnections (NAO, PNA, EA, WP, EP, TNH, POL)
TELE_URL = "https://ftp.cpc.ncep.noaa.gov/wd52dg/data/indices/tele_index.nh"

# Feature lags for XGBoost:
# AO, NAO, PNA, EPO, WPO: lag-0, lag-1, lag-3, lag-7
# MJO: lag-0, lag-7, lag-10, lag-14
# ONI: lag-0 (monthly)
# Encode as raw standardized values — NOT tercile categories
```

---

## THE 6-GATE SYSTEM

### Gate 1 — HGEFS Convergence
```python
PASS = (abs(physics_mean - ai_mean) <= 1.5 and
        physics_spread < 3.0 and ai_spread < 3.0)
```

### Gate 2 — Gumbel Gap
```python
from scipy.stats import gumbel_r
mu = consensus_temp_f - 0.45
beta = 0.742
P_model = gumbel_r.cdf(hi+0.5, mu, beta) - gumbel_r.cdf(lo-0.5, mu, beta)
gap_pp = (P_model - market_price) * 100
PASS = abs(gap_pp) > 20.0
```

### Gate 3 — Price Band
```python
PASS = 0.25 <= yes_price <= 0.75
```

### Gate 4 — Dead Zone
```python
PASS = not (35.0 <= abs(gap_pp) <= 40.0)
```

### Gate 5 — METAR (9:51 AM ET reading)
```python
# YES: PASS if abs(metar_temp_f - bracket_center) <= 8.0
# NO:  PASS if abs(metar_temp_f - bracket_center) > 3.0
# No reading → SKIP
```

### Gate 6 — Evening Reversal
```python
# FAIL if bracket price rose >10¢ then fell >10¢ before midnight
# Cold brackets (<=52°F): 94 cases → 98% NO rate
# Both Gate 1 fail + Gate 6 fire → definitely skip
```

---

## EVENT-DRIVEN TRIGGERS

```python
# Trigger conditions — any fires gate check:
# 1. New HRRR run_time detected
# 2. New HGEFS cycle on NOMADS
# 3. NWS forecast version incremented
# 4. KNYC temp deviates >1.5°F from trajectory
# 5. Kalshi bracket price moves >5¢ in 30 min
# 6. DSM detected

# Fallback: if no trigger fires by 11 AM ET → run gates anyway
```

---

## TRADE EXECUTION

```python
TARGET_EXIT    = 0.68
STOP_LOSS_DIFF = 0.20
DSM_CANCEL_ET  = "16:15"   # 4:15 PM — cancel before 4:21 DSM
MAX_HOLD_ET    = "23:00"   # 11 PM

STARTING_BANKROLL  = 500.00
MAX_TRADE_PCT      = 0.05   # 5% max per trade
POSITION_SIZING    = "quarter_kelly"
```

---

## CITY CONFIGS

```python
CITIES = {
    "KNYC": {
        "series": "KXHIGHNY", "timezone": "America/New_York",
        "dsm_times_et": ["16:21", "17:21", "01:17"],
        "lat": 40.7789, "lon": -73.9692,
        "sharpe": 4.72, "active": True
    },
    "KPHL": {
        "series": "KXHIGHPHL", "timezone": "America/New_York",
        "dsm_times_et": ["16:21", "17:21"],
        "lat": 39.8729, "lon": -75.2408,
        "sharpe": 2.83, "active": True
    },
    "KMDW": {
        "series": "KXHIGHCHI", "timezone": "America/Chicago",
        "dsm_times_et": ["17:17", "18:17", "02:17"],
        "lat": 41.7868, "lon": -87.7522,
        "sharpe": 1.58, "active": False
    }
}
# NEVER trade KAUS — Sharpe -1.57
# Best season: Aug-Nov. Worst: Apr-May (minimum size)
```

---

## POLLING SCHEDULE

```python
# wethr.net usage: ~400 REST calls/day (within 5,000/day limit)

SCHEDULE = {
    "60s":    ["wethr_latest_obs", "wethr_high_nws", "wethr_dsm_check"],
    "5min":   ["nws_version_check", "hrrr_run_check", "nbm_run_check"],
    "30min":  ["kalshi_prices", "hgefs_cycle_check", "model_multi_check"],
    "daily":  ["teleconnections", "cli_confirmation", "performance_summary"]
}
```

---

## KNOWN FAILURE MODES

1. Fixed 10 AM entry → -$116 vs event-driven
2. 65¢ exit → suboptimal vs 68¢
3. 15¢ stop → -$96 vs 20¢
4. Gaussian distribution → -$75 vs Gumbel
5. Trading 35-40pp dead zone → negative P&L
6. Holding past 4:15 PM ET → DSM bot destroys position
7. Public weather apps for settlement → wrong source
8. Trading KAUS → Sharpe -1.57
9. Contracts < 25¢ → 60%+ capital loss
10. Contracts > 75¢ → NWS error risk
11. Float for Kalshi prices → corrupts orderbook
12. GFS alone → 29% win rate
13. S3 for HGEFS → bucket does not exist

---

## F-1 VISA — UNRESOLVED

**DO NOT DEPOSIT REAL MONEY WITHOUT DSO WRITTEN GUIDANCE**
Talk to university DSO. Get written guidance before any real deposits.
Log all trades for frequency documentation.