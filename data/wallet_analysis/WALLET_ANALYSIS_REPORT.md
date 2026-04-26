# TOP POLYMARKET WEATHER WALLET ANALYSIS REPORT

Generated: 2026-04-26T17:39:40.472645-04:00

Wallets analyzed: gopfan2, aenews2, ColdMath, Hans323, bama124, automatedAItradingbot, WeatherTraderBot, BigMike11, gopfan, Kapii

Total weather trades analyzed: 223,648

Date range: 2024-09-30 to 2026-04-26

## Scope And Evidence Quality

This report is research-only. It uses public Polymarket Data API activity/trade-tape data when available and local public Phase 1 artifacts as fallback. The public Polymarket API can still be capped or incomplete, so durable 24-month alpha claims are not made here. Maker/passive fill truth, unfilled orders, queue position, and exact historical spread are not recoverable from these public retrospective artifacts.

Polymarket NYC weather markets are treated as KLGA-like for diagnostics, while our Kalshi pipeline settles KXHIGHNY on KNYC. The `2.5F` station correction is a diagnostic bridge, not exchange settlement truth.

## DATA COVERAGE

| wallet | trade_count | resolved_trades | win_rate | date_start | date_end | city_counts | market_count | event_count | median_entry_price | mean_entry_price | pct_price_lt_15c | pct_price_gt_90c | avg_notional | max_notional | size_gap_corr | median_hold_hours | hold_to_settlement_proxy_rate | dominant_bracket_type | dominant_hour |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ColdMath | 173813 | 173527 | 0.4097 | 2025-12-03 | 2026-04-26 | {"NYC": 13002, "LON": 5640, "OTHER": 86552, "MIA": 10088, "DAL": 13034, "ATL": 13391, "SEA": 3252, "CHI": 10096, "PAR": 4612, "TOK": 10748, "LAX": 1199, "DEN": 2199} | 6363 | 2082 | 0.0790 | 0.4047 | 0.5751 | 0.3478 | 33.48 | 22238.33 | -0.1650 | 9.62 | 0.9446 | central | 3 |
| Hans323 | 18917 | 18872 | 0.4625 | 2025-01-26 | 2026-04-21 | {"LON": 10107, "NYC": 8246, "OTHER": 313, "MIA": 20, "LAX": 1, "SEA": 69, "DEN": 2, "ATL": 94, "DAL": 28, "PAR": 30, "TOK": 7} | 2214 | 672 | 0.2000 | 0.4353 | 0.4635 | 0.3128 | 155.21 | 34965.00 | -0.2281 | 1.12 | 0.4569 | central | 8 |
| automatedAItradingbot | 14705 | 14582 | 0.1273 | 2025-02-02 | 2026-04-25 | {"NYC": 5538, "LON": 5575, "OTHER": 2887, "ATL": 18, "SEA": 14, "CHI": 29, "MIA": 120, "DAL": 60, "PAR": 131, "TOK": 314, "DEN": 19} | 1885 | 690 | 0.0130 | 0.1014 | 0.8309 | 0.0257 | 9.52 | 5078.44 | -0.1884 | 2.04 | 0.5475 | central | 10 |
| WeatherTraderBot | 6988 | 6929 | 0.2986 | 2024-11-28 | 2026-03-24 | {"NYC": 2784, "OTHER": 1462, "LON": 2705, "SEA": 36, "DAL": 1} | 930 | 372 | 0.0600 | 0.2374 | 0.6162 | 0.0653 | 63.12 | 14813.22 | -0.1541 | 9.61 | 0.6956 | central | 5 |
| gopfan2 | 4923 | 4255 | 0.5093 | 2024-10-01 | 2026-04-21 | {"OTHER": 4919, "NYC": 4} | 102 | 39 | 0.3500 | 0.4247 | 0.2878 | 0.1381 | 294.53 | 31808.00 |  | 96.65 | 0.4599 | central | 8 |
| aenews2 | 2240 | 2240 | 0.6772 | 2024-10-01 | 2026-04-03 | {"OTHER": 2238, "CHI": 2} | 111 | 36 | 0.9740 | 0.6706 | 0.2580 | 0.5929 | 2301.00 | 169828.02 |  | 95.08 | 0.7953 | central | 9 |
| Kapii | 1897 | 1897 | 0.5061 | 2024-10-04 | 2025-12-30 | {"OTHER": 1897} | 53 | 24 | 0.4400 | 0.4861 | 0.2388 | 0.2457 | 296.84 | 54803.45 |  | 235.40 | 0.4024 | central | 12 |
| BigMike11 | 165 | 165 | 1.00 | 2024-09-30 | 2024-10-17 | {"OTHER": 165} | 2 | 2 | 0.9820 | 0.9834 | 0.0000 | 1.00 | 272.92 | 9880.00 |  | 13.37 | 0.0000 | central | 10 |

