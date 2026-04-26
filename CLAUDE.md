# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Commands

```bash
uv run pytest tests/ -v              # run all tests
uv run pytest tests/test_gates.py -v # run a single test file
uv run ruff check .                  # lint
uv run ruff format .                 # format

# KXHIGHNY API-only backtest (does NOT use Becker parquet data)
uv run python scripts/backtest.py --skip-fetch  # use cached CSVs
uv run python scripts/backtest.py --refresh     # re-download Kalshi/IEM/Open-Meteo data

# Run the pipeline (requires env vars below)
.venv/bin/python main.py             # run indefinitely
.venv/bin/python main.py --once      # single polling pass
.venv/bin/python main.py --report 2026-04-25  # print daily report

# Historical research data (Becker dataset, 806k+ KXHIGHNY trades)
uv run main.py analyze   # interactive analysis menu
uv run main.py index     # interactive data collection menu
```

**Environment variables** (set in `~/.zshrc`):
```
KALSHI_API_KEY    RSA key ID (UUID)
KALSHI_KEY_PATH   path to RSA private key PEM
WETHR_API_KEY     wethr.net Pro bearer token
ECCODES_DIR       path from `brew --prefix eccodes` (required for GRIB2)
```

**GRIB2 decoding** requires the native ecCodes library: `brew install eccodes`. The `ModelFetcher._ensure_eccodes()` method auto-detects the Homebrew prefix, but `ECCODES_DIR` must be in the environment for the LaunchAgent.

---

## Standing Maintenance Rules

After any code or strategy change:
1. Update `CLAUDE.md` with the new behavior, thresholds, assumptions, and test/backtest status.
2. Run the relevant tests; run `uv run pytest` for strategy/pipeline changes.
3. Commit the changed source/docs and push to the `weather` remote (`git push weather main`).
4. Do not stage or commit live log churn from `logs/` unless explicitly requested.

---

## Architecture

This repo has two independent systems that share the same codebase:

**System 1 — Research framework** (`src/`, `data/kalshi/`, `data/polymarket/`): Static analysis of the Becker dataset (806k KXHIGHNY trades in Parquet). Uses DuckDB for queries. Entry points: `make analyze`, `make index`.

**System 2 — Live trading pipeline** (all root-level packages): A continuously running asyncio event loop that collects live weather/market data, runs a 6-gate signal filter, and paper-trades confirmed signals.

---

## Live Pipeline Architecture

### Data flow

```
wethr.net API (60s/5min) ──► metar_observations, dsm_reports, cli_reports
GEFS S3 (30min)           ──► model_runs (physics_mean, physics_spread)
AIGEFS NOMADS (30min)     ──► model_runs (ai_mean, ai_spread)
NBM NOMADS (30min)        ──► model_runs (nbm_p10..p90)
Kalshi REST (30min)       ──► kalshi_prices
Kalshi WebSocket (live)   ──► kalshi_prices (source=websocket), price_history

All ──► EventTriggerEngine ──► gate_checks ──► signals ──► paper_trades
```

### Execution flow

`main.py` builds `EventTriggerEngine` + `KalshiOrderbookManager` and runs them as concurrent asyncio tasks.

`EventTriggerEngine.run_forever()` runs five concurrent loops:
- `poll_60s`: wethr observations/DSM/CLI
- `poll_5min`: NWS version check (triggers `fire_gate_check` on increment), HRRR/NBM maxt
- `poll_30min`: Kalshi prices, GEFS cycle check, multi-model maxt, NBM bulletin
- `_wall_clock_daily_loop`: teleconnections at 6 AM, CLI at 7 AM, report at 8 AM
- `_fallback_loop`: forces `fire_gate_check` at 11 AM ET if no trigger fired

`KalshiOrderbookManager.run()` maintains a live WebSocket orderbook and records price history used by Gate 6.

### Signal generation path

`fire_gate_check(city, trigger_reason)` is the central function:
1. Fetches latest Kalshi brackets, wethr models, HGEFS DB record, NBM DB record
2. `_hgefs_or_fallback()` — returns physics+AI means; if AIGEFS is unavailable, uses wethr multi-model consensus as AI proxy (`gate1_ai_source = 'wethr_proxy'`) with dynamic `ai_spread = std(wethr_models)`
3. For each bracket: runs Gumbel probability → Bayesian NBM update → isotonic calibration → `run_all_gates()`
4. All 6 gates pass → `insert_signal` → `paper_trader.on_signal()`

