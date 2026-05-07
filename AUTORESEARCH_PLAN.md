# Autoresearch Plan — Weather Prediction Market Strategy Discovery

_Last updated: 2026-05-07_

---

## Goal

Use autonomous AI-agent research (karpathy/autoresearch pattern) to discover the best possible
trading strategies for Kalshi weather prediction markets by giving the agent a complete,
leakage-free picture of everything the market knew at each historical decision point:
orderbook state, trade flow, weather model forecasts (as actually issued), observations,
and cross-market signals.

---

## 1. The Core Research Question

At time T, given a Kalshi weather bracket market for day D:
- What is the true probability of this bracket resolving YES?
- Is the current market price wrong enough to trade?
- How much to size the trade?

Autoresearch will autonomously modify a strategy script, run backtests, keep improvements,
discard failures — cycling hundreds of experiments overnight.

---

## 2. Data Architecture — The Epoch Problem

Different datasets have different historical coverage. This is the most important
architectural constraint. Every row in the training data must only contain features
that were knowable at decision time T (no leakage), and features must be marked
unavailable for periods before they existed.

### Epoch Table

| Period | Duration | Available Features |
|--------|----------|-------------------|
| **Epoch 0**: Jun 2021 – Dec 2021 | 7 months | Kalshi trades only + ASOS obs + climate normals |
| **Epoch 1**: Jan 2022 – Dec 2025 | 4 years | + Open-Meteo GFS/ECMWF/ICON vintages + GEFS ensemble |
| **Epoch 2**: Jan 2026 – Feb 2026 | 6 weeks | + Predexon orderbooks + Kalshi trades (live) + NBM + AIGEFS |
| **Epoch 3**: Feb 2026 – now | ~3 months | + Smart Money positioning + Polymarket cross-market |

### How Autoresearch Handles the Epoch Problem

**Rule: Features are only valid in the epochs they exist. Never fill missing with future data.**

Three strategies, in order of preference:

1. **Epoch-aware feature sets (recommended)**
   - Define 3 feature tiers: Core (all epochs), Extended (Epoch 1+), Full (Epoch 2+)
   - Autoresearch trains on whichever tier matches the available data window
   - Core-tier strategies get 4.5 years of training data
   - Full-tier strategies get 4 months — still testable, but holdout is smaller

2. **Proxy substitution (for specific gaps)**
   - AIGEFS missing before 2026 → substitute GFS + 4°F bias (documented in CLAUDE.md)
   - NBM missing before 2022 → substitute GFS P50 as NBM proxy
   - Orderbook missing before 2026 → use trade-derived proxies (VWAP, trade count, buy ratio)
   - Document each substitution in program.md so agent knows what is real vs proxy

3. **Feature masking**
   - Mark unavailable features as NaN
   - Let models learn to handle missingness (gradient boosting handles this natively)
   - Do NOT impute with zeros — zero has meaning in price/probability space

### Feature Tiers

**Tier 1 — Core (Jun 2021–now, ~4.5 years)**
- `trade_count_1h` — trades in last hour (from HuggingFace Kalshi trades)
- `yes_buy_ratio` — fraction of taker-side=yes in last N trades
- `implied_prob` — current market mid price
- `time_to_settlement_h` — hours until 4pm ET close
- `gfs_tmax_f` — GFS T-max forecast for day D (Open-Meteo, issued at T)
- `gfs_lead_h` — forecast lead time in hours
- `gfs_vs_bracket_delta` — GFS T-max minus bracket ceiling in °F
- `asos_running_max_f` — observed running max so far today (IEM ASOS)
- `climo_normal_f` — 30-year normal for that date/city
- `climo_std_f` — 30-year std dev
- `climo_pct` — percentile of GFS forecast vs climatology
- `day_of_year`, `hour_of_day` — seasonal/diurnal features

**Tier 2 — Extended (Jan 2022–now, ~4 years)**
- `ecmwf_tmax_f` — ECMWF T-max forecast (Open-Meteo)
- `icon_tmax_f` — ICON T-max forecast (Open-Meteo)
- `model_spread_f` — std dev across GFS/ECMWF/ICON
- `model_agreement` — all models on same side of bracket ceiling (bool)
- `gefs_p10_f`, `gefs_p25_f`, `gefs_p50_f`, `gefs_p75_f`, `gefs_p90_f` — GEFS percentiles
- `gefs_ensemble_spread` — P90-P10 range
- `gefs_bracket_prob` — empirical probability from ensemble of bracket resolving YES