## FINDING 1: WHAT PRICE DO TOP WALLETS ACTUALLY ENTER AT?

| price_bucket | trade_count | resolved | win_rate | avg_entry_price | median_entry_price | avg_size | pct |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 00-10c | 120252 | 120128 | 0.0199 | 0.0364 | 0.0360 | 1.20 | 0.5377 |
| 90-100c | 71116 | 71062 | 0.9923 | 0.9606 | 0.9600 | 204.44 | 0.3180 |
| 10-20c | 11250 | 10933 | 0.2164 | 0.1345 | 0.1300 | 10.58 | 0.0503 |
| 80-90c | 6101 | 6045 | 0.8991 | 0.8544 | 0.8600 | 83.34 | 0.0273 |
| 20-30c | 3605 | 3478 | 0.2967 | 0.2408 | 0.2478 | 37.69 | 0.0161 |
| 30-40c | 2604 | 2343 | 0.3833 | 0.3395 | 0.3400 | 99.19 | 0.0116 |
| 70-80c | 2555 | 2535 | 0.8284 | 0.7404 | 0.7400 | 102.12 | 0.0114 |
| 50-60c | 2122 | 2067 | 0.6522 | 0.5300 | 0.5200 | 85.40 | 0.0095 |
| 60-70c | 2116 | 2091 | 0.7379 | 0.6444 | 0.6500 | 121.83 | 0.0095 |
| 40-50c | 1927 | 1785 | 0.5255 | 0.4442 | 0.4471 | 74.70 | 0.0086 |

Winner by resolved win rate among populated price buckets: 90-100c.

gopfan2 confirmed rule: 33.6% of fetched gopfan2 YES trades were below 15c (3,919 YES trades in this slice).

ColdMath confirmed rule: 100.0% of fetched ColdMath NO entries above 90c token price in the deep-tail proxy set (52,939 trades).

Combined top-wallet median entry price: 7.9c.

OUR PIPELINE IMPLICATION: add research/paper diagnostics for extreme-price behavior instead of forcing top-wallet patterns through the 25c-75c Kalshi core gate.

## FINDING 2: WHAT TIME OF DAY DO TOP WALLETS TRADE?

| trade_hour_et | trade_count | resolved | win_rate | avg_entry_price | median_entry_price | avg_size |
| --- | --- | --- | --- | --- | --- | --- |
| 0.0000 | 2149.00 | 2117.00 | 0.4133 | 0.3874 | 0.0700 | 182.66 |
| 1.00 | 1733.00 | 1714.00 | 0.2987 | 0.2873 | 0.0500 | 281.04 |
| 2.00 | 14227.00 | 14206.00 | 0.3834 | 0.3690 | 0.0690 | 54.78 |
| 3.00 | 35466.00 | 35300.00 | 0.4070 | 0.4066 | 0.0710 | 30.42 |
| 4.00 | 19754.00 | 19661.00 | 0.3662 | 0.3553 | 0.0680 | 45.65 |
| 5.00 | 13184.00 | 13150.00 | 0.3667 | 0.3616 | 0.0640 | 60.31 |
| 6.00 | 13574.00 | 13509.00 | 0.3994 | 0.3793 | 0.0940 | 87.28 |
| 7.00 | 10779.00 | 10711.00 | 0.3985 | 0.3812 | 0.1070 | 78.66 |
| 8.00 | 7162.00 | 7124.00 | 0.4064 | 0.3768 | 0.1040 | 116.23 |
| 9.00 | 8448.00 | 8415.00 | 0.3928 | 0.3743 | 0.0790 | 78.92 |
| 10.00 | 9608.00 | 9583.00 | 0.4238 | 0.4043 | 0.0890 | 119.22 |
| 11.00 | 10310.00 | 10256.00 | 0.4014 | 0.3906 | 0.0990 | 81.23 |
| 12.00 | 9951.00 | 9908.00 | 0.4089 | 0.4017 | 0.0870 | 80.42 |
| 13.00 | 9888.00 | 9741.00 | 0.4107 | 0.4018 | 0.1200 | 69.35 |
| 14.00 | 10050.00 | 9980.00 | 0.4158 | 0.3903 | 0.0990 | 77.82 |
| 15.00 | 9665.00 | 9613.00 | 0.4230 | 0.4084 | 0.0810 | 86.58 |
| 16.00 | 10860.00 | 10819.00 | 0.3950 | 0.3874 | 0.0780 | 83.76 |
| 17.00 | 10137.00 | 10120.00 | 0.3792 | 0.3742 | 0.0790 | 49.17 |
| 18.00 | 9227.00 | 9210.00 | 0.4307 | 0.4213 | 0.0770 | 65.77 |
| 19.00 | 3539.00 | 3508.00 | 0.4558 | 0.4424 | 0.0960 | 131.94 |
| 20.00 | 1308.00 | 1290.00 | 0.4186 | 0.3806 | 0.1100 | 322.33 |
| 21.00 | 862.00 | 825.00 | 0.3455 | 0.3295 | 0.0715 | 170.06 |
| 22.00 | 786.00 | 750.00 | 0.3440 | 0.3005 | 0.0500 | 309.12 |
| 23.00 | 981.00 | 957.00 | 0.2863 | 0.2799 | 0.0620 | 205.83 |