### Database

Single SQLite file at `data/pipeline.db`. `data_store/db.py` wraps it with `_table_columns()` caching — inserts silently ignore keys not in the schema, so adding schema columns requires `ALTER TABLE` on the live DB **and** updating `data_store/schema.py`.

Key tables: `model_runs`, `gate_checks`, `signals`, `paper_trades`, `kalshi_prices`, `metar_observations`, `dsm_reports`, `cli_reports`, `performance_daily`, `teleconnections`.

---

## GEFS/AIGEFS Data Sources (Critical Infrastructure Facts)

- **NOMADS returns 403** for all GEFS file downloads. GEFS physics members must come from `noaa-gefs-pds.s3.amazonaws.com` (no auth needed).
- **AIGEFS NOMADS** (`noaa-hgefs-pds` S3 bucket does not exist). AIGEFS file downloads sometimes 403 due to rate limiting; when unavailable, the wethr proxy path is used.
- AIGEFS files are `pres` (pressure-level, 6-hourly), not `sfc`. Members are `mem000`–`mem030`. TMAX is not available; instead, `TMP:1000 mb` is used with a `+4°F` bias correction (`_AIGEFS_1000MB_BIAS_F`).
- Cycle discovery probes `gefs.{date}/{cycle}/atmos/pgrb2sp25/gec00.t{cycle}z.pgrb2s.0p25.f024.idx` on S3.
- NBM bulletins: `blend_nbptx` KNYC blocks are often empty (headers only). The parser falls through to `blend_nbetx` which has real `TXN`/`XND` rows. NOMADS rate-limits after rapid successive requests; production polling at 30-min intervals avoids this.

---

## The 6-Gate System

Gates are in `signal_engine/gate_checker.py`; thresholds are in `config.py`. The current implementation is tiered:

- **Tier 1 hard gates:** Gate 1 model convergence, Gate 2 gap/dead-zone filter, Gate 3 price band. All must pass to generate a core signal.
- **Tier 2 confidence modifiers:** Gate 4 dead-zone diagnostic, Gate 5 METAR confirmation, Gate 6 reversal check. These are still evaluated and logged on every check, but they modify confidence rather than blocking by themselves. The dead zone is hard-blocked inside Gate 2.

| Gate | Condition | Key config |
|------|-----------|------------|
| 1 | `abs(physics_mean - ai_mean) <= 1.5°F` AND both spreads `< 3.0°F` | `HGEFS_MAX_SPREAD_BETWEEN=1.5`, `HGEFS_MAX_SUBSET_SPREAD=3.0` |
| 2 | `abs(gap_pp) > 20pp` where `gap_pp = (gumbel_prob - market_price) * 100`, excluding 35–40pp dead zone | `MIN_GAP_PP=20.0`, `DEAD_ZONE_LO=35`, `DEAD_ZONE_HI=40` |
| 3 | `0.25 <= entry_price <= 0.75` | `MIN_YES_PRICE`, `MAX_YES_PRICE` |
| 4 | Dead-zone confidence modifier (diagnostic; hard block is in Gate 2) | `DEAD_ZONE_LO=35`, `DEAD_ZONE_HI=40` |
| 5 | 9:51 AM ET METAR within 8°F of bracket center (YES) or outside 3°F (NO). Missing reading is neutral. | `METAR_YES_MAX_DISTANCE=8`, `METAR_NO_MIN_DISTANCE=3` |
| 6 | Evening reversal confidence modifier (>10¢ rise then >10¢ fall), strongest penalty on cold brackets (≤52°F) | `REVERSAL_THRESHOLD=0.10`, `COLD_BRACKET_MAX_TEMP=52` |

`run_all_gates()` returns `{"all_pass": bool, "confidence_score": float, "gate1"..6: {...}, ...}`. `confidence_score` is 0–100 from weighted gate metrics.

---

## Gumbel Probability Model

Daily temperature maxima follow a Gumbel (not Gaussian) distribution:
- `mu = consensus_temp_f - 0.45` (`GUMBEL_MU_CORRECTION`)
- `beta = 0.742` (`GUMBEL_BETA`, derived from ECMWF MAE / 1.28)

