# Polymarket Risk and Capital Efficiency

Generated: 2026-04-26T15:06:58.318990-04:00

## Scope

Research-only. Capital efficiency is inferred from observed public executions only. True inventory, collateral usage, unfilled orders, netting, split/merge/redeem, and drawdown are partially or fully unobservable.

## Strongest Capital Recycling Proxies

| user_name | trades | active_days | turnover_notional_proxy | notional_per_active_day | max_concurrent_market_count_proxy |
| --- | --- | --- | --- | --- | --- |
| KingZeManel | 3410 | 8 | 741893.6030666869 | 92736.70038333586 | 118 |
| OraculumNobius | 1477 | 9 | 798417.6421434536 | 88713.07134927262 | 54 |
| largeleeks888 | 3197 | 20 | 1262064.5189228258 | 63103.22594614129 | 99 |
| HondaCivic | 3412 | 18 | 796597.6721713747 | 44255.42623174304 | 63 |
| Dreamer3bcbcd6c | 3040 | 10 | 417779.92922829575 | 41777.99292282957 | 82 |
| ColdMath | 3141 | 3 | 99406.5060446428 | 33135.502014880934 | 48 |
| meropi | 1641 | 10 | 284553.9571094711 | 28455.39571094711 | 26 |
| NoonienSoong | 3298 | 62 | 1146113.8509133135 | 18485.70727279538 | 35 |

## Concentration Proxies

| user_name | top_event_notional_share_pct | top_market_notional_share_pct | event_notional_gini | market_notional_gini |
| --- | --- | --- | --- | --- |
| cry.eth2 | 88.13523897520565 | 65.90098733928671 | 0.8672518712397095 | 0.8875339907396911 |
| planktonXD | 34.12839406554206 | 30.948415726584344 | 0.6275208554538942 | 0.6443464302347506 |
| IsabelaEstrellaPaz | 26.801606436560494 | 12.563024097579653 | 0.5547917719568232 | 0.5460593522654253 |
| Poligarch | 15.590198195512508 | 8.804028667636752 | 0.6068011202089589 | 0.6723394146683661 |
| oVyg7f | 15.099461692447893 | 6.568155502557295 | 0.7372727561684496 | 0.8863193785122989 |
| meropi | 13.480622904258537 | 7.937401915062531 | 0.6009242717097927 | 0.6184149502716212 |
| ColdMath | 12.989438353849453 | 12.916160950965999 | 0.7004917411087466 | 0.7220068968713882 |
| VibeTrader | 10.936311861812413 | 10.936311861812415 | 0.6327544303588823 | 0.771875341727063 |

## Ladder Usage Proxies

| user_name | same_event_ladder_median_markets | same_event_ladder_p95_markets | repeat_trade_market_share_pct | scale_in_out_proxy_pct |
| --- | --- | --- | --- | --- |
| oVyg7f | 10.0 | 11.0 | 53.48542458808618 | 23.954372623574145 |
| IsabelaEstrellaPaz | 3.0 | 9.2 | 92.42424242424242 | 75.75757575757575 |
| cry.eth2 | 1.0 | 8.549999999999999 | 42.857142857142854 | 0.0 |
| dpnd | 5.0 | 8.0 | 79.76653696498055 | 19.455252918287936 |
| TENETENET | 3.0 | 7.0 | 52.036199095022624 | 0.22624434389140272 |
| Poligarch | 4.0 | 6.200000000000003 | 80.39867109634551 | 0.0 |
| meropi | 2.0 | 6.0 | 91.30434782608695 | 1.4492753623188406 |
| VibeTrader | 2.0 | 5.0 | 78.67647058823529 | 51.470588235294116 |

## Observed / Estimated / Unobservable

- Observed: trade size, trade price, event/market concentration, repeated market activity, same-event multi-market usage.
- Estimated: capital recycling speed, max concurrent market count, scale-in/scale-out behavior, ladder intensity.
- Unobservable: true wallet inventory path, passive order miss rate, queue position, collateral usage, complete PnL path, redeem/split behavior if not exposed by this API slice.
