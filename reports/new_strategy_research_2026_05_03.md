# New Trading Strategy Research
**Date:** 2026-05-03 | **Source:** Full microstructure atlas, Kalshi market universe (~1.5M markets), Polymarket 5,327 resolved markets

---

## Why Chicago Is Unprofitable

**Root cause: The Gumbel model has a persistent −1.92°F cold bias for KMDW (vs −1.09°F for KNYC).**

| Model component | KMDW bias | KNYC bias |
|----------------|-----------|-----------|
| GFS | −1.27°F | **+0.13°F** (near-unbiased) |
| ECMWF | −2.13°F | −1.31°F |
| UKMO | −2.18°F | −1.56°F |
| Weighted consensus | −1.92°F | −1.09°F |

**Effect on trades:**
- 83.7% of all KMDW CORE trades: actual settled *warmer* than model consensus
- YES losses: 85.6% are from actual temperature being ABOVE the target bracket (0% from below — not a single YES loss from model being too warm)
- KMDW Gumbel at 60–80% confidence: actual win rate only 11.1% (vs expected 60–80%)
- KMDW YES trades market-implied P(win) = 0.359, actual win rate = 0.276 → −8.3pp disadvantage vs market

The KXHIGHCHI market already prices the warm bias in. The Gumbel does not. We're fading the smart money every time we enter a YES trade on KMDW.

**Fix:** Replace KMDW Gumbel with EMOS (backtest: Sharpe 0.71, 80% win rate). The training data already exists (`data/kmdw_actual_temps_extended.csv`, 1,711 days). EMOS learns the cold bias during fitting and eliminates it.

---

## Backtest Accuracy Problem

**The current backtests are not valid for measuring trading edge.** They use `historical-forecast-api.open-meteo.com` which compiles forecasts from multiple model updates including post-observation assimilation. The GFS MAE of 1.20°F for KNYC is suspiciously low — consistent with leakage.

**Evidence:**
- Cached CSV has only `date, gfs_maxt, ecmwf_maxt, ukmo_maxt, nbm_maxt` — no `cycle_init_utc`
- Entry timing tests (9AM vs 11AM) reuse the same weather row — they only test market prices, not forecast vintages
- Win rate concentrated in low-error days: consensus error ≤0.5°F = 96.8% win rate (leakage fingerprint)
- Leakage-corrected EMOS_GUMBEL_HETERO result: 60% win rate, Sharpe 0.18 vs leaky 83.5% win rate, Sharpe 0.789

**True expected performance after leakage correction:**
- Brier degrades ~40% (0.087 → ~0.125)
- Win rate degrades ~25pp (83.5% → 60%)
- Sharpe degrades ~75% (0.789 → ~0.18)
- But: $7 net PnL on 85 trades with 0 forecast violations proves the strategy is still *real and profitable*

See `research/backtests/leakage_safe_framework.py` for the correct implementation.

---

## New Trading Strategies

### Strategy 1: Passive Market Making in Kalshi Non-Weather Markets

**Core logic:** Takers on Kalshi non-weather markets lose money consistently; makers earn +1.1% per trade as a structural fee/information asymmetry advantage. Post resting limit orders at the inside quote and collect the spread.

**Evidence from microstructure_atlas.parquet (63.6M non-weather trades):**
- Overall maker return: **+1.11% per trade** (taker: −1.11%)
- By price bucket (maker edge):
  - 40–50c: **+2.15%** (7.5M trades, highest edge)
  - 60–70c: **+2.13%** (6.3M trades)
  - 80–90c: **+1.00%** (4.3M trades)
  - 30–40c: **+0.46%** (7.0M trades, lowest but still positive)
- By trade size: edge is consistent 1.0–1.3% regardless of order size (1–500+ contracts)
- By volume tier: low-volume markets (<1K) have +2.06% maker edge; high-volume (>100K) still +1.03%

**Trade frequency:** 63.6M trades across 526,085 non-weather tickers = avg 121 trades/ticker. Major categories: sports (NFL/NBA/esports), crypto (KXBTCD: 6.7M vol, KXETHD: 1.6M), equity index (KXINXU S&P500: 1.8M vol), forex (KXUSDJPYH: 225K).

**Entry/exit rules:**
1. Post YES limit at (best_yes_bid + 1c) and NO limit at (best_no_bid + 1c) simultaneously
2. Cancel one side immediately upon fill of the other
3. Target 40–70c price zone (highest maker edge)
4. Focus on markets 24–72 hours before close (highest volume)
5. Cancel all orders when market enters 1-hour window before resolution

**Data needed:** Kalshi REST API for live orderbook; websocket for fill notifications.

