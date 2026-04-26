# Polymarket Weather Trader Phase 1 Collection

Generated: 2026-04-26T14:07:16.800730-04:00
Window: 2024-04-26T13:57:25.940765-04:00 to 2026-04-26T13:57:25.940765-04:00

## APIs Used

- Leaderboard: `https://data-api.polymarket.com/v1/leaderboard` with `{'category': 'WEATHER', 'timePeriod': 'ALL', 'orderBy': 'VOL', 'limit': 20, 'offset': 0}`
- Trades: `https://data-api.polymarket.com/trades` with `user`, `limit=500`, `offset`, `takerOnly=false`
- Market metadata: `https://gamma-api.polymarket.com/markets?condition_ids=<conditionId>`

## Important Limitations

- The leaderboard supports `DAY`, `WEEK`, `MONTH`, and `ALL`, but not an exact 24-month ranking window. Phase 1 seeds from all-time weather volume, then filters fetched trades to the last 24 months.
- The public Data API currently caps historical trade pagination around offset 3000; wallets marked `reached_api_offset_cap=True` may have additional older trades not collected here.
- Settlement inference uses Gamma `closed` plus near-1.0 `outcomePrices`; unresolved/open markets remain null.

## Top 20 Weather Traders by Polymarket Leaderboard Volume

| rank | userName | proxyWallet | vol | pnl | weather_trades_24m | raw_trades_fetched | reached_api_offset_cap |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | largeleeks888 | 0x57dedd62596dd4f85c7ebe5317e07d22795ecd90 | 12283841.022946002 | -16020.683410497431 | 3204 | 3500 | True |
| 2 | planktonXD | 0x4ffe49ba2a4cae123536a8af4fda48faeb609f71 | 10704532.668061 | -375.6339465867323 | 76 | 3500 | True |
| 3 | aenews2 | 0x44c1dfe43260c94ed4f1d00de2e1f80fb113ebc1 | 9972308.555525 | 277050.178424862 | 0 | 3500 | True |
| 4 | IsabelaEstrellaPaz | 0x8b761995bbde7278a2f536b415fb5f60815fc036 | 8976660.852813 | 711.5344004969999 | 2049 | 3500 | True |
| 5 | ColdMath | 0x594edb9112f526fa6a80b8f858a6379c8a2c1c11 | 8909540.131665 | 122840.04157844154 | 3152 | 3500 | True |
| 6 | dpnd | 0x5f211a24da4c005d9438a1ea269673b85ed0b376 | 8397979.082362 | 22274.727885363067 | 3483 | 3500 | True |
| 7 | KingZeManel | 0x7bff96579b20fe3530e140d6a3c223c9f2127cd6 | 7395578.015284001 | -11011.712909895976 | 3410 | 3500 | True |
| 8 | VibeTrader | 0xcbbc5e035504421b084ad9248b660f6e9618b5d0 | 7073022.663024002 | 11818.438724076395 | 3499 | 3500 | True |
| 9 | TENETENET | 0x3329cfc2b8d8ceb8d198f081bdf4262f421f43a6 | 7019431.887999999 | 2688.020991999973 | 2159 | 3500 | True |
| 10 | Hans323 | 0x0f37cb80dee49d55b5f6d9e595d52591d6371410 | 6971546.614699 | 80872.36773858605 | 1971 | 3500 | True |
| 11 | meropi | 0x9977760c6bd6f824cac834d1a36ee99478d63020 | 6509549.770689 | 21632.90701090127 | 1641 | 3500 | True |
| 12 | HondaCivic | 0x15ceffed7bf820cd2d90f90ea24ae9909f5cd5fa | 6456192.12288 | 56319.11386720304 | 3499 | 3500 | True |
| 13 | Poligarch | 0xb40e89677d59665d5188541ad860450a6e2a7cc9 | 6193817.155182 | 50358.6351379749 | 3432 | 3500 | True |
| 14 | 0x3d3869cf51cf429b5f7f00f5a299f69edb3ce6ed | 0x3d3869cf51cf429b5f7f00f5a299f69edb3ce6ed | 5949260.936663036 | -456.50847006592903 | 0 | 3500 | True |
| 15 | 0x04011eeb35d62f9cc002b600c5ad83378c6d2bbc | 0x04011eeb35d62f9cc002b600c5ad83378c6d2bbc | 5949047.2872080365 | -224.77598685570797 | 0 | 3500 | True |
| 16 | OraculumNobius | 0xd25b8718f61fb64a754356ad8cf16b5579f59f3d | 5712895.599876999 | 1108.905818720572 | 1477 | 3500 | True |
| 17 | oVyg7f | 0x5f390e4b7d6f06d6756a6c92afdbf7b3176aa78c | 5697984.909916 | 18379.991602257352 | 2363 | 3500 | True |
| 18 | cry.eth2 | 0xe3726a1b9c6ba2f06585d1c9e01d00afaedaeb38 | 5673606.608399001 | 5458.1388348425335 | 141 | 3500 | True |
| 19 | NoonienSoong | 0x38cc1d1f95d12039324809d8bb6ca6da6cbef88e | 5515280.274522999 | 30306.312092115262 | 3298 | 3500 | True |
| 20 | Dreamer3bcbcd6c | 0xd28021317c1be36239e8d930dee7d6c3a40082b3 | 5251340.716405001 | 9687.680943807438 | 3061 | 3500 | True |

## Output Files

- `data/research/polymarket_top_weather_traders.csv`
- `data/research/polymarket_trades_raw.parquet`
- `data/research/polymarket_market_outcomes.parquet`
- `data/research/polymarket_phase1_summary.json`
