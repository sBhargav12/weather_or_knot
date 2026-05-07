# Model Bakeoff v2 — Complete Test

Generated: 2026-05-01T15:57:53

Git SHA: `d892deb`

## Scope

Complete model bakeoff with realistic execution.

**Training:** all pre-2026-01-07 historical data (1615 days)
with weather features from `open_meteo_historical.csv` and Kalshi settlement labels.
No orderbook data used in training — models learn from temperature forecasts only.

**Evaluation:** 108 days from 2026-01-07 onward.
Entry prices sourced from predexon orderbook snapshots at 9:51 AM ET
(the METAR gate decision time). Orderbook coverage: 97 dates / 526 tickers.
Dates or tickers with no snapshot fall back to the 9AM CSV price ± 1¢ synthetic spread.

**Execution model:** always limit (maker) orders.
- YES buy: limit at `best_bid` (cents/100), fee rate 0.0175
- NO buy: limit at `(100 - best_ask) / 100`, same fee rate
- No-fill flag raised when depth at entry level = 0

**Models:** GUMBEL (current), EMOS, EMOS_GUMBEL, EMOS_GUMBEL_HETERO,
IDR, NGBOOST (100 trees), NGBOOST_GUMBEL (100 trees), SEASONAL_EMOS,
RF_DISTRIBUTION, HGBR_QUANTILE.

## Probability Metrics (Evaluation Period)

| model_name | rows | days | brier_score | binary_log_loss | winner_log_loss |
| --- | --- | --- | --- | --- | --- |
| SEASONAL_EMOS | 648 | 108 | 0.0845 | 0.2713 | 0.9659 |
| EMOS_GUMBEL_HETERO | 648 | 108 | 0.0865 | 0.3251 | 1.2779 |
| EMOS_GUMBEL | 648 | 108 | 0.0898 | 0.2980 | 1.0988 |
| EMOS | 648 | 108 | 0.0907 | 0.2841 | 1.0096 |
| NGBOOST | 648 | 108 | 0.1021 | 0.3595 | 1.3747 |
| RF_DISTRIBUTION | 648 | 108 | 0.1033 | 0.6442 | 3.0924 |
| NGBOOST_GUMBEL | 648 | 108 | 0.1050 | 0.3264 | 1.1936 |
| IDR | 648 | 108 | 0.1465 | 1.2362 | 4.8208 |
| HGBR_QUANTILE | 648 | 108 | 0.1619 | 0.6194 | 2.5349 |
| GUMBEL | 648 | 108 | 0.1694 | 0.5658 | 2.1724 |

Lower Brier and winner_log_loss = better calibration.

## Strategy Metrics (Maker Execution, All Gates Applied)

Gates: edge > 20pp from maker entry, dead zone 35–40pp excluded,
price band 0.25–0.75, wing_low excluded.

| model_name | trades | no_fill_trades | days | win_rate | net_pnl | sharpe | max_drawdown | avg_entry_price | avg_spread_cents | avg_maker_fee | avg_net_edge_pp | pct_from_orderbook |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EMOS_GUMBEL_HETERO | 85 | 0 | 65 | 0.8353 | 23.9400 | 0.7891 | -1.0100 | 0.5436 | 2.1765 | 0.0100 | 29.7697 | 83.5294 |
| EMOS | 67 | 0 | 56 | 0.8507 | 19.0700 | 0.8348 | -0.9700 | 0.5561 | 2.4627 | 0.0100 | 27.7905 | 76.1194 |
| EMOS_GUMBEL | 70 | 0 | 57 | 0.8286 | 18.3300 | 0.7667 | -1.0100 | 0.5567 | 2.2571 | 0.0100 | 29.1587 | 87.1429 |
| NGBOOST_GUMBEL | 90 | 0 | 67 | 0.7444 | 17.7800 | 0.4497 | -2.8700 | 0.5369 | 2.1556 | 0.0100 | 31.0407 | 85.5556 |
| SEASONAL_EMOS | 72 | 0 | 57 | 0.8056 | 17.2700 | 0.6446 | -0.9700 | 0.5557 | 2.0556 | 0.0100 | 29.4192 | 84.7222 |
| NGBOOST | 89 | 0 | 68 | 0.7416 | 16.2400 | 0.4537 | -2.9200 | 0.5491 | 2.1910 | 0.0100 | 32.7600 | 82.0225 |
| RF_DISTRIBUTION | 88 | 0 | 64 | 0.7159 | 15.7800 | 0.4248 | -2.3800 | 0.5266 | 2.3295 | 0.0100 | 34.7162 | 87.5000 |
| HGBR_QUANTILE | 119 | 0 | 85 | 0.6555 | 10.0000 | 0.1868 | -1.6500 | 0.5614 | 2.4286 | 0.0100 | 34.8885 | 82.3529 |
| IDR | 86 | 0 | 67 | 0.5930 | 3.2800 | 0.0797 | -5.1200 | 0.5449 | 2.4767 | 0.0100 | 35.4358 | 84.8837 |
| GUMBEL | 105 | 0 | 74 | 0.5048 | -3.0900 | -0.0634 | -7.2200 | 0.5242 | 2.3810 | 0.0100 | 33.9622 | 78.0952 |

