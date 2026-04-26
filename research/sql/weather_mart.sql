-- Phase 2 research-only weather mart.
--
-- Canonical row definition:
--   one row per (ticker, hourly decision_time_et) for KXHIGH* temperature
--   markets with at least one trade in the trailing 60 minutes.
--
-- Important leakage guard:
--   Becker market parquet rows are one latest metadata row per ticker, not a
--   point-in-time orderbook history. Bid/ask columns are therefore left NULL in
--   the mart. Trade-derived fields provide the point-in-time market state.

CREATE OR REPLACE TEMP VIEW becker_markets AS
SELECT *
FROM read_parquet('{markets_glob}', union_by_name=true);

CREATE OR REPLACE TEMP VIEW becker_trades AS
SELECT *
FROM read_parquet('{trades_glob}', union_by_name=true);

CREATE OR REPLACE TEMP VIEW weather_markets AS
WITH parsed AS (
    SELECT
        ticker,
        event_ticker,
        market_type,
        title,
        yes_sub_title,
        no_sub_title,
        status,
        result,
        created_time,
        open_time,
        close_time,
        _fetched_at,
        volume,
        volume_24h,
        open_interest,
        regexp_extract(ticker, '^(KXHIGH(?:NY|CHI|AUS|MIA|DEN|PHIL|LAX|HOU))-', 1) AS series,
        regexp_extract(event_ticker, '-([0-9]{{2}}[A-Z]{{3}}[0-9]{{2}})$', 1) AS date_token,
        regexp_extract(title, 'be <([0-9]+)', 1) AS lower_tail_strike,
        regexp_extract(title, 'be >([0-9]+)', 1) AS upper_tail_strike,
        regexp_extract(title, 'be ([0-9]+)-([0-9]+)', 1) AS range_lo,
        regexp_extract(title, 'be ([0-9]+)-([0-9]+)', 2) AS range_hi
    FROM becker_markets
    WHERE regexp_matches(ticker, '^KXHIGH(NY|CHI|AUS|MIA|DEN|PHIL|LAX|HOU)-')
)
SELECT
    ticker,
    event_ticker,
    CASE series
        WHEN 'KXHIGHNY' THEN 'NYC'
        WHEN 'KXHIGHCHI' THEN 'CHI'
        WHEN 'KXHIGHAUS' THEN 'AUS'
        WHEN 'KXHIGHMIA' THEN 'MIA'
        WHEN 'KXHIGHDEN' THEN 'DEN'
        WHEN 'KXHIGHPHIL' THEN 'PHIL'
        WHEN 'KXHIGHLAX' THEN 'LAX'
        WHEN 'KXHIGHHOU' THEN 'HOU'
    END AS city,
    series,
    strptime(date_token, '%y%b%d')::DATE AS target_date_et,
    CASE
        WHEN lower_tail_strike != '' THEN 'lower_tail'
        WHEN upper_tail_strike != '' THEN 'upper_tail'
        ELSE 'central'
    END AS bracket_type,
    CASE
        WHEN range_lo != '' THEN range_lo::DOUBLE
        WHEN upper_tail_strike != '' THEN upper_tail_strike::DOUBLE
        ELSE NULL
    END AS bracket_lo_f,
    CASE
        WHEN range_hi != '' THEN range_hi::DOUBLE
        WHEN lower_tail_strike != '' THEN lower_tail_strike::DOUBLE
        ELSE NULL
    END AS bracket_hi_f,
    market_type,
    title,
    yes_sub_title,
    no_sub_title,
    status,
    result,
    CASE
        WHEN result = 'yes' THEN TRUE
        WHEN result = 'no' THEN FALSE
        ELSE NULL
    END AS kalshi_result_yes,
    created_time AS market_created_time,
    open_time,
    close_time,
    _fetched_at AS market_metadata_fetched_at,
    volume AS market_metadata_volume,
    volume_24h AS market_metadata_volume_24h,
    open_interest AS market_metadata_open_interest
FROM parsed
WHERE date_token != '';

CREATE OR REPLACE TEMP VIEW weather_trades AS
SELECT
    t.trade_id,
    t.ticker,
    t.count,
    t.yes_price / 100.0 AS yes_price_frac,
    t.no_price / 100.0 AS no_price_frac,
    t.taker_side,
    t.created_time,
    t._fetched_at
FROM becker_trades t
INNER JOIN weather_markets m USING (ticker);

CREATE OR REPLACE TEMP VIEW decision_times AS
SELECT
    ticker,
    date_trunc('hour', created_time) + INTERVAL 1 HOUR AS decision_time_et
FROM weather_trades
GROUP BY 1, 2;