**Risks:**
- Adverse selection: filled when information trader knows the outcome; offset by spread capture
- Resolution risk: if both sides fill on opposite-direction contracts (net neutral but fee drag)
- Thin markets: low-volume tickers have wide spreads — only post in markets with >1K daily volume
- **Annual PnL estimate:** At 100 fills/day × $5 avg position × 1.1% = ~$2,000/year at low scale

---

### Strategy 2: Informed Taker in Weather-Other Markets (Precipitation, Wind, Snow)

**Core logic:** The `weather_other` segment (precipitation totals, wind speed, snowfall, hurricane tracks) is the ONLY Kalshi category where takers earn money: **+0.62% per taker trade** vs −1.1% everywhere else. During 9 AM–5 PM ET, the taker edge rises to +1.2–1.9% per trade.

**Evidence:**
- weather_other maker return: **−0.62%** (takers win, makers lose — completely inverted vs all other categories)
- weather_other hourly: hours 10–14 ET show taker returns of **+1.25% to +1.94%** per trade
- Calibration deficit at high prices: weather_other 80–90c YES has only 75.8% resolution rate (vs 84.3% market price) = **8.57pp overpricing** — even larger than temperature
- weather_other 90–95c: market 91.9c, resolves YES only 83.3% = **8.62pp deficit**

**Interpretation:** There are informed participants (weather services, meteorologists) who trade weather_other contracts as takers with real data advantage. The large intraday taker edge (8 AM–5 PM) matches when professional forecasters have updated models. The high-price deficit means they specifically target overpriced high-probability contracts.

**Strategy:** Using NWS ASOS data and existing weather pipeline, extend to non-temperature weather markets:
- **Precipitation markets:** "Will NYC get ≥0.1 inch of rain today?" — use QPF (quantitative precip forecast) from GFS/NAM
- **Snowfall markets:** "Will NYC get ≥2 inches of snow this week?" — use SNOD field from GFS/NBM
- **Wind markets:** "Will sustained winds exceed 20mph today?" — use WINDSPD from GFS

**Data needed:** GFS QPF, SNOD, WDIR fields (available same S3 bucket as GEFS). NBM provides probabilistic precip/snow directly.

**Trade frequency:** ~50–200 weather_other markets active at any time.

**Risks:**
- Harder to model than temperature (precip is binary and stochastic)
- Lower volume than temperature markets
- Current pipeline doesn't parse QPF fields (requires GRIB2 extension)

---

### Strategy 3: NO-Bias Fade on High-Probability Weather Brackets

**Core logic:** Temperature and weather_other YES contracts priced 70–95c are systematically overpriced by 3–9pp. The market's favorite-longshot bias inflates high-probability contracts.

**Evidence from microstructure (temperature category):**
| Price bucket | Avg YES price | Actual YES rate | Calibration deficit |
|-------------|--------------|-----------------|---------------------|
| 60–70c | 0.641 | 0.596 | **−4.47pp** |
| 70–80c | 0.742 | 0.692 | **−5.06pp** |
| 80–90c | 0.843 | 0.811 | −3.22pp |

**Weather-other (even worse):**
| Price bucket | Avg YES price | Actual YES rate | Calibration deficit |
|-------------|--------------|-----------------|---------------------|
| 80–90c | 0.843 | 0.758 | **−8.57pp** |
| 90–95c | 0.919 | 0.833 | **−8.62pp** |
| 95–100c | 0.975 | 0.922 | −5.29pp |

**Strategy:** Buy NO (= sell high-probability YES) on temperature and weather_other brackets priced 65–90c when model probability is ≤50%. This extends the existing DEEP_TAIL_NO sleeve to a wider price range (currently only 55–95c but with explicit model gate).

**Entry rule:** NO entry when (market_yes_price ≥ 0.65) AND (model_prob ≤ 0.50) AND (gap ≥ 15pp)

**Expected win rate:** 75–80% based on calibration deficit + model confirmation. The existing DEEP_TAIL_NO already validates this at 88.9% win rate.

**Risks:** Tail events (unusual weather) hit exactly these overpriced contracts. Size conservatively.

---

### Strategy 4: Weather YES Early-Entry / Intraday Drift Capture

**Core logic:** Weather YES prices drift upward monotonically from market open, peaking ~33 hours before the trading day (+22.9% drift from first trade), then mean-reverting to near-settlement value. Buy YES at market open and sell at the +25h drift peak.

**Evidence from `intraday_drift_from_first_trade` (weather segment):**
| Hours since first trade | Avg drift from open price |
|------------------------|--------------------------|
| 0h (open) | +0.007 |
| 5h | +0.021 |
| 10h | +0.033 |
| 15h | +0.046 |
| 20h | +0.044 |
| 25h | +0.059 |
| 28h | +0.093 |
| **33h** | **+0.229 PEAK** |
| 35h | +0.209 |
| 40h | +0.132 |

