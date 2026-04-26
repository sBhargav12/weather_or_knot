# Weather Mart Data Dictionary

Research-only Phase 2 mart for Kalshi KXHIGH daily high-temperature markets.

## Canonical Row Definition

one row per ticker x hourly decision_time_et with at least one trade in the trailing 60 minutes.

Market state is derived from trailing executions. Becker market parquet bid/ask fields are latest metadata snapshots, not historical orderbook snapshots, so Phase 2 leaves bid/ask and spread fields null to avoid leakage.

## Coverage

- Rows: 288,707
- Unique tickers: 15,468
- Unique event tickers: 2,722
- Rows with Kalshi settlement labels: 287,340
- Target dates: 2024-10-24 00:00:00 to 2025-11-24 00:00:00
- Decision hours ET: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]
- Cities: {'AUS': 2298, 'CHI': 2290, 'DEN': 2152, 'HOU': 372, 'LAX': 1842, 'MIA': 2147, 'NYC': 2288, 'PHIL': 2079}

## Fields

### Identity/time

| Field | dtype | Description |
|---|---|---|
| `ticker` | `object` | Kalshi market ticker. |
| `event_ticker` | `object` |  |
| `target_date_et` | `datetime64[us]` |  |
| `city` | `object` |  |
| `bracket_type` | `object` |  |
| `bracket_lo_f` | `float64` |  |
| `bracket_hi_f` | `float64` |  |
| `decision_time_et` | `datetime64[us, America/New_York]` | Hourly decision timestamp ending a trailing trade-flow window. |
| `decision_hour_et` | `int64` |  |
| `hours_to_close` | `float64` |  |

### Market state

| Field | dtype | Description |
|---|---|---|
| `yes_bid` | `float64` | Null in Phase 2 because Becker market bid snapshots are not point-in-time. |
| `yes_ask` | `float64` |  |
| `no_bid` | `float64` |  |
| `no_ask` | `float64` |  |
| `last_price` | `float64` | Latest prior YES trade price in the trailing 60-minute decision window, as 0-1 fraction. |
| `implied_mid_yes` | `float64` | Phase 2 proxy equal to last trade price; true point-in-time orderbook midpoint is unavailable. |
| `spread_yes` | `float64` |  |
| `spread_no` | `float64` |  |
| `open_interest` | `int64` |  |
| `volume` | `int64` |  |
| `volume_24h` | `int64` |  |
| `recent_trade_count_15m` | `int64` |  |
| `recent_trade_count_60m` | `int64` |  |
| `recent_signed_flow_15m` | `float64` |  |
| `recent_signed_flow_60m` | `float64` |  |
| `taker_yes_share_15m` | `float64` |  |
| `taker_yes_share_60m` | `float64` |  |
| `vwap_yes_15m` | `float64` |  |
| `vwap_yes_60m` | `float64` |  |
| `price_change_15m` | `float64` |  |
| `price_change_60m` | `float64` |  |
| `realized_vol_60m` | `float64` |  |

### Weather/fair-value state

| Field | dtype | Description |
|---|---|---|
| `consensus_temp_f` | `float64` |  |
| `model_spread_f` | `float64` |  |
| `physics_mean_f` | `float64` |  |
| `ai_mean_f` | `float64` |  |
| `spread_between_f` | `float64` |  |
| `prior_day_error_f` | `float64` |  |
| `morning_obs_f` | `float64` |  |
| `morning_vs_forecast_f` | `float64` |  |
| `regime_hgefs` | `int32` |  |
| `regime_aifs` | `int32` |  |
| `regime_nbm_v43` | `int32` |  |
| `regime_nbm_v50` | `int32` |  |
| `month` | `int64` |  |
| `is_peak_season` | `int32` |  |

### Label state

| Field | dtype | Description |
|---|---|---|
| `kalshi_result_yes` | `boolean` | Settlement label from Kalshi/Becker market result; this is the P&L truth field. |
| `settlement_source` | `object` |  |
| `actual_temp_f_diagnostic` | `float64` | External KNYC daily max diagnostic, NYC only; never P&L truth. |
| `settlement_mismatch_flag` | `object` |  |

### Decision state

| Field | dtype | Description |
|---|---|---|
| `model_prob_raw` | `float64` |  |
| `model_prob_calibrated` | `float64` | Reserved for later calibration phases; null in Phase 2 mart. |
| `market_price_yes` | `float64` |  |
| `edge_pp_raw` | `float64` |  |
| `edge_pp_calibrated` | `float64` |  |

### Audit/metadata

| Field | dtype | Description |
|---|---|---|
| `last_trade_time_et` | `datetime64[us, America/New_York]` |  |
| `open_time` | `datetime64[us, America/New_York]` |  |
| `close_time` | `datetime64[us, America/New_York]` |  |
| `status` | `object` |  |
| `result` | `object` |  |
| `title` | `object` |  |
| `market_metadata_fetched_at` | `datetime64[ns]` |  |
| `market_state_source` | `object` |  |
| `forecast_vintage_status` | `object` | Documents whether forecast data has true intraday vintage timestamps. |

## Known Phase 2 Limitations

- This is not a full orderbook-history mart. Bid/ask and spread fields remain null until a true point-in-time book source is available.
- Forecast features are currently NYC-only because local historical Open-Meteo/KNYC files cover KNYC. Other cities retain market/trade/label structure with null forecast fields.
- Open-Meteo historical rows are daily and do not carry real intraday model-run vintage timestamps. The mart labels this explicitly via `forecast_vintage_status`.
- `model_prob_calibrated` is intentionally null; calibration belongs to later research phases.
