# Kalshi Weather Trading — Complete Strategy Document
**Last updated: April 25, 2026**
**Sources: Becker dataset (806,295 trades), wethr.net Discord, r/Kalshi, r/PredictionsMarkets,
UCD academic paper, predictandprofit.io, Oalkhadra GitHub, deep research (April 25 2026),
live API testing (April 25 2026), microstructure analysis (10 analyses)**

---

## SECTION 1: MARKET STRUCTURE

### How Kalshi NYC Temperature Markets Work
- **Series:** KXHIGHNY — daily high temperature at Central Park (KNYC station)
- **Settlement source:** NWS Daily CLI — NOT Google, NOT Weather Underground, NOT apps
- **Market open:** 10 AM ET the day before
- **Last trading:** 11:59 PM ET on event day
- **Settlement:** NWS CLI released following morning ~7-8 AM ET
- **Bracket structure:** 6 mutually exclusive brackets — 4 narrow 2°F + 2 wide tail brackets
- **Position limit:** $25,000 per market

### Settlement Timing — DST Critical Detail
- CLIs recorded midnight to midnight **Local Standard Time (LST)**
- During **Daylight Saving Time**: CLI measures **1 AM to 1 AM ET** (NOT midnight)
- Affects the final trading hour — always check DST status

### Expiration Delay Triggers
Settlement delayed when:
1. High temp inconsistent with 6-hr or 24-hr METAR highs
2. Final CLI lower than preliminary report

### Settlement Finality Rule (CFTC)
"Revisions to the Underlying made after Expiration will not be accounted for."
Once Kalshi's expiration snapshot is taken, even a corrected NWS report cannot change settlement.

### Other Platforms
- **Robinhood:** Same Kalshi infrastructure, same NWS CLI. Fee: flat $0.02/contract.
- **Polymarket:** Settles on Weather Underground — NYC uses LaGuardia (KLGA) NOT Central Park.
- **ForecastEx (IBKR):** 31 temperature markets, 3.14-3.83% APY on open positions.
  YES + NO bids sum to $1.01 (1¢ = fee built in).

### Structural Market Inefficiency
Markets systematically over-price uncertainty by ~1.27× realized uncertainty.
Favorite-longshot bias: wing brackets over-priced, central brackets under-priced.
"Makers and Takers" paper (300k+ Kalshi contracts): contracts >50¢ earn positive returns.
Oalkhadra system: 1.27× mispricing exploited → 38% total return, 3.16 Sharpe (live).

---

## SECTION 2: PRIMARY WEATHER MODEL — HGEFS (62-MEMBER)

**MOST IMPORTANT TECHNICAL FINDING. NEVER REVERT TO 4-MODEL APPROACH.**

### What HGEFS Is
NOAA launched AIGEFS December 17, 2025 as part of Project EAGLE.
AI ensemble built on Google DeepMind's GraphCast architecture.
Combined with 31 physical GFS members = HGEFS (62 total members).

- **Physics:** 31 GFS members
- **AI:** 31 AIGEFS members
- **Cycles:** 00Z, 06Z, 12Z, 18Z
- **Available:** NOMADS HTTPS ~3-4 hours after cycle initialization

**CRITICAL: S3 bucket `noaa-hgefs-pds` does NOT exist yet.**
Use NOMADS HTTPS with .idx byte-range subsetting:
```
https://nomads.ncep.noaa.gov/pub/data/nccf/com/hgefs/prod/hgefs.YYYYMMDD/CC/
```

### Why HGEFS Beats 4-Model Approach
"4 API providers" = 4 interpretations of same underlying GFS/ECMWF data = false confidence.
HGEFS provides genuine independence: physics uncertainty + AI uncertainty.
When two DIFFERENT methodologies agree → strong signal.