`no_fill_trades` = snapshots where depth at entry price was zero.
`pct_from_orderbook` = % of trades where entry price came from real predexon snapshot vs 9AM fallback.

## Key Differences vs v1

- **Entry price**: orderbook at 9:51 AM ET vs 9AM CSV snapshot
- **Fee**: maker 0.0175 rate vs taker 0.0700 rate (4× cheaper)
- **Training**: full single-pass train/test split vs rolling-origin (more eval power on short window)
- **Evaluation window**: 2026 dates only (predexon coverage) vs longer mixed window

## Execution Stress Test — +1pp Adverse Fill

Simulates limit orders filling 1pp worse than best_bid/no_bid. Trades that fall
below the 20pp gate after stress are dropped.

| model_name | base_trades | stressed_trades | trades_dropped_pct | stressed_win_rate | stressed_net_pnl | stressed_sharpe | stressed_max_dd |
| --- | --- | --- | --- | --- | --- | --- | --- |
| EMOS_GUMBEL_HETERO | 85 | 75 | 11.8000 | 0.8133 | 19.1400 | 0.6879 | -1.2800 |
| NGBOOST_GUMBEL | 90 | 86 | 4.4000 | 0.7558 | 17.6200 | 0.4740 | -3.0000 |
| EMOS_GUMBEL | 70 | 63 | 10.0000 | 0.8413 | 16.8800 | 0.7858 | -0.9700 |
| EMOS | 67 | 58 | 13.4000 | 0.8621 | 16.7500 | 0.8541 | -0.7000 |
| SEASONAL_EMOS | 72 | 67 | 6.9000 | 0.8060 | 16.2200 | 0.6521 | -1.0100 |
| RF_DISTRIBUTION | 88 | 84 | 4.5000 | 0.7024 | 13.9500 | 0.3845 | -2.4900 |
| NGBOOST | 89 | 81 | 9.0000 | 0.7284 | 13.5700 | 0.4025 | -3.5700 |
| HGBR_QUANTILE | 119 | 114 | 4.2000 | 0.6404 | 7.4300 | 0.1425 | -1.7200 |
| IDR | 86 | 83 | 3.5000 | 0.6145 | 4.0800 | 0.1040 | -4.2900 |
| GUMBEL | 105 | 102 | 2.9000 | 0.5196 | -2.0700 | -0.0444 | -5.7900 |

## Execution Stress Test — +2pp Adverse Fill

Simulates limit orders filling 2pp worse than best_bid/no_bid (queue delay,
stale book). Trades that fall below the 20pp gate after stress are dropped.

| model_name | base_trades | stressed_trades | trades_dropped_pct | stressed_win_rate | stressed_net_pnl | stressed_sharpe | stressed_max_dd |
| --- | --- | --- | --- | --- | --- | --- | --- |
| EMOS_GUMBEL_HETERO | 85 | 69 | 18.8000 | 0.7971 | 16.0900 | 0.6087 | -1.3100 |
| EMOS_GUMBEL | 70 | 61 | 12.9000 | 0.8361 | 15.7900 | 0.7469 | -1.0100 |
| EMOS | 67 | 52 | 22.4000 | 0.8654 | 14.3800 | 0.8253 | -0.7300 |
| NGBOOST_GUMBEL | 90 | 77 | 14.4000 | 0.7403 | 14.2200 | 0.4180 | -3.7000 |
| SEASONAL_EMOS | 72 | 62 | 13.9000 | 0.7903 | 13.8300 | 0.5823 | -1.0500 |
| RF_DISTRIBUTION | 88 | 77 | 12.5000 | 0.7013 | 11.9800 | 0.3546 | -2.7200 |
| NGBOOST | 89 | 75 | 15.7000 | 0.7067 | 10.9200 | 0.3385 | -3.7300 |
| HGBR_QUANTILE | 119 | 111 | 6.7000 | 0.6396 | 6.4100 | 0.1259 | -2.0000 |
| IDR | 86 | 74 | 14.0000 | 0.6081 | 2.9900 | 0.0845 | -4.3600 |
| GUMBEL | 105 | 95 | 9.5000 | 0.5053 | -3.2100 | -0.0736 | -6.1500 |

