# CLAUDE.md

## Key Files (read these before editing strategy or config)

| File | What it contains |
|------|-----------------|
| `AGENTS.md` | Full strategy rationale, backtest results, failure modes, community findings |
| `MASTER_PIPELINE_PLAN.md` | Complete architecture spec, DB schema, module specs, build order |
| `config.py` | All live thresholds, gate params, Gumbel params, fee functions, city config |
| `paper_trader/config_paper.py` | All paper-only flags, execution margins, seasonal/regime multipliers |
| `signal_engine/gate_checker.py` | 6-gate logic with tier docs and confidence → size mapping |
| `signal_engine/gumbel_model.py` | Bracket probability model, Bayesian NBM update, wethr fallback |
| `data_store/schema.py` | Full SQLite schema (10 tables) |

---

## Commands

```bash
uv run pytest tests/ -v
uv run ruff check . && uv run ruff format .

# Pipeline
.venv/bin/python main.py             # run indefinitely
.venv/bin/python main.py --once      # single polling pass
.venv/bin/python main.py --report 2026-04-25

# Backtests
uv run python research/backtests/backtest.py --skip-fetch            # KNYC (default)
uv run python research/backtests/backtest.py --city KMDW --skip-fetch  # Chicago
uv run python research/backtests/strategy_variation_research.py
uv run python research/backtests/loss_analysis.py
uv run python research/backtests/report_improvement_backtest.py
uv run python research/backtests/report7_policy_stress_backtest.py
uv run python research/backtests/model_bakeoff_research.py

# Becker / Polymarket research
uv run python research/becker/becker_inventory.py
uv run python research/becker/build_weather_mart.py
uv run python research/becker/microstructure_atlas.py
uv run python research/polymarket/polymarket_wallet_analysis.py
```

**Env vars** (`~/.zshrc`): `KALSHI_API_KEY`, `KALSHI_KEY_PATH` (RSA PEM), `WETHR_API_KEY`, `ECCODES_DIR` (`brew --prefix eccodes`). GRIB2 requires `brew install eccodes`.

---

## Maintenance Rules

After any code or strategy change:
1. Update `CLAUDE.md` with new behavior, thresholds, and test status.
2. Run `uv run pytest` for strategy/pipeline changes.
3. Commit and push to the `weather` remote (`git push weather main`).
4. Do not stage or commit live log churn from `logs/`.

---

## Architecture

```
wethr.net API (60s/5min) ──► metar_observations, dsm_reports, cli_reports
GEFS S3 (30min)           ──► model_runs (physics_mean, physics_spread)
AIGEFS NOMADS (30min)     ──► model_runs (ai_mean, ai_spread)
NBM NOMADS (30min)        ──► model_runs (nbm_p10..p90)
Kalshi REST/WebSocket     ──► kalshi_prices, price_history
All ──► EventTriggerEngine ──► gate_checks ──► signals ──► paper_trades
```

Two independent systems:
- **Research framework** (`src/`, `data/kalshi/`, `data/polymarket/`): Static Becker dataset analysis. DuckDB.
- **Live trading pipeline** (root-level packages): Asyncio event loop → 6-gate filter → paper-trading.

**Database:** Single SQLite at `data/pipeline.db`. Adding columns requires `ALTER TABLE` on the live DB **and** updating `data_store/schema.py`.

---

## GEFS/AIGEFS Operational Gotchas

- **NOMADS 403s** on GEFS downloads — use `noaa-gefs-pds.s3.amazonaws.com` (no auth required).
- `noaa-hgefs-pds` S3 bucket does not exist; AIGEFS sometimes 403s → wethr proxy fallback kicks in.
- AIGEFS files are `pres` (pressure-level, 6-hourly); members `mem000`–`mem030`. Use `TMP:1000 mb` + `+4°F` bias; TMAX field unavailable.
- NBM: `blend_nbptx` KNYC blocks often empty; parser falls through to `blend_nbetx` for real `TXN`/`XND` rows.
- Fallback ensemble weights in `config.py` are fallback-only — do not replace the HGEFS-first path.

---

## Critical Constraints

**Research scripts are read-only.** Never modify `config.py`, live thresholds, `main.py`, or LaunchAgent from a research script. Results go to `data/research/` and `reports/` only.

**Paper trader math:** `simulate_entry()` deducts `stake + maker_fee_entry`. `_exit_trade()` adds `contracts * exit_price - maker_fee_exit`. `net_maker` in DB = `gross_pnl - maker_total` — do not add fees again.

**Seasonal/regime multipliers** in `config_paper.py` are soft size-only — must not hard-stop whole months or regimes.

**Weather mart leakage guard:** `yes_bid`/`ask`/`no_bid`/`ask` are intentionally null in `weather_mart.parquet` — Becker rows are latest metadata, not historical orderbook snapshots.

**Polymarket:** Do not copy NYC Polymarket behavior into KXHIGHNY — Polymarket settles on KLGA (LaGuardia), Kalshi settles on KNYC (Central Park). Different stations.