### HGEFS Gate Logic
```
Step 1: Pull all 62 members
Step 2: Split — physics (c00+p01-p30) vs AI (p31-p61)
Step 3: physics_mean, physics_spread = mean/std of physics subset
Step 4: ai_mean, ai_spread = mean/std of AI subset
Step 5: PASS if abs(physics_mean - ai_mean) <= 1.5°F
             AND physics_spread < 3.0°F
             AND ai_spread < 3.0°F
Step 6: Disagree → genuine uncertainty → SKIP
```

### Historical Fallback (pre-Dec 2025 backtest only)
4-model: GFS + ECMWF + ICON + GEM. Gate: 3-of-4 within 2.0°F.

---

## SECTION 3: THE MODEL STACK (FULL)

### Primary Sources (in order of importance)
1. **HGEFS 62-member** — primary gate (physics vs AI agreement)
2. **NBM v5.0 probabilistic** — Bayesian prior (10th/25th/50th/75th/90th percentile MaxT)
3. **HRRR** — highest-accuracy 0-24h model, always live via wethr.net Pro API
4. **NBM** — always live, hourly, via wethr.net Pro API
5. **GFS, ECMWF, NAM, ICON, UKMO, ARPEGE, JMA** — via wethr.net Pro API

### wethr.net Pro API Models
```python
# Confirmed working for KNYC:
Always live:        HRRR, NBM
Trading hours:      GFS, ECMWF, NAM, ICON, UKMO, ARPEGE, JMA

# wethr.net Pro: $24.99/mo
# 60 calls/min, 5,000 calls/day
# Push API BETA not deployed — use REST polling
```

### NBM Text Bulletin (Bayesian Prior)
```
URL: https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/blend.YYYYMMDD/CC/text/blend_nbptx.tCCz
Percentiles: TXNP1(10th), TXNP2(25th), TXNP5(50th), TXNP7(75th), TXNP9(90th) — all in °F
NBM v5.0 went operational April 15, 2026 (cutover point for calibration)
```

### HRRR Known Biases (Apply Corrections)
- Warm/dry bias in summer (~1.5°F warm) → lean LOW vs HRRR in June-August
- Diurnal cold bias under <50% sky cover in winter → lean HIGH on clear winter days
- Source: NY State Mesonet validation studies

### AI Model Notes
- **AIFS (ECMWF AI):** ~10% RMSE reduction vs IFS through troposphere. Underestimates tails.
- **GenCast (DeepMind):** Outperforms ENS on 97.2% of variables. Code/weights public on GitHub.
- Neither directly accessible via API currently — use wethr.net for ECMWF data.

---

## SECTION 4: PROBABILITY MODEL — GUMBEL + ISOTONIC CALIBRATION

### Why Gumbel (Not Gaussian)
Daily temperature maxima are extreme values → Gumbel distribution.
Ablation test A2: Gaussian → -$75 P&L impact. Gumbel is mandatory.

### Gumbel Parameters
```python
from scipy.stats import gumbel_r

mu   = consensus_temp_f - 0.45   # mode correction (NOT -0.5)
beta = 0.742                      # = ECMWF_MAE / 1.28 = 0.95 / 1.28

# Model biases for KNYC:
ECMWF: MAE = 0.95°F, bias = -0.42°F (runs cold)
GFS:   MAE = 1.58°F, bias = +0.47°F (runs warm)
```

### Bracket Probability
```python
# Range bracket (e.g., 72-73°F)
P = gumbel_r.cdf(hi + 0.5, mu, beta) - gumbel_r.cdf(lo - 0.5, mu, beta)

# Lower tail (<=53°F)
P = gumbel_r.cdf(threshold - 0.5, mu, beta)

# Upper tail (>=75°F)
P = 1 - gumbel_r.cdf(threshold + 0.5, mu, beta)
# ±0.5 = continuity corrections for NWS integer rounding
```

### Bayesian Update with NBM
```python
# NBM p50 = prior center
# HGEFS spread = likelihood width
# Posterior mu = weighted average of HGEFS consensus and NBM p50
# Posterior beta = adjusted by HGEFS spread

nbm_weight = 0.4   # NBM calibration weight
hgefs_weight = 0.6 # HGEFS weight
posterior_mu = (hgefs_weight * hgefs_consensus) + (nbm_weight * nbm_p50) - 0.45
```