Bracket probabilities use ±0.5 continuity correction for NWS integer rounding. The `GumbelModel` class optionally applies a Bayesian update from NBM percentiles (only when `percentiles_real=True`) and isotonic regression calibration (requires ≥10 settled trades).

`consensus_temp_f` is derived from GEFS physics+AI means. If HGEFS/AIGEFS is unavailable and the code must use the wethr fallback, `compute_consensus_from_wethr()` applies per-model bias corrections (ECMWF: −0.42°F, GFS: +0.47°F, HRRR summer: −1.5°F) and then uses the fallback weights learned from the exchange-settlement backtest:

```python
FALLBACK_ENSEMBLE_WEIGHTS = {
    "GFS": 0.3575441093,
    "ECMWF": 0.2121428382,
    "UKMO": 0.1938071607,
    "NBM": 0.2365058918,
}
```

These weights are fallback-only. Do not replace the HGEFS-first path with a 4-model provider consensus.

---

## API-Only Backtest System

`scripts/backtest.py` is the current KXHIGHNY backtest harness. It intentionally **does not use the Becker parquet trade dataset**.

Data files:
- `data/kxhighny_markets.csv` — settled KXHIGHNY markets from Kalshi API/historical API.
- `data/kxhighny_prices.csv` — hourly Kalshi candlestick prices at open, 9 AM, 11 AM, 1 PM, 3 PM ET.
- `data/knyc_actual_temps.csv` — IEM KNYC daily max temps for diagnostic comparison only.
- `data/open_meteo_historical.csv` — daily historical model forecasts from Open-Meteo.
- `data/backtest_results.csv` — trade-by-trade simulated results.
- `data/backtest_summary.json` — summary, audit, stress tests, walk-forward results.

Current methodology:
- P&L and win/loss are settled from `kalshi_result_yes`, not reconstructed IEM temperatures.
- IEM temperatures are kept only to measure model error and audit IEM-vs-Kalshi mismatches.
- Open-Meteo historical data has one daily forecast row per date, so entry timing tests reuse the same forecast values and vary only market price. Treat 9 AM/11 AM/1 PM/3 PM timing as price-timing research, not true forecast-vintage research.
- Baseline core backtest follows live `config.MIN_GAP_PP` (currently 20pp), `9AM` entry, fixed WeatherBot-style weights unless a comparison explicitly selects inverse-MAE weights. The threshold bakeoff compares 20/25/30 before promoting any new production threshold.
- `models/distributional_temp.py` is the research-only bracket-coherent model. It maps one Gumbel daily-high distribution onto all brackets and normalizes probabilities so one day's brackets sum to 1.0.
- `features/bracket_targets.py` builds one row per date/bracket with consensus temperature, spread, bracket-edge distances, wing/central flags, prior-day error, hours to close, regime flags, market price, and gap.

Latest cached backtest output after the research-hardening pass:
- Core baseline at 20pp is recalculated by `scripts/backtest.py`; do not treat 20pp as final strategy truth until threshold bakeoff results are reviewed.
- Walk-forward inverse-MAE core: 273 trades, 62.3% win rate, +$27.70 net.
- Global inverse-MAE comparison: 325 trades, 64.9% win rate, +$41.92 net. Treat this as retrospective fit, not proof.
- Settlement audit: 3426/3426 market rows have Kalshi result labels; 60 market-level IEM/Kalshi mismatches; 5 trade-level mismatches.
- `DEEP_TAIL_NO` baseline: 492 trades, 94.1% win rate, +$46.29 net.
- `DEEP_TAIL_NO` stress tests: +3¢ worse fills still +$31.89; +5¢ worse fills still +$23.42; missing best 10% plus +3¢ still +$22.55.

Interpretation: good research baseline, not proof of durable edge. Current research requirement: threshold bakeoff plus true forecast-vintage data by entry time.

---

## Strategy Sleeves

Core signals use HGEFS/Gumbel/tiered gates and require the canonical 20pp edge floor from `config.MIN_GAP_PP`.

`TAIL_NO`:
- Research/log-only by default: `ENABLE_TAIL_NO_TRADES = False`.
- Tightened rule: `P_yes < 0.30` and YES market price `> 0.55`.
- The old loose `P_yes < 0.40` / YES `> 0.45` rule was too noisy.