**Tier 3 — Full (Jan 2026–now, ~4 months)**
- `ob_best_bid`, `ob_best_ask`, `ob_spread` — orderbook top of book
- `ob_bid_depth`, `ob_ask_depth` — depth at top 3 levels
- `ob_imbalance` — bid_depth / (bid_depth + ask_depth) — directional pressure
- `taker_yes_1h`, `taker_no_1h` — aggressive buy/sell pressure last hour
- `nbm_p50_f` — NBM median forecast
- `nbm_p90_f` — NBM P90 (upper tail)
- `aigefs_mean_f` — AIGEFS ensemble mean
- `poly_implied_prob` — Polymarket equivalent market price (from Pro trial)
- `poly_kalshi_spread` — cross-market price gap (arbitrage signal)
- `smart_money_net_buyers` — smart wallets net long/short (Feb 2026+)

---

## 3. Complete Dataset Inventory

### 3A. Already In Project

| File | Description | Coverage |
|------|-------------|----------|
| `data/open_meteo_historical_extended.csv` | GFS/open-meteo training data KNYC | ~1723 rows |
| `data/knyc_actual_temps_extended.csv` | NWS CLI actual highs KNYC | ~1723 rows |
| `data/kmdw_actual_temps_extended.csv` | NWS CLI actual highs KMDW | ~1711 rows |
| `data/kxlowt*_actual_tmin_extended.csv` | NWS CLI actual lows, 7 cities | ~855 rows each |
| `data/kxlowt*_markets.csv` / `*_prices.csv` | Kalshi market + price data | Jan 2026–now |
| `data/pipeline.db` | Live SQLite: prices, signals, trades | Jan 2026–now |

**Critical gap: no historical Kalshi trade data before Jan 2026.**

### 3B. Tier 1 — Get Now (Free, No Trial Needed)

| # | Dataset | Source | Size | Script needed |
|---|---------|--------|------|---------------|
| 1 | Kalshi historical trades | HuggingFace `TrevorJS/kalshi-trades` | ~8GB (171M rows) | `fetch_hf_kalshi_trades.py` |
| 2 | Open-Meteo Historical Forecast (GFS/ECMWF/ICON) | `historical-forecast-api.open-meteo.com` | ~50MB | `fetch_openmeteo_forecast_vintages.py` |
| 3 | IEM ASOS full hourly backfill | `mesonet.agron.iastate.edu` | ~10MB | `fetch_iem_asos_backfill.py` |
| 4 | NOAA Climate Normals (30-year) | `ncei.noaa.gov/data/normals-daily` | ~1MB | `fetch_climate_normals.py` |
| 5 | HuggingFace Becker Polymarket dataset | `jon-becker/prediction-market-analysis` | ~2GB | `fetch_becker_polymarket.py` |

### 3C. Tier 2 — Pro Trial (100 rps, ~5-6 hrs)

| # | Dataset | Source | Est. Size | Script needed |
|---|---------|--------|-----------|---------------|
| 6 | Kalshi orderbooks, 14 series | Predexon | ~30-50GB | `predexon_orderbook_download.py` (exists) |
| 7 | Kalshi trades, 14 series | Predexon | ~2-3GB | `predexon_trades_download.py` |
| 8 | Polymarket weather market slugs | Predexon cross-platform matching | tiny | `find_polymarket_weather_slugs.py` |
| 9 | Polymarket weather trades | Predexon `/v2/polymarket/trades` | ~500MB | `predexon_poly_trades_download.py` |
| 10 | Smart money positioning | Predexon Pro tier | small | `fetch_smart_money.py` |
| 11 | Wallet trading labels | Predexon Pro tier | small | `fetch_wallet_labels.py` |

### 3D. Tier 3 — Post Trial (Complex, Lower Priority)