### Isotonic Calibration
```python
from sklearn.isotonic import IsotonicRegression

# Rolling 90-day calibration on (model_prob, outcome) pairs
# Fit new calibrator every 7 days
# Apply calibration before gap calculation
# Treat April 15, 2026 as calibration reset (NBM v5.0 cutover)
# Trade only when calibrated_prob - market_price > 0.03 after fees
```

---

## SECTION 5: THE 6-GATE SYSTEM

**All 6 gates must pass. Any failure = NO TRADE. No exceptions.**

### Gate 1 — HGEFS Convergence
```python
PASS = (abs(physics_mean - ai_mean) <= 1.5 and
        physics_spread < 3.0 and ai_spread < 3.0)
# FAIL → genuine uncertainty → skip, log reason
```

### Gate 2 — Gumbel Gap Filter
```python
gap_pp = (P_model - market_price) * 100
PASS = abs(gap_pp) > 20.0
# Positive gap → YES trade
# Negative gap → NO trade
# Sweet spots: 20-25pp and 40pp+
```

### Gate 3 — Price Band
```python
PASS = 0.25 <= yes_price <= 0.75
# <0.25: longshot trap (UCD: <20¢ loses 60%+ of capital)
# >0.75: NWS error risk (one error: 95¢ → 1¢ instantly)
```

### Gate 4 — Dead Zone Exclusion
```python
PASS = not (35.0 <= abs(gap_pp) <= 40.0)
# Confirmed negative P&L in all backtest configurations
# Every other gap range is profitable — this one is not
```

### Gate 5 — METAR Confirmation (9:51 AM ET)
```python
# Source: wethr.net Pro latest observation API
# Use 9:51 AM reading (XX:51-XX:54 window)
# Priority: SPECI > hourly XX:51 > 6-hourly > 5-min

# YES trades: PASS if abs(metar_temp_f - bracket_center) <= 8.0
# NO trades:  PASS if abs(metar_temp_f - bracket_center) > 3.0
# No reading available → SKIP (never assume)
# Gate blocked 19% of backtest trades — all blocks were correct
```

### Gate 6 — Evening Reversal Check
```python
# Scan Kalshi price history since 3 PM ET for signal bracket
# FAIL if: price rose >10¢ THEN reversed >10¢ before midnight

# Base rate from 806,295 trades:
#   Cold brackets (<=52°F): 94 cases → 0 YES, 92 NO = 98% NO rate
#   Avg rise: 31¢ | Avg fall after: 52¢ | Next-day 11AM price: 25¢

# Cold brackets: SKIP or maximum half size
# Both Gate 1 fail + Gate 6 fire → definitely skip
# Apr 24 2026 live example: 66→51¢ reversal caused by GEM +1.5°F update
```

---

## SECTION 6: OBSERVATION DATA HIERARCHY

Priority order (highest to lowest confidence):

1. **SPECI** — Between 5-min readings on visibility change. Exact °F, zero rounding. RARE.
2. **Hourly XX:51-XX:54** — High confidence. 0.1°F precision before C conversion.
3. **6-hourly METAR high** — Releases 23:51Z, 05:51Z, 11:51Z, 17:51Z.
4. **DSM report** — Confirmed high up to release time. Fires 4:21 PM ET for NYC.
5. **5-minute readings** — Whole °F → °C → rounded → °F. Rounding artifacts.
6. **Public weather apps** — DO NOT USE. Settlement is NWS CLI only.

### NWS Rounding Chain
```
OMO: recorded whole °F
→ converted to °C
→ rounded to nearest °C
→ converted back to °F (graph displays this)
→ rounded to nearest °F (list displays this)
Graph ≠ List for same reading. CLI uses separate path. Only CLI matters.
```

### Sensor Noise Warning
On calm sunny days at 1-3 PM, ASOS sensor can spike 1-2°F above true temperature.
When 5-min data spikes above HRRR/NBM on calm sunny day → treat skeptically.
Wait for next 6-hour METAR to confirm.

