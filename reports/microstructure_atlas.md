# Exchange-Wide Microstructure Atlas

Generated: 2026-04-26T14:09:15.658293+00:00

Research-only analysis of settled Becker Kalshi trades. All return and calibration metrics use Kalshi settlement labels from `markets.result`; active/unsettled markets are excluded.

## Output Files

- Aggregate atlas parquet: `data/research/microstructure_atlas.parquet`
- Summary JSON: `data/research/microstructure_atlas_summary.json`
- Figures: `reports/figures/`

## Dataset Scope

| table_name | segment | trades | contracts | tickers | event_tickers | min_trade_time | max_trade_time | avg_taker_return | avg_maker_return |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dataset_scope | non_weather | 63603934 | 1.69654e+10 | 526085 | 187506 | 2021-06-30 16:09:14.185137-04 | 2025-11-23 14:02:02.507858-05 | -0.0111278 | 0.0111278 |
| dataset_scope | temperature | 3612718 | 2.36734e+08 | 15415 | 2708 | 2024-10-24 08:05:04.902879-04 | 2025-11-23 02:53:22.839864-05 | -0.0152338 | 0.0152338 |
| dataset_scope | weather_other | 545696 | 2.85566e+07 | 12733 | 3136 | 2021-07-16 10:31:11.049535-04 | 2025-11-22 19:23:33.33006-05 | 0.00615508 | -0.00615508 |

## Strongest Maker/Taker Findings

Top maker-return slices by price bucket:

| table_name | segment | bucket | trades | contracts | avg_maker_return |
| --- | --- | --- | --- | --- | --- |
| maker_taker_by_price_bucket | weather | 80-90 | 131028 | 6.85421e+06 | 0.0370612 |
| maker_taker_by_price_bucket | weather | 70-80 | 163605 | 6.8671e+06 | 0.0320215 |
| maker_taker_by_price_bucket | weather | 60-70 | 226296 | 8.09935e+06 | 0.0298765 |
| maker_taker_by_price_bucket | weather | 90-95 | 65985 | 4.85706e+06 | 0.0248241 |
| maker_taker_by_price_bucket | non_weather | 40-50 | 7556196 | 1.77312e+09 | 0.0215482 |
| maker_taker_by_price_bucket | non_weather | 60-70 | 6263819 | 1.47947e+09 | 0.0213449 |
| maker_taker_by_price_bucket | weather | 95-100 | 141230 | 2.62899e+07 | 0.0132482 |
| maker_taker_by_price_bucket | non_weather | 05-10 | 3863358 | 1.17808e+09 | 0.0132156 |
| maker_taker_by_price_bucket | non_weather | 10-20 | 6791971 | 1.69423e+09 | 0.0125779 |
| maker_taker_by_price_bucket | weather | 05-10 | 369288 | 2.21332e+07 | 0.0114586 |

Worst maker-return slices by price bucket:

| table_name | segment | bucket | trades | contracts | avg_maker_return |
| --- | --- | --- | --- | --- | --- |
| maker_taker_by_price_bucket | non_weather | 50-60 | 7388478 | 1.82577e+09 | 0.00399052 |
| maker_taker_by_price_bucket | non_weather | 30-40 | 7041236 | 1.58322e+09 | 0.00460665 |
| maker_taker_by_price_bucket | weather | 30-40 | 558611 | 1.94108e+07 | 0.00623529 |
| maker_taker_by_price_bucket | non_weather | 00-05 | 3806542 | 1.77107e+09 | 0.00664827 |
| maker_taker_by_price_bucket | non_weather | 70-80 | 4981988 | 1.21513e+09 | 0.00682025 |
| maker_taker_by_price_bucket | weather | 00-05 | 498758 | 9.37989e+07 | 0.00699586 |
| maker_taker_by_price_bucket | non_weather | 90-95 | 2139644 | 6.5647e+08 | 0.00841646 |
| maker_taker_by_price_bucket | weather | 40-50 | 454214 | 1.45402e+07 | 0.00881063 |
| maker_taker_by_price_bucket | weather | 50-60 | 347053 | 1.08475e+07 | 0.00912783 |
| maker_taker_by_price_bucket | non_weather | 95-100 | 2709666 | 1.08246e+09 | 0.00916302 |

