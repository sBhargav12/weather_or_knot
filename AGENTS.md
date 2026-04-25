# Kalshi Weather Trading — Complete Strategy & Backtest Guide
# Last updated: April 24, 2026
# READ THIS ENTIRE FILE BEFORE WRITING ANY CODE OR MAKING ANY TRADE DECISION

---

## SECTION 0: CRITICAL RULES (read first, never violate)

1. PRIMARY MODEL IS HGEFS (62-member) — NOT the 4-model approach. See Section 2.
2. GUMBEL DISTRIBUTION ONLY — never Gaussian. mu = consensus - 0.45, beta = 0.742
3. ENTRY TIME IS 11 AM ET — not 10 AM. Confirmed +$116 improvement in backtest.
4. EXIT AT 68¢ — not 65¢. Place limit sell immediately at entry. Never hold above 70¢.
5. LOSS CUT AT 20¢ — not 15¢. Wider cut allows mean reversion.
6. MAKER FEES ONLY — always limit orders. Taker fees consumed 49% of gross profit.
7. METAR IS 9:51 AM — not 10 AM. Must be pre-entry reading.
8. NEVER leave open orders between 4:15-4:30 PM ET (DSM bot fires at 4:21 PM).
9. DEAD ZONE: never trade gaps between 35-40pp. Historical negative P&L.
10. F-1 VISA: talk to DSO before depositing any money on any platform.

---

## SECTION 1: MARKET STRUCTURE

### KXHIGHNY Series
- Settlement: NWS Daily CLI for Central Park (KNYC) — NOT Google, NOT WUnderground
- Ticker format: KXHIGHNY-YYMMMDD-B{strike} (below) or T{strike} (above)
- Markets open: 10 AM ET the day BEFORE the event
- Last trading: 11:59 PM ET on event day
- Settlement: NWS CLI released next morning ~7-8 AM ET
- 6 brackets per day: 4 narrow 2°F ranges + 2 wide tail brackets
- Position limit: $25,000 per market

### DST Settlement Critical Detail
- Final CLIs recorded 12:00 AM to 11:59 PM LOCAL STANDARD TIME
- During Daylight Saving Time: CLI measures 1 AM to 1 AM ET (NOT midnight)
- This affects the final hour of trading — always check DST status

### Expiration Delay Triggers
Market settlement delayed when:
1. High temp inconsistent with 6-hr or 24-hr METAR highs
2. Final CLI lower than preliminary report

### Other Platforms
- Robinhood: "Greater than X°F" format. Same Kalshi infrastructure. Flat $0.02/contract fee.
- Polymarket: Settles on Weather Underground (NOT NWS CLI). NYC uses LaGuardia (KLGA).
  Never cross-platform arb weather without accounting for different stations.

---

## SECTION 2: PRIMARY MODEL — HGEFS (62-MEMBER ENSEMBLE)

### THIS IS THE MOST IMPORTANT SECTION. DO NOT REVERT TO 4-MODEL APPROACH.

NOAA launched AIGEFS in December 2025 as part of Project EAGLE.
AI ensemble built on Google DeepMind's GraphCast architecture.
Combined with 31 physical GFS members = HGEFS (62 total).

- Physical component: 31 GFS members → s3://noaa-gfs-bdp-pds/
- AI component: 31 AIGEFS members → s3://noaa-hgefs-pds/
- Available: December 2025 onwards (free, NOAA AWS S3)

### Why HGEFS Beats 4-Model Approach
Most API providers are downstream consumers of the same underlying GFS/ECMWF data.
"Consensus of 4 providers" = 4 interpretations of same data = false confidence.

HGEFS provides genuine independence:
- Physics ensemble: captures atmospheric dynamics uncertainty
- AI ensemble: captures pattern-recognition uncertainty
- Agreement between two DIFFERENT methodologies = far stronger signal

Key rule from u/stfarm (verified HGEFS trader, wethr.net Discord):
"When physics ensemble and AI ensemble agree → confidence HIGH.
 When they disagree → probability moves toward 50/50."

### HGEFS Entry Gate
Step 1: Calculate spread across all 31 physical GFS members
Step 2: Calculate spread across all 31 AIGEFS members
Step 3: Compare the two consensus temperatures
Step 4: ONLY proceed if BOTH subsets agree within 1.5°F AND
         individual spread within each subset < 3°F