Peak entry hour: 3:00 ET (35,466 trades, 40.7% win rate).

Highest observed win-rate hour: 19:00 ET (3,539 trades, 45.6% win rate).

Pre-12Z model (before 1PM): 39.4% win rate across 156,345 trades.

Post-12Z model (after 1PM): 40.8% win rate across 67,303 trades.

Best hour for our pipeline to investigate in paper: 19:00 ET, but do not change live timing from this retrospective slice alone.

OUR PIPELINE IMPLICATION: track hour-of-entry and pre/post-12Z as paper analytics; do not move live 11AM/9AM research timing until Kalshi-specific forward paper data supports it.

## FINDING 3: WHICH BRACKET TYPES DO THEY PREFER?

| bracket_type | trade_count | resolved | win_rate | avg_entry_price | median_entry_price | avg_size | pct |
| --- | --- | --- | --- | --- | --- | --- | --- |
| central | 167825 | 166806 | 0.4017 | 0.3901 | 0.0800 | 72.17 | 0.7504 |
| upper_tail | 32294 | 32237 | 0.3798 | 0.3625 | 0.0690 | 69.18 | 0.1444 |
| lower_tail | 23390 | 23388 | 0.3969 | 0.3918 | 0.0690 | 93.62 | 0.1046 |
|  | 103 | 0 |  | 0.4628 | 0.4900 | 74.19 | 0.0005 |
| unknown | 36 | 36 | 0.8889 | 0.5813 | 0.5900 | 162.92 | 0.0002 |

Wing/tail brackets: 24.9% of all trades, 38.7% win rate.

Central brackets: 75.0% of all trades, 40.2% win rate.

OUR PIPELINE IMPLICATION: keep central and wing/tail analytics separate; do not summarize them as one weather edge.

## FINDING 4: DO THEY BUY THE DIP OR THE MOMENTUM?

| trend_direction | trade_count | resolved | win_rate | avg_entry_price | median_entry_price | avg_size |
| --- | --- | --- | --- | --- | --- | --- |
| unknown | 135744 | 135582 | 0.4015 | 0.3904 | 0.0790 | 38.19 |
| falling | 39036 | 38940 | 0.1649 | 0.1647 | 0.0430 | 14.44 |
| flat | 29549 | 28752 | 0.4766 | 0.4475 | 0.1600 | 223.16 |
| rising | 19319 | 19193 | 0.7294 | 0.7119 | 0.9250 | 217.79 |

Trades entering on falling price: 39,036 (16.5% win rate).

Trades entering on rising price: 19,319 (72.9% win rate).

OUR PIPELINE IMPLICATION: add pre-entry trend direction as a research feature and paper-report field. It is descriptive here, not a proven causal alpha signal.

## FINDING 5: WHAT GAP DO THEY REQUIRE BEFORE ENTERING?

| gap_bucket | trade_count | resolved | win_rate | avg_entry_price | median_entry_price | avg_size |
| --- | --- | --- | --- | --- | --- | --- |
| unknown | 194629 | 193448 | 0.4068 | 0.3997 | 0.0790 | 76.93 |
| 25+pp | 13413 | 13413 | 0.4476 | 0.4236 | 0.2040 | 85.60 |
| <10pp | 12558 | 12558 | 0.1715 | 0.1545 | 0.0310 | 21.65 |
| 10-15pp | 1560 | 1560 | 0.5872 | 0.2835 | 0.1300 | 56.40 |
| 15-20pp | 1000 | 1000 | 0.5480 | 0.3386 | 0.1700 | 32.69 |
| 20-25pp | 488 | 488 | 0.5164 | 0.4303 | 0.3572 | 72.38 |

Median gap at entry for NYC rows with reconstructed weather context: -1.08pp.