---

## SECTION 7: EXIT RULES

### Primary Exit: 68¢ limit sell
Place IMMEDIATELY at entry. Do not adjust.
Sensitivity test B2: 68¢ is optimal (80¢ has NWS error risk not in 13-month backtest).

### Stop Loss: Entry - 20¢
Sensitivity test B3: 20¢ confirmed (+$96 vs 15¢ stop).

### Time-Based Exits
- 4:15 PM ET: Cancel ALL unfilled orders (DSM fires at 4:21)
- 11:00 PM ET: Force exit any remaining positions

### NWS Error Risk
Frequency: ~3×/year for NYC.
Impact: 95¢ → 1¢ instantly.
NEVER hold above 70¢ under any circumstances.

### Liquidity Filter
```python
# Skip if spread is too wide
if bracket_type == 'central' and spread > 0.04: skip
if bracket_type == 'wing' and spread > 0.06: skip
```

---

## SECTION 8: ENTRY TIMING

### Event-Driven (Primary)
Trigger fires when ANY condition is met:
1. New HRRR run_time detected (hourly)
2. New HGEFS cycle on NOMADS (~every 6 hours)
3. NWS forecast version increments
4. KNYC temperature deviates >1.5°F from forecast trajectory
5. Kalshi price moves >5¢ on any bracket within 30 minutes
6. DSM detected (check remaining signals only)

On trigger → run all 6 gates → enter if all pass.

### 11 AM ET Fallback
If no trigger fires by 11 AM ET → run gates anyway.
Confirmed optimal fixed window from sensitivity test B4:
```
10 AM: 52.7% win, +$196
11 AM: 59.0% win, +$313 ← BEST fixed time
12 PM: 53.8% win, +$236
```

### Daily Decision Timeline
```
6:00 AM  — CLI from yesterday confirmed, teleconnections updated
9:00 AM  — HGEFS 6Z run check, NBM latest bulletin
9:51 AM  — METAR gate reading (from wethr.net latest obs)
10:00 AM — Monitor Kalshi bracket prices open
11:00 AM — Fallback gate check if no trigger yet
4:15 PM  — Cancel ALL open orders
4:21 PM  — DSM fires (do not trade)
Next AM  — CLI confirmation, log settlement
```

---

## SECTION 9: BACKTEST RESULTS (BECKER DATASET)

**Dataset:** 806,295 tick-level KXHIGHNY trades, Oct 2024 – Nov 2025

```
Total trades:    260
Win rate:        60.0%
Net P&L:         +$427
Sharpe ratio:    4.72 (NYC)
Max drawdown:    -$46
```

### City Comparison
```
NYC (KNYC):  Sharpe 4.72  ← Primary city
PHL (KPHL):  Sharpe 2.83  ← Secondary city
Denver:      Sharpe 1.58
Austin:      Sharpe -1.57 ← NEVER TRADE
```

### Seasonal P&L
```
Oct 2024 – Jul 2025: +$52   (nearly flat, 10 months)
Aug 2025:            +$42
Sep 2025:            +$53   (best month)
Oct 2025:            +$23
Nov 2025:            +$33
93% of profit in final 4 months (Aug-Nov shoulder season)
```

### Gap Performance
```
20-25pp:  profitable ✅
25-35pp:  profitable ✅
35-40pp:  NEGATIVE ❌ — dead zone
40pp+:    profitable ✅
```

---

## SECTION 10: POSITION SIZING

### Quarter-Kelly Formula
```python
import math

def position_size(bankroll, model_prob, market_price, contracts=1):
    edge = model_prob - market_price
    b = (1 - market_price) / market_price  # payout ratio
    kelly_f = (b * model_prob - (1 - model_prob)) / b
    quarter_kelly = kelly_f * 0.25
    max_stake = bankroll * 0.05  # 5% hard cap
    stake = min(quarter_kelly * bankroll, max_stake)
    return max(0, stake)

# Correlation discount across cities:
# NYC + PHL errors correlate ~0.7 → divide combined position by ~1.4
# Never deploy >15% bankroll across all open positions simultaneously
```