`DEEP_TAIL_NO`:
- Paper-traded by default: `ENABLE_DEEP_TAIL_NO_TRADES = True`.
- Rule: `P_yes < 0.02` and YES market price `> 0.05`.
- Strongest sleeve in current backtest, but still requires live fill-quality monitoring because it is sensitive to availability/slippage.

---

## Paper Trader

`PaperTrader.on_signal()` → `simulate_entry()`: deducts `stake + maker_fee_entry` from bankroll.

`_exit_trade()` bankroll update: `bankroll += contracts * exit_price - maker_fee_exit`. The `net_maker` stored in the DB is `gross_pnl - maker_total` (both legs). Do not add `net_maker` separately to the bankroll — it's already factored in through the entry deduction and exit credit.

Position sizing uses quarter-Kelly capped at `MAX_TRADE_PCT=0.05` (5% of bankroll).

`check_exits()` must be called from the live loop with current prices to enforce: 68¢ target, 20¢ stop loss, 70¢ never-hold-above, 11 PM time limit, and 4:15 PM DSM cancel.

---

## Kalshi Price Conventions

All Kalshi prices are `decimal.Decimal` — never `float`. From the orderbook:
- `yes_ask = 1.00 - best_no_bid`
- `no_ask = 1.00 - best_yes_bid`
- To buy NO: executable entry = `1 - yes_bid` (not `1 - yes_ask`)

`KalshiOrderbookManager` must invalidate all local books and reconnect when it detects a WebSocket sequence gap. Continuing after a sequence gap means the book may be stale and untrustworthy.

Fees use `math.ceil()` (ceiling-rounded):
- Maker: `ceil(0.0175 * contracts * P * (1-P) * 100) / 100`
- Taker: `ceil(0.07 * contracts * P * (1-P) * 100) / 100`

---

## Settlement Source

Settlement = NWS Daily CLI for each city's official station. wethr.net provides this via `observation_type=cli_high`. **Never use Google, Weather Underground, or public weather apps** — they differ by 1–2°F from CLI.

DSM (Daily Summary Message) fires at predictable UTC times (e.g., KNYC at 20:21Z). Cancel all open orders by 4:15 PM ET; the DSM bot fires in milliseconds.

During Daylight Saving Time, the NYC CLI measures 1 AM to 1 AM ET (not midnight to midnight).

---

## Key Config Constants

All in `config.py`. Critical values that differ from naive assumptions:

```python
TARGET_EXIT_PRICE = Decimal("0.68")   # NOT 0.65
STOP_LOSS_DIFF    = Decimal("0.20")   # NOT 0.15
NEVER_HOLD_ABOVE  = Decimal("0.70")
DSM_CANCEL_TIME_ET = "16:15"
MAX_HOLD_TIME_ET   = "23:00"
MIN_YES_PRICE = Decimal("0.25")        # below this → longshot trap
MAX_YES_PRICE = Decimal("0.75")        # above this → NWS error risk
MIN_GAP_PP    = 20.0
```

Sleeve controls:

```python
TAIL_NO_PROB_MAX = 0.30
TAIL_NO_YES_PRICE_MIN = Decimal("0.55")
ENABLE_TAIL_NO_TRADES = False

DEEP_TAIL_NO_PROB_MAX = 0.02
DEEP_TAIL_NO_YES_PRICE_MIN = Decimal("0.05")
ENABLE_DEEP_TAIL_NO_TRADES = True
```

Cities: KNYC (active, Sharpe 4.72), KPHL (active, Sharpe 2.83), KMDW (inactive). Never trade KAUS (Sharpe −1.57, convective weather breaks synoptic models).

Best season: Aug–Nov. Worst: Apr–May (minimum size).

---

## LaunchAgent

The pipeline runs as a macOS LaunchAgent:
```
plist: ~/prediction-market-analysis/logs/com.bhargavsukhavasi.kalshi-weather-pipeline.plist
cmd:   source ~/.zshrc; cd ~/prediction-market-analysis; exec .venv/bin/python main.py
logs:  logs/launchd.out.log, logs/launchd.err.log, logs/pipeline.log
```

Restart: `launchctl kickstart -k gui/$(id -u)/com.bhargavsukhavasi.kalshi-weather-pipeline`

Check status: `launchctl list | grep kalshi`

The process does NOT hot-reload — code changes require a restart.
