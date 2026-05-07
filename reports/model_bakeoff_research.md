# Model Bakeoff Research

Generated: 2026-04-29T23:52:36

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
| EMOS | 352 | 60 | 0.1124 | 0.5376 | 2.3447 | 1.0000 | 1.0000 | 1.0000 |
| GUMBEL | 352 | 60 | 0.1193 | 0.5884 | 2.5920 | 1.0000 | 1.0000 | 1.0000 |
| RF_DISTRIBUTION | 352 | 60 | 0.1239 | 0.7168 | 2.9928 | 1.0000 | 1.0000 | 1.0000 |
| HGBR_QUANTILE | 352 | 60 | 0.1668 | 0.8936 | 4.1043 | 1.0000 | 1.0000 | 1.0000 |

## Strategy Overlay Metrics

The strategy overlay uses the same basic research gates for each model's
probability map: 9AM price, 20pp edge, 35-40pp dead-zone exclusion, 25-75c side
price band, and lower-tail caution.

| model_name | trades | days | win_rate | net_pnl | sharpe | max_drawdown | avg_entry_price |
| --- | --- | --- | --- | --- | --- | --- | --- |
| EMOS | 26 | 22 | 0.8846 | 8.3300 | 1.0137 | -0.5100 | 0.5442 |
| GUMBEL | 51 | 37 | 0.6667 | 6.3600 | 0.2686 | -5.1200 | 0.5220 |
| RF_DISTRIBUTION | 47 | 35 | 0.6383 | 4.3800 | 0.1928 | -2.9900 | 0.5251 |
| HGBR_QUANTILE | 58 | 45 | 0.6207 | 4.0600 | 0.1478 | -1.8300 | 0.5307 |

## Read

This establishes the model-bakeoff framework the report asked for. Do not
promote any model from this single retrospective run. A model is only a future
paper candidate if it improves probability metrics and survives the existing
execution-stress policy tests.
