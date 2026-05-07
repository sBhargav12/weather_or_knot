# Model Bakeoff Research

Generated: 2026-05-03T10:17:03

Git SHA: `d892deb`

## Scope

This is a research-only implementation of the valid parts of
`/Users/bhargavsukhavasi/Downloads/deep-research-report (8).md`.

It compares the current coherent Gumbel baseline against seven offline
post-processing models:

- `EMOS`: linear bias correction plus residual normal spread,
- `EMOS_GUMBEL`: EMOS with Gumbel predictive distribution (OLS mu, beta from residual std * sqrt(6)/pi, loc shifted by Euler gamma),
- `EMOS_GUMBEL_HETERO`: EMOS-Gumbel with spread-linked heteroscedastic beta (beta = c + d*model_spread),
- `IDR`: Isotonic Distributional Regression on consensus temperature (Henzi et al. 2021),
- `NGBOOST`: Natural Gradient Boosting with Normal distribution (Duan et al. 2020), 100 trees,
- `NGBOOST_GUMBEL`: Natural Gradient Boosting with Gumbel distribution, 100 trees,
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
| EMOS | 3392 | 571 | 0.1122 | 0.4707 | 1.9385 | 1.0000 | 1.0000 | 1.0000 |
| EMOS_GUMBEL | 3392 | 571 | 0.1101 | 0.4993 | 1.9714 | 1.0000 | 1.0000 | 1.0000 |
| NGBOOST_GUMBEL | 3392 | 571 | 0.1098 | 0.5133 | 2.0406 | 1.0000 | 1.0000 | 1.0000 |
| NGBOOST | 3392 | 571 | 0.1128 | 0.5188 | 2.0854 | 1.0000 | 1.0000 | 1.0000 |
| EMOS_GUMBEL_HETERO | 3392 | 571 | 0.1085 | 0.5389 | 2.1038 | 1.0000 | 1.0000 | 1.0000 |
| GUMBEL | 3392 | 571 | 0.1360 | 0.5739 | 2.3548 | 1.0000 | 1.0000 | 1.0000 |
| RF_DISTRIBUTION | 3392 | 571 | 0.1181 | 0.6969 | 2.8865 | 1.0000 | 1.0000 | 1.0000 |
| HGBR_QUANTILE | 3392 | 571 | 0.1690 | 0.7571 | 3.1339 | 1.0000 | 1.0000 | 1.0000 |
| IDR | 3392 | 571 | 0.1352 | 0.8667 | 3.6017 | 1.0000 | 1.0000 | 1.0000 |

## Strategy Overlay Metrics

The strategy overlay uses the same basic research gates for each model's
probability map: 9AM price, 20pp edge, 35-40pp dead-zone exclusion, 25-75c side
price band, and lower-tail caution.

| model_name | trades | days | win_rate | net_pnl | sharpe | max_drawdown | avg_entry_price |
| --- | --- | --- | --- | --- | --- | --- | --- |
| NGBOOST | 506 | 366 | 0.7194 | 88.4700 | 0.4147 | -3.9900 | 0.5245 |
| EMOS_GUMBEL_HETERO | 474 | 341 | 0.7257 | 86.1300 | 0.4305 | -4.8300 | 0.5240 |
| RF_DISTRIBUTION | 507 | 359 | 0.6884 | 73.9000 | 0.3348 | -5.3200 | 0.5226 |
| NGBOOST_GUMBEL | 435 | 319 | 0.7080 | 68.4500 | 0.3678 | -3.2900 | 0.5307 |
| EMOS_GUMBEL | 365 | 285 | 0.7260 | 63.2700 | 0.4251 | -2.8700 | 0.5327 |
| EMOS | 318 | 254 | 0.7327 | 54.6100 | 0.4234 | -3.1100 | 0.5410 |
| IDR | 413 | 322 | 0.5956 | 21.8800 | 0.1140 | -10.1500 | 0.5227 |
| GUMBEL | 539 | 384 | 0.5788 | 21.8000 | 0.0874 | -18.1300 | 0.5184 |
| HGBR_QUANTILE | 608 | 441 | 0.6053 | 20.1400 | 0.0707 | -10.5800 | 0.5521 |

## Read

This establishes the model-bakeoff framework the report asked for. Do not
promote any model from this single retrospective run. A model is only a future
paper candidate if it improves probability metrics and survives the existing
execution-stress policy tests.
