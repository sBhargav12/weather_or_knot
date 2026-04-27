# Model Bakeoff Research

Generated: 2026-04-27T04:10:59

Git SHA: `6a81fdf`

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
| EMOS | 315 | 53 | 0.1104 | 0.4088 | 1.5936 | 1.0000 | 1.0000 | 1.0000 |
| GUMBEL | 315 | 53 | 0.1329 | 0.5159 | 2.0267 | 1.0000 | 1.0000 | 1.0000 |
| HGBR_QUANTILE | 315 | 53 | 0.1875 | 0.9195 | 3.8125 | 1.0000 | 1.0000 | 1.0000 |
| RF_DISTRIBUTION | 315 | 53 | 0.1477 | 1.0621 | 4.2520 | 1.0000 | 1.0000 | 1.0000 |

## Strategy Overlay Metrics

The strategy overlay uses the same basic research gates for each model's
probability map: 9AM price, 20pp edge, 35-40pp dead-zone exclusion, 25-75c side
price band, and lower-tail caution.

| model_name | trades | days | win_rate | net_pnl | sharpe | max_drawdown | avg_entry_price |
| --- | --- | --- | --- | --- | --- | --- | --- |
| RF_DISTRIBUTION | 46 | 34 | 0.6739 | 4.3400 | 0.1982 | -3.3500 | 0.5596 |
| EMOS | 27 | 19 | 0.7037 | 3.7400 | 0.2836 | -1.1000 | 0.5452 |
| HGBR_QUANTILE | 57 | 40 | 0.6140 | 2.1600 | 0.0785 | -2.9100 | 0.5561 |
| GUMBEL | 46 | 35 | 0.5652 | 1.7300 | 0.0742 | -2.4300 | 0.5076 |

## Read

This establishes the model-bakeoff framework the report asked for. Do not
promote any model from this single retrospective run. A model is only a future
paper candidate if it improves probability metrics and survives the existing
execution-stress policy tests.