### Bankroll Rules
- Starting paper bankroll: $500
- Maximum per trade: 5% of bankroll ($25 at $500)
- Scale up ONLY after 30 documented profitable paper trades
- Reserve 15% as opportunistic capital for high-conviction setups

### Seasonal Sizing
- Apr-May: Minimum size (worst months historically)
- Jun-Jul: Normal size
- Aug-Nov: Scale up (shoulder season — 93% of profit)

---

## SECTION 11: FEE STRUCTURE

### Kalshi Fees (Ceiling-Rounded)
```python
import math

def taker_fee(contracts, price):
    return math.ceil(0.07 * contracts * price * (1 - price) * 100) / 100

def maker_fee(contracts, price):
    return math.ceil(0.0175 * contracts * price * (1 - price) * 100) / 100

# Always use limit orders → maker fee (4× cheaper)
# Fee is largest at 50¢: 7¢ × 0.5 × 0.5 = 1.75¢/contract taker
# Fee is smallest at wings: near 0 at 5¢ or 95¢
```

### Kalshi Incentive Programs (active through Sep 1, 2026)
- **VIP:** $0.005 cashback per contract (3¢-97¢ price range)
- **LIP:** Paid for resting limit orders (random 1-second snapshots)

### Slippage Assumption (paper trading)
- Taker fill: half-spread + 1 tick
- Stress test: double the above

---

## SECTION 12: DATA SOURCES (COMPLETE VERIFIED)

### wethr.net Pro API (Primary Hub) — $24.99/mo
```python
BASE = "https://wethr.net/api/v2/"
HEADERS = {"Authorization": f"Bearer {os.environ['WETHR_API_KEY']}"}

# All confirmed working endpoints (April 25, 2026):
observations.php?station_code=KNYC&mode=latest
observations.php?station_code=KNYC&mode=wethr_high&logic=nws
observations.php?station_code=KNYC&mode=latest&observation_type=dsm_high
observations.php?station_code=KNYC&mode=latest&observation_type=cli_high
observations.php?station_code=KNYC&mode=history&start_time=...&end_time=...
forecasts.php?location_name=KNYC&model=HRRR&run=latest
forecasts.php?location_name=KNYC&model=NBM&run=latest
nws_forecasts.php?station_code=KNYC

# Rate: 60/min, 5,000/day. Push API: NOT deployed (use REST polling)
# Note: temperatures returned in Celsius — convert to Fahrenheit
```

### HGEFS (NOMADS HTTPS)
```
https://nomads.ncep.noaa.gov/pub/data/nccf/com/hgefs/prod/hgefs.YYYYMMDD/CC/
S3 bucket noaa-hgefs-pds does NOT exist yet
Subscribe nodd@noaa.gov for bucket announcement
```

### NBM Text Bulletin
```
https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/blend.YYYYMMDD/CC/text/blend_nbptx.tCCz
```

### Teleconnections (Free)
```python
BoM_RMM  = "http://www.bom.gov.au/climate/mjo/graphics/rmm.74toRealtime.txt"
ONI      = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
TELE_NH  = "https://ftp.cpc.ncep.noaa.gov/wd52dg/data/indices/tele_index.nh"
# CPC daily AO/NAO/PNA URLs unstable — wrap in try/except + local cache
```

### Kalshi API
```
REST:      https://api.elections.kalshi.com/trade-api/v2
WebSocket: wss://api.elections.kalshi.com/trade-api/v2/ws
Auth:      RSA-PSS (key confirmed working April 25, 2026)
Balance:   $10.00 cash confirmed
```