Step 5: If physics and AI disagree → genuine uncertainty → SKIP

### Model Update Times (ET)
- GFS 6Z run: initialized 6 AM UTC → available ~9-10 AM ET (USE THIS at 9 AM check)
- GFS 12Z run: initialized noon UTC → available ~1 PM ET
- ECMWF 0Z: midnight UTC → available ~7-8 AM ET
- GEM 0Z: midnight UTC → available ~5-6 AM ET
- ICON 0Z: midnight UTC → available ~5-6 AM ET

### Pre-December 2025 Fallback (for historical backtest ONLY)
Use 4-model approach:
- GFS (NOAA), ECMWF (European), ICON (German DWD), GEM (Canadian)
- All via Open-Meteo historical API
- Gate: 3 of 4 agree within 2.0°F of consensus
- Confirmed optimal threshold in sensitivity test B6

---

## SECTION 3: PROBABILITY DISTRIBUTION — GUMBEL NOT GAUSSIAN

Daily temperature maxima are extreme values. They follow Gumbel distribution.
Gaussian is wrong. Confirmed -$75 P&L impact in ablation test A2.

### Parameters
mu   = consensus_forecast - 0.45°F  (Gumbel mode correction)
beta = ECMWF_MAE / 1.28 = 0.95 / 1.28 = 0.742°F

ECMWF MAE for NYC = 0.95°F (30-day measured)
GFS MAE for NYC   = 1.58°F (30-day measured)
ECMWF bias = -0.42°F (runs cold)
GFS bias   = +0.47°F (runs warm)

### Bracket Probability Formulas
from scipy.stats import gumbel_r

Range bracket (e.g. 72-73°F):
  P = gumbel_r.cdf(hi + 0.5, mu, beta) - gumbel_r.cdf(lo - 0.5, mu, beta)

Lower tail (e.g. ≤53°F):
  P = gumbel_r.cdf(threshold - 0.5, mu, beta)

Upper tail (e.g. ≥75°F):
  P = 1 - gumbel_r.cdf(threshold + 0.5, mu, beta)

The ±0.5 continuity corrections account for NWS integer rounding.

---

## SECTION 4: THE COMPLETE TRADE ENTRY PROCESS — ALL 6 GATES

All 6 gates must pass. If any gate fails → NO TRADE. No exceptions.

### Gate 1 — HGEFS Convergence (Primary Gate)
Check at 9 AM ET (after 6Z run) and optionally at 1 PM ET (after 12Z)
Physics ensemble mean and AI ensemble mean must agree within 1.5°F.
If they disagree → skip. Spread blown = 98% of time market catches it first.

For historical backtest (pre-Dec 2025): 3-of-4 models within 2.0°F.

### Gate 2 — Gumbel Gap Filter
gap = model_probability - market_price_as_fraction
Minimum gap: abs(gap) > 20pp
Positive gap → YES trade. Negative gap → NO trade.

### Gate 3 — Price Band Filter
YES trade entry: 25¢ minimum, 75¢ maximum
NO trade entry: same applied to NO price (1 - yes_price)
Below 25¢: longshot trap (UCD paper: <20¢ loses 60%+ of capital)
Above 75¢: NWS error risk zone (one error turns 95¢ to 1¢)

### Gate 4 — Dead Zone Exclusion
SKIP any trade where abs(gap) is between 35pp and 40pp.
Backtest confirmed this zone produces negative P&L.
All other gap zones are profitable. This one is not.

### Gate 5 — METAR Confirmation
Use the 9:51 AM ET KNYC reading (last hourly BEFORE 11 AM entry).
URL: https://www.weather.gov/wrh/timeseries?site=knyc
Hourly readings are at XX:51-XX:54 — most accurate, no rounding ambiguity.

  YES trades: PASS if abs(METAR - bracket_center) ≤ 8°F
  NO trades:  PASS if abs(METAR - bracket_center) > 3°F

No METAR available → skip. Assume nothing.
This gate blocked 19% of trades in backtest — all were correct blocks.