| # | Dataset | Source | Notes |
|---|---------|--------|-------|
| 12 | GEFS ensemble S3 backfill (P10-P90) | `noaa-gefs-pds` S3 | GRIB2, requires eccodes, ~100GB raw |
| 13 | GEFS reforecast (20yr hindcast) | `noaa-gefs-reforecast` S3 | Best model skill analysis |
| 14 | ERA5 reanalysis | Copernicus CDS (free reg) | Ground truth for model skill |
| 15 | HRRR intraday archives | AWS S3 `noaa-hrrr-bdp-pds` | Complex, high value for bracket-lock |

---

## 4. Download Execution Order

### Phase 1: Right Now (free, start immediately)
```bash
# 1. HuggingFace Kalshi trades — filter to weather series only
uv run python research/data/fetch_hf_kalshi_trades.py

# 2. Open-Meteo forecast vintages — all 7 cities, Jan 2022–now
uv run python research/data/fetch_openmeteo_forecast_vintages.py

# 3. IEM ASOS hourly backfill — all 7 cities, 2021–now
uv run python research/data/fetch_iem_asos_backfill.py

# 4. NOAA climate normals — one-time
uv run python research/data/fetch_climate_normals.py

# 5. Becker Polymarket dataset
uv run python research/data/fetch_becker_polymarket.py
```
**Est. time: 2-3 hours total, all parallelizable.**

### Phase 2: Pro Trial (activate when ready, run all in sequence)
```bash
# Orderbooks first (biggest, ~5hrs at 100rps)
nohup .venv/bin/python -u research/data/predexon_orderbook_download.py \
  --rps 100 --resume > /tmp/predexon_ob.log 2>&1 &

# Trades in parallel (fast, ~30min)
nohup .venv/bin/python -u research/data/predexon_trades_download.py \
  --rps 100 > /tmp/predexon_trades.log 2>&1 &

# After orderbooks done:
uv run python research/data/find_polymarket_weather_slugs.py
uv run python research/data/predexon_poly_trades_download.py --rps 100
uv run python research/data/fetch_smart_money.py
uv run python research/data/fetch_wallet_labels.py
```

### Phase 3: After trial (background, no rush)
- GEFS S3 backfill (need a machine with more disk)
- ERA5 via Copernicus CDS API

---

## 5. Storage Layout

```
data/
├── pipeline.db                          # live SQLite (existing)
├── predexon_orderbooks/                 # Tier-3 full features (downloading)
│   ├── kxhighny_orderbooks.parquet
│   └── ...
├── predexon_trades/                     # Tier-3 trade flow
│   ├── kxhighny_trades.parquet
│   └── ...
├── hf_kalshi_trades/                    # Tier-1 historical trades (4.5 yrs)
│   ├── weather_trades.parquet           # filtered to KXHIGH*/KXLOWT* only
│   └── raw/                            # original HF shards (optional)
├── openmeteo_forecast_vintages/         # Tier-2 weather model vintages
│   ├── knyc_forecast_vintages.parquet   # GFS/ECMWF/ICON by model run time
│   ├── kmdw_forecast_vintages.parquet
│   └── ...  (one per city)
├── asos_hourly/                         # Tier-1 observations
│   ├── knyc_asos_hourly.parquet
│   └── ...
├── climate_normals/                     # Tier-1 climatology
│   └── normals_by_city_doy.parquet     # city × day-of-year
├── polymarket/                          # Cross-market signals
│   ├── weather_slugs.json              # Polymarket slug → Kalshi ticker mapping
│   ├── weather_trades.parquet          # Polymarket weather trades
│   └── becker/                        # Becker HuggingFace dataset
├── smart_money/                         # Predexon Pro analytics
│   ├── smart_money_daily.parquet
│   └── wallet_labels.parquet
└── research/                            # Autoresearch outputs
    ├── master_feature_store.parquet    # Joined, epoch-tagged, ready for agents
    └── holdout_dates.json              # Dates agent can NEVER see
```

---

## 6. Feature Store Build

Before running autoresearch, all datasets must be joined into a single
**master_feature_store.parquet** — one row per (ticker, decision_time).

### Join Key
`(city_icao, date, decision_hour)` e.g. `(KNYC, 2024-07-15, 09:00 ET)`

