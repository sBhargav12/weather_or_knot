from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from datetime import time as dt_time
from statistics import median
from typing import Optional
from zoneinfo import ZoneInfo

import config
from dashboard.daily_report import generate_daily_report
from data_ingest.kalshi_client import KalshiClient
from data_ingest.model_fetcher import ModelFetcher, fetch_nws_remaining_max_f
from data_ingest.teleconn_fetcher import TeleconnFetcher
from data_ingest.wethr_client import WethrClient
from data_store.db import Database
from live_trader.trader import LiveTrader
from paper_trader import config_paper as _cp
from paper_trader.simulator import PaperTrader
from signal_engine.emos_model import LiveEMOSModel
from signal_engine.gate_checker import check_gate_1, run_all_gates
from signal_engine.gumbel_model import GumbelModel
from signal_engine.llm_synthesis import synthesize_trade_decision
from signal_engine.weather_memory import WeatherMemoryLog

logger = logging.getLogger(__name__)


class EventTriggerEngine:
    def __init__(
        self,
        wethr: WethrClient,
        kalshi: KalshiClient,
        model_fetcher: ModelFetcher,
        gumbel: GumbelModel,
        paper_trader: PaperTrader,
        orderbook_manager,
        db: Database,
        live_trader: Optional[LiveTrader] = None,
    ):
        self.wethr = wethr
        self.kalshi = kalshi
        self.model_fetcher = model_fetcher
        self.gumbel = gumbel
        self.paper_trader = paper_trader
        self.orderbook_manager = orderbook_manager
        self.db = db
        self.live_trader = live_trader
        self.latest_hgefs_cycle: dict[str, str] = {}
        self.triggered_today = set()
        self.daily_completed: set[tuple[str, str]] = set()
        self._last_dsm_received: dict[str, str] = {}  # station → last dsm_received_at seen
        # Pre-populate from DB (dsm_received_at lives inside raw_json, not a column).
        try:
            rows = self.db.execute(
                """SELECT station, MAX(json_extract(raw_json, '$.dsm_received_at')) as last_recv
                   FROM dsm_reports
                   WHERE raw_json IS NOT NULL
                   GROUP BY station"""
            )
            for row in rows:
                last_recv = row["last_recv"]
                if last_recv:
                    self._last_dsm_received[row["station"]] = last_recv
            if self._last_dsm_received:
                logger.info("Pre-populated _last_dsm_received from DB: %s", self._last_dsm_received)
        except Exception as _exc:
            logger.warning("Could not pre-populate _last_dsm_received: %s", _exc)
        self.emos: dict[str, LiveEMOSModel] = {}
        for city, cfg in config.CITIES.items():
            if cfg.get("active"):
                model = LiveEMOSModel(city_code=city)
                if model.train():
                    self.emos[city] = model
                else:
                    logger.warning("LiveEMOSModel training failed for %s — city excluded from EMOS sleeve", city)
        self.weather_memory: Optional[WeatherMemoryLog] = (
            WeatherMemoryLog(db) if _cp.PAPER_WEATHER_MEMORY_ENABLED else None
        )
        self.stream_client = None
        # Load any previously computed accuracy weights from DB so they apply immediately
        try:
            existing = db.compute_local_model_accuracy(min_days=20)
            if existing:
                weights = {r["model"]: 1.0 / r["mae"] for r in existing if r["mae"] > 0}
                total = sum(weights.values())
                weights = {m: w / total for m, w in weights.items()}
                biases = {r["model"]: r["bias"] for r in existing}
                self.gumbel.update_dynamic_weights(weights, biases)
        except Exception as _acc_exc:
            logger.debug("Could not pre-load model accuracy weights: %s", _acc_exc)

    async def run_forever(self) -> None:
        await asyncio.gather(
            self._loop(self.poll_60s, config.POLL_INTERVAL_60S),
            self._loop(self.poll_5min, config.POLL_INTERVAL_5MIN),
            self._loop(self.poll_30min, config.POLL_INTERVAL_30MIN),
            self._wall_clock_daily_loop(),
            self._fallback_loop(),
            self._early_deep_tail_loop(),
        )

    async def run_once(self) -> None:
        await self.poll_60s()
        await self.poll_5min()
        await self.poll_30min()

    async def _loop(self, fn, interval: int) -> None:
        while True:
            try:
                await fn()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("%s failed: %s", fn.__name__, exc)
            await asyncio.sleep(interval)

    def _active_cities(self) -> list:
        return [(city, cfg) for city, cfg in config.CITIES.items() if cfg.get("active")]

    async def poll_60s(self) -> None:
        now_et = datetime.now(ZoneInfo("America/New_York"))
        dsm_detected = self._is_dsm_window(now_et)

        for city, cfg in self._active_cities():
            station = cfg["wethr_station"]
            try:
                obs = self.wethr.get_latest_obs(station)
                self.db.insert_observation(self._latest_obs_record(station, obs))
                high = self.wethr.get_wethr_high(station, "nws")
                self.db.insert_observation(self._wethr_high_record(station, high))
                try:
                    high_wu = self.wethr.get_wethr_high_wu(station)
                    wu_val = high_wu.get("wethr_high")
                    nws_val = high.get("wethr_high")
                    if wu_val is not None and nws_val is not None:
                        delta = float(wu_val) - float(nws_val)
                        if abs(delta) >= 1.0:
                            logger.info(
                                "wethr_high NWS/WU divergence for %s: nws=%.1f wu=%.1f delta=%.1f°F",
                                station, float(nws_val), float(wu_val), delta,
                            )
                        self.db.insert_observation({
                            "station": station,
                            "observation_time": high_wu.get("time_of_high_utc"),
                            "obs_type": "WETHR_HIGH_WU",
                            "wethr_high_f": wu_val,
                            "wethr_high_wu_f": wu_val,
                            "wethr_low_f": high_wu.get("wethr_low"),
                            "caution_flag": int(bool(high_wu.get("caution_flag"))),
                            "raw_json": json.dumps(high_wu),
                        })
                except Exception as _wu_exc:
                    logger.debug("wu wethr_high fetch failed for %s: %s", station, _wu_exc)
                # DSM extracted from obs — no extra API call needed.
                # dsm_high_f and dsm_received_at are already in every METAR response.
                dsm_ts = obs.get("dsm_received_at") or ""
                if obs.get("dsm_high_f") is not None and dsm_ts and dsm_ts != self._last_dsm_received.get(station):
                    self._last_dsm_received[station] = dsm_ts
                    self.db.insert_dsm_report(self._dsm_record_from_obs(city, station, obs))
            except Exception as exc:
                logger.warning("60s poll failed for %s: %s", city, exc)

        # Check exits on all open paper trades using latest DB prices (no new API calls)
        try:
            current_prices = self._get_current_prices()
            self.paper_trader.check_exits(current_prices, dsm_detected=dsm_detected)
            self._enforce_time_exits(now_et)
        except Exception as exc:
            logger.warning("Exit check failed: %s", exc)

        # Live trader: poll fills then check exits.
        if self.live_trader is not None:
            try:
                self.live_trader.poll_fills()
                current_prices = self._get_current_prices()
                self.live_trader.check_exits(current_prices, dsm_detected=dsm_detected)
            except Exception as exc:
                logger.warning("Live trader poll/exit failed: %s", exc)

    async def poll_5min(self) -> None:
        target_date = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        for city, cfg in self._active_cities():
            station = cfg["wethr_station"]
            try:
                nws = self.wethr.get_nws_evolution(station)
                version = int(nws.get("version", 0) or 0)
                if version and self.wethr.nws_version_incremented(station, version):
                    await self.fire_gate_check(city, "nws_version")
                for model in ["HRRR", "NBM"]:
                    maxt = self.wethr.get_forecast_maxt(station, model, target_date)
                    if maxt is not None:
                        self.db.insert_model_run(
                            {
                                "model": model,
                                "city": city,
                                "target_date": target_date,
                                "run_time": (nws.get("forecast_date") or target_date),
                                "consensus_temp_f": maxt,
                                "hrrr_maxt_f": maxt if model == "HRRR" else None,
                                "nbm_p50": maxt if model == "NBM" else None,
                                "raw_data_json": json.dumps({"nws_version": version}),
                                "source": "wethr_api",
                            }
                        )
            except Exception as exc:
                logger.warning("5min poll failed for %s: %s", city, exc)

    async def poll_30min(self) -> None:
        target_date = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        for city, cfg in self._active_cities():
            try:
                markets = self.kalshi.get_active_markets(cfg["series_ticker"])
                brackets = self.kalshi.parse_brackets(markets)
                for bracket in brackets:
                    self.db.insert_kalshi_price(
                        {
                            "ticker": bracket["ticker"],
                            "city": city,
                            "target_date": bracket.get("target_date"),
                            "bracket_label": bracket.get("bracket_label"),
                            "strike_lo": bracket.get("strike_lo"),
                            "strike_hi": bracket.get("strike_hi"),
                            "bracket_type": bracket.get("bracket_type"),
                            "yes_bid": str(bracket.get("yes_bid")) if bracket.get("yes_bid") is not None else None,
                            "yes_ask": str(bracket.get("yes_ask")) if bracket.get("yes_ask") is not None else None,
                            "yes_last": str(bracket.get("yes_last")) if bracket.get("yes_last") is not None else None,
                            "no_bid": str(bracket.get("no_bid")) if bracket.get("no_bid") is not None else None,
                            "no_ask": str(bracket.get("no_ask")) if bracket.get("no_ask") is not None else None,
                            "spread": str(bracket.get("spread")) if bracket.get("spread") is not None else None,
                            "spread_cents": bracket.get("spread_cents"),
                            "volume": bracket.get("volume"),
                            "open_interest": bracket.get("open_interest"),
                            "source": "rest_poll",
                        }
                    )

                models = self.wethr.get_all_models_maxt(cfg["wethr_station"], target_date)
                consensus = self.gumbel.compute_consensus_from_wethr(models, target_date)
                if consensus is not None:
                    self.db.insert_model_run(
                        {
                            "model": "WETHR_CONSENSUS",
                            "city": city,
                            "target_date": target_date,
                            "consensus_temp_f": consensus,
                            "hrrr_maxt_f": models.get("HRRR"),
                            "gfs_maxt_f": models.get("GFS"),
                            "ecmwf_maxt_f": models.get("ECMWF"),
                            "raw_data_json": json.dumps(models),
                            "source": "wethr_api",
                        }
                    )
                self._fetch_and_store_nbm_bulletin(city, cfg, target_date)
                date_str = datetime.now(UTC).strftime("%Y%m%d")
                last_cycle = self.latest_hgefs_cycle.get(city)
                cycle = self.model_fetcher.check_new_hgefs_cycle(last_cycle, date_str=date_str)
                if cycle:
                    self.latest_hgefs_cycle[city] = cycle
                    await asyncio.to_thread(self._fetch_and_store_hgefs, city, cfg, target_date, date_str, cycle)
                    # Only fire signal checks from 10 AM ET onward; HGEFS cycles
                    # arriving before market open (06Z run ~8-9 AM ET) have lower
                    # liquidity and wider spreads. The 11 AM fallback_loop handles
                    # the first clean entry window if no cycle arrives after 10 AM.
                    now_for_check = datetime.now(ZoneInfo("America/New_York"))
                    if now_for_check.time() >= dt_time(10, 0):
                        await self.fire_gate_check(city, "new_hgefs")
            except Exception as exc:
                logger.warning("30min poll failed for %s: %s", city, exc)

    async def poll_daily(self) -> None:
        await self.update_teleconnections()
        await self.check_cli_settlements()
        await self.generate_daily_summary()

    async def update_teleconnections(self) -> None:
        today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        tele = TeleconnFetcher(config.DB_PATH)
        try:
            tele.save_to_db(today, tele.build_daily_features(today))
        except Exception as exc:
            logger.warning("teleconnection update failed: %s", exc)

    async def _refresh_precipitation(self) -> None:
        today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        for city, cfg in self._active_cities():
            station = cfg["wethr_station"]
            try:
                precip = self.wethr.get_precipitation(station)
                if precip:
                    self.db.upsert_precipitation_cache({
                        "station": station,
                        "date": today,
                        "precip_today_in": precip.get("today_precip"),
                        "official_mtd_in": precip.get("official_mtd"),
                        "has_trace": int(bool(precip.get("has_trace", False))),
                    })
                    logger.info(
                        "Precipitation %s: today=%.2f\" mtd=%s",
                        station,
                        float(precip.get("today_precip") or 0),
                        precip.get("official_mtd"),
                    )
            except Exception as exc:
                logger.warning("Precipitation refresh failed for %s: %s", city, exc)

    async def _refresh_model_accuracy(self) -> None:
        try:
            rows = self.db.compute_local_model_accuracy(min_days=20)
        except Exception as exc:
            logger.warning("Local model accuracy computation failed: %s", exc)
            rows = []

        if rows:
            for row in rows:
                self.db.upsert_model_accuracy({
                    "station": "ALL",
                    "model": row["model"],
                    "mae": row["mae"],
                    "bias": row["bias"],
                    "rmse": row["rmse"],
                    "n": row["n"],
                    "window_days": 0,
                })
            import numpy as _np
            weights = {r["model"]: 1.0 / r["mae"] for r in rows if r["mae"] > 0}
            total = sum(weights.values())
            weights = {m: w / total for m, w in weights.items()}
            biases = {r["model"]: r["bias"] for r in rows}
            self.gumbel.update_dynamic_weights(weights, biases)
            logger.info(
                "Model accuracy refresh: %d models, best=%s MAE=%.2f bias=%.2f°F",
                len(rows), rows[0]["model"], rows[0]["mae"], rows[0]["bias"],
            )

        # Also try wethr API (Developer tier) — silently no-ops on Pro
        for city, cfg in self._active_cities():
            station = cfg["wethr_station"]
            try:
                api_rows = self.wethr.get_model_accuracy(station, window_days=7)
                for r in api_rows:
                    self.db.upsert_model_accuracy({
                        "station": station,
                        "model": r.get("model"),
                        "mae": r.get("mae"),
                        "bias": r.get("bias"),
                        "rmse": r.get("rmse"),
                        "n": r.get("n"),
                        "window_days": 7,
                    })
            except Exception:
                pass

    async def check_cli_settlements(self) -> None:
        today_dt = datetime.now(ZoneInfo("America/New_York")).date()
        yesterday = (today_dt - timedelta(days=1)).isoformat()
        for city, cfg in self._active_cities():
            station = cfg["wethr_station"]
            try:
                # Read CLI settlement from the latest stored METAR — cli_high_f is
                # embedded in every METAR response, no separate API call needed.
                cli_data = self.db.get_latest_cli_from_metar(station)
                if cli_data and cli_data.get("cli_high_f") is not None:
                    self.db.insert_cli_report(
                        {
                            "city": city,
                            "station": station,
                            "settlement_date": yesterday,
                            "cli_fire_time_utc": cli_data.get("cli_received_at"),
                            "official_high_f": cli_data["cli_high_f"],
                            "official_low_f": cli_data.get("cli_low_f"),
                            "raw_json": cli_data.get("raw_json"),
                        }
                    )
                    # Mark settled_correct on all paper trades for yesterday's target date.
                    # This is metadata-only; PnL was already recorded by DSM_CANCEL/TIME_LIMIT.
                    # Any trade still open at this point (TIME_LIMIT missed) is also closed here.
                    cli_high = float(cli_data["cli_high_f"])
                    all_yesterday = self.db.execute(
                        "SELECT * FROM paper_trades WHERE city = ? AND target_date = ?",
                        (city, yesterday),
                    )
                    for row in all_yesterday:
                        trade = dict(row)
                        self.paper_trader.settle_trade(trade, cli_high)
                        if trade.get("exit_time") is None:
                            # Safety net: close trades missed by TIME_LIMIT
                            correct = self.paper_trader._direction_correct(trade, cli_high)
                            settlement_exit_price = 1.0 if correct else 0.0
                            self.paper_trader._exit_trade(
                                int(trade["id"]), settlement_exit_price, "CLI_SETTLEMENT"
                            )
                            logger.info(
                                "CLI_SETTLEMENT fallback exit for trade %s %s correct=%s",
                                trade["id"], trade.get("ticker"), correct,
                            )
            except Exception as exc:
                logger.warning("CLI update failed for %s: %s", city, exc)

    async def generate_daily_summary(self) -> None:
        today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        logger.info("\n%s", generate_daily_report(config.DB_PATH, today))

    async def generate_eod_report(self) -> None:
        from dashboard.daily_report import generate_eod_llm_analysis, generate_eod_summary
        from dashboard.notifications import notify_phone

        today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        full_report = generate_daily_report(config.DB_PATH, today)

        # LLM analysis appended to the full log report (runs async in thread to avoid blocking)
        llm_analysis = await asyncio.to_thread(generate_eod_llm_analysis, config.DB_PATH, today)
        logger.info("EOD REPORT\n%s%s", full_report, llm_analysis)

        summary = generate_eod_summary(config.DB_PATH, today)
        if llm_analysis:
            # Append the first sentence of LLM analysis to the phone notification
            first_sentence = llm_analysis.strip().splitlines()[-1].split(". ")[0] + "."
            summary += f"\n\n{first_sentence}"

        first_line = summary.splitlines()[0] if summary else ""
        pnl_positive = "+$" in first_line or ("P&L: $" in first_line and "-" not in first_line.split("P&L:")[-1])
        notify_phone(
            title=f"EOD {today} | {first_line}",
            message=summary,
            priority="default",
            tags="chart_increasing" if pnl_positive else "chart_decreasing",
        )

    async def _wall_clock_daily_loop(self) -> None:
        jobs = [
            ("teleconnections", config.TELECONN_UPDATE_ET, self.update_teleconnections),
            ("precipitation", "08:00", self._refresh_precipitation),
            ("cli", config.CLI_CHECK_TIME_ET, self.check_cli_settlements),
            ("report", config.DAILY_REPORT_TIME_ET, self.generate_daily_summary),
            ("eod_report", config.EOD_REPORT_TIME_ET, self.generate_eod_report),
        ]
        while True:
            now = datetime.now(ZoneInfo("America/New_York"))
            for name, scheduled, fn in jobs:
                key = (now.date().isoformat(), name)
                if key not in self.daily_completed and now.time() >= self._parse_et_time(scheduled):
                    try:
                        await fn()
                        self.daily_completed.add(key)
                    except Exception as exc:
                        logger.warning("daily job %s failed: %s", name, exc)

            # 12:40 PM ET — 12Z GFS peak model run trigger (most important of the day)
            peak_key = (now.date().isoformat(), "peak_model_run_12z")
            if peak_key not in self.daily_completed and now.time() >= self._parse_et_time(config.PEAK_MODEL_RUN_ET):
                logger.info("Peak model run window (12:40 PM ET) — triggering gate checks")
                all_ok = True
                for city, _ in self._active_cities():
                    try:
                        await self.fire_gate_check(city, "peak_model_run_12z")
                    except Exception as exc:
                        logger.warning("peak_model_run gate check failed for %s: %s", city, exc)
                        all_ok = False
                if all_ok:
                    self.daily_completed.add(peak_key)

            # 10:00 AM ET — Strategy 2 ladder event window.
            # This uses the same model/probability pass as core, but creates a
            # small event-level YES/NO portfolio only during the researched
            # 9:00–10:30 AM entry window.
            ladder_key = (now.date().isoformat(), "ladder_event_10am")
            if ladder_key not in self.daily_completed and now.time() >= self._parse_et_time(config.LADDER_EVENT_RUN_ET):
                logger.info("Strategy 2 ladder window (10:00 AM ET) — triggering event-level checks")
                all_ok = True
                for city, _ in self._active_cities():
                    try:
                        await self.fire_gate_check(city, "ladder_event_10am")
                    except Exception as exc:
                        logger.warning("ladder_event gate check failed for %s: %s", city, exc)
                        all_ok = False
                if all_ok:
                    self.daily_completed.add(ladder_key)

            # 3:00 PM ET — bracket-lock confirmation window
            # Running ASOS daily max is reliable at this point; enter the confirmed bracket
            # before DSM fires at 4:21 PM and reprices it to 95c.
            lock_key = (now.date().isoformat(), "bracket_lock_3pm")
            if lock_key not in self.daily_completed and now.time() >= self._parse_et_time(config.BRACKET_LOCK_RUN_ET):
                logger.info("Bracket-lock window (3:00 PM ET) — checking intraday confirmed high")
                all_ok = True
                for city, _ in self._active_cities():
                    try:
                        await self.fire_bracket_lock_check(city)
                    except Exception as exc:
                        logger.warning("bracket_lock check failed for %s: %s", city, exc)
                        all_ok = False
                if all_ok:
                    self.daily_completed.add(lock_key)

            # Weekly: refresh model accuracy on Mondays at 06:00 ET
            if now.weekday() == 0:
                acc_key = (now.date().isoformat(), "model_accuracy_refresh")
                if acc_key not in self.daily_completed and now.time() >= self._parse_et_time("06:00"):
                    self.daily_completed.add(acc_key)
                    try:
                        await self._refresh_model_accuracy()
                    except Exception as exc:
                        logger.warning("model_accuracy refresh failed: %s", exc)

            await asyncio.sleep(60)

    async def fire_gate_check(self, city: str, trigger_reason: str) -> None:
        # Resolve any pending memory entries now that overnight CLI may be available.
        if self.weather_memory is not None:
            self.weather_memory.resolve_pending(city)

        now_et = datetime.now(ZoneInfo("America/New_York"))
        if self._is_dsm_window(now_et):
            logger.info("fire_gate_check skipped for %s — inside DSM cancel window", city)
            return

        cfg = config.CITIES[city]
        station = cfg["wethr_station"]
        now_local = datetime.now(ZoneInfo(cfg["timezone"]))
        today = now_local.date()
        allowed_dates = self._allowed_target_dates(now_local)
        markets = self.kalshi.get_active_markets(cfg["series_ticker"])
        brackets = self.kalshi.parse_brackets(markets)
        brackets = self._brackets_for_trading_horizon(brackets, allowed_dates, city)

        for target_date, target_brackets in self._group_brackets_by_target_date(brackets).items():
            # Block same-day entries using two independent guards:
            #   1. Time-based: after the DSM window ends (18:30 ET), no same-day entries ever.
            #      Unconditional — doesn't depend on DB state or in-memory _last_dsm_received.
            #   2. DSM-receipt-based: if we're still before 18:30 ET but we've already seen
            #      today's DSM in-memory, block too (catches intraday re-entry between 16:15-18:30).
            if target_date == today.isoformat():
                now_et_time = now_et.time()
                past_window = now_et_time >= dt_time(18, 30)
                last_dsm = self._last_dsm_received.get(station, "")
                dsm_received_today = last_dsm.startswith(today.isoformat())
                if past_window or dsm_received_today:
                    logger.info(
                        "fire_gate_check skipping same-day %s for %s "
                        "(past_window=%s, dsm_received_today=%s, last_dsm=%r)",
                        target_date,
                        city,
                        past_window,
                        dsm_received_today,
                        last_dsm,
                    )
                    continue
            models = self.wethr.get_all_models_maxt(station, target_date)
            hgefs_like = self._hgefs_or_fallback(city, models, target_date)
            nbm = self._latest_nbm(city, target_date) or {}
            consensus = self._consensus(hgefs_like, models, target_date)
            # Use latest stored METAR from DB — avoids a wethr history API call on
            # every gate check. six_hour_high_f is the rolling 6-hour max, a better
            # proxy for today's peak than the instantaneous METAR temp.
            metar, six_hour_high = (
                self.db.get_latest_metar_with_six_hour(station) if target_date == today.isoformat() else (None, None)
            )
            if consensus is None:
                logger.info("No consensus available for %s %s gate check", city, target_date)
                continue

            ladder_candidates = []
            for bracket in target_brackets:
                market_price = self._market_price(bracket)
                if market_price is None:
                    continue
                prob = self.gumbel.compute_bracket_prob(
                    bracket.get("strike_lo"),
                    bracket.get("strike_hi"),
                    consensus,
                    bracket.get("bracket_type", "central"),
                )
                prob = self.gumbel.bayesian_update_with_nbm(
                    prob,
                    nbm.get("p50"),
                    nbm.get("p10"),
                    nbm.get("p90"),
                    bracket.get("strike_lo"),
                    bracket.get("strike_hi"),
                    bracket.get("bracket_type", "central"),
                    bool(nbm.get("percentiles_real", True)),
                )
                prob = self.gumbel.apply_calibration(prob)
                center = self._bracket_center(bracket)
                history = (
                    self.orderbook_manager.get_price_history(bracket["ticker"], 8 * 60)
                    if self.orderbook_manager
                    else []
                )

                # EMOS probability — computed first so it drives gates and logging too
                emos_prob = None
                if _cp.PAPER_ENABLE_EMOS and city in self.emos:
                    emos_prob = self.emos[city].bracket_probability(
                        bracket.get("strike_lo"),
                        bracket.get("strike_hi"),
                        bracket.get("bracket_type", "central"),
                        hgefs_like,
                        models,
                        nbm,
                        target_date,
                    )

                # Use EMOS prob everywhere when available; Gumbel is the fallback only
                gate_prob = emos_prob if emos_prob is not None else prob

                gate = run_all_gates(
                    hgefs_like.get("physics_mean"),
                    hgefs_like.get("physics_spread"),
                    hgefs_like.get("ai_mean"),
                    hgefs_like.get("ai_spread"),
                    gate_prob,
                    market_price,
                    market_price,
                    metar,
                    center,
                    bracket.get("strike_lo") or center,
                    "YES",
                    history,
                    bracket["ticker"],
                    wethr_models=models,
                    nbm_p50=nbm.get("p50"),
                    six_hour_high_f=six_hour_high,
                )
                self.db.insert_gate_check(
                    self._gate_record(city, bracket, target_date, trigger_reason, gate, hgefs_like)
                )

                # Log every evaluation to candidate_signals (research DB)
                self._log_candidate(city, bracket, target_date, gate, gate_prob, market_price, hgefs_like)
                ladder_candidates.append(
                    {
                        "bracket": bracket,
                        "model_prob": gate_prob,
                        "market_price": market_price,
                        "gate": gate,
                    }
                )

                # SLEEVE: CORE_HGEFS_EMOS — gate already computed with EMOS prob above
                if gate["all_pass"] and self._liquid(bracket):
                    using_proxy = hgefs_like.get("gate1_ai_source") == "wethr_proxy"
                    confidence = gate["confidence_score"]
                    if using_proxy:
                        confidence = max(0.0, confidence - 20.0)

                    # LLM synthesis: refine action and sizing using past city context.
                    llm_decision = None
                    if _cp.PAPER_LLM_SYNTHESIS_ENABLED and self.weather_memory is not None:
                        try:
                            past_ctx = self.weather_memory.get_past_context(city)
                            llm_decision = synthesize_trade_decision(
                                city=city,
                                ticker=bracket["ticker"],
                                gate=gate,
                                emos_prob=emos_prob,
                                gumbel_prob=prob,
                                market_price=market_price,
                                past_context=past_ctx,
                                bracket_label=bracket.get("bracket_label", ""),
                            )
                            if llm_decision.action == "PASS":
                                logger.info(
                                    "LLM synthesis PASS for %s %s: %s",
                                    city,
                                    bracket["ticker"],
                                    llm_decision.reasoning,
                                )
                                continue
                            # Scale confidence by the LLM-derived sizing fraction.
                            confidence = round(confidence * llm_decision.sizing_fraction, 2)
                        except Exception as _llm_exc:
                            logger.warning("LLM synthesis error for %s: %s", bracket["ticker"], _llm_exc)

                    entry_price = market_price if gate["direction"] == "YES" else self._no_entry_price(bracket)
                    default_reasoning = f"EMOS gates passed; gap={gate['gap_pp']:.1f}pp; prob={gate_prob:.3f}"
                    signal_id = self.db.insert_signal(
                        {
                            "city": city,
                            "ticker": bracket["ticker"],
                            "target_date": target_date,
                            "bracket": bracket.get("bracket_label"),
                            "bracket_lo": bracket.get("strike_lo"),
                            "bracket_hi": bracket.get("strike_hi"),
                            "direction": gate["direction"],
                            "entry_price": entry_price,
                            "target_price": float(config.TARGET_EXIT_PRICE),
                            "stop_price": max(0.0, entry_price - float(config.STOP_LOSS_DIFF)),
                            "model_prob": gate_prob,
                            "market_price": market_price,
                            "gap_pp": gate["gap_pp"],
                            "confidence_score": confidence,
                            "physics_mean": hgefs_like.get("physics_mean"),
                            "ai_mean": hgefs_like.get("ai_mean"),
                            "nbm_p50": nbm.get("p50"),
                            "metar_temp_f": metar,
                            "trigger_reason": trigger_reason,
                            "hgefs_proxy": int(using_proxy),
                            "strategy_sleeve": "CORE_HGEFS_EMOS",
                            "reasoning": (llm_decision.reasoning if llm_decision else default_reasoning),
                        }
                    )
                    signal = dict(self.db.execute("SELECT * FROM signals WHERE id = ?", (signal_id,))[0])
                    signal["spread"] = bracket.get("spread") or "0"
                    self.paper_trader.on_signal(signal)
                    if self.live_trader is not None:
                        self.live_trader.on_signal(signal)

                    # Write pending memory entry after the trade is placed.
                    if self.weather_memory is not None:
                        self.weather_memory.write_pending(
                            city,
                            {
                                "trade_date": target_date,
                                "ticker": bracket["ticker"],
                                "bracket": bracket.get("bracket_label"),
                                "direction": gate["direction"],
                                "entry_price": entry_price,
                                "emos_prob": emos_prob,
                                "gumbel_prob": prob,
                                "gap_pp": gate["gap_pp"],
                                "confidence_score": confidence,
                                "gate1_reason": gate.gate1.reason,
                                "gate5_reason": gate.gate5.reason,
                                "gate6_reason": gate.gate6.reason,
                                "llm_action": llm_decision.action if llm_decision else None,
                                "llm_reasoning": llm_decision.reasoning if llm_decision else None,
                                "llm_key_risk": llm_decision.key_risk if llm_decision else None,
                            },
                        )

                # SLEEVE: TAIL_NO — model says bracket unlikely but market still priced in
                self._check_tail_no_sleeve(city, bracket, target_date, gate_prob, market_price)

                # SLEEVE: DEEP_TAIL_NO — model says near-zero probability
                self._check_deep_tail_no_sleeve(
                    city, bracket, target_date, gate_prob, market_price, hgefs_like, models, nbm, metar
                )

            # SLEEVE: LADDER_EVENT — event-level Strategy 2 portfolio.
            # Runs after all bracket probabilities are known, so the sleeve can
            # reason about top YES brackets and clearly wrong NO brackets together.
            self._check_ladder_event_sleeve(city, target_date, ladder_candidates, hgefs_like, models, nbm)

    def _check_ladder_event_sleeve(
        self,
        city: str,
        target_date: str,
        candidates: list[dict],
        hgefs_like: dict,
        models: dict,
        nbm: Optional[dict],
    ) -> None:
        """Strategy 2: event-level YES/NO ladder sleeve.

        Paper-only implementation of the ColdMath-inspired idea:
        - Anchor the event with 1-2 YES legs where model probability is well
          above market.
        - Add up to 3 NO legs on clearly wrong central brackets where the model
          says the bracket is near-impossible but the market still offers 86-93c NO.

        The sleeve is deliberately same-day and morning-only.  It avoids tail
        markets in v1 because DEEP_TAIL_NO already owns tail logic and lower
        wings remain suspended by paper policy.
        """
        if not _cp.PAPER_LADDER_EVENT_ENABLED:
            return

        now_et = datetime.now(ZoneInfo("America/New_York"))
        start = self._parse_et_time(_cp.PAPER_LADDER_ENTRY_START_ET)
        end = self._parse_et_time(_cp.PAPER_LADDER_ENTRY_END_ET)
        if not (start <= now_et.time() <= end):
            return
        if _cp.PAPER_LADDER_TODAY_ONLY and target_date != now_et.date().isoformat():
            return
        if not candidates:
            return

        g1_pass, _ = check_gate_1(
            hgefs_like.get("physics_mean"),
            hgefs_like.get("physics_spread"),
            hgefs_like.get("ai_mean"),
            hgefs_like.get("ai_spread"),
            wethr_models=models,
            nbm_p50=nbm.get("p50") if nbm else None,
        )
        if not g1_pass:
            return

        existing = self.db.execute(
            """
            SELECT id FROM signals
            WHERE city = ? AND target_date = ? AND strategy_sleeve = 'LADDER_EVENT'
            LIMIT 1
            """,
            (city, target_date),
        )
        if existing:
            logger.info("ladder_event %s %s: already emitted today — skipping", city, target_date)
            return

        central = [
            c
            for c in candidates
            if c["bracket"].get("bracket_type", "central") == "central" and self._liquid(c["bracket"])
        ]
        if not central:
            return

        top = max(central, key=lambda c: float(c["model_prob"]))
        top_center = self._bracket_center(top["bracket"])

        yes_legs = []
        for cand in sorted(central, key=lambda c: float(c["model_prob"]), reverse=True):
            bracket = cand["bracket"]
            prob = float(cand["model_prob"])
            yes_price = float(cand["market_price"])
            edge_pp = (prob - yes_price) * 100.0
            if prob < float(_cp.PAPER_LADDER_YES_MIN_PROB):
                continue
            if edge_pp < float(_cp.PAPER_LADDER_YES_MIN_EDGE_PP):
                continue
            if yes_price >= float(config.NEVER_HOLD_ABOVE):
                continue
            yes_legs.append(
                {
                    "bracket": bracket,
                    "direction": "YES",
                    "entry_price": yes_price,
                    "model_prob": prob,
                    "gap_pp": edge_pp,
                    "reason": (
                        f"LADDER_EVENT YES anchor: prob={prob:.3f}, price={yes_price:.2f}, edge={edge_pp:.1f}pp"
                    ),
                }
            )
            if len(yes_legs) >= int(_cp.PAPER_LADDER_MAX_YES_LEGS):
                break

        # Require at least one YES anchor so this remains an event ladder, not a
        # second independent deep-tail/NO sleeve.
        if not yes_legs:
            return

        yes_tickers = {leg["bracket"].get("ticker") for leg in yes_legs}
        no_legs = []
        for cand in sorted(central, key=lambda c: float(c["model_prob"])):
            bracket = cand["bracket"]
            if bracket.get("ticker") in yes_tickers:
                continue
            prob = float(cand["model_prob"])
            if prob > float(_cp.PAPER_LADDER_NO_MAX_MODEL_PROB):
                continue
            distance = abs(self._bracket_center(bracket) - top_center)
            if distance < float(_cp.PAPER_LADDER_NO_MIN_DISTANCE_F):
                continue
            no_entry = self._no_entry_price(bracket)
            if not (
                float(_cp.PAPER_LADDER_NO_MIN_ENTRY_PRICE) <= no_entry <= float(_cp.PAPER_LADDER_NO_MAX_ENTRY_PRICE)
            ):
                continue
            side_edge_pp = ((1.0 - prob) - no_entry) * 100.0
            no_legs.append(
                {
                    "bracket": bracket,
                    "direction": "NO",
                    "entry_price": no_entry,
                    "model_prob": prob,
                    "gap_pp": side_edge_pp,
                    "reason": (
                        f"LADDER_EVENT NO harvest: prob_yes={prob:.3f}, no_entry={no_entry:.2f}, "
                        f"distance={distance:.1f}F, side_edge={side_edge_pp:.1f}pp"
                    ),
                }
            )
            if len(no_legs) >= int(_cp.PAPER_LADDER_MAX_NO_LEGS):
                break

        legs = yes_legs + no_legs
        logger.info(
            "ladder_event %s %s: emitting %d legs (%d YES, %d NO)",
            city,
            target_date,
            len(legs),
            len(yes_legs),
            len(no_legs),
        )
        for leg in legs:
            self._emit_ladder_event_signal(city, target_date, leg)

    def _emit_ladder_event_signal(self, city: str, target_date: str, leg: dict) -> None:
        bracket = leg["bracket"]
        entry_price = float(leg["entry_price"])
        direction = leg["direction"]
        signal_id = self.db.insert_signal(
            {
                "city": city,
                "ticker": bracket.get("ticker"),
                "target_date": target_date,
                "bracket": bracket.get("bracket_label"),
                "bracket_lo": bracket.get("strike_lo"),
                "bracket_hi": bracket.get("strike_hi"),
                "direction": direction,
                "entry_price": entry_price,
                "target_price": float(config.TARGET_EXIT_PRICE),
                "stop_price": max(0.0, entry_price - float(config.STOP_LOSS_DIFF)),
                "model_prob": float(leg["model_prob"]),
                "market_price": float(leg["entry_price"] if direction == "YES" else 1.0 - entry_price),
                "gap_pp": float(leg["gap_pp"]),
                "confidence_score": float(_cp.PAPER_LADDER_CONFIDENCE),
                "trigger_reason": "ladder_event_10am",
                "strategy_sleeve": "LADDER_EVENT",
                "reasoning": leg["reason"],
            }
        )
        signal = dict(self.db.execute("SELECT * FROM signals WHERE id = ?", (signal_id,))[0])
        signal["spread"] = bracket.get("spread") or "0"
        self.paper_trader.on_signal(signal)

    async def fire_bracket_lock_check(self, city: str) -> None:
        """
        Strategy 3 sleeve: enter YES on the bracket containing today's running
        ASOS daily max when the temp peak is clearly established (3 PM ET window).

        Conditions (all must hold):
          1. PAPER_BRACKET_LOCK_ENABLED is True
          2. Not inside DSM cancel window
          3. wethr_high_f is available and within a Kalshi bracket (not tail)
          4. upper_margin ≥ PAPER_BRACKET_LOCK_MIN_MARGIN_F  (running max safely inside bracket)
          5. NWS remaining-day max ≤ running_max + PAPER_BRACKET_LOCK_NWS_BUFFER_F
          6. No existing S3_BRACKET_LOCK_YES position already open for today's bracket
          7. YES price in [PAPER_BRACKET_LOCK_MIN_PRICE, PAPER_BRACKET_LOCK_MAX_PRICE]

        Backtest (571 days, Oct 2024–Apr 2026, upper_margin≥1°F):
          78.4% win rate, avg entry 64c, EV $12.11/100 contracts, Sharpe 0.382
        """
        import paper_trader.config_paper as _cp

        if not _cp.PAPER_BRACKET_LOCK_ENABLED:
            return

        now_et = datetime.now(ZoneInfo("America/New_York"))
        if self._is_dsm_window(now_et):
            logger.info("bracket_lock skipped for %s — inside DSM cancel window", city)
            return

        cfg = config.CITIES[city]
        station = cfg["wethr_station"]

        # Use city's local time for the 3 PM check so KMDW (CT) waits until
        # 3 PM CT (= 4 PM ET) instead of firing at 3 PM ET (= 2 PM CT) before
        # Chicago's daily high is established.
        city_tz = ZoneInfo(cfg.get("timezone", "America/New_York"))
        now_local = datetime.now(city_tz)
        if now_local.time() < dt_time(15, 0):
            logger.debug("bracket_lock skipped for %s — not yet 3 PM local (%s)", city, now_local.strftime("%H:%M %Z"))
            return

        today_str = now_local.date().isoformat()

        # Step 1: Get running daily max from latest METAR obs
        obs_rows = self.db.execute(
            """
            SELECT wethr_high_f, temp_f, observation_time
            FROM metar_observations
            WHERE station = ?
              AND observation_time >= ?
            ORDER BY observation_time DESC LIMIT 1
            """,
            (station, today_str),
        )
        if not obs_rows:
            logger.debug("bracket_lock %s: no intraday obs found", city)
            return

        obs = obs_rows[0]
        running_max = obs.get("wethr_high_f") or obs.get("temp_f")
        if running_max is None:
            logger.debug("bracket_lock %s: wethr_high_f is None", city)
            return
        running_max = float(running_max)

        # Step 2: Get active same-day brackets from Kalshi
        markets = self.kalshi.get_active_markets(cfg["series_ticker"])
        brackets = self.kalshi.parse_brackets(markets)
        today_brackets = [b for b in brackets if b.get("target_date") == today_str]
        if not today_brackets:
            logger.debug("bracket_lock %s: no same-day brackets available", city)
            return

        # Step 3: Find the bracket containing running_max
        running_max_int = int(round(running_max))
        predicted_bracket = None
        for bracket in today_brackets:
            lo = bracket.get("strike_lo")
            hi = bracket.get("strike_hi")
            if lo is None or hi is None:
                continue
            lo_int, hi_int = int(lo), int(hi)
            if lo_int <= running_max_int <= hi_int:
                predicted_bracket = bracket
                break

        if predicted_bracket is None:
            logger.info(
                "bracket_lock %s: running_max=%.1f°F not in any bracket (tail territory)",
                city,
                running_max,
            )
            return

        # Step 4: Compute upper_margin
        bracket_hi = float(predicted_bracket.get("strike_hi", running_max + 1))
        upper_margin = bracket_hi - running_max
        if upper_margin < _cp.PAPER_BRACKET_LOCK_MIN_MARGIN_F:
            logger.info(
                "bracket_lock %s: upper_margin=%.1f°F < %.1f threshold — skipping",
                city,
                upper_margin,
                _cp.PAPER_BRACKET_LOCK_MIN_MARGIN_F,
            )
            return

        # Step 5: NWS remaining-day forecast filter
        nws_remaining = fetch_nws_remaining_max_f(station, lookahead_hours=6, wethr_client=self.wethr)
        if nws_remaining is not None:
            nws_ceiling = running_max + _cp.PAPER_BRACKET_LOCK_NWS_BUFFER_F
            if nws_remaining > nws_ceiling:
                logger.info(
                    "bracket_lock %s: NWS remaining max=%.1f°F > ceiling=%.1f°F — skipping",
                    city,
                    nws_remaining,
                    nws_ceiling,
                )
                return
        else:
            logger.debug("bracket_lock %s: NWS forecast unavailable — proceeding without it", city)

        # Precipitation gate: dry days have more stable peaks
        now_date_str = now_et.date().isoformat()
        precip_data = self.db.get_precipitation_today(station, now_date_str)
        precip_today = precip_data.get("precip_today_in") if precip_data else None
        if precip_today is not None and precip_today > 0.25:
            logger.info(
                "bracket_lock %s: precip_today=%.2f\" — wet day, peak may not be established",
                city, precip_today,
            )
            # Don't skip — wet days can still lock, just log as lower confidence

        # Step 6: Check no existing BRACKET_LOCK position for this ticker today
        ticker = predicted_bracket["ticker"]
        existing = self.db.execute(
            """
            SELECT id FROM paper_trades
            WHERE city = ? AND ticker = ? AND strategy_sleeve = 'S3_BRACKET_LOCK_YES'
              AND target_date = ?
              AND exit_time IS NULL
            LIMIT 1
            """,
            (city, ticker, today_str),
        )
        if existing:
            logger.info("bracket_lock %s: position already open for %s — skipping", city, ticker)
            return

        # Step 7: Check YES price range
        current_prices = self._get_current_prices()
        market_price = self._yes_maker_entry_price(predicted_bracket)
        if market_price is None:
            market_price = current_prices.get(ticker)
        if market_price is None:
            logger.debug("bracket_lock %s: no price for %s", city, ticker)
            return
        market_price = float(market_price)

        if not (_cp.PAPER_BRACKET_LOCK_MIN_PRICE <= market_price <= _cp.PAPER_BRACKET_LOCK_MAX_PRICE):
            logger.info(
                "bracket_lock %s: price=%.2f outside [%.2f, %.2f] — skipping",
                city,
                market_price,
                _cp.PAPER_BRACKET_LOCK_MIN_PRICE,
                _cp.PAPER_BRACKET_LOCK_MAX_PRICE,
            )
            return

        # All conditions met — generate signal
        dry_day_bonus = 5.0 if (precip_today is not None and precip_today == 0.0) else 0.0
        logger.info(
            "bracket_lock %s ENTRY: %s YES @ %.2f | running_max=%.1f°F upper_margin=%.1f°F nws_remaining=%s°F",
            city,
            ticker,
            market_price,
            running_max,
            upper_margin,
            f"{nws_remaining:.1f}" if nws_remaining else "N/A",
        )

        signal_id = self.db.insert_signal(
            {
                "city": city,
                "ticker": ticker,
                "target_date": today_str,
                "bracket": predicted_bracket.get("bracket_label"),
                "bracket_lo": predicted_bracket.get("strike_lo"),
                "bracket_hi": predicted_bracket.get("strike_hi"),
                "direction": "YES",
                "entry_price": market_price,
                "target_price": _cp.PAPER_BRACKET_LOCK_TARGET_PRICE,
                "stop_price": max(0.0, market_price - _cp.PAPER_BRACKET_LOCK_STOP_DIFF),
                "model_prob": 0.80,
                "market_price": market_price,
                "gap_pp": None,
                "confidence_score": 75.0 + dry_day_bonus,
                "physics_mean": None,
                "ai_mean": None,
                "nbm_p50": None,
                "metar_temp_f": running_max,
                "trigger_reason": "bracket_lock_3pm",
                "hgefs_proxy": 0,
                "strategy_sleeve": "S3_BRACKET_LOCK_YES",
                "never_hold_above": 0.99,
                "reasoning": (
                    f"Intraday lock: running_max={running_max:.1f}°F in bracket "
                    f"{predicted_bracket.get('bracket_label')}; "
                    f"upper_margin={upper_margin:.1f}°F; "
                    f"nws_remaining={nws_remaining:.1f}°F"
                    if nws_remaining
                    else f"Intraday lock: running_max={running_max:.1f}°F; upper_margin={upper_margin:.1f}°F"
                ),
            }
        )
        signal = dict(self.db.execute("SELECT * FROM signals WHERE id = ?", (signal_id,))[0])
        signal["spread"] = predicted_bracket.get("spread") or "0"
        signal["n_contracts"] = _cp.PAPER_BRACKET_LOCK_SIZE
        signal["target_price"] = _cp.PAPER_BRACKET_LOCK_TARGET_PRICE
        signal["stop_price"] = max(0.0, market_price - _cp.PAPER_BRACKET_LOCK_STOP_DIFF)
        signal["never_hold_above"] = 0.99
        trade = self.paper_trader.on_signal(signal)
        if trade is not None:
            self._fire_far_bracket_no_overlay(
                city=city,
                target_date=today_str,
                predicted_bracket=predicted_bracket,
                brackets=today_brackets,
                running_max=running_max,
            )

    def _fire_far_bracket_no_overlay(
        self,
        city: str,
        target_date: str,
        predicted_bracket: dict,
        brackets: list[dict],
        running_max: float,
    ) -> None:
        """Strategy 1: buy NO on far-away central brackets after Strategy 3 locks.

        This is deliberately a separate paper-only sleeve from Strategy 3. It
        does not touch live execution and excludes tail markets until the paper
        sample is larger.
        """
        if not _cp.PAPER_FAR_BRACKET_NO_OVERLAY_ENABLED:
            return

        pred_floor = predicted_bracket.get("strike_lo")
        if pred_floor is None:
            return
        pred_floor = float(pred_floor)

        for bracket in brackets:
            if bracket.get("ticker") == predicted_bracket.get("ticker"):
                continue
            if bracket.get("bracket_type") != "central":
                continue
            strike_lo = bracket.get("strike_lo")
            if strike_lo is None:
                continue
            distance = abs(float(strike_lo) - pred_floor)
            if distance < _cp.PAPER_FAR_BRACKET_NO_MIN_DISTANCE_F:
                continue

            ticker = bracket["ticker"]
            no_entry = self._no_maker_entry_price(bracket)
            if no_entry is None:
                continue
            no_entry = float(no_entry)
            if not (_cp.PAPER_FAR_BRACKET_NO_MIN_PRICE <= no_entry <= _cp.PAPER_FAR_BRACKET_NO_MAX_PRICE):
                continue

            existing = self.db.execute(
                """
                SELECT id FROM paper_trades
                WHERE city = ? AND ticker = ? AND direction = 'NO'
                  AND target_date = ?
                  AND exit_time IS NULL
                LIMIT 1
                """,
                (city, ticker, target_date),
            )
            if existing:
                continue

            logger.info(
                "far_bracket_no_overlay %s ENTRY: %s NO @ %.2f | running_max=%.1f°F distance=%.1f°F",
                city, ticker, no_entry, running_max, distance,
            )

            signal_id = self.db.insert_signal(
                {
                    "city": city,
                    "ticker": ticker,
                    "target_date": target_date,
                    "bracket": bracket.get("bracket_label"),
                    "bracket_lo": bracket.get("strike_lo"),
                    "bracket_hi": bracket.get("strike_hi"),
                    "direction": "NO",
                    "entry_price": no_entry,
                    "target_price": _cp.PAPER_FAR_BRACKET_NO_TARGET_PRICE,
                    "stop_price": max(0.0, no_entry - _cp.PAPER_FAR_BRACKET_NO_STOP_DIFF),
                    "model_prob": 0.01,
                    "market_price": self._yes_maker_entry_price(bracket),
                    "gap_pp": None,
                    "confidence_score": 95.0,
                    "metar_temp_f": running_max,
                    "trigger_reason": "far_bracket_no_overlay_3pm",
                    "hgefs_proxy": 0,
                    "strategy_sleeve": "S1_FAR_BRACKET_NO_OVERLAY",
                    "reasoning": (
                        f"Strategy 1 NO overlay: bracket {bracket.get('bracket_label')} is "
                        f"{distance:.1f}°F from confirmed 3PM bracket "
                        f"{predicted_bracket.get('bracket_label')}; running_max={running_max:.1f}°F"
                    ),
                }
            )
            signal = dict(self.db.execute("SELECT * FROM signals WHERE id = ?", (signal_id,))[0])
            signal["spread"] = bracket.get("spread") or "0"
            signal["n_contracts"] = _cp.PAPER_FAR_BRACKET_NO_SIZE
            signal["target_price"] = _cp.PAPER_FAR_BRACKET_NO_TARGET_PRICE
            signal["stop_price"] = max(0.0, no_entry - _cp.PAPER_FAR_BRACKET_NO_STOP_DIFF)
            self.paper_trader.on_signal(signal)

    async def on_stream_new_high(self, station: str, high_f: float, ts, payload: dict) -> None:
        """Called by WethrStreamClient when a new_high event fires."""
        for city, cfg in self._active_cities():
            if cfg["wethr_station"] == station:
                logger.info("Stream new_high for %s %.1f°F — checking bracket lock", city, high_f)
                try:
                    await self.fire_bracket_lock_check(city)
                except Exception as exc:
                    logger.warning("Stream bracket_lock check failed for %s: %s", city, exc)
                break

    async def on_stream_cli(self, station: str, cli_high_f, cli_low_f, ts, payload: dict) -> None:
        """Called by WethrStreamClient when a cli event fires — immediate settlement."""
        logger.info("Stream CLI event for %s: high=%s low=%s", station, cli_high_f, cli_low_f)
        try:
            await self.check_cli_settlements()
        except Exception as exc:
            logger.warning("Stream CLI settlement check failed: %s", exc)

    async def on_stream_dsm(self, station: str, dsm_high_f, ts, payload: dict) -> None:
        """Called by WethrStreamClient when a dsm event fires."""
        logger.info("Stream DSM event for %s: high=%s", station, dsm_high_f)
        for city, cfg in self._active_cities():
            if cfg["wethr_station"] == station:
                dsm_ts = ts or payload.get("dsm_received_at", "")
                if dsm_ts and dsm_ts != self._last_dsm_received.get(station):
                    self._last_dsm_received[station] = str(dsm_ts)
                    try:
                        obs_like = {
                            "dsm_high_f": dsm_high_f,
                            "dsm_received_at": dsm_ts,
                            "caution_flag": payload.get("caution_flag", 0),
                        }
                        self.db.insert_dsm_report(self._dsm_record_from_obs(city, station, obs_like))
                    except Exception as exc:
                        logger.warning("Stream DSM record insert failed for %s: %s", city, exc)
                break

    @staticmethod
    def _yes_maker_entry_price(bracket: dict) -> float | None:
        """Visible YES bid for maker-style paper entry."""
        val = bracket.get("yes_bid")
        if val is None:
            return None
        try:
            return round(float(val), 4)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _no_maker_entry_price(bracket: dict) -> float | None:
        """Visible NO bid = 1 - YES ask for maker-style paper entry."""
        no_bid = bracket.get("no_bid")
        if no_bid is not None:
            try:
                return round(float(no_bid), 4)
            except (TypeError, ValueError):
                pass
        yes_ask = bracket.get("yes_ask")
        if yes_ask is None:
            return None
        try:
            return round(max(0.0, min(1.0, 1.0 - float(yes_ask))), 4)
        except (TypeError, ValueError):
            return None

    def _get_current_prices(self) -> dict:
        """Return {ticker: last_yes_price} from kalshi_prices without API calls."""
        rows = self.db.execute(
            """
            SELECT ticker, yes_last, yes_ask, yes_bid
            FROM kalshi_prices
            WHERE id IN (SELECT MAX(id) FROM kalshi_prices GROUP BY ticker)
            """
        )
        prices = {}
        for row in rows:
            for col in ("yes_last", "yes_ask", "yes_bid"):
                val = row[col]
                if val is not None:
                    try:
                        prices[row["ticker"]] = float(val)
                        break
                    except (ValueError, TypeError):
                        continue
        return prices

    @staticmethod
    def _allowed_target_dates(now_local: datetime) -> set[str]:
        return {
            (now_local.date() + timedelta(days=offset)).isoformat()
            for offset in range(config.TRADE_TARGET_DAYS_AHEAD + 1)
        }

    @staticmethod
    def _next_day_target_date(now_local: datetime) -> str:
        """Target date for markets that just opened today at 10 AM local time."""
        return (now_local.date() + timedelta(days=1)).isoformat()

    @staticmethod
    def _brackets_for_trading_horizon(brackets: list[dict], allowed_dates: set[str], city: str = "") -> list[dict]:
        """Keep only brackets whose ticker date is in the configured trading horizon."""
        filtered = []
        for bracket in brackets:
            bracket_date = bracket.get("target_date")
            ticker = bracket.get("ticker")
            if bracket_date not in allowed_dates:
                logger.warning(
                    "Skipping out-of-horizon Kalshi market for %s: ticker=%s ticker_date=%s allowed_dates=%s",
                    city,
                    ticker,
                    bracket_date,
                    sorted(allowed_dates),
                )
                continue
            filtered.append(bracket)
        return filtered

    @staticmethod
    def _brackets_for_target_date(brackets: list[dict], target_date: str, city: str = "") -> list[dict]:
        """Compatibility wrapper for callers that need exactly one event date."""
        return EventTriggerEngine._brackets_for_trading_horizon(brackets, {target_date}, city)

    @staticmethod
    def _group_brackets_by_target_date(brackets: list[dict]) -> dict[str, list[dict]]:
        grouped: dict[str, list[dict]] = {}
        for bracket in brackets:
            target_date = bracket.get("target_date")
            if target_date is None:
                continue
            grouped.setdefault(target_date, []).append(bracket)
        return grouped

    def _is_dsm_window(self, now_et: datetime) -> bool:
        """True if current time is in any active city's DSM cancel window (ET).

        DSM fire times (EDT, UTC-4):
          KNYC/KMIA/KPHL: 20:21 UTC = 16:21 ET → window opens 16:15
          KMDW/KXLOWTCHI: 21:17 UTC = 17:17 ET
          KXLOWTDEN:       22:17 UTC = 18:17 ET  ← requires window to extend past 17:30

        Extended combined window 16:15–18:30 ET covers all active cities.
        The extra 60 min past the old 17:30 end blocks at most 9 gate-passing
        signals per week (backtest validated) and zero historical alpha is lost
        because no strategy entries were ever designed to fire after 5:30 PM ET.
        """
        t = now_et.time()
        return dt_time(16, 15) <= t <= dt_time(18, 30)

    def _get_last_known_yes_price(self, ticker: str) -> float | None:
        """Return the most recently stored yes price for ticker (no recency filter)."""
        rows = self.db.execute(
            """
            SELECT yes_last, yes_ask, yes_bid FROM kalshi_prices
            WHERE ticker = ?
            ORDER BY id DESC LIMIT 1
            """,
            (ticker,),
        )
        if not rows:
            return None
        for col in ("yes_last", "yes_ask", "yes_bid"):
            val = rows[0][col]
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    continue
        return None

    def _enforce_time_exits(self, now_et: datetime) -> None:
        """Force-close all open trades at 11 PM ET."""
        if now_et.time() < dt_time(23, 0):
            return
        current_prices = self._get_current_prices()

        for trade in self.db.get_open_trades():
            ticker = trade["ticker"]
            yes_price = current_prices.get(ticker) or self._get_last_known_yes_price(ticker)
            if yes_price is not None:
                price = self.paper_trader.current_side_price(trade, yes_price)
                reason = "TIME_LIMIT"
            else:
                # Truly no price ever stored — exit at entry_price and flag clearly
                price = float(trade.get("entry_price", 0))
                reason = "TIME_LIMIT_NO_PRICE"
                logger.warning("TIME_LIMIT for %s: no stored price found, exiting at entry_price=%.2f", ticker, price)
            self.paper_trader._exit_trade(trade["id"], price, reason)
            logger.info("TIME_LIMIT paper exit for %s at %.2f (reason=%s)", ticker, price, reason)

        if self.live_trader is None:
            return
        for trade in self.db.get_open_live_trades():
            ticker = trade["ticker"]
            yes_price = current_prices.get(ticker) or self._get_last_known_yes_price(ticker)
            if yes_price is not None:
                price = self.live_trader.current_side_price(trade, yes_price)
                reason = "TIME_LIMIT"
            else:
                price = float(trade.get("entry_price", 0))
                reason = "TIME_LIMIT_NO_PRICE"
                logger.warning("TIME_LIMIT live for %s: no stored price found, exiting at entry_price=%.2f", ticker, price)
            order_status = trade.get("order_status", "resting")
            filled_count = int(trade.get("filled_count", 0) or 0)
            self.live_trader._exit_trade(int(trade["id"]), price, reason, order_status, filled_count)
            logger.info("TIME_LIMIT live exit for %s at %.2f (reason=%s)", ticker, price, reason)

    def _log_candidate(
        self, city: str, bracket: dict, target_date: str, gate: dict, prob: float, market_price: float, hgefs_like: dict
    ) -> None:
        """Record every gate evaluation to candidate_signals for research."""
        from datetime import UTC as _UTC

        self.db.insert_candidate_signal(
            {
                "created_at": datetime.now(_UTC).isoformat(),
                "city": city,
                "ticker": bracket.get("ticker"),
                "target_date": target_date,
                "bracket": bracket.get("bracket_label"),
                "strategy_sleeve": "CORE_HGEFS_GUMBEL",
                "direction": gate.get("direction"),
                "yes_price": market_price,
                "model_prob": prob,
                "gap_pp": gate.get("gap_pp"),
                "confidence_score": gate.get("confidence_score"),
                "hgefs_real": int(gate.get("gate1", {}).get("hgefs_real", False)),
                "ai_source": hgefs_like.get("gate1_ai_source"),
                "physics_mean": hgefs_like.get("physics_mean"),
                "ai_mean": hgefs_like.get("ai_mean"),
                "gate1_pass": int(gate["gate1"]["pass"]),
                "gate2_pass": int(gate["gate2"]["pass"]),
                "gate3_pass": int(gate["gate3"]["pass"]),
                "gate4_pass": int(gate["gate4"]["pass"]),
                "gate5_pass": int(gate["gate5"]["pass"]),
                "gate6_pass": int(gate["gate6"]["pass"]),
                "would_pass_core": int(gate["all_pass"]),
            }
        )

    def _check_tail_no_sleeve(
        self, city: str, bracket: dict, target_date: str, prob: float, market_price: float
    ) -> None:
        """TAIL_NO: tightened research sleeve, logged by default but not traded."""
        if prob >= config.TAIL_NO_PROB_MAX or market_price <= float(config.TAIL_NO_YES_PRICE_MIN):
            return
        no_entry = self._no_entry_price(bracket)
        if no_entry <= 0 or no_entry >= 1:
            return
        confidence = 40.0
        gap_pp = (prob - market_price) * 100
        self.db.insert_candidate_signal(
            {
                "city": city,
                "ticker": bracket.get("ticker"),
                "target_date": target_date,
                "bracket": bracket.get("bracket_label"),
                "strategy_sleeve": "TAIL_NO",
                "direction": "NO",
                "yes_price": market_price,
                "model_prob": prob,
                "gap_pp": gap_pp,
                "confidence_score": confidence,
                "would_pass_core": 0,
                "notes": (
                    f"TAIL_NO candidate: model={prob:.3f}<{config.TAIL_NO_PROB_MAX:.2f} "
                    f"market={market_price:.2f}>{float(config.TAIL_NO_YES_PRICE_MIN):.2f} "
                    f"no_entry={no_entry:.2f}; trade_enabled={config.ENABLE_TAIL_NO_TRADES}"
                ),
            }
        )
        if not config.ENABLE_TAIL_NO_TRADES:
            return
        signal = {
            "id": None,
            "city": city,
            "ticker": bracket.get("ticker"),
            "target_date": target_date,
            "bracket": bracket.get("bracket_label"),
            "direction": "NO",
            "entry_price": no_entry,
            "market_price": market_price,
            "model_prob": prob,
            "confidence_score": confidence,
            "spread": str(bracket.get("spread") or "0"),
            "strategy_sleeve": "TAIL_NO",
        }
        signal_id = self.db.insert_signal(
            {
                "city": city,
                "ticker": bracket.get("ticker"),
                "target_date": target_date,
                "bracket": bracket.get("bracket_label"),
                "direction": "NO",
                "entry_price": no_entry,
                "market_price": market_price,
                "model_prob": prob,
                "gap_pp": gap_pp,
                "confidence_score": confidence,
                "strategy_sleeve": "TAIL_NO",
                "reasoning": (
                    f"TAIL_NO: model={prob:.3f}<{config.TAIL_NO_PROB_MAX:.2f} "
                    f"market={market_price:.2f}>{float(config.TAIL_NO_YES_PRICE_MIN):.2f}"
                ),
            }
        )
        signal["id"] = signal_id
        self.paper_trader.on_signal(signal)

    def _check_deep_tail_no_sleeve(
        self,
        city: str,
        bracket: dict,
        target_date: str,
        prob: float,
        market_price: float,
        hgefs_like: dict,
        models: dict,
        nbm: Optional[dict],
        metar: Optional[float],
    ) -> None:
        """DEEP_TAIL_NO: model says < 2% probability but market still > 5¢.

        NO entries can be well above NEVER_HOLD_ABOVE (e.g. 90c) because we are
        on the NO side.  The YES price floor (DEEP_TAIL_NO_YES_PRICE_MIN) already
        bounds NO entry below 95c.  Gate 1 (model convergence) guards against
        placing high-stakes tail bets when the ensemble disagrees.  METAR blocks
        the trade when the morning observation is already inside the tail bracket.
        """
        if prob >= config.DEEP_TAIL_NO_PROB_MAX or market_price <= float(config.DEEP_TAIL_NO_YES_PRICE_MIN):
            return
        no_entry = self._no_entry_price(bracket)
        if no_entry <= 0 or no_entry >= 1:
            return
        # Require model convergence before betting on extreme tail
        g1_pass, _ = check_gate_1(
            hgefs_like.get("physics_mean"),
            hgefs_like.get("physics_spread"),
            hgefs_like.get("ai_mean"),
            hgefs_like.get("ai_spread"),
            wethr_models=models,
            nbm_p50=nbm.get("p50") if nbm else None,
        )
        if not g1_pass:
            return
        # METAR check: if the morning observation is already inside the tail bracket,
        # the bracket is still live and we skip.  Missing METAR = neutral (no block).
        if metar is not None:
            btype = bracket.get("bracket_type", "central")
            strike_hi = bracket.get("strike_hi")
            strike_lo = bracket.get("strike_lo")
            if btype == "wing_low" and strike_hi is not None and metar <= float(strike_hi):
                return  # cold morning — low tail still reachable
            if btype == "wing_high" and strike_lo is not None and metar >= float(strike_lo):
                return  # hot morning — high tail still reachable
        self.db.insert_candidate_signal(
            {
                "city": city,
                "ticker": bracket.get("ticker"),
                "target_date": target_date,
                "bracket": bracket.get("bracket_label"),
                "strategy_sleeve": "DEEP_TAIL_NO",
                "direction": "NO",
                "yes_price": market_price,
                "model_prob": prob,
                "gap_pp": (prob - market_price) * 100,
                "confidence_score": 50.0,
                "would_pass_core": 0,
                "notes": (
                    f"DEEP_TAIL_NO: model={prob:.4f}<{config.DEEP_TAIL_NO_PROB_MAX:.2f} "
                    f"market={market_price:.2f}>{float(config.DEEP_TAIL_NO_YES_PRICE_MIN):.2f}"
                ),
            }
        )
        if not config.ENABLE_DEEP_TAIL_NO_TRADES:
            return
        signal_id = self.db.insert_signal(
            {
                "city": city,
                "ticker": bracket.get("ticker"),
                "target_date": target_date,
                "bracket": bracket.get("bracket_label"),
                "direction": "NO",
                "entry_price": no_entry,
                "market_price": market_price,
                "model_prob": prob,
                "gap_pp": (prob - market_price) * 100,
                "confidence_score": 50.0,
                "strategy_sleeve": "DEEP_TAIL_NO",
                "reasoning": (
                    f"DEEP_TAIL_NO: model={prob:.4f}<{config.DEEP_TAIL_NO_PROB_MAX:.2f} near-zero probability"
                ),
            }
        )
        signal = {
            "id": signal_id,
            "city": city,
            "ticker": bracket.get("ticker"),
            "target_date": target_date,
            "bracket": bracket.get("bracket_label"),
            "direction": "NO",
            "entry_price": no_entry,
            "market_price": market_price,
            "model_prob": prob,
            "confidence_score": 50.0,
            "spread": str(bracket.get("spread") or "0"),
            "strategy_sleeve": "DEEP_TAIL_NO",
        }
        self.paper_trader.on_signal(signal)

    async def _fallback_loop(self) -> None:
        while True:
            now = datetime.now(ZoneInfo("America/New_York"))
            key = now.date().isoformat()
            if now.strftime("%H:%M") >= config.FALLBACK_ENTRY_ET and key not in self.triggered_today:
                self.triggered_today.add(key)
                for city, _ in self._active_cities():
                    try:
                        await self.fire_gate_check(city, "fallback_11am")
                    except Exception as exc:
                        logger.warning("fallback gate check failed for %s: %s", city, exc)
            await asyncio.sleep(60)

    async def _early_deep_tail_loop(self) -> None:
        """Fire DEEP_TAIL_NO checks at 10:15 AM ET — 15 min after tomorrow's markets list.

        KXHIGH markets open at ~10:00 AM ET the day BEFORE the target date.  Backtest
        over 13 months shows that entering at the open price (first listed price) yields
        the best PnL and win rate.  The 11 AM fallback already catches tomorrow's market
        ~1 hour after open, but this fires 45 min earlier for the DEEP_TAIL_NO sleeve
        only (no core gate computation), giving a consistent head start on newly-listed
        tail brackets before the market drifts toward fair value.
        """
        triggered: set[str] = set()
        while True:
            now = datetime.now(ZoneInfo("America/New_York"))
            key = now.date().isoformat()
            if now.strftime("%H:%M") >= config.DEEP_TAIL_EARLY_ET and key not in triggered:
                triggered.add(key)
                for city, _ in self._active_cities():
                    try:
                        await self.fire_deep_tail_check(city)
                    except Exception as exc:
                        logger.warning("early deep-tail check failed for %s: %s", city, exc)
            await asyncio.sleep(60)

    async def fire_deep_tail_check(self, city: str) -> None:
        """Run only the DEEP_TAIL_NO sleeve for next-day newly opened brackets.

        Intentionally skips the full gate computation (core EMOS/Gumbel path) — those
        need 12Z model confidence and tighter spreads.  Tail probability is stable from
        the overnight 06Z run and doesn't need the full treatment.
        """
        cfg = config.CITIES[city]
        station = cfg["wethr_station"]
        now_local = datetime.now(ZoneInfo(cfg["timezone"]))
        target_date = self._next_day_target_date(now_local)
        markets = self.kalshi.get_active_markets(cfg["series_ticker"])
        brackets = self.kalshi.parse_brackets(markets)
        brackets = self._brackets_for_target_date(brackets, target_date, city)

        logger.info("Early deep-tail check for %s %s (%d brackets)", city, target_date, len(brackets))

        for target_date, target_brackets in self._group_brackets_by_target_date(brackets).items():
            models = self.wethr.get_all_models_maxt(station, target_date)
            hgefs_like = self._hgefs_or_fallback(city, models, target_date)
            nbm = self._latest_nbm(city, target_date) or {}
            consensus = self._consensus(hgefs_like, models, target_date)
            metar = None
            if consensus is None:
                continue

            for bracket in target_brackets:
                market_price = self._market_price(bracket)
                if market_price is None:
                    continue

                # Compute bracket probability (EMOS when available, else Gumbel)
                prob = self.gumbel.compute_bracket_prob(
                    bracket.get("strike_lo"),
                    bracket.get("strike_hi"),
                    consensus,
                    bracket.get("bracket_type", "central"),
                )
                prob = self.gumbel.bayesian_update_with_nbm(
                    prob,
                    nbm.get("p50"),
                    nbm.get("p10"),
                    nbm.get("p90"),
                    bracket.get("strike_lo"),
                    bracket.get("strike_hi"),
                    bracket.get("bracket_type", "central"),
                    bool(nbm.get("percentiles_real", True)),
                )
                prob = self.gumbel.apply_calibration(prob)

                if _cp.PAPER_ENABLE_EMOS and city in self.emos:
                    emos_prob = self.emos[city].bracket_probability(
                        bracket.get("strike_lo"),
                        bracket.get("strike_hi"),
                        bracket.get("bracket_type", "central"),
                        hgefs_like,
                        models,
                        nbm,
                        target_date,
                    )
                    if emos_prob is not None:
                        prob = emos_prob

                self._check_deep_tail_no_sleeve(
                    city,
                    bracket,
                    target_date,
                    prob,
                    market_price,
                    hgefs_like,
                    models,
                    nbm,
                    metar,
                )

    def _hgefs_or_fallback(self, city: str, models: dict, target_date: Optional[str] = None) -> dict:
        latest = self.db.get_model_run_latest(city, "HGEFS")
        if latest and target_date and latest.get("target_date") != target_date:
            logger.warning(
                "HGEFS run for %s targets %s, not %s — stale model data, treating as missing",
                city,
                latest.get("target_date"),
                target_date,
            )
            latest = None
        if latest and latest.get("physics_mean") is not None:
            raw = json.loads(latest.get("raw_data_json") or "{}")
            result = dict(latest)
            result["fallback"] = False
            result["member_counts"] = raw.get("member_counts", {})

            result["gate1_ai_source"] = "aigefs_real" if result.get("ai_mean") is not None else None

            # AIGEFS is currently blocked (NOMADS 403 for all file downloads).
            # When physics data is real but ai_mean is absent, use the multi-model
            # wethr consensus as the AI proxy so Gate 1 still runs a cross-check.
            # ai_spread is the actual std-dev of the wethr models, not a constant.
            if result.get("ai_mean") is None and models:
                effective_target_date = (
                    target_date or datetime.now(ZoneInfo(config.CITIES[city]["timezone"])).date().isoformat()
                )
                wethr_consensus = self.gumbel.compute_consensus_from_wethr(models, effective_target_date)
                if wethr_consensus is not None:
                    wethr_values = [float(v) for v in models.values() if v is not None]
                    import numpy as _np

                    ai_spread = float(_np.std(wethr_values)) if len(wethr_values) >= 2 else 1.5
                    result["ai_mean"] = wethr_consensus
                    result["ai_spread"] = ai_spread
                    result["ai_proxy"] = "wethr_consensus"
                    result["gate1_ai_source"] = "wethr_proxy"
                    logger.info(
                        "AIGEFS unavailable for %s; using wethr consensus %.1f°F (spread %.2f°F) as AI proxy",
                        city,
                        wethr_consensus,
                        ai_spread,
                    )
            return result

        # No physics data at all — try multi-model fallback
        if config.REQUIRE_HGEFS_FOR_SIGNALS:
            logger.warning("No real GEFS physics data available for %s; Gate 1 will fail", city)
            return {"physics_mean": None, "ai_mean": None, "physics_spread": None, "ai_spread": None}
        values = [float(v) for v in models.values() if v is not None]
        if len(values) >= config.FALLBACK_MIN_AGREEMENT:
            med = median(values)
            agreeing = [v for v in values if abs(v - med) <= config.FALLBACK_AGREEMENT_BAND]
            if len(agreeing) >= config.FALLBACK_MIN_AGREEMENT:
                return {
                    "physics_mean": med,
                    "ai_mean": med,
                    "physics_spread": 1.0,
                    "ai_spread": 1.0,
                    "fallback": True,
                }
        return {"physics_mean": None, "ai_mean": None, "physics_spread": None, "ai_spread": None}

    def _latest_nbm(self, city: str, target_date: Optional[str] = None) -> dict:
        if target_date is None:
            logger.warning("_latest_nbm called without target_date for %s — skipping to avoid stale data", city)
            return {}
        rows = self.db.execute(
            """
            SELECT * FROM model_runs
            WHERE city = ? AND model = ? AND target_date = ?
            ORDER BY run_time DESC, created_at DESC
            LIMIT 1
            """,
            (city, "NBM_BULLETIN", target_date),
        )
        latest = dict(rows[0]) if rows else None
        if latest and latest.get("nbm_p50") is not None:
            raw = json.loads(latest.get("raw_data_json") or "{}")
            return {
                "p10": latest.get("nbm_p10"),
                "p25": latest.get("nbm_p25"),
                "p50": latest.get("nbm_p50"),
                "p75": latest.get("nbm_p75"),
                "p90": latest.get("nbm_p90"),
                "percentiles_real": bool(raw.get("percentiles_real", False)),
                "derived_from": raw.get("derived_from"),
                "source_file": raw.get("source_file"),
            }
        return {}

    def _consensus(self, hgefs_like: dict, models: dict, target_date: str) -> Optional[float]:
        if hgefs_like.get("physics_mean") is not None and hgefs_like.get("ai_mean") is not None:
            return (float(hgefs_like["physics_mean"]) + float(hgefs_like["ai_mean"])) / 2
        return self.gumbel.compute_consensus_from_wethr(models, target_date)

    def _get_metar_951(self, station: str, target_date: str) -> Optional[float]:
        tz = ZoneInfo("America/New_York")
        start_local = datetime.fromisoformat(f"{target_date}T09:45:00").replace(tzinfo=tz)
        end_local = datetime.fromisoformat(f"{target_date}T10:05:00").replace(tzinfo=tz)
        try:
            rows = self.wethr.get_history(
                station,
                start_local.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
                end_local.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
            )
            candidates = []
            for row in rows:
                obs_time = row.get("observation_time")
                if not obs_time:
                    continue
                minute = datetime.fromisoformat(str(obs_time).replace("Z", "+00:00")).minute
                if 51 <= minute <= 54 and row.get("temperature") is not None:
                    candidates.append(row)
            row = candidates[-1] if candidates else (rows[-1] if rows else None)
            if row and row.get("temperature") is not None:
                return self.wethr.celsius_to_fahrenheit(float(row["temperature"]))
        except Exception as exc:
            logger.warning("METAR 9:51 lookup failed for %s: %s", station, exc)
        return None

    @staticmethod
    def _market_price(bracket: dict) -> Optional[float]:
        for key in ["yes_ask", "yes_last", "yes_bid"]:
            value = bracket.get(key)
            if value is not None:
                return float(value)
        return None

    @staticmethod
    def _no_entry_price(bracket: dict) -> float:
        """Executable NO ask = 1 - yes_bid (not 1 - yes_ask).
        YES bid at X means someone buys YES at X, so the NO ask is 1 - X.
        """
        yes_bid = bracket.get("yes_bid")
        if yes_bid is not None:
            return round(1.0 - float(yes_bid), 4)
        # Fallback if bid not available
        yes_ask = bracket.get("yes_ask") or bracket.get("yes_last")
        return round(1.0 - float(yes_ask), 4) if yes_ask is not None else 0.5

    @staticmethod
    def _bracket_center(bracket: dict) -> float:
        lo = bracket.get("strike_lo")
        hi = bracket.get("strike_hi")
        if lo is not None and hi is not None:
            return (float(lo) + float(hi)) / 2
        return float(lo if lo is not None else hi)

    @staticmethod
    def _liquid(bracket: dict) -> bool:
        spread = bracket.get("spread")
        if spread is None:
            return False
        limit = config.LIQUIDITY_CENTRAL_MAX if bracket.get("bracket_type") == "central" else config.LIQUIDITY_WING_MAX
        return spread <= limit

    @staticmethod
    def _parse_et_time(value: str) -> dt_time:
        hour, minute = [int(part) for part in value.split(":", 1)]
        return dt_time(hour, minute)

    def _fetch_and_store_nbm_bulletin(self, city: str, cfg: dict, target_date: str) -> None:
        date_str = datetime.now(UTC).strftime("%Y%m%d")
        for cycle in ["18", "12", "06", "00"]:
            nbm = self.model_fetcher.fetch_nbm_bulletin(date_str, cycle, cfg["wethr_station"])
            if nbm:
                # Use the forecast date parsed from the bulletin header when available;
                # fall back to the polling date only if parsing failed.
                stored_date = nbm.get("forecast_date") or target_date
                if stored_date != target_date:
                    logger.info(
                        "NBM bulletin for %s: bulletin forecast_date=%s overrides polling date=%s",
                        city,
                        stored_date,
                        target_date,
                    )
                self.db.insert_model_run(
                    {
                        "model": "NBM_BULLETIN",
                        "city": city,
                        "target_date": stored_date,
                        "run_time": nbm.get("run_time"),
                        "nbm_p10": nbm.get("p10"),
                        "nbm_p25": nbm.get("p25"),
                        "nbm_p50": nbm.get("p50"),
                        "nbm_p75": nbm.get("p75"),
                        "nbm_p90": nbm.get("p90"),
                        "raw_data_json": json.dumps(nbm),
                        "source": "nbm_bulletin",
                    }
                )
                if not nbm.get("percentiles_real"):
                    logger.warning(
                        "NBM bulletin for %s %s uses derived TXN/XND values; skipping full Bayesian percentile prior",
                        city,
                        nbm.get("run_time"),
                    )
                return

    def _fetch_and_store_hgefs(self, city: str, cfg: dict, target_date: str, date_str: str, cycle: str) -> None:
        logger.info("Fetching GEFS physics members for %s date=%s cycle=%s", city, date_str, cycle)
        result = self.model_fetcher.fetch_all_hgefs_members(date_str, cycle, cfg)
        physics_count = len(result.get("physics_members", {}))
        ai_count = len(result.get("ai_members", {}))

        # Physics threshold: need enough members for a meaningful ensemble mean.
        # AI (AIGEFS) may be absent if NOMADS blocks downloads; that is handled
        # later in _hgefs_or_fallback by substituting the wethr consensus.
        physics_ok = physics_count >= config.HGEFS_MIN_PHYSICS_MEMBERS and result.get("physics_mean") is not None
        ai_ok = ai_count >= config.HGEFS_MIN_AI_MEMBERS and result.get("ai_mean") is not None

        consensus_f = None
        if physics_ok and ai_ok:
            consensus_f = (result["physics_mean"] + result["ai_mean"]) / 2
        elif physics_ok:
            consensus_f = result["physics_mean"]

        self.db.insert_model_run(
            {
                "model": "HGEFS",
                "city": city,
                "target_date": target_date,
                "run_time": f"{date_str} {cycle}Z",
                # Always store physics data when available; ai_mean may be None.
                "physics_mean": result.get("physics_mean") if physics_ok else None,
                "physics_spread": result.get("physics_spread") if physics_ok else None,
                "ai_mean": result.get("ai_mean") if ai_ok else None,
                "ai_spread": result.get("ai_spread") if ai_ok else None,
                "aigefs_temp_raw": result.get("aigefs_temp_raw") if ai_ok else None,
                "aigefs_temp_corrected": result.get("aigefs_temp_corrected") if ai_ok else None,
                "consensus_temp_f": consensus_f,
                "raw_data_json": json.dumps(
                    {
                        **result,
                        "cycle": cycle,
                        "date_str": date_str,
                        "physics_ok": physics_ok,
                        "ai_ok": ai_ok,
                        "member_counts": {"physics": physics_count, "ai": ai_count},
                    },
                    default=str,
                ),
                "source": "nomads",
            }
        )
        if physics_ok:
            logger.info(
                "Stored GEFS physics %s %s: mean=%.1f°F spread=%.2f°F (%d members); AIGEFS=%s",
                city,
                cycle,
                result["physics_mean"],
                result.get("physics_spread", 0.0),
                physics_count,
                f"mean={result['ai_mean']:.1f}°F ({ai_count} members)" if ai_ok else "unavailable",
            )
        else:
            logger.warning(
                "GEFS %s %s insufficient: physics=%d (need %d), ai=%d",
                city,
                cycle,
                physics_count,
                config.HGEFS_MIN_PHYSICS_MEMBERS,
                ai_count,
            )

    @staticmethod
    def _latest_obs_record(station: str, obs: dict) -> dict:
        temp_c = obs.get("temperature")
        return {
            "station": station,
            "observation_time": obs.get("observation_time"),
            "temp_c": temp_c,
            "temp_f": WethrClient.celsius_to_fahrenheit(float(temp_c)) if temp_c is not None else None,
            "obs_type": obs.get("observation_type", "METAR"),
            "six_hour_high_f": WethrClient.celsius_to_fahrenheit(obs.get("six_hour_high"))
            if obs.get("six_hour_high") is not None
            else None,
            "six_hour_low_f": WethrClient.celsius_to_fahrenheit(obs.get("six_hour_low"))
            if obs.get("six_hour_low") is not None
            else None,
            "dew_point_c": obs.get("dew_point"),
            "wind_speed": obs.get("wind_speed"),
            "relative_humidity": obs.get("relative_humidity"),
            # Store DSM and CLI values from the METAR response so they're queryable
            # without a separate API call.
            "dsm_high_f": obs.get("dsm_high_f"),
            "cli_high_f": obs.get("cli_high_f"),
            "anomaly": int(bool(obs.get("anomaly", False))),
            "suspect_temp_json": json.dumps(obs["suspect_temperature"]) if obs.get("suspect_temperature") else None,
            "precision_level": obs.get("precision_level"),
            "raw_json": json.dumps(obs),
        }

    @staticmethod
    def _dsm_record_from_obs(city: str, station: str, obs: dict) -> dict:
        """Build a DSM record from a METAR obs response (no separate API call)."""
        return {
            "city": city,
            "station": station,
            "dsm_date": (obs.get("dsm_received_at") or "")[:10],
            "dsm_fire_time_utc": obs.get("dsm_received_at"),
            "max_temp_c": None,
            "max_temp_f": obs.get("dsm_high_f"),
            "caution_flag": int(bool(obs.get("caution_flag"))),
            "raw_json": json.dumps(
                {"dsm_high_f": obs.get("dsm_high_f"), "dsm_received_at": obs.get("dsm_received_at")}
            ),
        }

    @staticmethod
    def _wethr_high_record(station: str, high: dict) -> dict:
        return {
            "station": station,
            "observation_time": high.get("time_of_high_utc"),
            "obs_type": "WETHR_HIGH",
            "wethr_high_f": high.get("wethr_high"),
            "wethr_low_f": high.get("wethr_low"),
            "caution_flag": int(bool(high.get("caution_flag"))),
            "raw_json": json.dumps(high),
        }

    @staticmethod
    def _dsm_record(city: str, station: str, dsm: dict) -> dict:
        return {
            "city": city,
            "station": station,
            "dsm_date": (dsm.get("observation_time") or "")[:10],
            "dsm_fire_time_utc": dsm.get("observation_time"),
            "max_temp_c": dsm.get("dsm_high"),
            "max_temp_f": dsm.get("dsm_high_display"),
            "caution_flag": int(bool(dsm.get("caution_flag"))),
            "raw_json": json.dumps(dsm),
        }

    @staticmethod
    def _gate_record(
        city: str, bracket: dict, target_date: str, trigger_reason: str, gate: dict, hgefs_like: dict = None
    ) -> dict:
        return {
            "city": city,
            "ticker": bracket.get("ticker"),
            "target_date": target_date,
            "trigger_reason": trigger_reason,
            "gate1_pass": gate["gate1"]["pass"],
            "gate1_physics_mean": gate["gate1"].get("physics_mean"),
            "gate1_ai_mean": gate["gate1"].get("ai_mean"),
            "gate1_spread_between": gate["gate1"].get("spread_between"),
            "gate1_physics_spread": gate["gate1"].get("physics_spread"),
            "gate1_ai_spread": gate["gate1"].get("ai_spread"),
            "gate1_ai_source": (hgefs_like or {}).get("gate1_ai_source"),
            "gate2_pass": gate["gate2"]["pass"],
            "gate2_model_prob": gate["gate2"].get("model_prob"),
            "gate2_market_price": gate["gate2"].get("market_price"),
            "gate2_gap_pp": gate["gate2"].get("gap_pp"),
            "gate2_direction": gate["gate2"].get("direction"),
            "gate3_pass": gate["gate3"]["pass"],
            "gate3_yes_price": gate["gate3"].get("yes_price"),
            "gate4_pass": gate["gate4"]["pass"],
            "gate4_in_dead_zone": gate["gate4"].get("in_dead_zone"),
            "gate5_pass": gate["gate5"]["pass"],
            "gate5_metar_temp_f": gate["gate5"].get("metar_temp_f"),
            "gate5_bracket_center_f": gate["gate5"].get("bracket_center_f"),
            "gate5_distance": gate["gate5"].get("distance"),
            "gate6_pass": gate["gate6"]["pass"],
            "gate6_reversal_detected": gate["gate6"].get("reversal_detected"),
            "gate6_is_cold_bracket": gate["gate6"].get("is_cold_bracket"),
            "all_pass": gate["all_pass"],
            "signal_generated": gate["all_pass"],
            "skip_reason": gate["skip_reason"],
        }