### Gate 6 — Evening Reversal Check (NEW — from microstructure analysis)
If signal bracket rose >10¢ between 3-8 PM then reversed >10¢ before midnight:
  Cold brackets (≤52°F): 98% historical NO settlement rate → SKIP or half size
  Warm brackets (≥68°F): run equivalent analysis
This pattern and Gate 1 failure are correlated. When both warn → definitely skip.
Historical base rate: 94 cases, 0 YES settlements, 92 NO (98%).

---

## SECTION 5: EXIT RULES (NON-NEGOTIABLE)

### Primary Exit: Limit sell at 68¢
Place limit sell order IMMEDIATELY at entry. Do not wait. Do not move it.
The 79% win rate on target hits came from this discipline.

Never hold above 70¢. NWS errors occur ~3x/year.
One error at 95¢ turns it to 1¢ instantly. One error = year of gains wiped.
KevinLuWX (top earner, r/Kalshi): "Never buy >90¢ weather contracts."

### Loss Cut: Exit when price moves 20¢ against position
Entry at 40¢ → cut at 20¢
Entry at 55¢ → cut at 35¢
Sensitivity test B3 confirmed: 20¢ cut outperforms 15¢ by +$96.
Wider cut allows mean reversion on positions that drift before recovering.

### Time Cut: Exit at 11 PM ET regardless
Never hold overnight. Settlement is next morning. Too much unknown risk.

### The 1¢ Dead Bracket Signal
When any bracket drops to 1¢ → sophisticated money is saying it is dead.
Buy NO on 1¢ brackets with high confidence. Low risk, high certainty.

### Never Leave Open Orders at DSM Release Time
Cancel all open orders by 4:15 PM ET.
NYC DSM fires at 4:21 PM ET (20:21Z). DSM bot fires in milliseconds.
Any open limit order gets filled at adversarial price during this window.

---

## SECTION 6: FEE STRUCTURE

### Kalshi Fees
Taker fee = 7¢ × P × (1-P) per contract
Maker fee = 25% of taker fee (limit orders ONLY)

Example at 50¢: Taker = 1.75¢, Maker = 0.44¢
Apply to BOTH entry AND exit legs.

### Why Maker Fees Are Mandatory
Backtest (taker fees):  +$211.93 net on $2,440 staked (8.7% ROI)
Projected (maker fees): +$270.43 net (28% improvement, zero added risk)
Taker fees consumed 37% of gross profit. Always use limit orders.

---

## SECTION 7: CONFIRMED BACKTEST RESULTS

### Test 0 — Full Baseline (Oct 2024 → Nov 2025, NYC only)
Trades: 260 | Win rate: 53.1% | Net P&L taker: +$211.93 | Sharpe: 2.56
Max drawdown: -$41.25 | Fees: $78.01

### Ablation Results (value of each component)
Component removed          | P&L impact | Verdict
Model agreement gate       | -$91       | KEEP
Gumbel (→Gaussian)         | -$75       | KEEP GUMBEL
METAR confirmation         | -$38       | KEEP
Gap filter (→any gap)      | -$78       | KEEP 20pp threshold
Price filter               | Artifact   | KEEP 25¢-75¢ band
Loss cut (→hold to 11PM)   | +$703      | DANGEROUS — NWS error trap
Dead zone exclusion        | +$20       | ADD to strategy

### Sensitivity Results — Optimal Parameters
Parameter      | Tested range      | Optimal    | Baseline
Entry time     | 10AM-3PM          | 11 AM      | 10 AM (+$116)
Exit target    | 60¢-80¢           | 68¢ live*  | 65¢
Loss cut       | 10¢-25¢           | 20¢        | 15¢ (+$96)
Gap threshold  | 10pp-40pp         | 20pp       | 20pp (flat 10-20pp)
Min price      | 15¢-35¢           | 25¢        | 25¢
Max price      | 65¢-85¢           | 75¢        | 75¢
Agreement      | 1.0-3.0°F         | 2.0°F      | 2.0°F

*80¢ shows best backtest P&L but NWS error risk not captured in data.
 Use 68¢ in live trading — above community consensus danger zone.

### Walk-Forward Validation
Training (Oct24-Apr25):   118 trades | 52.5% | +$51.94  | Sharpe 1.51
Validation (May25-Nov25): 142 trades | 53.5% | +$159.99 | Sharpe 3.34
VERDICT: Edge is REAL. Not overfit. Validation outperformed training.