### DSM Release Times (ET)
```
NYC:     4:21 PM, 5:21 PM, 1:17 AM
Chicago: 5:17 PM, 6:17 PM, 2:17 AM
Miami:   4:12 PM, 5:12 PM, 3:22 AM
Austin:  6:16 PM, 9:16 AM, 2:16 AM (NEVER TRADE)
Denver:  6:17 PM, 7:17 PM, 8:17 AM
LA:      6:08 PM, 9:08 PM, 4:08 AM
```

### Fallback Sources (if wethr.net down)
```
IEM ASOS: https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py
NWS DSM:  https://mesonet.agron.iastate.edu/wx/afos/p.php?pil=DSMNYC
NWS CLI:  https://forecast.weather.gov/product.php?site=OKX&product=CLI&issuedby=NYC
```

---

## SECTION 13: KALSHI WEBSOCKET IMPLEMENTATION

```python
# Authentication
ts = str(int(time.time() * 1000))  # milliseconds
msg = f"{ts}GET/trade-api/v2/ws".encode()
sig = private_key.sign(msg, PSS(MGF1(SHA256()), DIGEST_LENGTH), SHA256())
headers = {
    "KALSHI-ACCESS-KEY": key_id,
    "KALSHI-ACCESS-TIMESTAMP": ts,
    "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode()
}

# Subscribe
{"id": 1, "cmd": "subscribe",
 "params": {"channels": ["orderbook_delta"],
            "market_tickers": ["KXHIGHNY-26APR25-T70"]}}

# Critical rules:
# - All prices: decimal.Decimal (NEVER float)
# - Implied YES ask = 1.00 - best_no_bid
# - Sequence gap → resubscribe immediately
# - Backoff: 1s → 2s → 4s → 8s → max 60s
# - Read only — orders via REST
# - Archive raw orderbook data from day 1 (no historical replay available)
```

---

## SECTION 14: BOTS IN THE MARKET

1. **DSM Bot** — Fires instantly at 4:21 PM ET NYC. Unbeatable. Cancel before 4:15.
2. **OMO Bot** — Calls ASOS phone line for 1-min obs before public.
3. **6-Hour Bot** — Monitors 6-hourly max temp in METAR.
4. **CLI Bot** — Next-morning CLI.
5. **Market Maker (SIG)** — Susquehanna International Group. Designated MM.

### Insider Trading Note
From Atte (wethr.net Discord, most sophisticated community trader):
"On Kalshi/CLI resolution, NWS employees have access to resolution-affecting
observation numbers hours before release. I can't play a fair game on Kalshi."
Unexplained large orders before DSM may not always be bots.

---

## SECTION 15: COMMUNITY SOURCES

- **wethr.net Discord:** Primary community. Atte and Hermie most sophisticated.
- **u/stfarm:** HGEFS approach confirmed. 62-member, 5-min scan cycle.
- **u/Gumby808:** $125k Kalshi, $30k Robinhood. NO at 50¢, exit 65-70¢.
- **u/KevinLuWX:** Top earner. Never >90¢.
- **Oalkhadra (GitHub):** XGBoost 30-feature system, 3.16 Sharpe, 923 trades, live.
- **predictandprofit.io:** V1 lost (<20¢). V2 profitable (min 40¢, 3-of-4 models).
- **UCD Academic Paper (Jan 2026):** >50¢ positive. Maker beats Taker.
- **Becker Dataset:** 806,295 KXHIGHNY ticks, Oct 2024–Nov 2025.

---

## SECTION 16: TELECONNECTION FEATURES (XGBoost)

### Most Predictive Indices for NYC
```
NAO: correlates 0.3-0.5 with NYC temp anomaly in winter
PNA: correlates -0.4 with NYC temp anomaly in winter
AO:  strong: negative AO → cold air outbreaks
EPO: moderate: negative EPO → Alaskan ridge → cold East
MJO phases 7-8: cold over Eastern CONUS in 1-3 weeks
```

### Feature Engineering
```python
# Confirmed optimal lags for NYC 24h MaxT prediction:
# AO, NAO, PNA, EPO, WPO: lag-0, lag-1, lag-3, lag-7
# MJO RMM1, RMM2, amplitude, phase: lag-0, lag-7, lag-10, lag-14
# ONI: lag-0 (monthly)

# Encoding: raw standardized values — NOT tercile categories
# XGBoost handles nonlinearity natively
```