## Execution Stress Test — +3pp Adverse Fill

Extreme scenario: 3pp slippage (wide spread day or thin book).

| model_name | base_trades | stressed_trades | trades_dropped_pct | stressed_win_rate | stressed_net_pnl | stressed_sharpe | stressed_max_dd |
| --- | --- | --- | --- | --- | --- | --- | --- |
| EMOS_GUMBEL_HETERO | 85 | 66 | 22.4000 | 0.7879 | 14.5300 | 0.5628 | -1.3400 |
| EMOS_GUMBEL | 70 | 52 | 25.7000 | 0.8462 | 13.6500 | 0.7571 | -0.9700 |
| SEASONAL_EMOS | 72 | 58 | 19.4000 | 0.8103 | 13.5500 | 0.6175 | -1.0900 |
| NGBOOST_GUMBEL | 90 | 72 | 20.0000 | 0.7361 | 12.8000 | 0.3976 | -4.0500 |
| EMOS | 67 | 48 | 28.4000 | 0.8542 | 12.4800 | 0.7478 | -1.1000 |
| NGBOOST | 89 | 69 | 22.5000 | 0.7246 | 11.2000 | 0.3855 | -3.3700 |
| RF_DISTRIBUTION | 88 | 73 | 17.0000 | 0.6986 | 10.8800 | 0.3402 | -2.8100 |
| HGBR_QUANTILE | 119 | 105 | 11.8000 | 0.6476 | 6.1800 | 0.1285 | -2.3400 |
| IDR | 86 | 71 | 17.4000 | 0.5915 | 1.1800 | 0.0345 | -4.9300 |
| GUMBEL | 105 | 91 | 13.3000 | 0.4835 | -5.6200 | -0.1344 | -6.7400 |

## Execution Stress Test — +5pp Adverse Fill

Severe stale-book / missed-queue scenario. This is a break-glass comparison,
not a normal execution assumption.

| model_name | base_trades | stressed_trades | trades_dropped_pct | stressed_win_rate | stressed_net_pnl | stressed_sharpe | stressed_max_dd |
| --- | --- | --- | --- | --- | --- | --- | --- |
| EMOS_GUMBEL | 70 | 45 | 35.7000 | 0.8222 | 10.3900 | 0.6297 | -1.0100 |
| SEASONAL_EMOS | 72 | 48 | 33.3000 | 0.7917 | 10.3800 | 0.5525 | -1.1700 |
| EMOS_GUMBEL_HETERO | 85 | 51 | 40.0000 | 0.7843 | 10.3400 | 0.4988 | -0.9600 |
| NGBOOST_GUMBEL | 90 | 62 | 31.1000 | 0.7258 | 9.6500 | 0.3454 | -3.6900 |
| NGBOOST | 89 | 58 | 34.8000 | 0.7241 | 9.1500 | 0.3740 | -2.5000 |
| EMOS | 67 | 37 | 44.8000 | 0.8378 | 9.0500 | 0.6821 | -1.1800 |
| RF_DISTRIBUTION | 88 | 64 | 27.3000 | 0.6875 | 8.6500 | 0.3069 | -2.9900 |
| HGBR_QUANTILE | 119 | 94 | 21.0000 | 0.6489 | 4.9800 | 0.1165 | -2.3700 |
| IDR | 86 | 61 | 29.1000 | 0.6066 | 1.4800 | 0.0504 | -4.2600 |
| GUMBEL | 105 | 80 | 23.8000 | 0.4625 | -6.5900 | -0.1772 | -7.0800 |

## Verdict

A model passes stress if it remains profitable (`stressed_net_pnl > 0`) and
retains > 50% of its baseline trades at +2pp shock.
If it survives +3pp it is considered execution-robust.

## Next Step

Any model that beats GUMBEL on brier_score AND survives both stress tiers
is ready for paper-trading promotion via the standard paper_trader/policy.py path.
Re-run this script after collecting full orderbook coverage (run collect_orderbooks.py
to completion) for the final evaluation.