### City Comparison Results
City   | Trades | Win%  | Net P&L | Sharpe | Verdict
NYC    |    195 | 60.0% | +$427   |  4.72  | START HERE
PHIL   |    196 | 53.1% | +$198   |  2.83  | Second city
DEN    |    248 | 58.1% | +$75    |  1.58  | Third
MIA    |    255 | 52.2% | +$95    |  0.83  | Volatile
CHI    |    241 | 48.5% | +$31    |  0.31  | Weak
LAX    |     76 | 52.6% | +$19    |  0.39  | Too few trades
AUS    |    242 | 47.1% | -$115   | -1.57  | AVOID

Start with NYC only. Add Philadelphia after 30 profitable NYC trades.
Never trade Austin — convective weather pattern breaks synoptic models.

---

## SECTION 8: MICROSTRUCTURE FINDINGS (806,295 trades analyzed)

### Volume Profile
Peak volume: 1 PM ET (10.2% of daily). Enter at 11 AM BEFORE the surge.
DSM window (4-6 PM): 16.9% of daily volume. Do not chase this.
Tightest spreads: 3-7 AM ET. Irrelevant — no volume then.

### DSM Bot Fingerprint
4 PM hour: 1,611 volume spikes, avg price move 6.6¢.
NEVER leave open limit orders between 4:15-4:30 PM ET.
DSM bot fires in milliseconds. You will not win this race.

### Price Velocity by Window
Window         | Avg velocity | Notes
10AM-12PM      | 1.9¢/hr      | Gaps still open — best entry window
12PM-3PM       | 1.8¢/hr      | Compression beginning
3PM-5PM        | 2.4¢/hr      | DSM window, fastest
5PM-11PM       | 1.1¢/hr      | Slower, position settling
11PM-close     | 5.7¢/hr      | High velocity but tiny volume — settlement approach

### Order Flow Structure
Buy imbalance exists ALL day — market has structural YES bias.
Strongest buy pressure: 8 PM ET (informed overnight model positioning).
YES trades align with order flow. Slight structural advantage over NO trades.

### Reversal Pattern (Gate 6 foundation)
1,463 historical reversals (rise >10¢ then fall >5¢ within 3 hours).
73% of reversed markets settle NO.
Cold-bracket reversals (≤52°F): 98% settle NO (94 cases, 0 YES).
Evening reversal = informed selling, not random noise.

### Overnight Drift
YES-settling brackets: avg -41.6¢ overnight (converging toward 99¢)
NO-settling brackets: avg +6.0¢ overnight (hedging)
Bracket dropping overnight = YES signal strengthening.
Bracket rising overnight = WARNING — someone knows something.

### Volume and Outcome
YES-settling markets: avg 38,754 contracts traded
NO-settling markets:  avg 19,467 contracts traded
Volume correlation with YES outcome: +0.193
Higher volume = directional signal toward YES.

### VWAP vs Last Price
Difference: 0.29¢. Negligible. Use last traded price. Keep it simple.

---

## SECTION 9: OBSERVATION TYPE HIERARCHY

Not all temperature readings are equal. Priority order:

1. SPECI observations — appear between 5-min readings when visibility changes.
   EXACT temperature, zero rounding ambiguity. Rare but highest confidence.

2. Hourly readings (XX:51-XX:54) — high confidence.
   Retain 0.1°F precision before C conversion. Small rounding error.
   USE THESE for METAR gate check.

3. 6-hourly METAR high — moderate confidence.
   Releases at 23:51Z, 05:51Z, 11:51Z, 17:51Z.

4. DSM report — high confidence when it drops.
   Confirmed high up to release time. What the DSM bot reads.

5. 5-minute readings — lower confidence.
   Rounded to whole °F BEFORE C conversion. Must apply rounding formula.

6. Public weather apps — DO NOT USE.
   Subject to C/F double-rounding artifacts. Settlement source is NWS CLI only.

### NWS Time Series Rounding Formula (from wethr.net Discord)
1. OMO recorded in whole °F
2. Converted to °C
3. Rounded to nearest °C
4. Converted back to °F → displayed on NWS Time Series GRAPH
5. Rounded to nearest °F → displayed on NWS Time Series LIST
Note: Graph and List show DIFFERENT values. CLI uses yet another path.