## Strongest Hour-of-Day Findings

| table_name | segment | bucket | trades | contracts | avg_maker_return |
| --- | --- | --- | --- | --- | --- |
| maker_taker_by_hour | weather | 5 | 27438 | 900878 | 0.0247595 |
| maker_taker_by_hour | non_weather | 3 | 233995 | 4.69905e+07 | 0.0237087 |
| maker_taker_by_hour | weather | 19 | 117531 | 1.07533e+07 | 0.0219024 |
| maker_taker_by_hour | weather | 17 | 235026 | 2.32487e+07 | 0.0191177 |
| maker_taker_by_hour | weather | 0 | 101560 | 6.09135e+06 | 0.0183369 |
| maker_taker_by_hour | non_weather | 2 | 688563 | 1.76259e+08 | 0.0181865 |
| maker_taker_by_hour | weather | 16 | 308527 | 2.6756e+07 | 0.0174182 |
| maker_taker_by_hour | weather | 15 | 337245 | 2.61527e+07 | 0.0167025 |
| maker_taker_by_hour | non_weather | 5 | 179958 | 3.51905e+07 | 0.0163178 |
| maker_taker_by_hour | weather | 3 | 24470 | 790980 | 0.0162297 |
| maker_taker_by_hour | non_weather | 1 | 1154010 | 3.1971e+08 | 0.015441 |
| maker_taker_by_hour | weather | 2 | 82267 | 3.86956e+06 | 0.0153493 |

## Weather and Temperature Findings

Temperature city summary:

| table_name | segment | bucket | trades | contracts | tickers | avg_taker_return | avg_maker_return | avg_yes_calibration_edge | taker_yes_share |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| temperature_city_summary | KXHIGHNY | all | 799571 | 5.20031e+07 | 2280 | -0.0195346 | 0.0195346 | -0.0127525 | 0.61576 |
| temperature_city_summary | KXHIGHAUS | all | 559813 | 3.91772e+07 | 2291 | -0.013816 | 0.013816 | -0.0103872 | 0.607888 |
| temperature_city_summary | KXHIGHLAX | all | 526968 | 2.69684e+07 | 1832 | -0.0147723 | 0.0147723 | -0.00575488 | 0.649546 |
| temperature_city_summary | KXHIGHCHI | all | 499772 | 3.90196e+07 | 2283 | -0.0142539 | 0.0142539 | -0.00549941 | 0.630156 |
| temperature_city_summary | KXHIGHDEN | all | 455553 | 2.61974e+07 | 2144 | -0.0110458 | 0.0110458 | -0.00700979 | 0.563791 |
| temperature_city_summary | KXHIGHMIA | all | 415190 | 2.96913e+07 | 2141 | -0.016754 | 0.016754 | -0.00387745 | 0.624226 |
| temperature_city_summary | KXHIGHPHIL | all | 293074 | 1.72624e+07 | 2071 | -0.012611 | 0.012611 | -0.0048352 | 0.613675 |
| temperature_city_summary | KXHIGHHOU | all | 62777 | 6.41468e+06 | 373 | -0.0173557 | 0.0173557 | -0.0193523 | 0.54578 |

Favorite-longshot calibration by weather segment:

| table_name | segment | bucket | trades | contracts | avg_yes_price | realized_yes_rate | realized_minus_price |
| --- | --- | --- | --- | --- | --- | --- | --- |
| favorite_longshot_by_decile | non_weather | 00-05 | 3806542 | 1.77107e+09 | 0.0235095 | 0.0187574 | -0.00475203 |
| favorite_longshot_by_decile | non_weather | 05-10 | 3863358 | 1.17808e+09 | 0.0692707 | 0.0552387 | -0.0140319 |
| favorite_longshot_by_decile | non_weather | 10-20 | 6791971 | 1.69423e+09 | 0.144236 | 0.130211 | -0.0140253 |
| favorite_longshot_by_decile | non_weather | 20-30 | 6753870 | 1.52666e+09 | 0.244579 | 0.235742 | -0.00883717 |
| favorite_longshot_by_decile | non_weather | 30-40 | 7041236 | 1.58322e+09 | 0.345389 | 0.345612 | 0.00022278 |
| favorite_longshot_by_decile | non_weather | 40-50 | 7556196 | 1.77312e+09 | 0.446214 | 0.426433 | -0.0197811 |
| favorite_longshot_by_decile | non_weather | 50-60 | 7388478 | 1.82577e+09 | 0.543734 | 0.546412 | 0.00267752 |
| favorite_longshot_by_decile | non_weather | 60-70 | 6263819 | 1.47947e+09 | 0.64318 | 0.627981 | -0.0151989 |
| favorite_longshot_by_decile | non_weather | 70-80 | 4981988 | 1.21513e+09 | 0.743646 | 0.74647 | 0.00282429 |
| favorite_longshot_by_decile | non_weather | 80-90 | 4307166 | 1.17976e+09 | 0.843616 | 0.846728 | 0.00311204 |
| favorite_longshot_by_decile | non_weather | 90-95 | 2139644 | 6.5647e+08 | 0.91991 | 0.927888 | 0.00797737 |
| favorite_longshot_by_decile | non_weather | 95-100 | 2709666 | 1.08246e+09 | 0.972983 | 0.973533 | 0.000550204 |
| favorite_longshot_by_decile | temperature | 00-05 | 434830 | 8.57536e+07 | 0.0209082 | 0.0210634 | 0.000155164 |
| favorite_longshot_by_decile | temperature | 05-10 | 322874 | 1.94654e+07 | 0.0686795 | 0.0708574 | 0.00217788 |
| favorite_longshot_by_decile | temperature | 10-20 | 539056 | 2.52925e+07 | 0.143033 | 0.142625 | -0.00040775 |
| favorite_longshot_by_decile | temperature | 20-30 | 478819 | 1.89323e+07 | 0.243664 | 0.244504 | 0.0008399 |
| favorite_longshot_by_decile | temperature | 30-40 | 476969 | 1.65718e+07 | 0.344445 | 0.34318 | -0.00126568 |
| favorite_longshot_by_decile | temperature | 40-50 | 397499 | 1.27872e+07 | 0.442832 | 0.43226 | -0.0105714 |
| favorite_longshot_by_decile | temperature | 50-60 | 308042 | 9.6108e+06 | 0.54136 | 0.527217 | -0.0141431 |
| favorite_longshot_by_decile | temperature | 60-70 | 202771 | 7.34115e+06 | 0.640984 | 0.596254 | -0.0447304 |
| favorite_longshot_by_decile | temperature | 70-80 | 147617 | 6.03135e+06 | 0.742229 | 0.691567 | -0.0506625 |
| favorite_longshot_by_decile | temperature | 80-90 | 118852 | 6.23827e+06 | 0.843404 | 0.811227 | -0.0321762 |
| favorite_longshot_by_decile | temperature | 90-95 | 59675 | 4.4368e+06 | 0.91912 | 0.915442 | -0.00367842 |
| favorite_longshot_by_decile | temperature | 95-100 | 125714 | 2.42728e+07 | 0.977821 | 0.974434 | -0.00338697 |
| favorite_longshot_by_decile | weather_other | 00-05 | 63928 | 8.0453e+06 | 0.0191883 | 0.0283287 | 0.00914044 |
| favorite_longshot_by_decile | weather_other | 05-10 | 46414 | 2.66779e+06 | 0.0696406 | 0.0898651 | 0.0202245 |
| favorite_longshot_by_decile | weather_other | 10-20 | 94107 | 3.78351e+06 | 0.144204 | 0.165641 | 0.021437 |
| favorite_longshot_by_decile | weather_other | 20-30 | 90364 | 3.58392e+06 | 0.242988 | 0.251073 | 0.00808497 |
| favorite_longshot_by_decile | weather_other | 30-40 | 81642 | 2.83904e+06 | 0.342526 | 0.333211 | -0.00931469 |
| favorite_longshot_by_decile | weather_other | 40-50 | 56715 | 1.75307e+06 | 0.442216 | 0.413894 | -0.0283218 |
| favorite_longshot_by_decile | weather_other | 50-60 | 39011 | 1.23668e+06 | 0.539559 | 0.49668 | -0.0428787 |
| favorite_longshot_by_decile | weather_other | 60-70 | 23525 | 758199 | 0.640485 | 0.587588 | -0.0528969 |
| favorite_longshot_by_decile | weather_other | 70-80 | 15988 | 835752 | 0.741413 | 0.705342 | -0.0360714 |
| favorite_longshot_by_decile | weather_other | 80-90 | 12176 | 615940 | 0.843398 | 0.75772 | -0.0856784 |
| favorite_longshot_by_decile | weather_other | 90-95 | 6310 | 420255 | 0.919463 | 0.833281 | -0.0861823 |
| favorite_longshot_by_decile | weather_other | 95-100 | 15516 | 2.0171e+06 | 0.97544 | 0.922467 | -0.0529731 |