CREATE OR REPLACE TEMP VIEW trade_features AS
SELECT
    d.ticker,
    d.decision_time_et,
    COUNT(*) FILTER (
        WHERE t.created_time > d.decision_time_et - INTERVAL 15 MINUTE
          AND t.created_time <= d.decision_time_et
    ) AS recent_trade_count_15m,
    COUNT(*) AS recent_trade_count_60m,
    COALESCE(SUM(CASE WHEN t.taker_side = 'yes' THEN t.count ELSE -t.count END) FILTER (
        WHERE t.created_time > d.decision_time_et - INTERVAL 15 MINUTE
          AND t.created_time <= d.decision_time_et
    ), 0) AS recent_signed_flow_15m,
    COALESCE(SUM(CASE WHEN t.taker_side = 'yes' THEN t.count ELSE -t.count END), 0) AS recent_signed_flow_60m,
    COALESCE(
        SUM(CASE WHEN t.taker_side = 'yes' THEN t.count ELSE 0 END) FILTER (
            WHERE t.created_time > d.decision_time_et - INTERVAL 15 MINUTE
              AND t.created_time <= d.decision_time_et
        )
        / NULLIF(SUM(t.count) FILTER (
            WHERE t.created_time > d.decision_time_et - INTERVAL 15 MINUTE
              AND t.created_time <= d.decision_time_et
        ), 0),
        NULL
    ) AS taker_yes_share_15m,
    SUM(CASE WHEN t.taker_side = 'yes' THEN t.count ELSE 0 END) / NULLIF(SUM(t.count), 0) AS taker_yes_share_60m,
    SUM(t.yes_price_frac * t.count) FILTER (
        WHERE t.created_time > d.decision_time_et - INTERVAL 15 MINUTE
          AND t.created_time <= d.decision_time_et
    ) / NULLIF(SUM(t.count) FILTER (
        WHERE t.created_time > d.decision_time_et - INTERVAL 15 MINUTE
          AND t.created_time <= d.decision_time_et
    ), 0) AS vwap_yes_15m,
    SUM(t.yes_price_frac * t.count) / NULLIF(SUM(t.count), 0) AS vwap_yes_60m,
    (
        arg_max(t.yes_price_frac, t.created_time) FILTER (
            WHERE t.created_time > d.decision_time_et - INTERVAL 15 MINUTE
              AND t.created_time <= d.decision_time_et
        )
        - arg_min(t.yes_price_frac, t.created_time) FILTER (
            WHERE t.created_time > d.decision_time_et - INTERVAL 15 MINUTE
              AND t.created_time <= d.decision_time_et
        )
    ) AS price_change_15m,
    arg_max(t.yes_price_frac, t.created_time) - arg_min(t.yes_price_frac, t.created_time) AS price_change_60m,
    stddev_samp(t.yes_price_frac) AS realized_vol_60m,
    arg_max(t.yes_price_frac, t.created_time) AS last_trade_yes_price,
    max(t.created_time) AS last_trade_time_et
FROM decision_times d
INNER JOIN weather_trades t
    ON t.ticker = d.ticker
   AND t.created_time > d.decision_time_et - INTERVAL 60 MINUTE
   AND t.created_time <= d.decision_time_et
GROUP BY 1, 2;

CREATE OR REPLACE TEMP VIEW weather_forecasts AS
SELECT
    date::DATE AS target_date_et,
    gfs_maxt::DOUBLE AS gfs_maxt,
    ecmwf_maxt::DOUBLE AS ecmwf_maxt,
    ukmo_maxt::DOUBLE AS ukmo_maxt,
    nbm_maxt::DOUBLE AS nbm_maxt,
    0.35 * ecmwf_maxt::DOUBLE
      + 0.25 * gfs_maxt::DOUBLE
      + 0.20 * ukmo_maxt::DOUBLE
      + 0.20 * nbm_maxt::DOUBLE AS consensus_temp_f,
    sqrt(
        (
            pow(gfs_maxt::DOUBLE - (
                0.35 * ecmwf_maxt::DOUBLE
              + 0.25 * gfs_maxt::DOUBLE
              + 0.20 * ukmo_maxt::DOUBLE
              + 0.20 * nbm_maxt::DOUBLE
            ), 2)
          + pow(ecmwf_maxt::DOUBLE - (
                0.35 * ecmwf_maxt::DOUBLE
              + 0.25 * gfs_maxt::DOUBLE
              + 0.20 * ukmo_maxt::DOUBLE
              + 0.20 * nbm_maxt::DOUBLE
            ), 2)
          + pow(ukmo_maxt::DOUBLE - (
                0.35 * ecmwf_maxt::DOUBLE
              + 0.25 * gfs_maxt::DOUBLE
              + 0.20 * ukmo_maxt::DOUBLE
              + 0.20 * nbm_maxt::DOUBLE
            ), 2)
          + pow(nbm_maxt::DOUBLE - (
                0.35 * ecmwf_maxt::DOUBLE
              + 0.25 * gfs_maxt::DOUBLE
              + 0.20 * ukmo_maxt::DOUBLE
              + 0.20 * nbm_maxt::DOUBLE
            ), 2)
        ) / 4.0
    ) AS model_spread_f,
    (gfs_maxt::DOUBLE + ecmwf_maxt::DOUBLE) / 2.0 AS physics_mean_f,
    abs(gfs_maxt::DOUBLE - ecmwf_maxt::DOUBLE) / 2.0 AS physics_spread_f,
    (ukmo_maxt::DOUBLE + nbm_maxt::DOUBLE) / 2.0 AS ai_mean_f,
    abs(ukmo_maxt::DOUBLE - nbm_maxt::DOUBLE) / 2.0 AS ai_spread_f,
    abs(((gfs_maxt::DOUBLE + ecmwf_maxt::DOUBLE) / 2.0) - ((ukmo_maxt::DOUBLE + nbm_maxt::DOUBLE) / 2.0)) AS spread_between_f