---

## SECTION 10: DATA SOURCES

### Weather Models
HGEFS physics: s3://noaa-gfs-bdp-pds/
HGEFS AI:      s3://noaa-hgefs-pds/
Open-Meteo:    https://api.open-meteo.com/v1/forecast (live)
               https://archive-api.open-meteo.com/v1/archive (historical)
               Models: gfs_seamless, ecmwf_ifs025, icon_seamless, gem_seamless
               Params: latitude=40.7789, longitude=-73.9692, temperature_unit=fahrenheit

### NWS Data (NYC)
Time Series: https://www.weather.gov/wrh/timeseries?site=knyc
CLI Report:  https://forecast.weather.gov/product.php?site=OKX&product=CLI&issuedby=NYC
DSM Feed:    https://mesonet.agron.iastate.edu/wx/afos/p.php?pil=DSMNYC
IEM ASOS:    https://mesonet.agron.iastate.edu/sites/hist.phtml?station=NYC&network=NY_ASOS

### DSM Release Times (ET)
NYC (KNYC):     4:21 PM, 5:21 PM, 1:17 AM
Chicago (KMDW): 5:17 PM, 6:17 PM, 2:17 AM
Miami (KMIA):   4:12 PM, 5:12 PM, 3:22 AM
Austin (KAUS):  6:16 PM, 9:16 AM, 2:16 AM
Denver (KDEN):  6:17 PM, 7:17 PM, 8:17 AM
LA (KLAX):      6:08 PM, 9:08 PM, 4:08 AM

### DSM and CLI Counts Per City
City          Daily DSMs    Daily CLIs    Notes
New York           3             2
Philadelphia       4             2
Miami              4             2
Chicago            3             2
Austin             3             4        Faster confirmation
Denver             4             4        Faster confirmation
Los Angeles        3             2

