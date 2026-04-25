from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, time as dt_time, timedelta
from statistics import median
from typing import Optional
from zoneinfo import ZoneInfo

import config
from data_ingest.kalshi_client import KalshiClient
from data_ingest.model_fetcher import ModelFetcher
from data_ingest.teleconn_fetcher import TeleconnFetcher
from data_ingest.wethr_client import WethrClient
from data_store.db import Database
from dashboard.daily_report import generate_daily_report
from paper_trader.simulator import PaperTrader
from signal_engine.gate_checker import run_all_gates
from signal_engine.gumbel_model import GumbelModel

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
    ):
        self.wethr = wethr
        self.kalshi = kalshi
        self.model_fetcher = model_fetcher
        self.gumbel = gumbel
        self.paper_trader = paper_trader
        self.orderbook_manager = orderbook_manager
        self.db = db
        self.latest_hgefs_cycle: dict[str, str] = {}
        self.triggered_today = set()
        self.daily_completed: set[tuple[str, str]] = set()

    async def run_forever(self) -> None:
        await asyncio.gather(
            self._loop(self.poll_60s, config.POLL_INTERVAL_60S),
            self._loop(self.poll_5min, config.POLL_INTERVAL_5MIN),
            self._loop(self.poll_30min, config.POLL_INTERVAL_30MIN),
            self._wall_clock_daily_loop(),
            self._fallback_loop(),
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
        for city, cfg in self._active_cities():
            station = cfg["wethr_station"]
            try:
                obs = self.wethr.get_latest_obs(station)
                self.db.insert_observation(self._latest_obs_record(station, obs))
                high = self.wethr.get_wethr_high(station, "nws")
                self.db.insert_observation(self._wethr_high_record(station, high))
                dsm = self.wethr.get_dsm_high(station)
                if dsm and dsm.get("dsm_high_display") is not None:
                    self.db.insert_dsm_report(self._dsm_record(city, station, dsm))
            except Exception as exc:
                logger.warning("60s poll failed for %s: %s", city, exc)

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

    async def check_cli_settlements(self) -> None:
        today_dt = datetime.now(ZoneInfo("America/New_York")).date()
        yesterday = (today_dt - timedelta(days=1)).isoformat()
        for city, cfg in self._active_cities():
            try:
                cli = self.wethr.get_cli_high(cfg["wethr_station"])
                if cli and cli.get("cli_high_display") is not None:
                    self.db.insert_cli_report(
                        {
                            "city": city,
                            "station": cfg["wethr_station"],
                            "settlement_date": yesterday,
                            "cli_fire_time_utc": cli.get("observation_time"),
                            "official_high_f": cli.get("cli_high_display"),
                            "official_low_f": cli.get("cli_low_display"),
                            "raw_json": json.dumps(cli),
                        }
                    )
            except Exception as exc:
                logger.warning("CLI update failed for %s: %s", city, exc)

    async def generate_daily_summary(self) -> None:
        today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        logger.info("\n%s", generate_daily_report(config.DB_PATH, today))

    async def _wall_clock_daily_loop(self) -> None:
        jobs = [
            ("teleconnections", config.TELECONN_UPDATE_ET, self.update_teleconnections),
            ("cli", config.CLI_CHECK_TIME_ET, self.check_cli_settlements),
            ("report", config.DAILY_REPORT_TIME_ET, self.generate_daily_summary),
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
            await asyncio.sleep(60)

    async def fire_gate_check(self, city: str, trigger_reason: str) -> None:
        cfg = config.CITIES[city]
        station = cfg["wethr_station"]
        target_date = datetime.now(ZoneInfo(cfg["timezone"])).date().isoformat()
        markets = self.kalshi.get_active_markets(cfg["series_ticker"])
        brackets = self.kalshi.parse_brackets(markets)
        models = self.wethr.get_all_models_maxt(station, target_date)
        hgefs_like = self._hgefs_or_fallback(city, models)
        nbm = self._latest_nbm(city)
        if not nbm:
            nbm = {}
        consensus = self._consensus(hgefs_like, models, target_date)
        metar = self._get_metar_951(station, target_date)
        if consensus is None:
            logger.info("No consensus available for %s gate check", city)
            return

        for bracket in brackets:
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
            history = self.orderbook_manager.get_price_history(bracket["ticker"], 8 * 60) if self.orderbook_manager else []
            gate = run_all_gates(
                hgefs_like.get("physics_mean"),
                hgefs_like.get("physics_spread"),
                hgefs_like.get("ai_mean"),
                hgefs_like.get("ai_spread"),
                prob,
                market_price,
                market_price,
                metar,
                center,
                bracket.get("strike_lo") or center,
                "YES",
                history,
                bracket["ticker"],
            )
            self.db.insert_gate_check(self._gate_record(city, bracket, target_date, trigger_reason, gate, hgefs_like))
            if gate["all_pass"] and self._liquid(bracket):
                signal_id = self.db.insert_signal(
                    {
                        "city": city,
                        "ticker": bracket["ticker"],
                        "target_date": target_date,
                        "bracket": bracket.get("bracket_label"),
                        "bracket_lo": bracket.get("strike_lo"),
                        "bracket_hi": bracket.get("strike_hi"),
                        "direction": gate["direction"],
                        "entry_price": market_price if gate["direction"] == "YES" else 1.0 - market_price,
                        "target_price": float(config.TARGET_EXIT_PRICE),
                        "stop_price": max(0.0, (market_price if gate["direction"] == "YES" else 1.0 - market_price) - float(config.STOP_LOSS_DIFF)),
                        "model_prob": prob,
                        "market_price": market_price,
                        "gap_pp": gate["gap_pp"],
                        "confidence_score": gate["confidence_score"],
                        "physics_mean": hgefs_like.get("physics_mean"),
                        "ai_mean": hgefs_like.get("ai_mean"),
                        "nbm_p50": nbm.get("p50"),
                        "metar_temp_f": metar,
                        "trigger_reason": trigger_reason,
                        "reasoning": f"All 6 gates passed; gap={gate['gap_pp']:.1f}pp",
                    }
                )
                signal = dict(self.db.execute("SELECT * FROM signals WHERE id = ?", (signal_id,))[0])
                signal["spread"] = bracket.get("spread") or "0"
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

    def _hgefs_or_fallback(self, city: str, models: dict) -> dict:
        latest = self.db.get_model_run_latest(city, "HGEFS")
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
                target_date = datetime.now(ZoneInfo(config.CITIES[city]["timezone"])).date().isoformat()
                wethr_consensus = self.gumbel.compute_consensus_from_wethr(models, target_date)
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
                        city, wethr_consensus, ai_spread,
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

    def _latest_nbm(self, city: str) -> dict:
        latest = self.db.get_model_run_latest(city, "NBM_BULLETIN")
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
                self.db.insert_model_run(
                    {
                        "model": "NBM_BULLETIN",
                        "city": city,
                        "target_date": target_date,
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
        physics_ok = (
            physics_count >= config.HGEFS_MIN_PHYSICS_MEMBERS
            and result.get("physics_mean") is not None
        )
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
                city, cycle,
                result["physics_mean"],
                result.get("physics_spread", 0.0),
                physics_count,
                f"mean={result['ai_mean']:.1f}°F ({ai_count} members)" if ai_ok else "unavailable",
            )
        else:
            logger.warning(
                "GEFS %s %s insufficient: physics=%d (need %d), ai=%d",
                city, cycle, physics_count, config.HGEFS_MIN_PHYSICS_MEMBERS, ai_count,
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
            "six_hour_high_f": WethrClient.celsius_to_fahrenheit(obs.get("six_hour_high")) if obs.get("six_hour_high") is not None else None,
            "six_hour_low_f": WethrClient.celsius_to_fahrenheit(obs.get("six_hour_low")) if obs.get("six_hour_low") is not None else None,
            "dew_point_c": obs.get("dew_point"),
            "wind_speed": obs.get("wind_speed"),
            "relative_humidity": obs.get("relative_humidity"),
            "raw_json": json.dumps(obs),
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
    def _gate_record(city: str, bracket: dict, target_date: str, trigger_reason: str, gate: dict, hgefs_like: dict = None) -> dict:
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