### Build Steps (script: `research/data/build_feature_store.py`)
1. Load HuggingFace Kalshi trades → aggregate to hourly: buy_ratio, volume, trade_count
2. Load Open-Meteo vintages → join on city + model_run_time closest to decision_hour
3. Load ASOS hourly → join on city + hour → running_max_f
4. Load climate normals → join on city + day_of_year
5. Load Predexon orderbooks → join on ticker + hour (Epoch 2+ only)
6. Load Predexon trades → join on ticker + hour (live period)
7. Load Polymarket trades → join on city + date → poly_implied_prob (where available)
8. Load Smart Money → join on ticker + date (Feb 2026+ only)
9. Tag each row with epoch (0/1/2/3)
10. Tag each row with available_feature_tier (core/extended/full)
11. Write master_feature_store.parquet

### Leakage Checks (automated, run after every build)
- No future ASOS data (running_max must only use hours ≤ decision_hour)
- No settlement outcome in any feature
- No same-day CLI actuals as a feature
- Open-Meteo vintage must be from model run ≥ 6h before decision_hour
- Flag any NaN fill that used post-decision data

---

## 7. Autoresearch Architecture

### Adapting karpathy/autoresearch to Trading

| autoresearch original | Our equivalent |
|----------------------|----------------|
| `train.py` | `strategy_experiment.py` — one file agent edits |
| `val_bpb` metric | Composite metric (see below) |
| `program.md` | `research/autoresearch/program.md` |
| 5-min GPU budget | 30-sec backtest budget |
| ~100 experiments/night | ~500 experiments/night |

### File Structure
```
research/autoresearch/
├── program.md              # Human-written agent instructions (edit this)
├── strategy_experiment.py  # Agent modifies this — entry logic, features, sizing
├── backtest_runner.py      # Fixed harness — never modified by agent
├── metric.py               # Fixed metric definition — never modified by agent
└── results/
    ├── run_log.jsonl       # Every experiment: params, metric, keep/discard
    └── best_strategy.py    # Current best version
```

### Composite Metric (never let agent change this)
```python
def score(trades_df) -> float:
    if len(trades_df) < 30:
        return -999  # not enough trades to be meaningful
    sharpe = annualized_sharpe(trades_df)
    win_rate = trades_df['profit'].gt(0).mean()
    max_dd = max_drawdown(trades_df)
    if max_dd < -0.40:        # catastrophic drawdown
        return -999
    if win_rate < 0.45:       # too lossy
        return sharpe * 0.5   # penalize
    return sharpe
```

### Train/Validation/Holdout Split (HARD — agent never touches holdout)
```
Jun 2021 – Sep 2025   →  TRAIN (agent modifies strategy on this)
Oct 2025 – Dec 2025   →  VALIDATION (agent sees this to pick best)
Jan 2026 – Feb 2026   →  HOLDOUT A (human-only, never in agent loop)
Mar 2026 – now        →  HOLDOUT B (forward test, live paper trading)
```
Rationale: Train on 4 years, validate on 3 months, two holdout sets.
Only promote to paper trading after BOTH holdouts show positive Sharpe.

### program.md Key Sections (to write)
1. **What you are**: agent researching weather prediction market strategies
2. **Data available**: feature store schema, epoch tags, what each column means
3. **What to modify**: entry conditions, feature selection, sizing logic in `strategy_experiment.py`
4. **What NOT to touch**: metric.py, backtest_runner.py, holdout dates
5. **Anti-leakage rules**: explicit list of forbidden patterns
6. **Settlement facts**: KNYC = Central Park CLI, KMDW = Midway CLI, etc.
7. **Market mechanics**: bracket structure, fee model, order types
8. **Current baseline**: EMOS_GUMBEL_HETERO Sharpe 0.60, 81% WR — must beat this

---

## 8. Anti-Leakage Rules (hard constraints in program.md)

```
FORBIDDEN — agent may never do these:
1. Use same-day actual temperature as a feature
2. Use settlement outcome as a feature
3. Use features from after decision_time in any training row
4. Access holdout_dates.json rows in training
5. Use next-day ASOS data
6. Use future Kalshi price (prices after decision_time)
7. Fill NaN weather model with actual observed temp
8. Use Open-Meteo vintage from model run after decision_time

REQUIRED checks before every experiment:
- assert no future_leakage in feature_store
- assert train rows only contain epoch-appropriate features
- assert holdout dates untouched
```