**Model bakeoff (v2 — 2026-05-01):** Extended bakeoff (81 eval days, KNYC) added EMOS_GUMBEL, EMOS_GUMBEL_HETERO, IDR, NGBoost. Results:
- **EMOS_GUMBEL**: best Brier 0.1058 (vs EMOS 0.1120 = −5.6%), PnL $11.47, Sharpe 0.60
- **EMOS_GUMBEL_HETERO**: best PnL $16.33, 81% win rate, 58 trades — top overall; heteroscedastic β widens when model_spread is high
- **EMOS**: still best Sharpe (1.29) but fewest trades (36) — high precision, lower throughput
- **NGBoost**: Brier 0.1225 but PnL $13.85 — finds different opportunities via nonlinear features
- **IDR**: disappointing (Brier 0.1410, PnL $3.48) — consensus-only predictor too coarse
- RF/HGBR: still last. None of the new models are live-approved yet.

**EMOS paper sleeve (`CORE_HGEFS_EMOS`):** Runs in parallel with `CORE_HGEFS_GUMBEL`. Same 6-gate structure; gate 2 uses EMOS probability instead of Gumbel. `LiveEMOSModel` is instantiated per active city at startup (one model each for KNYC and KMDW). Training data per city: KNYC uses `data/open_meteo_historical_extended.csv` + `data/knyc_actual_temps_extended.csv` (1,723 days); KMDW uses `data/open_meteo_kmdw_historical_extended.csv` + `data/kmdw_actual_temps_extended.csv` (1,711 days). Toggle: `PAPER_ENABLE_EMOS` in `paper_trader/config_paper.py`. To rebuild training data: `uv run python research/data/fetch_extended_training_data.py [--city KMDW]`.

**Chicago (KMDW) now active:** KXHIGHCHI paper trading enabled as of 2026-05-01. Settlement: NWS CLI Chicago Midway (`issuedby=MDW`). EMOS bakeoff: Sharpe 0.71, 80% win rate (vs Gumbel Sharpe -0.37). DSM cancel time same as NYC (16:15 ET). Backtest scripts support `--city KMDW`.

**Multi-city expansion (2026-05-04):** 5 new cities added to `config.py` (`active: False` — paper-validate before enabling):
| City | ICAO | Series | Timezone | Notes |
|------|------|--------|----------|-------|
| Miami | KMIA | KXHIGHMIA | America/New_York | Training data: 1088 rows |
| Austin | KAUS | KXHIGHAUS | America/Chicago | Training data: 928 rows (508 hindcast) |
| Los Angeles | KLAX | KXHIGHLAX | America/Los_Angeles | Training data: 324 rows |
| Denver | KDEN | KXHIGHDEN | America/Denver | Training data: 370 rows |
| Philadelphia | KPHL | KXHIGHPHIL | America/New_York | Training data: 370 rows (fixed series ticker from KXHIGHPHL) |

To add a city: (1) `uv run python research/data/fetch_city_kalshi_data.py --city KXXX`, (2) `uv run python research/data/fetch_extended_training_data.py --city KXXX`, (3) run `multicity_capital_backtest.py --cities KXXX`, (4) set `active: True` in `config.py` only after validating backtest Sharpe > 0.5.

**KPHL series ticker fix:** Corrected from `KXHIGHPHL` → `KXHIGHPHIL` (actual Kalshi series name).

**KXLOW daily low temperature markets (2026-05-05):** All KXLOWT* series launched Jan 28, 2026. 7-city leakage-safe backtest (EMOS_GUMBEL_HETERO, 168–171 training days from pre-market IEM actuals, eval Jan 28 – May 4):

| City | Trades | Win% | Sharpe | Verdict |
|------|--------|------|--------|---------|
| KXLOWTCHI | 5 | 80.0% | **0.714** | paper-trade candidate |
| KXLOWTDEN | 11 | 72.7% | **0.628** | paper-trade candidate |
| KXLOWTNYC | 15 | 66.7% | 0.057 | hold — need more data |
| KXLOWTAUS | 16 | 62.5% | 0.119 | hold |
| KXLOWTMIA | 10 | 40.0% | -0.025 | skip |
| KXLOWTPHIL | 16 | 50.0% | -0.215 | skip |
| KXLOWTLAX | 0 | — | — | no edge (LA lows too stable) |

Combined $500: **+$277.85 (+55.6%)**, 73 trades, 60.3% WR, Sharpe 0.099, max drawdown −$214.

Training architecture: `TRAIN_CUTOFF = "2026-01-28"` — EMOS trains on pre-market IEM TMIN actuals (Jul 2024–Jan 27, 2026) + Single Runs API `temperature_2m_min` vintages. All cities `active: False` — paper-validate CHI/DEN for 60+ forward days before activating.