---

## SECTION 17: FORECAST VERIFICATION METRICS

```python
# Track these for model health monitoring:
from sklearn.metrics import brier_score_loss, log_loss

# Brier score (binary outcomes)
brier = brier_score_loss(y_true, y_pred)
# Lower = better. Random = 0.25. Perfect = 0.

# CRPS (continuous MaxT)
# Lower = better. Equals MAE for deterministic forecasts.

# Brier Skill Score (vs climatology)
BSS = 1 - (brier / brier_climatology)
# Positive = beats climatology. Kill any city-bracket with BSS < 0 for 14+ days.

# Rolling window: 30 days
# Recalibrate isotonic regression: every 7 days
```

---

## SECTION 18: PAPER TRADING PROTOCOL

### 19 Required Fields (log BEFORE checking outcome)
```
1.  Date, city
2.  HGEFS physics_mean, ai_mean
3.  Gate 1: pass/fail + spread
4.  Target bracket
5.  Kalshi price at entry
6.  Gumbel model probability (calibrated)
7.  Gap in percentage points
8.  Gate 2: pass/fail + dead zone check
9.  Gate 3: pass/fail
10. METAR temp at 9:51 AM ET
11. Gate 5: pass/fail
12. Gate 6: pass/fail + reversal detected?
13. Direction: YES/NO/SKIP
14. Reasoning (written BEFORE outcome)
15. Entry price, entry time
16. Exit price, exit reason
17. Settlement from next morning CLI
18. Win/Loss, net P&L after fees
19. Notes: what was missed, was reasoning correct?
```

### Thresholds
- 30 paper trades minimum before real money
- Win rate > 55% required
- No single loss > $25 (5% of $500 bankroll)

---

## SECTION 19: RISK CONTROLS

### Hard Rules
- Cancel all orders 4:15 PM ET daily
- Never hold above 70¢
- Max 5% bankroll per trade
- Max 15% bankroll total open positions
- Stop trading if bankroll drops >20% in 7 days
- Kill any city-bracket with negative BSS for 14+ consecutive days

### Settlement Review Risk
Monitor for elevated review risk when:
- Preliminary DSM reading differs from 6-hour METAR high by >2°F
- wethr.net shows caution flag on Wethr High
- Final CLI lower than preliminary report

### Regulatory Risk
Nevada/Massachusetts/Washington/Connecticut lawsuits target sports markets — NOT weather.
Weather markets not in regulatory crosshairs as of April 2026.
Platform availability could change — maintain fallback monitoring.

---

## SECTION 20: F-1 VISA

**UNRESOLVED — DO NOT DEPOSIT REAL MONEY WITHOUT DSO WRITTEN GUIDANCE**

- Kalshi weather contracts: no LPR-only restriction (confirmed)
- F-1 frequency risk: IRS trader-tax-status threshold ~60 trades/month
- DSO guidance letters: non-binding but document good faith
- Tax treatment: ordinary income (conservative) or Section 1256 (aggressive, needs CPA)
- Log ALL trades with timestamps for frequency documentation

---

## SECTION 21: IMPLEMENTATION CHECKLIST

### Before First Paper Trade
- [x] Kalshi RSA key authenticated (Status 200, balance confirmed)
- [x] wethr.net Pro API key working (all endpoints tested)
- [x] HGEFS NOMADS access verified
- [x] NBM text bulletin format understood
- [x] BoM MJO URL confirmed
- [x] Teleconnection URLs confirmed
- [ ] pipeline.db SQLite database created
- [ ] All 13 pipeline modules built
- [ ] 30-day paper trading run started

### Before Real Money
- [ ] 30+ paper trades completed
- [ ] Win rate > 55% confirmed
- [ ] DSO written guidance obtained
- [ ] CPA consultation completed
- [ ] Bankroll funded ($500 or less initially)