Our 20pp threshold vs actual top-wallet behavior: only NYC rows with bracket metadata and local KNYC/KLGA forecast context can be scored. The wallet dataset is Polymarket/KLGA-like, so it should not override the frozen Kalshi 20pp threshold.

OUR PIPELINE IMPLICATION: keep the 20pp live threshold frozen; use gap buckets to study missed paper candidates rather than changing production rules.

## FINDING 6: HOW LONG DO THEY HOLD?

| hold_category | trade_count | resolved | win_rate | avg_entry_price | avg_exit_price | avg_return | median_hold_hours |
| --- | --- | --- | --- | --- | --- | --- | --- |
| settlement_or_open | 184222 | 183506 | 0.3745 | 0.3699 |  | 0.0045 |  |
| intraday | 14893 | 14815 | 0.4362 | 0.3729 | 0.4406 | 0.0638 | 1.53 |
| day_trade | 6650 | 6634 | 0.6533 | 0.5798 | 0.6590 | 0.0733 | 9.78 |
| settlement | 4482 | 4274 | 0.6640 | 0.5601 | 0.6428 | 0.0857 | 103.58 |
| overnight | 2068 | 2061 | 0.7763 | 0.6934 | 0.7752 | 0.0815 | 31.83 |

ColdMath holds to settlement/open proxy: 94.5%.

gopfan2 average hold: 220.25 hours.

OUR PIPELINE IMPLICATION: keep recording open/close lifecycle in our own logs; public wallet data can infer holds only when both BUY and SELL appear in the captured slice.

## FINDING 7: COLDMATH DEEP TAIL NO ANALYSIS

ColdMath enters NO when token price is >90c in 52,939 fetched deep-tail proxy rows.

Our Gumbel model probability on ColdMath deep-tail proxy rows has median 0.101; coverage is 2,862/52,939 because only NYC rows can use our local forecast file.

Win rate: 99.4%.

OUR DEEP_TAIL_NO threshold (current research sleeve P_yes < 2%) vs ColdMath actual: keep the current strict threshold; this slice supports deep-tail monitoring but not direct copy-trading.

## FINDING 8: DAYS WE MISSED THAT TOP WALLETS CAUGHT

Top wallets traded 69 NYC days where our bot did NOT trade in the local backtest join.

Our gap_pp on those days averaged 4.79pp across all scored NYC wallet rows.

Those missed day rows had 38.5% win rate for top wallets.

If we had traded at a lower Polymarket-derived threshold, this report cannot honestly estimate captured P&L because station, market structure, and fees differ.

OUR PIPELINE IMPLICATION: create a paper-only missed-day watchlist instead of lowering the live gap threshold.

## FINDING 9: DAYS WE BOTH TRADED

Overlap days: 369.

Top wallet average entry price on overlap days: 6.5c.

Our average entry price on overlap days: 54.8c.

Price difference: top wallets got better fills by 48.3c average.

Our win rate on overlap days: 88.1%.

Top wallet win rate on overlap days: 85.9%.

## FINDING 10: WHAT MARKET CONDITIONS TRIGGER TOP WALLET ENTRIES?

Top wallets enter when:

- YES/token price is below 15c on 57.1% of entries.
- Market activity in the prior 6h averages 19.84 trades/hour.
- Price trend is most often `unknown` (60.7% of entries).
- Model consensus is 45.31F from bracket center on average for scored NYC rows.
- They avoid, or at least do not appear in this slice during, 3 calendar days between the first and last captured trade date.

## TOP 5 ACTIONABLE CHANGES FOR OUR KALSHI PIPELINE

1. Keep the 20pp live threshold frozen; use this wallet analysis only as research because the public Polymarket slice is incomplete and station-settlement differs from Kalshi.
2. Add paper/research diagnostics for entry price bucket and extreme-price wallet behavior; top-wallet behavior often concentrates at <15c or >90c, which is structurally different from our 25c-75c core band.
3. Separate central/range brackets from tails in research reports and paper policy; bracket-type win rates and entry prices differ enough that one rule set hides the real behavior.
4. Track pre-entry price trend and local market activity before paper entries; wallet trades can be bucketed as rising, falling, or flat using the public tape, and that is missing from the live signal explanation layer.
5. Do not copy Polymarket NYC trades directly into KXHIGHNY; Polymarket station proxy is KLGA while Kalshi settles KNYC, so keep the +2.5F station-difference diagnostic before comparing gaps.

Each recommendation above is research/paper-first. None is strong enough by itself to modify live execution, the LaunchAgent, `main.py`, `event_triggers.py`, or the frozen 20pp live threshold.