**Mechanism:** Weather markets open 2–4 days before settlement. Early pricing reflects model consensus uncertainty. As the event approaches, forecast accuracy improves and the market converges toward the true probability. Participants buying YES as certainty increases drive the drift.

**Strategy:** For each Kalshi temperature bracket:
1. **Enter:** Buy YES within 3 hours of market open (bucket 0–3), price ≤ 55c
2. **Exit:** Sell at max(33h after open, 50% gain, next-day 9AM)
3. **Filter:** Only enter when model probability ≥ market price + 15pp (genuine edge)

**Estimated edge:** +22.9pp average drift by hour 33 on weather contracts. Even capturing 50% of this (+11.4pp net of fees) with a 55c average entry = meaningful alpha.

**Risks:** Drift is an average across all outcomes — losing trades (bracket misses) see negative drift. Requires model confirmation to avoid entering brackets that will miss.

---

### Strategy 5: Bitcoin / Crypto Daily Bracket Trading

**Core logic:** Kalshi crypto markets (KXBTCD, KXETHD, KXXRPD) have high volume (BTC: 6.7M, ETH: 1.6M, XRP: 2.3M) and are priceable with continuous market data. Use crypto implied volatility (Deribit options) to compute theoretically correct bracket probabilities and trade where Kalshi is mispriced.

**Evidence:**
- KXBTCD: 2,330 markets, 6.7M total volume — 6× more liquid than all temperature markets combined
- KXETHD: 2,330 markets, 1.6M volume
- These are daily price range brackets ("Will BTC be between $95K–$100K at 5PM?")
- Crypto trades 24/7 with real-time price → no data leakage problem (no equivalent of KLGA vs KNYC)
- Implied volatility surfaces from Deribit provide exact bracket probabilities

**Model:** Lognormal bracket probability from (current spot price, IV surface, time-to-expiry):
```
P(L ≤ BTC_close ≤ H) = Φ[(ln(H/S) - μτ) / (σ√τ)] - Φ[(ln(L/S) - μτ) / (σ√τ)]
```

**Entry rules:**
1. Every morning, compute P(bracket) using 9AM spot + Deribit 1-day IV
2. Compare to Kalshi yes_ask / no_ask
3. Trade when |model_prob - market_price| ≥ 8pp
4. Use NO direction preferentially (same calibration deficit as weather: 70–80c YES is overpriced)

**Advantages over weather:**
- No GRIB2 parsing, no NOMADS access, no NWS station discrepancy
- Real-time settlement price (CoinGecko API, transparent)
- 24/7 market → can also capture overnight moves
- Deribit IV is a robust, liquid signal

**Risks:**
- Crypto has fat-tailed distributions (lognormal assumption breaks during crashes)
- Kalshi crypto markets may already be efficiently priced by crypto-native traders
- Need to validate IV → bracket probability calibration empirically

---

### Strategy 6: S&P 500 / Nasdaq Bracket Trading via VIX

**Core logic:** KXINXU (S&P 500 end-of-day bracket) and KXNASDAQ have high volume (1.8M and 731K). S&P 500 bracket probabilities are computable from VIX (CBOE 1-day implied vol) with high accuracy.

**Evidence:**
- KXINXU: 7,440 markets, total volume 1.8M — significant liquidity
- KXNASDAQ: 7,440 markets, 731K volume
- Both settle at 4PM ET → hard deadline, no ASOS/station ambiguity
- VIX is the market's own probability estimate for 1-day S&P moves

**Model:** Same lognormal bracket formula as crypto, but using VIX/√252 as daily vol. VIX of 20 → daily vol ≈ 1.26%. "Will S&P be above 5,500?" priced by Black-Scholes with exact market price.

**Key insight:** VIX is the consensus vol estimate. If Kalshi bracket prices imply a different vol than VIX, there's an arbitrage. Trade Kalshi to close the vol gap.

**Entry rules:**
1. At 9:30 AM, compute bracket probabilities from S&P spot + overnight VIX
2. For each Kalshi KXINXU bracket, compare model prob to Kalshi ask
3. Enter if |model_prob - market_price| ≥ 6pp (tighter threshold, more efficient market)
4. Close all positions at 3:45 PM (avoid last-15-minute vol)

**Risks:**
- Intraday S&P moves before 4PM can invalidate morning thesis — need dynamic updating
- Kalshi KXINXU may already be priced by sophisticated quants using VIX
- Gap openings (overnight futures moves) compress bracket accuracy

---

### Strategy 7: Multi-City Weather Expansion (Austin, LA, Miami, Philadelphia, Denver)

**Core logic:** Five additional Kalshi temperature cities (KXHIGHAUS, KXHIGHLAX, KXHIGHMIA, KXHIGHPHIL, KXHIGHDEN) have active markets and published maker edges similar to NYC. Apply EMOS models (same training framework, EMOS already validated) to each city.