---

## 9. Execution Timeline

| Phase | What | When | Blocker |
|-------|------|------|---------|
| **P1** | Download free datasets (HuggingFace, Open-Meteo, ASOS, Normals, Becker) | Now | None |
| **P2** | Write download scripts for P1 | Now | None |
| **P3** | Activate Pro trial → download orderbooks + trades + Polymarket | When ready | Pro subscription |
| **P4** | Build feature store (join all datasets) | After P1+P3 | Data complete |
| **P5** | Write strategy_experiment.py baseline | After P4 | Feature store |
| **P6** | Write program.md | After P5 | strategy_experiment.py |
| **P7** | First autoresearch run (overnight, 500 experiments) | After P6 | All above |
| **P8** | Human review — validate winners on holdout | Morning after P7 | P7 results |
| **P9** | Promote best strategy to paper trading | After P8 | Holdout validation |
| **P10** | Continuous overnight autoresearch runs | Ongoing | — |

---

## 10. Scripts To Write (Checklist)

### Phase 1 (free downloads)
- [ ] `research/data/fetch_hf_kalshi_trades.py` — HuggingFace 171M row Kalshi trades
- [ ] `research/data/fetch_openmeteo_forecast_vintages.py` — GFS/ECMWF/ICON vintages all 7 cities
- [ ] `research/data/fetch_iem_asos_backfill.py` — hourly obs all 7 cities 2021–now
- [ ] `research/data/fetch_climate_normals.py` — NOAA 30-year normals
- [ ] `research/data/fetch_becker_polymarket.py` — Becker HuggingFace dataset

### Phase 2 (Pro trial)
- [ ] `research/data/predexon_trades_download.py` — mirrors orderbook script
- [ ] `research/data/find_polymarket_weather_slugs.py` — cross-platform matching
- [ ] `research/data/predexon_poly_trades_download.py` — Polymarket trades by slug
- [ ] `research/data/fetch_smart_money.py` — smart money + wallet labels

### Feature Store
- [ ] `research/data/build_feature_store.py` — joins all datasets → master_feature_store.parquet
- [ ] `research/data/validate_feature_store.py` — leakage checks, epoch integrity

### Autoresearch
- [ ] `research/autoresearch/backtest_runner.py` — fixed harness
- [ ] `research/autoresearch/metric.py` — composite score function
- [ ] `research/autoresearch/strategy_experiment.py` — baseline strategy (agent modifies)
- [ ] `research/autoresearch/program.md` — agent instructions
- [ ] `research/autoresearch/run_autoresearch.py` — orchestrator loop

---

## 11. Open Questions (Decide Before Building)

1. **Autoresearch model**: Use Claude Sonnet 4.6 (current) or Opus 4.7 for agent?
   Recommendation: Sonnet for speed (~500/night), Opus for quality (~100/night)

2. **Backtest granularity**: Per-trade (each market entry/exit) or per-day?
   Recommendation: Per-trade — more signal, more realistic

3. **Cities in autoresearch**: Start with KNYC only or all 7?
   Recommendation: KNYC first (most data, most liquid), generalize after

4. **Feature store update frequency**: Rebuild nightly or incrementally?
   Recommendation: Incremental append, full rebuild weekly

5. **GEFS Tier 3 priority**: Given complexity of GRIB2 parsing, defer until
   feature store shows model_spread is a top feature by importance?
   Recommendation: Yes — defer until signal importance confirmed

---

## 12. Key Constraints (Do Not Forget)

- **Never modify live config.py from research scripts** — research is read-only
- **Polymarket = KLGA settlement, Kalshi = KNYC settlement** — different stations, never substitute directly
- **Proxy features must be labeled** — any feature that's a substitute must have `_proxy` suffix
- **Holdout dates are sacred** — hardcode in a JSON file, check in every runner
- **Multiple testing**: after 500 experiments, require p-value correction before trusting any result
- **Paper trade before live**: any autoresearch winner must run 30+ days paper before live promotion
- **Checkpoint everything**: all downloads checkpoint every 5 markets for resume safety
