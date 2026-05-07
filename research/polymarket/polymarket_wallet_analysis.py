#!/usr/bin/env python3
"""Top Polymarket weather-wallet analysis.

Research-only script. It writes all artifacts under data/wallet_analysis and
does not import or modify live pipeline modules.
"""

from __future__ import annotations

import ast
import json
import math
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def ensure_packages() -> None:
    required = {
        "requests": "requests",
        "pandas": "pandas",
        "numpy": "numpy",
        "scipy": "scipy",
        "pytz": "pytz",
        "tenacity": "tenacity",
        "pyarrow": "pyarrow",
    }
    missing: list[str] = []
    for module, package in required.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if missing:
        print(f"Installing missing analysis packages: {missing}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])


ensure_packages()

import numpy as np
import pandas as pd
import requests
from scipy.stats import gumbel_r


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "wallet_analysis"
PRICE_CACHE_DIR = OUT_DIR / "price_cache"
MARKET_CACHE_PATH = OUT_DIR / "market_cache.json"
TRADE_CACHE_PATH = OUT_DIR / "api_activity_cache.json"
LEADERBOARD_ATTEMPT_PATH = OUT_DIR / "leaderboard_attempt.json"

TOP_WALLETS = {
    "gopfan2": "0xf2f6af4f27ec2dcf4072095ab804016e14cd5817",
    "aenews2": "0x44c1dfe43260c94ed4f1d00de2e1f80fb113ebc1",
    "ColdMath": "0x594edb9112f526fa6a80b8f858a6379c8a2c1c11",
    "Hans323": "0x0f37cb80dee49d55b5f6d9e595d52591d6371410",
    "bama124": "0xe5c8026239919339b988fdb150a7ef4ea196d3e7",
    "automatedAItradingbot": "0xd8f8c13644ea84d62e1ec88c5d1215e436eb0f11",
    "WeatherTraderBot": "0xacc8e9dcabf9d65a5c78e3bec6941ed53a2b7d08",
    "BigMike11": "0xecdbd79566a25693b9971c48d7de84bc05f7da79",
    "gopfan": "0x6af75d4e4aaf700450efbac3708cce1665810ff1",
    "Kapii": "0xb74711992caf6d04fa55eecc46b8efc95311b050",
}

STATION_CORRECTION_F = 2.5
DATA_BASE_URL = "https://data-api.polymarket.com"
GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
GOLDSKY_URL = (
    "https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/"
    "subgraphs/orderbook-subgraph/0.0.1/gn"
)
OPEN_METEO_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}
START_TS = 1727740800
ET = ZoneInfo("America/New_York")

WEATHER_KEYWORDS = (
    "temperature",
    "highest temp",
    "highest temperature",
    "lowest temp",
    "lowest temperature",
    "°f",
    "ºf",
    "°c",
    "ºc",
    "weather",
    "hottest",
    "coldest",
)
WEATHER_SLUG_KEYWORDS = ("temperature", "weather", "temp")
MODEL_WEIGHTS = {
    "gfs_forecast_klga_f": 0.355,
    "ecmwf_forecast_klga_f": 0.213,
    "nbm_forecast_klga_f": 0.237,
    "ukmo_forecast_klga_f": 0.194,
}


def mkdirs() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PRICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any) -> Any:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return default
    return default


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))


