# Vintage EMOS-Gumbel-Hetero Backtest

Generated: 2026-05-01T21:02:33+00:00

## Scope

This is the leakage-controlled rerun. Forecast features come from Open-Meteo
Single Runs API, one explicit archived model run at a time, with each run
required to be available before the simulated 11:00 AM ET decision.

Model: `EMOS_GUMBEL_HETERO`

Forecast model features: GFS, ECMWF, ICON, GEM. This is the pre-HGEFS historical
fallback family from `AGENTS.md`; member-level HGEFS vintages are not yet present
in this repository.

Training: `2025-08-01` to `2026-01-06`.

Evaluation: `2026-01-07` to `2026-04-24`.

Entry: 11:00 AM ET maker price, using orderbook snapshot within 30 minutes when
available, otherwise the 11AM Kalshi candle with a synthetic 2c spread.

## Results

Core strategy:

- Trades: 85
- Days: 60
- Win rate: 60.0%
- Net P&L: $7.00
- Sharpe: 0.18
- Max drawdown: $-2.18
- Avg entry: 50.8%

Probability:

- Rows: 630
- Days: 105
- Brier: 0.1247
- Binary log loss: 0.5284
- Winner log loss: 2.2325
- Probability mass avg: 1.0000

## Data Integrity

- Vintage rows: 2284
- Complete vintage days: 255
- Rows with unavailable-later-than-entry violations: 0
- Orderbook entry share: 16.5%

Outputs:

- `data/research/vintage_emos_gumbel_hetero_predictions.csv`
- `data/research/vintage_emos_gumbel_hetero_trades.csv`
- `data/research/vintage_emos_gumbel_hetero_summary.json`
