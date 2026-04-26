# Polymarket Alpha Timing / Markout Analysis

Generated: 2026-04-26T15:06:51.216894-04:00

## Scope

Research-only. Markouts are trade-to-trade within the recent public Data API slice. They are not full orderbook paths, not passive fill truth, and not complete 24-month alpha proof.

## Data Coverage

- Trades analyzed: 41,709
- 60m markout coverage: 75.46%
- 1d markout coverage: 83.68%
- Settlement outcome coverage: 69.76%

## Best Timing Wallets by 60m Signed Markout

| user_name | provisional_archetype | trades | avg_1m_pp | avg_5m_pp | avg_60m_pp | avg_1d_pp | settlement_avg_pp |
| --- | --- | --- | --- | --- | --- | --- | --- |
| OraculumNobius | expiry / resolution specialist | 1477 | 75.19909703889056 | 75.3505961441103 | 74.33302202090373 | 74.49496883398383 | 0.1147941624565277 |
| Dreamer3bcbcd6c | expiry / resolution specialist | 3040 | 62.194618819411765 | 61.95452216536785 | 61.34671818948324 | 61.3666516132273 | 0.24845089779500626 |
| NoonienSoong | expiry / resolution specialist | 3298 | 60.18964891672722 | 60.305898359230525 | 59.72958208966633 | 59.50154328738635 | 0.10681466191481516 |
| meropi | expiry / resolution specialist | 1641 | 29.054214064453276 | 28.811655416187552 | 29.444488523545314 | 29.435307783828513 | -0.48569471064558556 |
| HondaCivic | expiry / resolution specialist | 3412 | 24.290187304214456 | 27.07139338742535 | 28.061187011385524 | 27.87891551896739 | 0.37732996505665084 |

## Worst Timing Wallets by 60m Signed Markout

| user_name | provisional_archetype | trades | avg_1m_pp | avg_5m_pp | avg_60m_pp | avg_1d_pp | settlement_avg_pp |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dpnd | ladder optimizer | 3483 | -91.2342543324433 | -90.83228436775325 | -88.97106387577236 | -88.71408470161076 | 1.4499990858226453 |
| TENETENET | ladder optimizer | 2159 | -76.16176535303497 | -76.8653011361333 | -75.1755647149568 | -75.25881653998077 | -0.09748427672955975 |
| VibeTrader | ladder optimizer | 3499 | -63.04618033152898 | -64.02766831849645 | -64.33508948984476 | -63.40451310220729 | -1.6831265072054784 |
| IsabelaEstrellaPaz | ladder optimizer | 2016 | -55.21219164402349 | -47.94828058934791 | -44.67004316436953 | -45.17046074758049 | -0.02668810289389068 |
| ColdMath | ladder optimizer | 3141 | -39.99906251320018 | -39.731052589661424 | -39.76427418356301 | -39.42984980321665 | -0.6697225919678244 |

## Timing by ET Hour

| hour_et | trades | avg_60m_pp | avg_1d_pp | settlement_avg_pp |
| --- | --- | --- | --- | --- |
| 23 | 1056 | 21.424146656959035 | 20.353822764781768 | -0.14949493724209353 |
| 14 | 1379 | 15.895631521520876 | 15.796593646848649 | 0.35750206385772254 |
| 21 | 1157 | 15.353757998292705 | 14.742697890694531 | -0.24245926960611602 |
| 18 | 1335 | 14.080985521413249 | 14.20234889504486 | -1.0602578076381164 |
| 22 | 1203 | 13.958242051963117 | 13.396305825758875 | -1.677294337784833 |
| 1 | 1224 | 9.539476665198853 | 5.168439532788492 | 0.16589528066905543 |
| 15 | 1602 | 9.516371797065833 | 10.159235906738022 | 0.5960087034305158 |
| 17 | 1349 | 3.806464906204446 | 4.722758631448719 | -0.16018528281697192 |
| 12 | 2742 | -0.20335189784596575 | -0.48647585601413357 | 0.9917058828061509 |
| 20 | 1058 | -1.0103797530266962 | -1.8977903744034723 | -1.248224181300468 |
| 10 | 2618 | -2.0221000339171877 | -3.940626209065236 | -0.07893304188705162 |
| 16 | 1690 | -4.886915895725878 | -4.135558986678368 | -0.29891663899099286 |

## Timing by Price Bucket

| price_bucket | trades | avg_60m_pp | avg_1d_pp | settlement_avg_pp |
| --- | --- | --- | --- | --- |
| 95-100 | 21270 | 35.289570255468426 | 34.33117647726723 | 0.2526897021643514 |
| 80-95 | 1323 | 30.2832902278643 | 32.08131667879296 | 6.0156285420353734 |
| 60-80 | 1047 | 29.25130731563259 | 30.151234802086613 | -1.9312707781909417 |
| 40-60 | 951 | 6.182658987956973 | 5.6315859093884875 | 0.7253116368030817 |
| 20-40 | 2430 | -39.23067325295073 | -37.720897109828314 | -4.302662585035944 |
| 10-20 | 1628 | -53.09670446059734 | -52.61875442516038 | -7.994768692461749 |
| 05-10 | 1562 | -58.64764309115562 | -58.68990454333444 | 1.7920611864000837 |
| 00-05 | 11498 | -61.75581991807476 | -61.784413214925465 | -0.3271019860365529 |

## Timing by Market/Bracket Family

| market_family | bracket_family | trades | avg_60m_pp | avg_1d_pp | settlement_avg_pp |
| --- | --- | --- | --- | --- | --- |
| other_weather | non_temperature_or_unknown | 13 | 92.30000000000001 | -22.499999999999996 | 0.04285714285714288 |
| snow | non_temperature_or_unknown | 4 | -0.7473924576045454 | -0.7473924576045454 | -9.79757813339061 |
| daily_temperature | exact_temp | 27322 | -2.3526362406029406 | -3.2635221256316576 | -0.371733576414031 |
| daily_temperature | range | 11736 | -8.972766080269816 | -9.29648239700996 | 0.6146628485610499 |
| daily_temperature | lower_tail | 2405 | -14.59774882167812 | -14.9505420338348 | -0.8068611065910055 |
| precipitation | range | 127 | -18.251193914045636 | -18.222876937752726 |  |
| precipitation | non_temperature_or_unknown | 87 | -18.602500633210447 | -16.587042533560812 | -5.143397557042789 |
| storm | non_temperature_or_unknown | 8 | -43.550000000000004 | -43.550000000000004 | -21.375 |
| macro_temperature | non_temperature_or_unknown | 7 | -58.80000000000001 | -60.650000000000006 |  |

## Interpretation

- Positive 60m markout means the next observed same-asset trade moved in the wallet's direction.
- Very high activity at extreme prices often produces small markouts but can still matter economically through settlement or ladder netting.
- Wallets with strong 60m markout but weak settlement are likely reactive/tactical rather than pure forecast-alpha traders.
- To distinguish true early alpha from price impact, Phase 4 needs eventual orderbook or subgraph backfill; current results are descriptive.