FROM read_csv_auto('{open_meteo_csv}');

CREATE OR REPLACE TEMP VIEW nyc_actuals AS
SELECT
    date::DATE AS target_date_et,
    max_temp_f::DOUBLE AS actual_temp_f_diagnostic
FROM read_csv_auto('{actuals_csv}');

CREATE OR REPLACE TEMP VIEW weather_mart_base AS
SELECT
    m.ticker,
    m.event_ticker,
    m.target_date_et,
    m.city,
    m.bracket_type,
    m.bracket_lo_f,
    m.bracket_hi_f,
    f.decision_time_et,
    date_part('hour', f.decision_time_et) AS decision_hour_et,
    date_diff('minute', f.decision_time_et, m.close_time) / 60.0 AS hours_to_close,

    NULL::DOUBLE AS yes_bid,
    NULL::DOUBLE AS yes_ask,
    NULL::DOUBLE AS no_bid,
    NULL::DOUBLE AS no_ask,
    f.last_trade_yes_price AS last_price,
    f.last_trade_yes_price AS implied_mid_yes,
    NULL::DOUBLE AS spread_yes,
    NULL::DOUBLE AS spread_no,
    m.market_metadata_open_interest AS open_interest,
    m.market_metadata_volume AS volume,
    m.market_metadata_volume_24h AS volume_24h,
    f.recent_trade_count_15m,
    f.recent_trade_count_60m,
    f.recent_signed_flow_15m,
    f.recent_signed_flow_60m,
    f.taker_yes_share_15m,
    f.taker_yes_share_60m,
    f.vwap_yes_15m,
    f.vwap_yes_60m,
    COALESCE(f.price_change_15m, 0.0) AS price_change_15m,
    COALESCE(f.price_change_60m, 0.0) AS price_change_60m,
    COALESCE(f.realized_vol_60m, 0.0) AS realized_vol_60m,

    CASE WHEN m.city = 'NYC' THEN wf.consensus_temp_f ELSE NULL END AS consensus_temp_f,
    CASE WHEN m.city = 'NYC' THEN wf.model_spread_f ELSE NULL END AS model_spread_f,
    CASE WHEN m.city = 'NYC' THEN wf.physics_mean_f ELSE NULL END AS physics_mean_f,
    CASE WHEN m.city = 'NYC' THEN wf.ai_mean_f ELSE NULL END AS ai_mean_f,
    CASE WHEN m.city = 'NYC' THEN wf.spread_between_f ELSE NULL END AS spread_between_f,
    NULL::DOUBLE AS prior_day_error_f,
    NULL::DOUBLE AS morning_obs_f,
    NULL::DOUBLE AS morning_vs_forecast_f,
    CASE WHEN m.target_date_et >= DATE '2024-12-17' THEN 1 ELSE 0 END AS regime_hgefs,
    CASE WHEN m.target_date_et >= DATE '2025-02-25' THEN 1 ELSE 0 END AS regime_aifs,
    CASE WHEN m.target_date_et >= DATE '2025-05-27' THEN 1 ELSE 0 END AS regime_nbm_v43,
    CASE WHEN m.target_date_et >= DATE '2026-04-15' THEN 1 ELSE 0 END AS regime_nbm_v50,
    month(m.target_date_et) AS month,
    CASE WHEN month(m.target_date_et) IN (8, 9, 10, 11) THEN 1 ELSE 0 END AS is_peak_season,

    m.kalshi_result_yes,
    'kalshi_market_result' AS settlement_source,
    CASE WHEN m.city = 'NYC' THEN a.actual_temp_f_diagnostic ELSE NULL END AS actual_temp_f_diagnostic,
    NULL::BOOLEAN AS settlement_mismatch_flag,

    NULL::DOUBLE AS model_prob_raw,
    NULL::DOUBLE AS model_prob_calibrated,
    f.last_trade_yes_price AS market_price_yes,
    NULL::DOUBLE AS edge_pp_raw,
    NULL::DOUBLE AS edge_pp_calibrated,

    f.last_trade_time_et,
    m.open_time,
    m.close_time,
    m.status,
    m.result,
    m.title,
    m.market_metadata_fetched_at,
    'trade_derived_hourly_prior_state' AS market_state_source,
    'daily_open_meteo_no_intraday_vintage' AS forecast_vintage_status
FROM weather_markets m
INNER JOIN trade_features f USING (ticker)
LEFT JOIN weather_forecasts wf
    ON wf.target_date_et = m.target_date_et
LEFT JOIN nyc_actuals a
    ON a.target_date_et = m.target_date_et
WHERE f.decision_time_et <= m.close_time;