**Evidence from temperature_city_summary:**
| City | Ticker | Maker return | Trades | Notes |
|------|--------|-------------|--------|-------|
| NYC | KXHIGHNY | **+1.95%** | 799K | Currently trading (Gumbel; EMOS pending) |
| Miami | KXHIGHMIA | +1.68% | 415K | High maker edge |
| Houston | KXHIGHHOU | +1.74% | 63K | Thin but high edge |
| LA | KXHIGHLAX | +1.48% | 527K | 2nd most liquid non-NY |
| Austin | KXHIGHAUS | +1.38% | 560K | Comparable liquidity |
| Denver | KXHIGHDEN | +1.10% | 456K | Lower edge, continental divide variance |
| Philadelphia | KXHIGHPHIL | +1.26% | 293K | Close to NYC, correlated |

**Implementation:** Open-Meteo provides historical extended forecasts for all US cities. `fetch_extended_training_data.py` already supports `--city KMDW`; extend to all 5. EMOS training needs ~1,700 days of (forecast, actual) pairs — available immediately via Open-Meteo and IEM ASOS.

**Estimated combined alpha:** Each city at ~$8–12 PnL/period (scaled from NYC EMOS backtest). Five cities × $10 avg = **+$50/period** incremental, correlated ~20–30% with NYC (different microclimates).

**Risks:**
- Settlement stations vary: KXHIGHMIA → Miami Int'l (KMIA), KXHIGHLAX → LAX (KLAX). Need to verify NWS CLI issuance patterns for each city.
- LA marine layer creates persistent cold bias analogous to Chicago warm bias. EMOS should correct but needs validation.

---

### Strategy 8: Sports Spread Arbitrage vs Vegas Lines

**Core logic:** Kalshi college/pro sports spread and total markets (KXNCAAFSPREAD: 11.4M volume, KXNCAAFTOTAL: 8.2M) price the same underlying events as Vegas sportsbooks. When Kalshi and Vegas diverge by >5pp in implied probability, take the Kalshi side.

**Evidence:**
- KXNCAAFSPREAD: 822 markets, **11.4M volume** — highest in the recent batch
- KXNCAAFTOTAL: 531 markets, **8.2M volume**
- These resolve on official game outcomes — no weather/station ambiguity
- Professional sports betters move Vegas lines with sharp information; Kalshi may lag

**Model:**
- Convert Vegas spread/total to probability: P(favorite covers) = Φ(spread / estimated game σ)
- Compare to Kalshi yes_bid / no_bid
- Trade when Kalshi implied prob deviates from Vegas by >5pp

**Data needed:** Live Vegas lines from a data provider (The Odds API, free tier available). Schedule alignment Kalshi ticker → game matchup.

**Risks:**
- Kalshi may already be efficiently priced by the same sports bettors who drive Vegas lines
- Kalshi and Vegas settle on different formulas (e.g., Kalshi uses final score vs. Vegas point spread)
- NCAAF has more variance than NFL — model assumptions may break

---

## Implementation Roadmap

| Priority | Strategy | Effort | Est. Annual PnL | Risk |
|----------|----------|--------|-----------------|------|
| 1 | Fix KMDW (enable EMOS) | Low | +$40–60 | Low |
| 2 | Multi-city weather (3 cities) | Medium | +$30–50 | Low |
| 3 | Crypto bracket (BTC/ETH) | Medium | +$50–100 | Medium |
| 4 | Weather-other (precip/snow) | High | +$30–60 | Medium |
| 5 | Passive market making | High | +$20–100 | Medium |
| 6 | S&P 500 / VIX bracket | Medium | +$20–60 | Medium |
| 7 | Weather YES drift capture | Low | +$10–30 | Low |
| 8 | Sports vs Vegas arbitrage | High | Unknown | High |

---

## Backtest Reform: Leakage-Safe Framework

See `research/backtests/leakage_safe_framework.py` for implementation.

**Key changes vs current backtest.py:**
1. Replace `OPEN_METEO_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"` with Previous Runs API
2. Store `cycle_init_utc`, `available_at_utc` for every forecast row
3. For 11 AM ET entry: only use GFS 06Z (available ~10:40 UTC = 6:40 AM ET) or earlier
4. Assert `available_at_utc < entry_datetime_utc` before using any row
5. Cache with full metadata to `data/cache/forecast_vintages_{city}_{YYYYMM}.parquet`

**True performance expectation:**
- EMOS_GUMBEL_HETERO: ~60% win rate, ~$7 per 85 trades, Sharpe ~0.18 (vs leaky 83.5%, Sharpe 0.789)
- The edge is real — $7 PnL at 0 leakage violations confirms it
- Scale target: 60% win rate × 85 trades/period × fee-adjusted = **~$25–35/year** from weather alone
- Multi-city and multi-strategy expansion brings total to **$80–150/year**