### Becker Dataset
Location: data/kalshi/trades/*.parquet (806,295 KXHIGHNY trades)
Markets:  data/kalshi/markets/*.parquet
Range:    Oct 2024 → Nov 2025
Query:    DuckDB (do not load all into memory)
Key fields: ticker, created_time, yes_price, count, taker_side

### Kalshi API
Base URL: https://api.elections.kalshi.com/trade-api/v2
API key:  stored in ~/.zshrc as KALSHI_API_KEY (never hardcode)
Note: Historical intraday prices NOT available via API. Use Becker dataset.
      previous_price_dollars field = POST-SETTLEMENT value (1¢ or 99¢). Not useful.

---

## SECTION 11: SEASONAL PATTERNS AND SIZING

### Confirmed Seasonal Pattern (Oct 2024 → Nov 2025)
Period              | Net P&L  | Notes
Oct 2024 - Jul 2025 | +$52     | Nearly flat across 10 months
Aug 2025            | +$42     | Shoulder season begins
Sep 2025            | +$53     | Best single month
Oct 2025            | +$23     | Still strong
Nov 2025            | +$33     | Strong finish

93% of profit came in final 4 months. Shoulder season = peak edge.

### Sizing Recommendations
Spring (April-May): Minimum size. Historically worst months.
Summer (June-July): Normal size. Moderate performance.
Shoulder (Aug-Nov): Scale up. Historically 3x+ better performance.

---

## SECTION 12: RISK MANAGEMENT

### Bankroll Rules
- Never risk more than 10% of bankroll per trade
- Start with $100 deployed, not $500
- With $500 bankroll: max $50 per trade
- Scale only after 30 documented profitable trades

### NWS Error Risk
Frequency: ~3 times per year for NYC
Impact: 95¢ contract → 1¢ instantly. Wipes entire gain.
Protection: Never hold above 70¢. Never. No exceptions.

### F-1 Visa Status — UNRESOLVED
MUST speak to DSO before depositing any money.
Kalshi is CFTC-regulated. USCIS may view regular trading as unauthorized employment.
Both Kalshi and Robinhood carry same legal risk (same infrastructure).
Polymarket lower regulatory risk (decentralized, crypto-based) but different strategy.

---

## SECTION 13: LIVE TRADING CHECKLIST

### Daily Routine
9:00 AM  — Run signal check script. Pull fresh 6Z model data.
           Check HGEFS physics vs AI agreement.
           If spread > 1.5°F between systems → likely no trade.

9:51 AM  — Check NWS Time Series for KNYC hourly reading.
           URL: https://www.weather.gov/wrh/timeseries?site=knyc
           Note the temperature. Apply METAR gate.

10:55 AM — Open Kalshi April XX market. Note exact prices for all brackets.
           Recalculate gaps with current prices (may have shifted from 9 AM).

11:00 AM — Final decision. All 6 gates must pass.
           If entering: place LIMIT order only (never market order).
           Simultaneously place LIMIT SELL at 68¢.
           Set price alert at loss cut level (entry - 20¢).

4:15 PM  — Cancel any unfilled limit orders before DSM fires at 4:21 PM.
           Do NOT try to trade the DSM spike without paid real-time data.

Next AM  — Check NWS CLI for settlement.
           Log result in paper trade spreadsheet.

### Paper Trade Log Columns
Date | City | Gate1_pass | Consensus_F | All4_spread | Gate2_pass |
Bracket | Model_prob | Market_price | Gap_pp | Direction |
Gate3_pass | METAR_951 | Gate4_pass | Gate5_pass | Gate6_pass |
Entry_price | Exit_price | Exit_reason | Settlement_CLI | Win_Loss | PnL | Notes

### Before Real Money: 30 Paper Trades Minimum
If after 30 paper trades win rate > 55% → deploy $100 (not $500)
If after 30 more real trades still profitable → scale to $200
Never skip the paper trade phase regardless of how confident you feel.

---

## SECTION 14: KNOWN FAILURE MODES (NEVER REPEAT)

1. Stale single-model GFS → 29% win rate (Polymarket backtest)
2. Cheap contracts <25¢ → 60%+ capital loss (UCD academic paper)
3. Holding to settlement → NWS error risk wipes year of gains
4. Using public weather apps → CLI differs from Google by 1-2°F
5. Taker fees at scale → consumed 49% of gross profit in backtest
6. 10 AM entry → 11 AM confirmed +$116 better
7. 15¢ loss cut → 20¢ confirmed +$96 better  
8. Gaussian distribution → Gumbel confirmed +$75 better
9. Trading during DSM window → bots fire in milliseconds, leave in peace
10. Ignoring evening reversals → 98% of cold-bracket reversals settle NO
11. Trading Austin → -$115, Sharpe -1.57, convective pattern breaks models
12. Cross-platform weather arb → Kalshi (KNYC) vs Polymarket (KLGA) different stations

---

## SECTION 15: COMMUNITY SOURCES AND KEY FINDINGS

### Documented Profitable Traders
- Gumby808: $600→$125k Kalshi, $200→$30k Robinhood in 1 month.
  Method: deep airport research, NO positions at 50¢, exit 65-70¢, limit orders only.
- KevinLuWX: "Top earner in weather markets." Never >90¢. NWS errors are real.
- Magiera: $50 in 2022 → hired by Kalshi by Nov 2025. Pure local weather physics knowledge.
- stfarm: HGEFS 62-member bot, scans every 5 min, enters 6-12 hours before resolution.
- BeefSlayer: $549→$58k on Polymarket. NYC alone +$19,698. Different approach (cheap YES).

### Academic Validation
UCD Paper (Jan 2026, 300k+ contracts):
- Contracts above 50¢ → statistically positive expected returns
- Contracts below 20¢ → lose 60%+ of capital
- Maker consistently outperforms Taker at every price range
- Favorite-longshot bias weakening over time (market maturing)

### Insider Trading Risk (Atte, wethr.net Discord)
"On Kalshi/CLI resolution, NWS employees have access to resolution-affecting
observation numbers hours before they are released. I want to play a fair game.
I can do that on most Poly temps. I can't do that on Kalshi."
Unexplained large orders before DSM may not always be bots.

### wethr.net Platform
Free tier: 3-minute data delay. Fine for morning model trades.
Basic $14.99/mo: Real-time data. Required for intraday DSM trading.
Pro $24.99/mo: Model forecasts, API access, NWS Forecast Evolution tracker.
OMO API: NOT available until Q3 2026 (contractual limitation).
OMO data IS visible on wethr.net website in real-time.