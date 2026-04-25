from __future__ import annotations

import os
import sqlite3


def create_database(db_path: str = "data/pipeline.db") -> None:
    """Create all pipeline database tables and indexes."""
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS model_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            run_time TEXT,
            model TEXT NOT NULL,
            city TEXT NOT NULL,
            target_date TEXT,
            physics_mean REAL,
            physics_spread REAL,
            ai_mean REAL,
            ai_spread REAL,
            consensus_temp_f REAL,
            nbm_p10 REAL,
            nbm_p25 REAL,
            nbm_p50 REAL,
            nbm_p75 REAL,
            nbm_p90 REAL,
            hrrr_maxt_f REAL,
            gfs_maxt_f REAL,
            ecmwf_maxt_f REAL,
            aigefs_temp_raw REAL,
            aigefs_temp_corrected REAL,
            aigefs_correction_validated INTEGER DEFAULT 0,
            raw_data_json TEXT,
            source TEXT
        );

        CREATE TABLE IF NOT EXISTS metar_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            station TEXT NOT NULL,
            observation_time TEXT,
            temp_c REAL,
            temp_f REAL,
            obs_type TEXT,
            six_hour_high_f REAL,
            six_hour_low_f REAL,
            wethr_high_f REAL,
            wethr_low_f REAL,
            dew_point_c REAL,
            wind_speed REAL,
            relative_humidity REAL,
            dsm_high_f REAL,
            cli_high_f REAL,
            caution_flag INTEGER DEFAULT 0,
            raw_json TEXT
        );

        CREATE TABLE IF NOT EXISTS kalshi_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            ticker TEXT NOT NULL,
            city TEXT NOT NULL,
            target_date TEXT,
            bracket_label TEXT,
            strike_lo REAL,
            strike_hi REAL,
            bracket_type TEXT,
            yes_bid TEXT,
            yes_ask TEXT,
            yes_last TEXT,
            no_bid TEXT,
            no_ask TEXT,
            spread TEXT,
            spread_cents REAL,
            volume INTEGER,
            open_interest INTEGER,
            source TEXT
        );

        CREATE TABLE IF NOT EXISTS gate_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            city TEXT NOT NULL,
            ticker TEXT,
            target_date TEXT,
            trigger_reason TEXT,
            gate1_pass INTEGER,
            gate1_physics_mean REAL,
            gate1_ai_mean REAL,
            gate1_spread_between REAL,
            gate1_physics_spread REAL,
            gate1_ai_spread REAL,
            gate2_pass INTEGER,
            gate2_model_prob REAL,
            gate2_market_price REAL,
            gate2_gap_pp REAL,
            gate2_direction TEXT,
            gate3_pass INTEGER,
            gate3_yes_price REAL,
            gate4_pass INTEGER,
            gate4_in_dead_zone INTEGER,
            gate5_pass INTEGER,
            gate5_metar_temp_f REAL,
            gate5_bracket_center_f REAL,
            gate5_distance REAL,
            gate6_pass INTEGER,
            gate6_reversal_detected INTEGER,
            gate6_is_cold_bracket INTEGER,
            all_pass INTEGER,
            signal_generated INTEGER,
            skip_reason TEXT,
            gate1_ai_source TEXT
        );

        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            city TEXT NOT NULL,
            ticker TEXT NOT NULL,
            target_date TEXT,
            bracket TEXT,
            bracket_lo REAL,
            bracket_hi REAL,
            direction TEXT,
            entry_price REAL,
            target_price REAL DEFAULT 0.68,
            stop_price REAL,
            model_prob REAL,
            market_price REAL,
            gap_pp REAL,
            confidence_score REAL,
            physics_mean REAL,
            ai_mean REAL,
            nbm_p50 REAL,
            metar_temp_f REAL,
            nws_version INTEGER,
            trigger_reason TEXT,
            reasoning TEXT,
            status TEXT DEFAULT 'ACTIVE',
            hgefs_proxy INTEGER DEFAULT 0,
            strategy_sleeve TEXT DEFAULT 'CORE_HGEFS_GUMBEL'
        );

        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            signal_id INTEGER,
            city TEXT NOT NULL,
            ticker TEXT NOT NULL,
            target_date TEXT,
            bracket TEXT,
            direction TEXT,
            contracts INTEGER DEFAULT 1,
            stake_dollars REAL,
            entry_time TEXT,
            entry_price REAL,
            exit_time TEXT,
            exit_price REAL,
            exit_reason TEXT,
            gross_pnl REAL,
            taker_fee_entry REAL,
            maker_fee_entry REAL,
            taker_fee_exit REAL,
            maker_fee_exit REAL,
            net_pnl_maker REAL,
            net_pnl_taker REAL,
            slippage_estimate REAL,
            settlement_temp_f REAL,
            settled_correct INTEGER,
            strategy_sleeve TEXT DEFAULT 'CORE_HGEFS_GUMBEL',
            FOREIGN KEY (signal_id) REFERENCES signals(id)
        );

        CREATE TABLE IF NOT EXISTS teleconnections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            mjo_rmm1 REAL, mjo_rmm2 REAL,
            mjo_phase INTEGER, mjo_amplitude REAL,
            nao REAL, pna REAL, ao REAL,
            epo REAL, wpo REAL, tnh REAL, pol REAL,
            oni REAL,
            nao_lag1 REAL, pna_lag1 REAL, ao_lag1 REAL,
            nao_lag3 REAL, pna_lag3 REAL, ao_lag3 REAL,
            nao_lag7 REAL, pna_lag7 REAL, ao_lag7 REAL,
            mjo_amplitude_lag7 REAL, mjo_phase_lag7 INTEGER,
            mjo_amplitude_lag14 REAL, mjo_phase_lag14 INTEGER,
            source TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS dsm_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            city TEXT NOT NULL,
            station TEXT,
            dsm_date TEXT,
            dsm_fire_time_utc TEXT,
            max_temp_c REAL,
            max_temp_f REAL,
            min_temp_c REAL,
            min_temp_f REAL,
            caution_flag INTEGER DEFAULT 0,
            raw_json TEXT
        );

        CREATE TABLE IF NOT EXISTS cli_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            city TEXT NOT NULL,
            station TEXT,
            settlement_date TEXT,
            cli_fire_time_utc TEXT,
            official_high_f REAL,
            official_low_f REAL,
            raw_json TEXT
        );

        CREATE TABLE IF NOT EXISTS performance_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            signals_generated INTEGER DEFAULT 0,
            trades_taken INTEGER DEFAULT 0,
            trades_skipped INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            cancelled INTEGER DEFAULT 0,
            gross_pnl REAL DEFAULT 0,
            total_maker_fees REAL DEFAULT 0,
            net_pnl_maker REAL DEFAULT 0,
            win_rate REAL,
            sharpe_daily REAL,
            max_dd_daily REAL,
            bankroll_start REAL,
            bankroll_end REAL,
            best_trade_pnl REAL,
            worst_trade_pnl REAL,
            avg_brier_score REAL,
            avg_calibration_error REAL,
            api_errors INTEGER DEFAULT 0,
            gate1_failures INTEGER DEFAULT 0,
            gate2_failures INTEGER DEFAULT 0,
            gate5_failures INTEGER DEFAULT 0,
            gate6_failures INTEGER DEFAULT 0,
            gate1_real_aigefs_count INTEGER DEFAULT 0,
            gate1_proxy_count INTEGER DEFAULT 0,
            notes TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        );
        """
    )

    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS candidate_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            city TEXT NOT NULL,
            ticker TEXT NOT NULL,
            target_date TEXT,
            bracket TEXT,
            strategy_sleeve TEXT,
            direction TEXT,
            yes_price REAL,
            model_prob REAL,
            edge_pp REAL,
            gap_pp REAL,
            confidence_score REAL,
            hgefs_real INTEGER DEFAULT 0,
            ai_source TEXT,
            physics_count INTEGER,
            ai_count INTEGER,
            physics_mean REAL,
            ai_mean REAL,
            gate1_pass INTEGER,
            gate2_pass INTEGER,
            gate3_pass INTEGER,
            gate4_pass INTEGER,
            gate5_pass INTEGER,
            gate6_pass INTEGER,
            would_pass_core INTEGER,
            actual_settlement_f REAL,
            settled_correct INTEGER,
            notes TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_model_runs_city_date ON model_runs(city, target_date);
        CREATE INDEX IF NOT EXISTS idx_metar_station_time ON metar_observations(station, observation_time);
        CREATE INDEX IF NOT EXISTS idx_kalshi_ticker_time ON kalshi_prices(ticker, created_at);
        CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_paper_trades_date ON paper_trades(target_date);
        CREATE INDEX IF NOT EXISTS idx_teleconn_date ON teleconnections(date);
        CREATE INDEX IF NOT EXISTS idx_dsm_city_date ON dsm_reports(city, dsm_date);
        CREATE INDEX IF NOT EXISTS idx_cli_city_date ON cli_reports(city, settlement_date);
        """
    )

    conn.commit()
    conn.close()
    print(f"Database created/verified at {db_path}")