def request_json(
    url: str,
    params: dict[str, Any] | None = None,
    *,
    max_retries: int = 3,
    sleep_seconds: float = 0.2,
) -> Any:
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
            if resp.status_code == 429:
                wait = 15
                print(f"429 from {url}; sleeping {wait}s")
                time.sleep(wait)
                continue
            if 500 <= resp.status_code < 600:
                wait = 5
                print(f"{resp.status_code} from {url}; sleeping {wait}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            time.sleep(sleep_seconds)
            return resp.json()
        except Exception as exc:
            if attempt >= max_retries:
                print(f"WARNING: request failed after retries: {url} {params} ({exc})")
                return None
            time.sleep(5)
    return None


def normalize_timestamp(value: Any) -> int | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    try:
        if isinstance(value, str) and not value.isdigit():
            dt = pd.to_datetime(value, utc=True)
            return int(dt.timestamp())
        return int(float(value))
    except Exception:
        return None


def ts_to_utc_iso(ts: int | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def ts_to_et(ts: int | None) -> datetime | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ET)


def clean_wallet(addr: str | None) -> str:
    return (addr or "").lower()


def coalesce(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        val = row.get(key)
        if val is not None and val != "":
            return val
    return None


def parse_jsonish(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            try:
                return ast.literal_eval(value)
            except Exception:
                return None
    return None


def is_weather_trade(trade: dict[str, Any]) -> bool:
    title = str(coalesce(trade, "title", "question", "marketTitle") or "").lower()
    slug = str(coalesce(trade, "slug", "eventSlug") or "").lower()
    return any(k in title for k in WEATHER_KEYWORDS) or any(
        k in slug for k in WEATHER_SLUG_KEYWORDS
    )


def is_daily_high_temp(trade: dict[str, Any]) -> bool:
    text = f"{coalesce(trade, 'title', 'question') or ''} {coalesce(trade, 'slug', 'eventSlug') or ''}".lower()
    return "highest temperature" in text or "highest temp" in text


def extract_city(text: str | None) -> str:
    s = (text or "").lower()
    city_patterns = {
        "NYC": ("new york", "nyc", "knyc", "laguardia", "lga"),
        "CHI": ("chicago",),
        "MIA": ("miami",),
        "LAX": ("los angeles", "lax", " la "),
        "LON": ("london",),
        "PAR": ("paris",),
        "DAL": ("dallas",),
        "DEN": ("denver",),
        "SEA": ("seattle",),
        "ATL": ("atlanta",),
        "TOK": ("tokyo",),
        "PHL": ("philadelphia",),
    }
    padded = f" {s} "
    for city, needles in city_patterns.items():
        if any(needle in padded for needle in needles):
            return city
    return "OTHER"


def safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        val = float(value)
        if math.isnan(val):
            return None
        return val
    except Exception:
        return None


def cents_bucket(price: Any) -> str:
    p = safe_float(price)
    if p is None:
        return "unknown"
    cents = max(0, min(99, int(p * 100)))
    lo = (cents // 10) * 10
    hi = lo + 10
    if lo >= 90:
        return "90-100c"
    return f"{lo:02d}-{hi:02d}c"


def gap_bucket(gap: Any) -> str:
    g = safe_float(gap)
    if g is None:
        return "unknown"
    ag = abs(g)
    if ag < 10:
        return "<10pp"
    if ag < 15:
        return "10-15pp"
    if ag < 20:
        return "15-20pp"
    if ag < 25:
        return "20-25pp"
    return "25+pp"


def c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def parse_temp_bounds(label: str | None, title: str | None = None) -> dict[str, Any]:
    text = (label or title or "").replace("º", "°")
    low = text.lower()
    unit_c = "°c" in low or re.search(r"\bc\b", low) is not None
    unit_f = "°f" in low or re.search(r"\bf\b", low) is not None
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", text)]
    lower_tail = (
        low.strip().startswith("<")
        or "or below" in low
        or "below" in low
        or "less than" in low
        or "or lower" in low
    )
    upper_tail = (
        low.strip().startswith(">")
        or "or above" in low
        or "above" in low
        or "greater than" in low
        or "or higher" in low
    )
    if not nums:
        return {
            "bracket_label": label or title,
            "bracket_lo_f": None,
            "bracket_hi_f": None,
            "bracket_type": "unknown",
        }
    vals = nums[:]
    if unit_c and ("highest temperature" in low or "lowest temperature" in low):
        vals = [c_to_f(v) for v in vals]
    elif not unit_f and not unit_c:
        # Temperature-increase macro markets are not daily high brackets.
        vals = nums[:]

    if lower_tail:
        hi = vals[0]
        return {
            "bracket_label": label or title,
            "bracket_lo_f": None,
            "bracket_hi_f": hi,
            "bracket_type": "lower_tail",
        }
    if upper_tail:
        lo = vals[0]
        return {
            "bracket_label": label or title,
            "bracket_lo_f": lo,
            "bracket_hi_f": None,
            "bracket_type": "upper_tail",
        }
    if len(vals) >= 2 and ("between" in low or "-" in low or "to" in low):
        lo, hi = min(vals[0], vals[1]), max(vals[0], vals[1])
        return {
            "bracket_label": label or title,
            "bracket_lo_f": lo,
            "bracket_hi_f": hi,
            "bracket_type": "central",
        }
    val = vals[0]
    return {
        "bracket_label": label or title,
        "bracket_lo_f": val,
        "bracket_hi_f": val,
        "bracket_type": "central",
    }


def bracket_center(row: pd.Series) -> float | None:
    lo = safe_float(row.get("bracket_lo_f"))
    hi = safe_float(row.get("bracket_hi_f"))
    if lo is not None and hi is not None:
        return (lo + hi) / 2.0
    if lo is not None:
        return lo
    if hi is not None:
        return hi
    return None


def bracket_overlap(row: pd.Series, other: pd.Series) -> bool:
    lo1, hi1 = safe_float(row.get("bracket_lo_f")), safe_float(row.get("bracket_hi_f"))
    lo2, hi2 = safe_float(other.get("bt_lo")), safe_float(other.get("bt_hi"))
    if lo1 is None and hi1 is None:
        return False
    if lo2 is None and hi2 is None:
        return False
    a1 = -999 if lo1 is None else lo1
    b1 = 999 if hi1 is None else hi1
    a2 = -999 if lo2 is None else lo2
    b2 = 999 if hi2 is None else hi2
    return max(a1, a2) <= min(b1, b2)


def gumbel_bracket_prob(consensus_klga_f: Any, row: pd.Series) -> float | None:
    consensus = safe_float(consensus_klga_f)
    if consensus is None:
        return None
    lo = safe_float(row.get("bracket_lo_f"))
    hi = safe_float(row.get("bracket_hi_f"))
    btype = row.get("bracket_type")
    mu = consensus - 0.45 - STATION_CORRECTION_F
    beta = 0.742
    if btype == "lower_tail" and hi is not None:
        return float(gumbel_r.cdf(hi - 0.5, mu, beta))
    if btype == "upper_tail" and lo is not None:
        return float(1.0 - gumbel_r.cdf(lo + 0.5, mu, beta))
    if lo is not None and hi is not None:
        return float(gumbel_r.cdf(hi + 0.5, mu, beta) - gumbel_r.cdf(lo - 0.5, mu, beta))
    return None


def normalize_activity_trade(row: dict[str, Any], wallet_name: str, proxy_wallet: str) -> dict[str, Any]:
    ts = normalize_timestamp(coalesce(row, "timestamp", "createdAt", "created_time", "createdTime"))
    et = ts_to_et(ts)
    title = coalesce(row, "title", "question", "marketTitle") or ""
    slug = coalesce(row, "slug", "marketSlug") or ""
    condition = coalesce(row, "conditionId", "condition_id", "market", "marketId")
    outcome_index = coalesce(row, "outcomeIndex", "outcome_index")
    try:
        outcome_index = int(outcome_index) if outcome_index is not None else None
    except Exception:
        outcome_index = None
    price = safe_float(coalesce(row, "price", "avgPrice", "lastPrice"))
    size = safe_float(coalesce(row, "size", "amount", "count", "shares"))
    return {
        "wallet_name": wallet_name,
        "proxyWallet": proxy_wallet.lower(),
        "side": str(coalesce(row, "side", "action") or "").upper(),
        "asset": coalesce(row, "asset", "assetId", "tokenId"),
        "conditionId": condition,
        "size": size,
        "price": price,
        "timestamp": ts,
        "title": title,
        "slug": slug,
        "eventSlug": coalesce(row, "eventSlug", "event_slug"),
        "outcome": coalesce(row, "outcome", "outcomeName"),
        "outcomeIndex": outcome_index,
        "transactionHash": coalesce(row, "transactionHash", "transaction_hash", "txHash"),
        "trade_datetime_utc": ts_to_utc_iso(ts),
        "trade_date_et": et.date().isoformat() if et else None,
        "trade_hour_et": et.hour if et else None,
        "city": extract_city(f"{title} {slug}"),
        "notional_usd_proxy": (price or 0.0) * (size or 0.0),
        "source": "activity_api",
    }


def try_leaderboard() -> None:
    print("Trying Polymarket leaderboard API for context...")
    payload = request_json(
        f"{DATA_BASE_URL}/v1/leaderboard",
        params={"category": "WEATHER", "timePeriod": "ALL", "orderBy": "VOL", "limit": 20},
        max_retries=1,
    )
    write_json(LEADERBOARD_ATTEMPT_PATH, payload if payload is not None else {"error": "unavailable"})


def pull_wallet_weather_trades(wallet_name: str, proxy_wallet: str) -> list[dict[str, Any]]:
    cache = read_json(TRADE_CACHE_PATH, {})
    cache_key = clean_wallet(proxy_wallet)
    if cache_key in cache:
        trades = cache[cache_key]
        print(f"{wallet_name}: using cached activity API trades ({len(trades)} rows before filter)")
    else:
        all_trades: list[dict[str, Any]] = []
        current_end = int(time.time())
        seen_batches = 0
        while current_end > START_TS:
            params = {
                "user": proxy_wallet,
                "type": "TRADE",
                "start": START_TS,
                "end": current_end,
                "limit": 500,
                "sortBy": "TIMESTAMP",
                "sortDirection": "DESC",
            }
            batch = request_json(f"{DATA_BASE_URL}/activity", params=params)
            if not isinstance(batch, list):
                print(f"{wallet_name}: activity endpoint returned no list; stopping API pull")
                break
            if not batch:
                break
            all_trades.extend(batch)
            timestamps = [normalize_timestamp(coalesce(x, "timestamp", "createdAt")) for x in batch]
            timestamps = [x for x in timestamps if x is not None]
            if not timestamps:
                break
            oldest = min(timestamps)
            seen_batches += 1
            if len(batch) < 500 or oldest <= START_TS:
                break
            current_end = oldest - 1
            if seen_batches % 5 == 0:
                print(f"{wallet_name}: pulled {len(all_trades)} activity rows so far...")
        cache[cache_key] = all_trades
        write_json(TRADE_CACHE_PATH, cache)
        trades = all_trades

    normalized = [normalize_activity_trade(t, wallet_name, proxy_wallet) for t in trades]
    weather = [t for t in normalized if is_weather_trade(t)]
    if weather:
        dates = [t["trade_date_et"] for t in weather if t.get("trade_date_et")]
        cities = Counter(t["city"] for t in weather)
        print(f"{wallet_name}: {len(weather)} weather trades from {min(dates)} to {max(dates)}")
        print(f"  Cities: {dict(cities)}")
    else:
        print(f"{wallet_name}: 0 weather trades from activity API")
    return weather


def fallback_phase1_trades(missing_wallets: set[str]) -> list[dict[str, Any]]:
    path = ROOT / "data" / "research" / "polymarket_trades_raw.parquet"
    if not path.exists() or not missing_wallets:
        return []
    print("Using local Phase 1 Polymarket trade artifact as fallback for missing wallets.")
    df = pd.read_parquet(path)
    wallet_to_name = {addr.lower(): name for name, addr in TOP_WALLETS.items()}
    df["_wallet"] = df.get("proxyWallet", "").astype(str).str.lower()
    df = df[df["_wallet"].isin([w.lower() for w in missing_wallets])].copy()
    out: list[dict[str, Any]] = []
    for rec in df.to_dict("records"):
        name = wallet_to_name.get(str(rec.get("proxyWallet", "")).lower(), rec.get("leaderboard_username", "unknown"))
        norm = normalize_activity_trade(rec, name, str(rec.get("proxyWallet", "")))
        norm["source"] = "local_phase1_public_api_artifact"
        if is_weather_trade(norm):
            out.append(norm)
    print(f"Fallback added {len(out)} rows from data/research/polymarket_trades_raw.parquet")
    return out


def market_from_gamma_record(record: dict[str, Any]) -> dict[str, Any]:
    label = (
        record.get("groupItemTitle")
        or record.get("question")
        or record.get("title")
        or record.get("slug")
    )
    parsed = parse_temp_bounds(label, record.get("question") or record.get("title"))
    outcome_prices = parse_jsonish(record.get("outcomePrices")) or []
    outcomes = parse_jsonish(record.get("outcomes")) or []
    clob_ids = parse_jsonish(record.get("clobTokenIds")) or []
    winning_index = None
    try:
        prices = [float(x) for x in outcome_prices]
        if prices and max(prices) >= 0.95:
            winning_index = int(np.argmax(prices))
    except Exception:
        pass
    resolved_status = str(record.get("umaResolutionStatus") or "").lower()
    closed = bool(record.get("closed"))
    is_resolved = closed and (resolved_status in {"resolved", "settled", ""} or winning_index is not None)
    return {
        **parsed,
        "is_resolved": is_resolved,
        "winning_outcome_index": winning_index,
        "total_volume_usd": safe_float(record.get("volumeNum") or record.get("volume")),
        "clob_token_id_yes": clob_ids[0] if clob_ids else None,
        "outcomes": outcomes,
        "outcomePrices": outcome_prices,
        "metadata_status": "ok",
    }


def get_market_metadata(condition_id: str, event_slug: str | None = None) -> dict[str, Any]:
    cache = read_json(MARKET_CACHE_PATH, {})
    if not condition_id:
        return {"metadata_status": "missing_condition_id"}
    if condition_id in cache:
        print(f"Using cached data for {condition_id}")
        return cache[condition_id]

    record = None
    payload = request_json(f"{GAMMA_BASE_URL}/markets", params={"condition_ids": condition_id})
    if isinstance(payload, list) and payload:
        record = payload[0]

    if record is None and event_slug:
        payload = request_json(f"{GAMMA_BASE_URL}/events", params={"slug": event_slug})
        events = payload if isinstance(payload, list) else []
        for event in events:
            for market in event.get("markets", []) or []:
                if str(market.get("conditionId")) == str(condition_id):
                    record = market
                    break
            if record:
                break

    if record is None:
        meta = {"metadata_status": "metadata_unavailable"}
    else:
        meta = market_from_gamma_record(record)
    cache[condition_id] = meta
    write_json(MARKET_CACHE_PATH, cache)
    return meta


def market_from_local_outcome_record(record: dict[str, Any]) -> dict[str, Any]:
    label = record.get("question") or record.get("slug") or record.get("event_title")
    parsed = parse_temp_bounds(label, record.get("question"))
    outcome_prices = parse_jsonish(record.get("outcomePrices")) or []
    resolved_yes = record.get("resolved_yes")
    winning_index = None
    if resolved_yes is True or str(resolved_yes).lower() == "true":
        winning_index = 0
    elif resolved_yes is False or str(resolved_yes).lower() == "false":
        winning_index = 1
    else:
        try:
            prices = [float(x) for x in outcome_prices]
            if prices and max(prices) >= 0.95:
                winning_index = int(np.argmax(prices))
        except Exception:
            winning_index = None
    return {
        **parsed,
        "is_resolved": winning_index is not None or bool(record.get("closed")),
        "winning_outcome_index": winning_index,
        "total_volume_usd": safe_float(record.get("volumeNum")),
        "clob_token_id_yes": None,
        "outcomes": parse_jsonish(record.get("outcomes")) or [],
        "outcomePrices": outcome_prices,
        "metadata_status": "local_phase1_outcome",
    }


def load_local_market_metadata() -> dict[str, dict[str, Any]]:
    path = ROOT / "data" / "research" / "polymarket_market_outcomes.parquet"
    if not path.exists():
        return {}
    local = pd.read_parquet(path)
    out: dict[str, dict[str, Any]] = {}
    for rec in local.to_dict("records"):
        cond = str(rec.get("conditionId") or "")
        if cond:
            out[cond] = market_from_local_outcome_record(rec)
    return out


def fetch_gamma_markets_batch(condition_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not condition_ids:
        return {}
    payload = request_json(
        f"{GAMMA_BASE_URL}/markets",
        params={"condition_ids": ",".join(condition_ids)},
        max_retries=2,
    )
    out: dict[str, dict[str, Any]] = {}
    if isinstance(payload, list):
        for record in payload:
            cond = str(record.get("conditionId") or "")
            if cond:
                out[cond] = market_from_gamma_record(record)
    return out


def fetch_gamma_event_markets(event_slug: str) -> dict[str, dict[str, Any]]:
    if not event_slug:
        return {}
    payload = request_json(f"{GAMMA_BASE_URL}/events", params={"slug": event_slug}, max_retries=2)
    events = payload if isinstance(payload, list) else []
    out: dict[str, dict[str, Any]] = {}
    for event in events:
        for market in event.get("markets", []) or []:
            cond = str(market.get("conditionId") or "")
            if cond:
                out[cond] = market_from_gamma_record(market)
    return out


def enrich_market_metadata(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    unique = df[["conditionId", "eventSlug"]].drop_duplicates().fillna("")
    cache = read_json(MARKET_CACHE_PATH, {})
    local = load_local_market_metadata()
    missing: list[dict[str, str]] = []
    for rec in unique.to_dict("records"):
        cond = str(rec["conditionId"])
        if cond in cache:
            meta = cache[cond]
        elif cond in local:
            meta = local[cond]
            cache[cond] = meta
        else:
            missing.append({"conditionId": cond, "eventSlug": str(rec.get("eventSlug") or "")})
            continue
        meta = dict(meta)
        meta["conditionId"] = cond
        rows.append(meta)

    print(
        f"Market metadata local/cache hit: {len(rows)}/{len(unique)} unique markets; "
        f"{len(missing)} need Gamma batch lookup."
    )
    by_event: dict[str, list[dict[str, str]]] = defaultdict(list)
    no_event: list[dict[str, str]] = []
    for rec in missing:
        if rec.get("eventSlug"):
            by_event[rec["eventSlug"]].append(rec)
        else:
            no_event.append(rec)
    max_events = int(os.getenv("WALLET_ANALYSIS_MAX_METADATA_EVENTS", "0"))
    fetched_events = 0
    for idx, (event_slug, batch) in enumerate(by_event.items(), 1):
        if max_events > 0 and fetched_events >= max_events:
            found = {}
        else:
            if idx % 25 == 0:
                print(f"Gamma event metadata {idx}/{len(by_event)} events...")
            found = fetch_gamma_event_markets(event_slug)
            fetched_events += 1
        for rec in batch:
            cond = rec["conditionId"]
            meta = found.get(cond, {"metadata_status": "metadata_unavailable"})
            cache[cond] = meta
            meta = dict(meta)
            meta["conditionId"] = cond
            rows.append(meta)
    for rec in no_event:
        cond = rec["conditionId"]
        meta = {"metadata_status": "metadata_unavailable"}
        cache[cond] = meta
        meta = dict(meta)
        meta["conditionId"] = cond
        rows.append(meta)
    write_json(MARKET_CACHE_PATH, cache)
    meta_df = pd.DataFrame(rows)
    out = df.merge(meta_df, on="conditionId", how="left")

    def won(row: pd.Series) -> bool | None:
        idx = row.get("outcomeIndex")
        prices = row.get("outcomePrices")
        if isinstance(prices, str):
            prices = parse_jsonish(prices)
        if prices is None or idx is None or pd.isna(idx):
            return None
        try:
            val = float(prices[int(idx)])
            if val >= 0.95:
                return True
            if val <= 0.05:
                return False
        except Exception:
            return None
        return None

    out["trade_won"] = out.apply(won, axis=1)
    print(f"Market metadata fetched for {len(unique)} unique markets")
    for wallet, grp in out.groupby("wallet_name"):
        resolved = grp["trade_won"].notna().sum()
        wins = (grp["trade_won"] == True).sum()
        rate = wins / resolved if resolved else float("nan")
        print(f"{wallet}: {wins}/{resolved} = {rate:.1%} win rate")
    return out


def fetch_market_trade_tape(condition_id: str, start_ts: int, end_ts: int) -> list[dict[str, Any]]:
    path = PRICE_CACHE_DIR / f"{condition_id}.json"
    if path.exists():
        print(f"Using cached data for {condition_id}")
        payload = read_json(path, [])
        return payload if isinstance(payload, list) else []
    payload = request_json(
        f"{DATA_BASE_URL}/trades",
        params={"market": condition_id, "start": start_ts, "end": end_ts, "limit": 1000},
        max_retries=2,
    )
    if not isinstance(payload, list):
        payload = []
    write_json(path, payload)
    return payload


def normalize_tape(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    t = df.copy()
    if "timestamp" not in t.columns:
        for alt in ("createdAt", "created_time", "createdTime"):
            if alt in t.columns:
                t["timestamp"] = t[alt].map(normalize_timestamp)
                break
    else:
        t["timestamp"] = t["timestamp"].map(normalize_timestamp)
    if "price" not in t.columns:
        for alt in ("avgPrice", "lastPrice"):
            if alt in t.columns:
                t["price"] = pd.to_numeric(t[alt], errors="coerce")
                break
    else:
        t["price"] = pd.to_numeric(t["price"], errors="coerce")
    if "side" in t.columns:
        t["side"] = t["side"].astype(str).str.upper()
    else:
        t["side"] = ""
    return t.dropna(subset=["timestamp", "price"]).sort_values("timestamp")


def last_price_at_or_before(tape: pd.DataFrame, cutoff: int) -> float | None:
    if tape.empty:
        return None
    sub = tape[tape["timestamp"] <= cutoff]
    if sub.empty:
        return None
    return float(sub.iloc[-1]["price"])


def add_price_context(df: pd.DataFrame) -> pd.DataFrame:
    context_rows: list[dict[str, Any]] = []
    local_tapes = {
        cond: normalize_tape(grp)
        for cond, grp in df.groupby("conditionId", dropna=True)
    }
    fetch_enabled = os.getenv("WALLET_ANALYSIS_FETCH_PRICE_TAPE", "1") != "0"
    max_fetches = int(os.getenv("WALLET_ANALYSIS_MAX_PRICE_MARKETS", "500"))
    api_tapes: dict[str, pd.DataFrame] = {}
    if fetch_enabled:
        print(
            "Fetching public market trade tapes for price context "
            f"(max unique markets={max_fetches}; set WALLET_ANALYSIS_MAX_PRICE_MARKETS=0 for no cap)."
        )
        for j, (cond, grp) in enumerate(df.groupby("conditionId", dropna=True), 1):
            if max_fetches > 0 and len(api_tapes) >= max_fetches:
                break
            if j % 50 == 0:
                print(f"Fetched/probed price tape for {j} unique markets...")
            ts_series = pd.to_numeric(grp["timestamp"], errors="coerce").dropna()
            if ts_series.empty:
                continue
            api_tape = fetch_market_trade_tape(
                str(cond),
                int(ts_series.min()) - 28800,
                int(ts_series.max()) + 3600,
            )
            if api_tape:
                api_tapes[str(cond)] = normalize_tape(pd.DataFrame(api_tape))
    else:
        print("Skipping external price-tape fetch; using captured public wallet trade slice only.")

    for i, row in enumerate(df.to_dict("records"), 1):
        if i % 5000 == 0:
            print(f"Processing price context: {i}/{len(df)} trades done...")
        cond = str(row.get("conditionId") or "")
        ts = normalize_timestamp(row.get("timestamp"))
        if not cond or ts is None:
            context_rows.append({})
            continue
        tape = api_tapes.get(cond) if cond in api_tapes else local_tapes.get(cond, pd.DataFrame())
        price_at_entry = safe_float(row.get("price"))
        p1 = last_price_at_or_before(tape, ts - 3600)
        p3 = last_price_at_or_before(tape, ts - 3 * 3600)
        p6 = last_price_at_or_before(tape, ts - 6 * 3600)
        trend = None if p3 is None or price_at_entry is None else price_at_entry - p3
        if trend is None:
            trend_dir = "unknown"
        elif abs(trend) < 0.03:
            trend_dir = "flat"
        elif trend > 0:
            trend_dir = "rising"
        else:
            trend_dir = "falling"
        prior6 = tape[(tape["timestamp"] >= ts - 6 * 3600) & (tape["timestamp"] <= ts)]
        prior30 = tape[(tape["timestamp"] >= ts - 1800) & (tape["timestamp"] <= ts)]
        approx_spread = None
        if not prior30.empty and "side" in prior30.columns:
            buys = prior30[prior30["side"] == "BUY"]["price"]
            sells = prior30[prior30["side"] == "SELL"]["price"]
            if not buys.empty and not sells.empty:
                maybe = float(sells.min()) - float(buys.max())
                approx_spread = maybe if maybe > 0 else None
        context_rows.append(
            {
                "price_at_entry": price_at_entry,
                "price_1h_before": p1,
                "price_3h_before": p3,
                "price_6h_before": p6,
                "price_trend": trend,
                "trend_direction": trend_dir,
                "market_activity_per_hour": len(prior6) / 6.0,
                "approx_spread": approx_spread,
                "price_context_source": "data_api_trade_tape" if cond in api_tapes else "wallet_slice_trade_tape",
            }
        )
    return pd.concat([df.reset_index(drop=True), pd.DataFrame(context_rows)], axis=1)


def load_weather_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    forecasts = pd.read_csv(ROOT / "data" / "open_meteo_historical.csv")
    actual = pd.read_csv(ROOT / "data" / "knyc_actual_temps.csv")
    forecasts["date"] = forecasts["date"].astype(str)
    actual["date"] = actual["date"].astype(str)
    return forecasts, actual


def add_weather_context(df: pd.DataFrame) -> pd.DataFrame:
    forecasts, actual = load_weather_data()
    f = forecasts.rename(columns={"date": "trade_date_et"}).copy()
    for src, dst in [
        ("gfs_maxt", "gfs_forecast_klga_f"),
        ("ecmwf_maxt", "ecmwf_forecast_klga_f"),
        ("ukmo_maxt", "ukmo_forecast_klga_f"),
        ("nbm_maxt", "nbm_forecast_klga_f"),
    ]:
        if src in f.columns:
            f[dst] = pd.to_numeric(f[src], errors="coerce") + STATION_CORRECTION_F
    out = df.merge(f[["trade_date_et", *MODEL_WEIGHTS.keys()]], on="trade_date_et", how="left")
    a = actual.rename(columns={"date": "trade_date_et", "max_temp_f": "actual_high_knyc_f"})
    out = out.merge(a[["trade_date_et", "actual_high_knyc_f"]], on="trade_date_et", how="left")
    out["actual_high_klga_f"] = pd.to_numeric(out["actual_high_knyc_f"], errors="coerce") + STATION_CORRECTION_F

    def consensus(row: pd.Series) -> float | None:
        vals = []
        weights = []
        for col, w in MODEL_WEIGHTS.items():
            v = safe_float(row.get(col))
            if v is not None:
                vals.append(v)
                weights.append(w)
        if not vals:
            return None
        return float(np.average(vals, weights=weights))

    out["model_consensus_klga_f"] = out.apply(consensus, axis=1)
    model_cols = list(MODEL_WEIGHTS.keys())
    out["model_spread_f"] = out[model_cols].std(axis=1, skipna=True)
    out.loc[out["city"] != "NYC", ["model_consensus_klga_f", "model_spread_f"]] = np.nan

    def update_bucket(hour: Any) -> str:
        try:
            h = int(hour)
        except Exception:
            return "unknown"
        if h < 5:
            return "overnight_00z"
        if h <= 10:
            return "morning_06z"
        if h <= 12:
            return "pre_12z"
        return "post_12z"

    out["model_update_available"] = out["trade_hour_et"].map(update_bucket)
    out["bracket_center_f"] = out.apply(bracket_center, axis=1)
    out["distance_from_consensus_f"] = out["model_consensus_klga_f"] - out["bracket_center_f"]

    def align(row: pd.Series) -> str:
        c = safe_float(row.get("model_consensus_klga_f"))
        lo = safe_float(row.get("bracket_lo_f"))
        hi = safe_float(row.get("bracket_hi_f"))
        center = safe_float(row.get("bracket_center_f"))
        if c is None or center is None:
            return "unavailable"
        if lo is not None and hi is not None and lo <= c <= hi:
            return "consensus_inside_bracket"
        if abs(c - center) <= 3:
            return "consensus_near_bracket"
        if abs(c - center) > 5:
            return "consensus_far_from_bracket"
        return "intermediate"

    out["bracket_alignment"] = out.apply(align, axis=1)
    out["gumbel_prob"] = out.apply(
        lambda r: gumbel_bracket_prob(r.get("model_consensus_klga_f"), r) if r.get("city") == "NYC" else None,
        axis=1,
    )
    out["gap_pp"] = (out["gumbel_prob"] - out["price_at_entry"]) * 100
    out["would_our_gate_pass"] = (
        out["gap_pp"].abs().gt(20)
        & out["price_at_entry"].between(0.25, 0.75, inclusive="both")
        & ~out["gap_pp"].abs().between(35, 40, inclusive="both")
    )
    out.loc[out["city"] != "NYC", "would_our_gate_pass"] = False
    return out


def parse_backtest_bracket(text: str) -> tuple[float | None, float | None]:
    s = str(text or "").replace("F", "")
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", s)]
    if s.startswith(">") and nums:
        return nums[0], None
    if s.startswith("<") and nums:
        return None, nums[0]
    if len(nums) >= 2:
        return min(nums[0], nums[1]), max(nums[0], nums[1])
    if len(nums) == 1:
        return nums[0], nums[0]
    return None, None


def add_backtest_comparison(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    path = ROOT / "data" / "backtest_results.csv"
    if not path.exists():
        return df, pd.DataFrame()
    bt = pd.read_csv(path)
    bt["date"] = bt["date"].astype(str)
    bounds = bt["bracket"].map(parse_backtest_bracket)
    bt["bt_lo"] = [x[0] for x in bounds]
    bt["bt_hi"] = [x[1] for x in bounds]
    bt_by_date = {d: g.copy() for d, g in bt.groupby("date")}
    rows = []
    for _, row in df.iterrows():
        if row.get("city") != "NYC":
            rows.append({})
            continue
        date = str(row.get("trade_date_et"))
        day_bt = bt_by_date.get(date)
        if day_bt is None or day_bt.empty:
            reason = "gap_or_price_or_metar_gate_failed"
            if safe_float(row.get("gap_pp")) is None:
                reason = "no_nyc_forecast_or_metadata_context"
            elif abs(float(row["gap_pp"])) <= 20:
                reason = "gap_below_20pp"
            elif not (0.25 <= float(row.get("price_at_entry") or -1) <= 0.75):
                reason = "price_band_fail"
            elif 35 <= abs(float(row["gap_pp"])) <= 40:
                reason = "dead_zone_35_40pp"
            rows.append(
                {
                    "our_bot_traded_same_day": False,
                    "our_bot_same_bracket": False,
                    "our_bot_would_have_traded": bool(row.get("would_our_gate_pass")),
                    "reason_we_didnt_trade": reason,
                }
            )
            continue
        matches = day_bt[day_bt.apply(lambda r: bracket_overlap(row, r), axis=1)]
        pick = matches.iloc[0] if not matches.empty else day_bt.iloc[0]
        our_price = safe_float(pick.get("entry_price"))
        wallet_price = safe_float(row.get("price_at_entry"))
        hour = safe_float(row.get("trade_hour_et"))
        our_hour = 9 if str(pick.get("entry_timing", "")).startswith("9") else None
        if our_hour is None or hour is None:
            timing = "unknown"
        elif hour < our_hour:
            timing = "wallet_earlier"
        elif hour > our_hour:
            timing = "wallet_later"
        else:
            timing = "same_hour"
        rows.append(
            {
                "our_bot_traded_same_day": True,
                "our_bot_same_bracket": not matches.empty,
                "our_bot_entry_price": our_price,
                "our_bot_gap_pp": safe_float(pick.get("gap_pp")),
                "our_bot_won": bool(pick.get("win")),
                "price_diff": None if our_price is None or wallet_price is None else wallet_price - our_price,
                "entry_timing_comparison": timing,
                "our_bot_would_have_traded": True,
                "reason_we_didnt_trade": None,
            }
        )
    out = pd.concat([df.reset_index(drop=True), pd.DataFrame(rows)], axis=1)

    nyc = out[out["city"] == "NYC"].copy()
    if nyc.empty:
        return out, pd.DataFrame()
    day_rows = []
    dates = sorted(set(nyc["trade_date_et"].dropna()) | set(bt["date"].dropna()))
    for date in dates:
        w = nyc[nyc["trade_date_et"] == date]
        b = bt[bt["date"] == date]
        top_entered = not w.empty
        bot_entered = not b.empty
        timing_mode = (
            w["entry_timing_comparison"].dropna().mode()
            if top_entered and "entry_timing_comparison" in w
            else pd.Series(dtype=object)
        )
        day_rows.append(
            {
                "date": date,
                "top_wallet_entered_polymarket": top_entered,
                "top_wallet_best_price_polymarket": w["price_at_entry"].min() if top_entered else None,
                "top_wallet_bracket_type_polymarket": w["bracket_type"].mode().iloc[0] if top_entered and not w["bracket_type"].dropna().empty else None,
                "top_wallet_won_polymarket": bool((w["trade_won"] == True).any()) if top_entered else None,
                "our_bot_entered_kalshi": bot_entered,
                "our_bot_best_price_kalshi": b["entry_price"].min() if bot_entered else None,
                "our_bot_gap_pp_kalshi": b["gap_pp"].abs().max() if bot_entered else None,
                "our_bot_won_kalshi": bool((b["win"] == True).any()) if bot_entered else None,
                "gumbel_prob_for_winner": w.loc[w["trade_won"] == True, "gumbel_prob"].max() if top_entered else None,
                "actual_settlement_knyc": w["actual_high_knyc_f"].dropna().iloc[0] if top_entered and not w["actual_high_knyc_f"].dropna().empty else None,
                "actual_settlement_klga": w["actual_high_klga_f"].dropna().iloc[0] if top_entered and not w["actual_high_klga_f"].dropna().empty else None,
                "price_advantage_wallet": (b["entry_price"].min() - w["price_at_entry"].min()) if top_entered and bot_entered else None,
                "same_direction": None,
                "timing_winner": timing_mode.iloc[0] if not timing_mode.empty else None,
            }
        )
    return out, pd.DataFrame(day_rows)


def win_rate(s: pd.Series) -> float | None:
    resolved = s.dropna()
    if resolved.empty:
        return None
    return float((resolved == True).mean())


def markdown_table(df: pd.DataFrame, max_rows: int = 30) -> str:
    if df.empty:
        return "_No rows._"
    view = df.head(max_rows).copy()
    cols = [str(c) for c in view.columns]

    def fmt(val: Any) -> str:
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return ""
        if isinstance(val, float):
            return f"{val:.4f}" if abs(val) < 1 else f"{val:.2f}"
        text = str(val).replace("\n", " ")
        return text[:180]

    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join(["---"] * len(cols)) + " |",
    ]
    for _, row in view.iterrows():
        lines.append("| " + " | ".join(fmt(row[c]) for c in view.columns) + " |")
    return "\n".join(lines)


def group_table(df: pd.DataFrame, by: str) -> pd.DataFrame:
    if df.empty or by not in df.columns:
        return pd.DataFrame()
    g = df.groupby(by, dropna=False)
    return (
        g.agg(
            trade_count=("price_at_entry", "size"),
            resolved=("trade_won", lambda x: x.notna().sum()),
            win_rate=("trade_won", win_rate),
            avg_entry_price=("price_at_entry", "mean"),
            median_entry_price=("price_at_entry", "median"),
            avg_size=("notional_usd_proxy", "mean"),
        )
        .reset_index()
        .sort_values("trade_count", ascending=False)
    )


def infer_holds(df: pd.DataFrame) -> pd.DataFrame:
    holds = []
    for (wallet, cond, outcome), grp in df.sort_values("timestamp").groupby(
        ["wallet_name", "conditionId", "outcomeIndex"], dropna=False
    ):
        buys = grp[grp["side"] == "BUY"].copy()
        sells = grp[grp["side"] == "SELL"].copy()
        for _, buy in buys.iterrows():
            later = sells[sells["timestamp"] > buy["timestamp"]]
            if later.empty:
                hold_hours = None
                exit_price = None
                category = "settlement_or_open"
            else:
                sell = later.iloc[0]
                hold_hours = (sell["timestamp"] - buy["timestamp"]) / 3600.0
                exit_price = sell.get("price_at_entry")
                if hold_hours < 6:
                    category = "intraday"
                elif hold_hours < 24:
                    category = "day_trade"
                elif hold_hours < 48:
                    category = "overnight"
                else:
                    category = "settlement"
            ret = None
            price = safe_float(buy.get("price_at_entry"))
            if price is not None and buy.get("trade_won") is not None:
                ret = (1 - price) if buy.get("trade_won") is True else -price
            holds.append(
                {
                    "wallet_name": wallet,
                    "conditionId": cond,
                    "outcomeIndex": outcome,
                    "entry_timestamp": buy["timestamp"],
                    "hold_hours": hold_hours,
                    "hold_category": category,
                    "entry_price": buy.get("price_at_entry"),
                    "exit_price": exit_price,
                    "trade_won": buy.get("trade_won"),
                    "return_per_contract": ret,
                }
            )
    return pd.DataFrame(holds)


def behavioral_summary(df: pd.DataFrame, holds: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for wallet, grp in df.groupby("wallet_name"):
        resolved = grp["trade_won"].notna().sum()
        hold_grp = holds[holds["wallet_name"] == wallet] if not holds.empty else pd.DataFrame()
        corr = np.nan
        if grp["gap_pp"].notna().sum() >= 3:
            corr = grp[["gap_pp", "notional_usd_proxy"]].corr().iloc[0, 1]
        rows.append(
            {
                "wallet": wallet,
                "trade_count": len(grp),
                "resolved_trades": resolved,
                "win_rate": win_rate(grp["trade_won"]),
                "date_start": grp["trade_date_et"].dropna().min(),
                "date_end": grp["trade_date_et"].dropna().max(),
                "city_counts": json.dumps(dict(Counter(grp["city"]))),
                "market_count": grp["conditionId"].nunique(),
                "event_count": grp["eventSlug"].nunique(),
                "median_entry_price": grp["price_at_entry"].median(),
                "mean_entry_price": grp["price_at_entry"].mean(),
                "pct_price_lt_15c": float((grp["price_at_entry"] < 0.15).mean()),
                "pct_price_gt_90c": float((grp["price_at_entry"] > 0.90).mean()),
                "avg_notional": grp["notional_usd_proxy"].mean(),
                "max_notional": grp["notional_usd_proxy"].max(),
                "size_gap_corr": corr,
                "median_hold_hours": hold_grp["hold_hours"].median() if not hold_grp.empty else np.nan,
                "hold_to_settlement_proxy_rate": float((hold_grp["hold_category"] == "settlement_or_open").mean()) if not hold_grp.empty else np.nan,
                "dominant_bracket_type": grp["bracket_type"].mode().iloc[0] if not grp["bracket_type"].dropna().empty else None,
                "dominant_hour": int(grp["trade_hour_et"].mode().iloc[0]) if not grp["trade_hour_et"].dropna().empty else None,
            }
        )
    return pd.DataFrame(rows).sort_values("trade_count", ascending=False)


def top_recommendations(df: pd.DataFrame, nyc_comparison: pd.DataFrame) -> list[str]:
    recs = [
        "Keep the 20pp live threshold frozen; use this wallet analysis only as research because the public Polymarket slice is incomplete and station-settlement differs from Kalshi.",
        "Add paper/research diagnostics for entry price bucket and extreme-price wallet behavior; top-wallet behavior often concentrates at <15c or >90c, which is structurally different from our 25c-75c core band.",
        "Separate central/range brackets from tails in research reports and paper policy; bracket-type win rates and entry prices differ enough that one rule set hides the real behavior.",
        "Track pre-entry price trend and local market activity before paper entries; wallet trades can be bucketed as rising, falling, or flat using the public tape, and that is missing from the live signal explanation layer.",
        "Do not copy Polymarket NYC trades directly into KXHIGHNY; Polymarket station proxy is KLGA while Kalshi settles KNYC, so keep the +2.5F station-difference diagnostic before comparing gaps.",
    ]
    if not nyc_comparison.empty:
        both = nyc_comparison[
            nyc_comparison["top_wallet_entered_polymarket"] & nyc_comparison["our_bot_entered_kalshi"]
        ]
        missed = nyc_comparison[
            nyc_comparison["top_wallet_entered_polymarket"] & ~nyc_comparison["our_bot_entered_kalshi"]
        ]
        if len(missed) > len(both):
            recs[1] = (
                "Investigate missed NYC Polymarket-active days in paper only; wallets traded "
                f"{len(missed)} NYC days where the Kalshi backtest had no trade, versus {len(both)} overlap days."
            )
    return recs[:5]


def generate_report(df: pd.DataFrame, nyc_comparison: pd.DataFrame, summary: pd.DataFrame, holds: pd.DataFrame) -> list[str]:
    print("Running Analysis A: Entry price distribution...")
    price_dist = group_table(df.assign(price_bucket=df["price_at_entry"].map(cents_bucket)), "price_bucket")
    price_dist["pct"] = price_dist["trade_count"] / len(df) if len(df) else 0
    best_price_bucket = price_dist.sort_values("win_rate", ascending=False).head(1)

    print("Running Analysis B: Entry timing by hour...")
    hour_tbl = group_table(df, "trade_hour_et").sort_values("trade_hour_et")
    peak_hour = hour_tbl.sort_values("trade_count", ascending=False).head(1)
    best_hour = hour_tbl.sort_values("win_rate", ascending=False).head(1)
    pre = df[df["trade_hour_et"] < 13]
    post = df[df["trade_hour_et"] >= 13]

    print("Running Analysis C: Bracket type preference...")
    bracket_tbl = group_table(df, "bracket_type")
    bracket_tbl["pct"] = bracket_tbl["trade_count"] / len(df) if len(df) else 0

    print("Running Analysis D: Price trend at entry...")
    trend_tbl = group_table(df, "trend_direction")

    print("Running Analysis E: Gumbel gap buckets...")
    gap_tbl = group_table(df.assign(gap_bucket=df["gap_pp"].map(gap_bucket)), "gap_bucket")

    print("Running Analysis F: Sizing and concentration...")
    sizing_tbl = summary[
        ["wallet", "trade_count", "avg_notional", "max_notional", "size_gap_corr", "median_entry_price"]
    ].copy()

    print("Running Analysis G: Hold duration...")
    if not holds.empty:
        hold_tbl = (
            holds.groupby("hold_category", dropna=False)
            .agg(
                trade_count=("entry_price", "size"),
                resolved=("trade_won", lambda x: x.notna().sum()),
                win_rate=("trade_won", win_rate),
                avg_entry_price=("entry_price", "mean"),
                avg_exit_price=("exit_price", "mean"),
                avg_return=("return_per_contract", "mean"),
                median_hold_hours=("hold_hours", "median"),
            )
            .reset_index()
            .sort_values("trade_count", ascending=False)
        )
    else:
        hold_tbl = pd.DataFrame()

    print("Running Analysis H: ColdMath deep tail NO...")
    cold = df[df["wallet_name"] == "ColdMath"].copy()
    cold_no = cold[(cold["outcome"].astype(str).str.lower() == "no") & (cold["price_at_entry"] > 0.9)]

    print("Running Analysis I: Avoid/no-trade diagnostics...")
    trade_dates = set(df["trade_date_et"].dropna())
    all_dates = pd.date_range(df["trade_date_et"].dropna().min(), df["trade_date_et"].dropna().max(), freq="D") if trade_dates else []
    no_trade_dates = [d.date().isoformat() for d in all_dates if d.date().isoformat() not in trade_dates]

    print("Running Cross-venue NYC comparison...")
    missed = nyc_comparison[
        nyc_comparison.get("top_wallet_entered_polymarket", False)
        & ~nyc_comparison.get("our_bot_entered_kalshi", False)
    ] if not nyc_comparison.empty else pd.DataFrame()
    both = nyc_comparison[
        nyc_comparison.get("top_wallet_entered_polymarket", False)
        & nyc_comparison.get("our_bot_entered_kalshi", False)
    ] if not nyc_comparison.empty else pd.DataFrame()

    gopfan2 = df[df["wallet_name"] == "gopfan2"]
    gopfan2_yes = gopfan2[gopfan2["outcome"].astype(str).str.lower() == "yes"]
    gopfan2_lt15 = float((gopfan2_yes["price_at_entry"] < 0.15).mean()) if len(gopfan2_yes) else np.nan
    cold_gt90 = float((cold_no["price_at_entry"] > 0.90).mean()) if len(cold_no) else np.nan
    median_entry_c = df["price_at_entry"].median() * 100 if len(df) else np.nan
    median_gap = df["gap_pp"].dropna().median()
    recs = top_recommendations(df, nyc_comparison)

    report = f"""# TOP POLYMARKET WEATHER WALLET ANALYSIS REPORT

Generated: {datetime.now(ET).isoformat()}

Wallets analyzed: {", ".join(TOP_WALLETS)}

Total weather trades analyzed: {len(df):,}

Date range: {df["trade_date_et"].dropna().min()} to {df["trade_date_et"].dropna().max()}

## Scope And Evidence Quality

This report is research-only. It uses public Polymarket Data API activity/trade-tape data when available and local public Phase 1 artifacts as fallback. The public Polymarket API can still be capped or incomplete, so durable 24-month alpha claims are not made here. Maker/passive fill truth, unfilled orders, queue position, and exact historical spread are not recoverable from these public retrospective artifacts.

Polymarket NYC weather markets are treated as KLGA-like for diagnostics, while our Kalshi pipeline settles KXHIGHNY on KNYC. The `{STATION_CORRECTION_F:.1f}F` station correction is a diagnostic bridge, not exchange settlement truth.

## DATA COVERAGE

{markdown_table(summary)}

## FINDING 1: WHAT PRICE DO TOP WALLETS ACTUALLY ENTER AT?

{markdown_table(price_dist)}

Winner by resolved win rate among populated price buckets: {best_price_bucket.iloc[0]["price_bucket"] if not best_price_bucket.empty else "unavailable"}.

gopfan2 confirmed rule: {gopfan2_lt15:.1%} of fetched gopfan2 YES trades were below 15c ({len(gopfan2_yes):,} YES trades in this slice).

ColdMath confirmed rule: {cold_gt90:.1%} of fetched ColdMath NO entries above 90c token price in the deep-tail proxy set ({len(cold_no):,} trades).

Combined top-wallet median entry price: {median_entry_c:.1f}c.

OUR PIPELINE IMPLICATION: add research/paper diagnostics for extreme-price behavior instead of forcing top-wallet patterns through the 25c-75c Kalshi core gate.

## FINDING 2: WHAT TIME OF DAY DO TOP WALLETS TRADE?

{markdown_table(hour_tbl, 40)}

Peak entry hour: {int(peak_hour.iloc[0]["trade_hour_et"]) if not peak_hour.empty and pd.notna(peak_hour.iloc[0]["trade_hour_et"]) else "unavailable"}:00 ET ({int(peak_hour.iloc[0]["trade_count"]) if not peak_hour.empty else 0:,} trades, {peak_hour.iloc[0]["win_rate"] if not peak_hour.empty and pd.notna(peak_hour.iloc[0]["win_rate"]) else np.nan:.1%} win rate).

Highest observed win-rate hour: {int(best_hour.iloc[0]["trade_hour_et"]) if not best_hour.empty and pd.notna(best_hour.iloc[0]["trade_hour_et"]) else "unavailable"}:00 ET ({int(best_hour.iloc[0]["trade_count"]) if not best_hour.empty else 0:,} trades, {best_hour.iloc[0]["win_rate"] if not best_hour.empty and pd.notna(best_hour.iloc[0]["win_rate"]) else np.nan:.1%} win rate).

Pre-12Z model (before 1PM): {win_rate(pre["trade_won"]) if len(pre) else np.nan:.1%} win rate across {len(pre):,} trades.

Post-12Z model (after 1PM): {win_rate(post["trade_won"]) if len(post) else np.nan:.1%} win rate across {len(post):,} trades.

Best hour for our pipeline to investigate in paper: {int(best_hour.iloc[0]["trade_hour_et"]) if not best_hour.empty and pd.notna(best_hour.iloc[0]["trade_hour_et"]) else "unavailable"}:00 ET, but do not change live timing from this retrospective slice alone.

OUR PIPELINE IMPLICATION: track hour-of-entry and pre/post-12Z as paper analytics; do not move live 11AM/9AM research timing until Kalshi-specific forward paper data supports it.

## FINDING 3: WHICH BRACKET TYPES DO THEY PREFER?

{markdown_table(bracket_tbl)}

Wing/tail brackets: {float(df["bracket_type"].isin(["lower_tail", "upper_tail"]).mean()):.1%} of all trades, {win_rate(df.loc[df["bracket_type"].isin(["lower_tail", "upper_tail"]), "trade_won"]) if len(df) else np.nan:.1%} win rate.

Central brackets: {float((df["bracket_type"] == "central").mean()):.1%} of all trades, {win_rate(df.loc[df["bracket_type"] == "central", "trade_won"]) if len(df) else np.nan:.1%} win rate.

OUR PIPELINE IMPLICATION: keep central and wing/tail analytics separate; do not summarize them as one weather edge.

## FINDING 4: DO THEY BUY THE DIP OR THE MOMENTUM?

{markdown_table(trend_tbl)}

Trades entering on falling price: {int((df["trend_direction"] == "falling").sum()):,} ({win_rate(df.loc[df["trend_direction"] == "falling", "trade_won"]) if len(df) else np.nan:.1%} win rate).

Trades entering on rising price: {int((df["trend_direction"] == "rising").sum()):,} ({win_rate(df.loc[df["trend_direction"] == "rising", "trade_won"]) if len(df) else np.nan:.1%} win rate).

OUR PIPELINE IMPLICATION: add pre-entry trend direction as a research feature and paper-report field. It is descriptive here, not a proven causal alpha signal.

## FINDING 5: WHAT GAP DO THEY REQUIRE BEFORE ENTERING?

{markdown_table(gap_tbl)}

Median gap at entry for NYC rows with reconstructed weather context: {median_gap:.2f}pp.

Our 20pp threshold vs actual top-wallet behavior: only NYC rows with bracket metadata and local KNYC/KLGA forecast context can be scored. The wallet dataset is Polymarket/KLGA-like, so it should not override the frozen Kalshi 20pp threshold.

OUR PIPELINE IMPLICATION: keep the 20pp live threshold frozen; use gap buckets to study missed paper candidates rather than changing production rules.

## FINDING 6: HOW LONG DO THEY HOLD?

{markdown_table(hold_tbl)}

ColdMath holds to settlement/open proxy: {float((holds.loc[holds["wallet_name"] == "ColdMath", "hold_category"] == "settlement_or_open").mean()) if not holds.empty and (holds["wallet_name"] == "ColdMath").any() else np.nan:.1%}.

gopfan2 average hold: {holds.loc[holds["wallet_name"] == "gopfan2", "hold_hours"].mean() if not holds.empty and (holds["wallet_name"] == "gopfan2").any() else np.nan:.2f} hours.

OUR PIPELINE IMPLICATION: keep recording open/close lifecycle in our own logs; public wallet data can infer holds only when both BUY and SELL appear in the captured slice.

## FINDING 7: COLDMATH DEEP TAIL NO ANALYSIS

ColdMath enters NO when token price is >90c in {len(cold_no):,} fetched deep-tail proxy rows.

Our Gumbel model probability on ColdMath deep-tail proxy rows has median {cold_no["gumbel_prob"].dropna().median() if len(cold_no) else np.nan:.3f}; coverage is {cold_no["gumbel_prob"].notna().sum() if len(cold_no) else 0:,}/{len(cold_no):,} because only NYC rows can use our local forecast file.

Win rate: {win_rate(cold_no["trade_won"]) if len(cold_no) else np.nan:.1%}.

OUR DEEP_TAIL_NO threshold (current research sleeve P_yes < 2%) vs ColdMath actual: keep the current strict threshold; this slice supports deep-tail monitoring but not direct copy-trading.

## FINDING 8: DAYS WE MISSED THAT TOP WALLETS CAUGHT

Top wallets traded {len(missed):,} NYC days where our bot did NOT trade in the local backtest join.

Our gap_pp on those days averaged {df.loc[df["city"] == "NYC", "gap_pp"].dropna().mean():.2f}pp across all scored NYC wallet rows.

Those missed day rows had {win_rate(df[df["trade_date_et"].isin(missed["date"] if not missed.empty else [])]["trade_won"]) if not missed.empty else np.nan:.1%} win rate for top wallets.

If we had traded at a lower Polymarket-derived threshold, this report cannot honestly estimate captured P&L because station, market structure, and fees differ.

OUR PIPELINE IMPLICATION: create a paper-only missed-day watchlist instead of lowering the live gap threshold.

## FINDING 9: DAYS WE BOTH TRADED

Overlap days: {len(both):,}.

Top wallet average entry price on overlap days: {both["top_wallet_best_price_polymarket"].mean() * 100 if not both.empty else np.nan:.1f}c.

Our average entry price on overlap days: {both["our_bot_best_price_kalshi"].mean() * 100 if not both.empty else np.nan:.1f}c.

Price difference: top wallets got {"better" if (both["price_advantage_wallet"].mean() if not both.empty else 0) > 0 else "worse/unknown"} fills by {abs(both["price_advantage_wallet"].mean()) * 100 if not both.empty and both["price_advantage_wallet"].notna().any() else np.nan:.1f}c average.

Our win rate on overlap days: {win_rate(both["our_bot_won_kalshi"]) if not both.empty else np.nan:.1%}.

Top wallet win rate on overlap days: {win_rate(both["top_wallet_won_polymarket"]) if not both.empty else np.nan:.1%}.

## FINDING 10: WHAT MARKET CONDITIONS TRIGGER TOP WALLET ENTRIES?

Top wallets enter when:

- YES/token price is below 15c on {float((df["price_at_entry"] < 0.15).mean()):.1%} of entries.
- Market activity in the prior 6h averages {df["market_activity_per_hour"].dropna().mean():.2f} trades/hour.
- Price trend is most often `{df["trend_direction"].mode().iloc[0] if not df["trend_direction"].dropna().empty else "unknown"}` ({float((df["trend_direction"] == (df["trend_direction"].mode().iloc[0] if not df["trend_direction"].dropna().empty else "")).mean()):.1%} of entries).
- Model consensus is {df["distance_from_consensus_f"].dropna().abs().mean():.2f}F from bracket center on average for scored NYC rows.
- They avoid, or at least do not appear in this slice during, {len(no_trade_dates):,} calendar days between the first and last captured trade date.

## TOP 5 ACTIONABLE CHANGES FOR OUR KALSHI PIPELINE

1. {recs[0]}
2. {recs[1]}
3. {recs[2]}
4. {recs[3]}
5. {recs[4]}

Each recommendation above is research/paper-first. None is strong enough by itself to modify live execution, the LaunchAgent, `main.py`, `event_triggers.py`, or the frozen 20pp live threshold.
"""
    (OUT_DIR / "WALLET_ANALYSIS_REPORT.md").write_text(report)
    return recs


def main() -> None:
    mkdirs()
    print("=== POLYMARKET WEATHER WALLET ANALYSIS ===")
    print("Research-only: no live pipeline files are imported or modified.")
    enriched_path = OUT_DIR / "all_weather_trades.csv"
    if enriched_path.exists() and os.getenv("WALLET_ANALYSIS_REFRESH", "0") != "1":
        print("Using enriched cached outputs from data/wallet_analysis/. Set WALLET_ANALYSIS_REFRESH=1 to rebuild.")
        df = pd.read_csv(enriched_path)
        for bool_col in ("trade_won", "would_our_gate_pass", "our_bot_traded_same_day", "our_bot_same_bracket", "our_bot_would_have_traded"):
            if bool_col in df.columns:
                df[bool_col] = df[bool_col].map(
                    lambda x: True
                    if str(x).lower() == "true"
                    else False
                    if str(x).lower() == "false"
                    else np.nan
                )
        nyc_comparison = (
            pd.read_csv(OUT_DIR / "nyc_comparison.csv")
            if (OUT_DIR / "nyc_comparison.csv").exists()
            else pd.DataFrame()
        )
        for bool_col in ("top_wallet_entered_polymarket", "top_wallet_won_polymarket", "our_bot_entered_kalshi", "our_bot_won_kalshi"):
            if bool_col in nyc_comparison.columns:
                nyc_comparison[bool_col] = nyc_comparison[bool_col].map(
                    lambda x: True
                    if str(x).lower() == "true"
                    else False
                    if str(x).lower() == "false"
                    else np.nan
                )
        holds = (
            pd.read_csv(OUT_DIR / "hold_duration_inference.csv")
            if (OUT_DIR / "hold_duration_inference.csv").exists()
            else pd.DataFrame()
        )
        if "trade_won" in holds.columns:
            holds["trade_won"] = holds["trade_won"].map(
                lambda x: True
                if str(x).lower() == "true"
                else False
                if str(x).lower() == "false"
                else np.nan
            )
        summary = (
            pd.read_csv(OUT_DIR / "behavioral_summary.csv")
            if (OUT_DIR / "behavioral_summary.csv").exists()
            else behavioral_summary(df, holds)
        )
        recs = generate_report(df, nyc_comparison, summary, holds)
        print("=== ANALYSIS COMPLETE ===")
        print(f"Total weather trades analyzed: {len(df):,}")
        print("Report saved to: data/wallet_analysis/WALLET_ANALYSIS_REPORT.md")
        print("=== TOP 5 RECOMMENDATIONS PREVIEW ===")
        for i, rec in enumerate(recs, 1):
            print(f"{i}. {rec}")
        return
    try_leaderboard()

    all_trades: list[dict[str, Any]] = []
    for wallet_name, wallet in TOP_WALLETS.items():
        try:
            trades = pull_wallet_weather_trades(wallet_name, wallet)
            print(f"Completed {wallet_name}: {len(trades)} weather trades")
            all_trades.extend(trades)
        except Exception as exc:
            print(f"WARNING: failed wallet {wallet_name}: {exc}")

    found_wallets = {t["proxyWallet"].lower() for t in all_trades}
    missing = {addr.lower() for addr in TOP_WALLETS.values()} - found_wallets
    all_trades.extend(fallback_phase1_trades(missing))

    if not all_trades:
        raise SystemExit("No weather trades available from API or local fallback.")

    df = pd.DataFrame(all_trades).drop_duplicates(
        subset=["wallet_name", "transactionHash", "conditionId", "timestamp", "outcomeIndex", "price"],
        keep="first",
    )
    df = df[df["timestamp"].fillna(0).astype(int) >= START_TS].copy()
    df = df.sort_values(["wallet_name", "timestamp"], ascending=[True, True]).reset_index(drop=True)

    print(f"Collected {len(df):,} weather trades after de-duplication.")
    df = enrich_market_metadata(df)
    df = add_price_context(df)
    df = add_weather_context(df)
    df, nyc_comparison = add_backtest_comparison(df)
    holds = infer_holds(df)
    summary = behavioral_summary(df, holds)
    df.to_csv(OUT_DIR / "all_weather_trades.csv", index=False)
    nyc_comparison.to_csv(OUT_DIR / "nyc_comparison.csv", index=False)
    summary.to_csv(OUT_DIR / "behavioral_summary.csv", index=False)
    if not holds.empty:
        holds.to_csv(OUT_DIR / "hold_duration_inference.csv", index=False)
    recs = generate_report(df, nyc_comparison, summary, holds)

    print("=== ANALYSIS COMPLETE ===")
    print(f"Total weather trades analyzed: {len(df):,}")
    print("Report saved to: data/wallet_analysis/WALLET_ANALYSIS_REPORT.md")
    print("=== TOP 5 RECOMMENDATIONS PREVIEW ===")
    for i, rec in enumerate(recs, 1):
        print(f"{i}. {rec}")


if __name__ == "__main__":
    main()