New files:
- `research/data/fetch_tmin_training_data.py` — IEM `min_tmpf` for all 7 cities (`--city KXLOWTCHI` or `--all`)
- `research/backtests/kxlow_backtest.py` — 7-city leakage-safe TMIN backtest
- `data/kxlowt{nyc,chi,mia,aus,lax,den,phil}_markets.csv` + `*_prices.csv` (738 rows each)
- `data/kxlowt*_actual_tmin_extended.csv` (855 rows each, Jan 2024–May 2026)

Settlement for KXLOW: `observation_type=cli_low` from wethr.net (not `cli_high`). Do **not** use IEM TMIN for settlement — use NWS CLI issued low.

To refresh after more data accumulates:
```bash
for city in KXLOWTNYC KXLOWTCHI KXLOWTDEN; do
  uv run python research/data/fetch_city_kalshi_data.py --city $city
done
uv run python research/data/fetch_tmin_training_data.py --all
uv run python research/backtests/kxlow_backtest.py --skip-fetch
```

---

**BRACKET_LOCK sleeve (2026-05-05):** Intraday confirmed high entry at 3:00 PM ET. Uses `wethr_high_f` (running daily max, already ingested every 60s) + NWS Hourly Forecast remaining-day ceiling.

Backtest (571 days, Oct 2024–Apr 2026): **78.4% WR, avg entry 64c, EV $12.11/100 contracts, Sharpe 0.382** with upper_margin ≥ 1°F filter. Timing sweep shows Sharpe peaks at 3 PM (0.382) vs 4 PM (0.098) because 4 PM prices are already 80c vs 64c.

Key mechanics:
- `upper_margin = bracket_hi - running_max_f ≥ 1.0°F` (temp must be ≥1°F from bracket ceiling)
- `nws_remaining_max ≤ running_max + 1.0°F` (NWS doesn't forecast a rise past the bracket)
- `YES price ∈ [0.20, 0.90]` — not already repriced
- 50 contracts per trade (conservative start)
- Bracket structure: `B{X.5}` wins if CLI ∈ {X, X+1} (2°F wide bracket, confirmed from Kalshi rules)

Toggle: `PAPER_BRACKET_LOCK_ENABLED` in `paper_trader/config_paper.py`.
NWS gridpoints: `data_ingest/model_fetcher.py:_NWS_GRIDPOINTS` (KNYC verified as OKX/34,45).
Backtest script: `uv run python research/backtests/intraday_lock_backtest.py`
ASOS data fetch: `uv run python research/data/fetch_intraday_asos.py`

---

## Kalshi Price Conventions

All prices are `decimal.Decimal` — never `float`.
- `yes_ask = 1.00 - best_no_bid`; `no_ask = 1.00 - best_yes_bid`
- To buy NO: entry = `1 - yes_bid` (not `1 - yes_ask`)

Reconnect on WebSocket sequence gap — stale books are untrustworthy.

---

## Settlement Source

Settlement = NWS Daily CLI via `wethr.net` (`observation_type=cli_high`). **Never use Google, Weather Underground, or public weather apps** — they differ 1–2°F from CLI.

DSM fires at predictable UTC times (KNYC ≈ 20:21Z). Cancel all open orders by 4:15 PM ET.

During DST, NYC CLI measures 1 AM–1 AM ET (not midnight–midnight).

---

## Live Bot — Oracle Ubuntu VM

The trading pipeline runs on an Oracle Ubuntu VM as a systemd service, **not** via launchctl (macOS-only). The Oracle deployment is a copied directory, not a git worktree — `git pull` will not work there.

```
service: kalshi-paper.service
WorkingDirectory: /home/ubuntu/prediction-market-analysis
ExecStart: /home/ubuntu/.local/bin/uv run python main.py
SSH key: ~/.ssh/oracle_kalshi
Host: ubuntu@129.159.170.20
```

```bash
# Restart after deploying changes
ssh -i ~/.ssh/oracle_kalshi ubuntu@129.159.170.20 \
  'sudo systemctl restart kalshi-paper.service'

# Check status
ssh -i ~/.ssh/oracle_kalshi ubuntu@129.159.170.20 \
  'systemctl --no-pager --full status kalshi-paper.service'

# Follow logs
ssh -i ~/.ssh/oracle_kalshi ubuntu@129.159.170.20 \
  'journalctl -u kalshi-paper.service -f'
```

**Deploying code changes:** rsync changed files to Oracle, then restart.
```bash
rsync -avz --exclude='data/' --exclude='logs/' --exclude='.venv/' \
  -e "ssh -i ~/.ssh/oracle_kalshi" \
  /Users/bhargavsukhavasi/prediction-market-analysis/ \
  ubuntu@129.159.170.20:/home/ubuntu/prediction-market-analysis/
ssh -i ~/.ssh/oracle_kalshi ubuntu@129.159.170.20 \
  'sudo systemctl restart kalshi-paper.service'
```

## Local Mac (non-live)

```
plist: ~/prediction-market-analysis/logs/com.bhargavsukhavasi.kalshi-weather-pipeline.plist
```

Local Mac only runs `com.bhargavsukhavasi.kalshi-a1-capacity-loop` — the trading pipeline is Oracle-only.