## Top 20 Actionable Findings

- 1. Across settled trades, maker return is exactly the economic mirror of taker return before explicit fee modeling; use maker/taker side as an execution-cost prior, not as independent alpha.
- 2. Weather and non-weather have materially different calibration curves, so execution priors should be segmented by weather status.
- 3. Temperature markets are a distinct weather sub-family; do not blend KXHIGH execution behavior with generic weather headlines without checking the segment.
- 4. Longshot YES buckets remain the most important calibration area to stress-test because small price errors become large percentage return swings.
- 5. High-probability buckets need separate handling: they often look safe by win rate while retaining large tail loss if the settlement label flips.
- 6. Hour-of-day maker return varies enough to justify hour-specific fill/slippage assumptions in future backtests.
- 7. Weather-only hourly flow is not interchangeable with exchange-wide flow; use the weather slice for temperature policy studies.
- 8. Temperature-city series show different average maker returns and taker-YES shares, so city-specific execution priors are justified.
- 9. Trade size buckets are useful for fill-cost priors, but they are observed executions only; they do not reveal unfilled passive order probability.
- 10. Volume/open-interest bins are a cleaner liquidity regime proxy than static market-family labels alone.
- 11. VWAP by hour gives a robust price-state proxy when bid/ask history is unavailable.
- 12. Opening-to-later drift can be studied from executions, but should not be mistaken for a full orderbook replay.
- 13. Settlement labels are available for return calculations only after filtering markets.result to yes/no; active blank labels must remain excluded.
- 14. Weather temperature analysis is now large enough for microstructure research: millions of observed trades across the KXHIGH city series.
- 15. KXHIGHNY is only one city slice; cross-city conclusions require city fixed effects or separate priors.
- 16. The atlas should feed the fill model as priors by price bucket, hour, weather flag, and city, not as direct live strategy rules.
- 17. Any apparent edge in maker returns is gross of Kalshi fees; fee-adjusted tables belong in the fill-model phase.
- 18. Deep-tail policy research should use the 00-05, 05-10, and 90-100 buckets separately rather than one broad tail group.
- 19. Taker-YES share is a useful order-flow feature for the weather mart and should be retained for later policy studies.
- 20. This atlas is statistically interesting, not live-ready. It informs execution assumptions and candidate policies only.

## Caveats

- These are observed executions, not unfilled quote logs. Passive maker fill probability remains partially unobserved.
- Returns are gross of explicit Kalshi fees in this phase. Fee-aware execution modeling comes later.
- Market bid/ask snapshots in Becker `markets` are not treated as point-in-time orderbook history.
- Strong microstructure slices are research priors, not live-trading instructions.
