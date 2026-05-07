# Model Bakeoff Research

Generated: 2026-05-01T13:41:50

Git SHA: `d892deb`

## Scope

This is a research-only implementation of the valid parts of
`/Users/bhargavsukhavasi/Downloads/deep-research-report (8).md`.

It compares the current coherent Gumbel baseline against three offline
post-processing models:

- `EMOS`: linear bias correction plus residual normal spread,
- `RF_DISTRIBUTION`: random-forest tree-prediction empirical distribution,
- `HGBR_QUANTILE`: histogram gradient boosting quantile distribution.

The bakeoff uses weekly rolling-origin validation with at least 120
prior training days. It uses Kalshi settlement labels for bracket outcomes and the
winning market's raw settlement temperature for continuous training. It does not
touch live strategy logic, `config.py`, `main.py`, `event_triggers.py`, or the
LaunchAgent.

## Probability Metrics

| model_name | rows | days | brier_score | binary_log_loss | winner_log_loss | mass_avg | mass_min | mass_max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EMOS | 489 | 82 | 0.0979 | 0.4524 | 1.9339 | 1.0000 | 1.0000 | 1.0000 |
| HGBR_QUANTILE | 489 | 82 | 0.1634 | 0.7277 | 2.9589 | 1.0000 | 1.0000 | 1.0000 |
| GUMBEL | 489 | 82 | 0.1836 | 0.7354 | 3.0193 | 1.0000 | 1.0000 | 1.0000 |
| RF_DISTRIBUTION | 489 | 82 | 0.1069 | 0.7287 | 3.0481 | 1.0000 | 1.0000 | 1.0000 |

## Strategy Overlay Metrics

The strategy overlay uses the same basic research gates for each model's
probability map: 9AM price, 20pp edge, 35-40pp dead-zone exclusion, 25-75c side
price band, and lower-tail caution.

| model_name | trades | days | win_rate | net_pnl | sharpe | max_drawdown | avg_entry_price |
| --- | --- | --- | --- | --- | --- | --- | --- |
| RF_DISTRIBUTION | 69 | 49 | 0.7246 | 13.2800 | 0.4608 | -1.3200 | 0.5122 |
| EMOS | 45 | 36 | 0.8000 | 11.3500 | 0.7104 | -0.9200 | 0.5278 |
| HGBR_QUANTILE | 75 | 57 | 0.6667 | 6.3200 | 0.1761 | -3.0700 | 0.5624 |
| GUMBEL | 72 | 56 | 0.4028 | -12.0300 | -0.3666 | -14.4800 | 0.5499 |

## Read

This establishes the model-bakeoff framework the report asked for. Do not
promote any model from this single retrospective run. A model is only a future
paper candidate if it improves probability metrics and survives the existing
execution-stress policy tests.
