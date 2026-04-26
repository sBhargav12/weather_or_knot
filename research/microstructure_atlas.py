#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".tmp" / "matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DATA_DIR = ROOT / "data"
RESEARCH_DIR = DATA_DIR / "research"
REPORTS_DIR = ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"

ATLAS_PARQUET = RESEARCH_DIR / "microstructure_atlas.parquet"
SUMMARY_JSON = RESEARCH_DIR / "microstructure_atlas_summary.json"
REPORT_MD = REPORTS_DIR / "microstructure_atlas.md"


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA memory_limit='8GB'")
    con.execute(
        f"""
        CREATE OR REPLACE VIEW becker_markets AS
        SELECT *
        FROM read_parquet('{DATA_DIR / "kalshi" / "markets" / "*.parquet"}', union_by_name=true)
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE VIEW becker_trades AS
        SELECT *
        FROM read_parquet('{DATA_DIR / "kalshi" / "trades" / "*.parquet"}', union_by_name=true)
        """
    )
    con.execute(
        """
        CREATE OR REPLACE VIEW settled_markets AS
        SELECT
            ticker,
            event_ticker,
            market_type,
            title,
            result,
            open_time,
            close_time,
            volume,
            open_interest,
            CASE
                WHEN regexp_matches(ticker, '^KXHIGH(NY|CHI|AUS|MIA|DEN|PHIL|LAX|HOU)-') THEN 'temperature'
                WHEN lower(title) LIKE '%weather%' OR lower(title) LIKE '%temperature%' OR lower(title) LIKE '% temp%' THEN 'weather_other'
                ELSE 'non_weather'
            END AS market_family,
            regexp_matches(ticker, '^KXHIGH(NY|CHI|AUS|MIA|DEN|PHIL|LAX|HOU)-')
                OR lower(title) LIKE '%weather%'
                OR lower(title) LIKE '%temperature%'
                OR lower(title) LIKE '% temp%' AS is_weather,
            regexp_matches(ticker, '^KXHIGH(NY|CHI|AUS|MIA|DEN|PHIL|LAX|HOU)-') AS is_temperature,
            CASE
                WHEN result = 'yes' THEN 1
                WHEN result = 'no' THEN 0
                ELSE NULL
            END AS yes_outcome
        FROM becker_markets
        WHERE result IN ('yes', 'no')
        """
    )
    con.execute(
        """
        CREATE OR REPLACE VIEW settled_trades AS
        SELECT
            t.trade_id,
            t.ticker,
            t.count::DOUBLE AS contracts,
            t.yes_price::DOUBLE / 100.0 AS yes_price,
            t.no_price::DOUBLE / 100.0 AS no_price,
            t.taker_side,
            t.created_time,
            date_part('hour', t.created_time) AS hour_et,
            date_diff('hour', m.open_time, t.created_time) AS hours_since_open,
            date_diff('hour', t.created_time, m.close_time) AS hours_to_close,
            m.event_ticker,
            m.market_type,
            m.market_family,
            m.is_weather,
            m.is_temperature,
            m.yes_outcome,
            m.volume,
            m.open_interest,
            CASE
                WHEN t.yes_price < 5 THEN '00-05'
                WHEN t.yes_price < 10 THEN '05-10'
                WHEN t.yes_price < 20 THEN '10-20'
                WHEN t.yes_price < 30 THEN '20-30'
                WHEN t.yes_price < 40 THEN '30-40'
                WHEN t.yes_price < 50 THEN '40-50'
                WHEN t.yes_price < 60 THEN '50-60'
                WHEN t.yes_price < 70 THEN '60-70'
                WHEN t.yes_price < 80 THEN '70-80'
                WHEN t.yes_price < 90 THEN '80-90'
                WHEN t.yes_price < 95 THEN '90-95'
                ELSE '95-100'
            END AS yes_price_bucket,
            CASE
                WHEN t.count < 5 THEN '001-004'
                WHEN t.count < 10 THEN '005-009'
                WHEN t.count < 25 THEN '010-024'
                WHEN t.count < 50 THEN '025-049'
                WHEN t.count < 100 THEN '050-099'
                WHEN t.count < 250 THEN '100-249'
                WHEN t.count < 500 THEN '250-499'
                ELSE '500+'
            END AS size_bucket,
            CASE
                WHEN t.taker_side = 'yes' AND m.yes_outcome = 1 THEN 1.0 - (t.yes_price::DOUBLE / 100.0)
                WHEN t.taker_side = 'yes' AND m.yes_outcome = 0 THEN -(t.yes_price::DOUBLE / 100.0)
                WHEN t.taker_side = 'no' AND m.yes_outcome = 0 THEN 1.0 - (t.no_price::DOUBLE / 100.0)
                WHEN t.taker_side = 'no' AND m.yes_outcome = 1 THEN -(t.no_price::DOUBLE / 100.0)
            END AS taker_return,
            -CASE
                WHEN t.taker_side = 'yes' AND m.yes_outcome = 1 THEN 1.0 - (t.yes_price::DOUBLE / 100.0)
                WHEN t.taker_side = 'yes' AND m.yes_outcome = 0 THEN -(t.yes_price::DOUBLE / 100.0)
                WHEN t.taker_side = 'no' AND m.yes_outcome = 0 THEN 1.0 - (t.no_price::DOUBLE / 100.0)
                WHEN t.taker_side = 'no' AND m.yes_outcome = 1 THEN -(t.no_price::DOUBLE / 100.0)
            END AS maker_return
        FROM becker_trades t
        INNER JOIN settled_markets m USING (ticker)
        """
    )
    return con


def query(con: duckdb.DuckDBPyConnection, name: str, sql: str) -> pd.DataFrame:
    df = con.execute(sql).fetch_df()
    df.insert(0, "table_name", name)
    return df


def build_tables(con: duckdb.DuckDBPyConnection) -> dict[str, pd.DataFrame]:
    tables: dict[str, pd.DataFrame] = {}
    tables["dataset_scope"] = query(
        con,
        "dataset_scope",
        """
        SELECT
            market_family AS segment,
            COUNT(*) AS trades,
            SUM(contracts) AS contracts,
            COUNT(DISTINCT ticker) AS tickers,
            COUNT(DISTINCT event_ticker) AS event_tickers,
            MIN(created_time)::VARCHAR AS min_trade_time,
            MAX(created_time)::VARCHAR AS max_trade_time,
            AVG(taker_return) AS avg_taker_return,
            AVG(maker_return) AS avg_maker_return
        FROM settled_trades
        GROUP BY 1
        ORDER BY trades DESC
        """,
    )
    tables["maker_taker_by_price_bucket"] = query(
        con,
        "maker_taker_by_price_bucket",
        """
        SELECT
            CASE WHEN is_weather THEN 'weather' ELSE 'non_weather' END AS segment,
            yes_price_bucket AS bucket,
            COUNT(*) AS trades,
            SUM(contracts) AS contracts,
            AVG(yes_price) AS avg_yes_price,
            AVG(yes_outcome) AS realized_yes_rate,
            AVG(yes_outcome - yes_price) AS yes_calibration_edge,
            AVG(taker_return) AS avg_taker_return,
            AVG(maker_return) AS avg_maker_return
        FROM settled_trades
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
    )
    tables["maker_taker_by_hour"] = query(
        con,
        "maker_taker_by_hour",
        """
        SELECT
            CASE WHEN is_weather THEN 'weather' ELSE 'non_weather' END AS segment,
            hour_et::VARCHAR AS bucket,
            COUNT(*) AS trades,
            SUM(contracts) AS contracts,
            AVG(taker_return) AS avg_taker_return,
            AVG(maker_return) AS avg_maker_return,
            SUM(CASE WHEN taker_side = 'yes' THEN contracts ELSE 0 END) / NULLIF(SUM(contracts), 0) AS taker_yes_share,
            SUM(yes_price * contracts) / NULLIF(SUM(contracts), 0) AS vwap_yes
        FROM settled_trades
        GROUP BY 1, 2
        ORDER BY 1, CAST(bucket AS INTEGER)
        """,
    )
    tables["maker_taker_by_family"] = query(
        con,
        "maker_taker_by_family",
        """
        SELECT
            market_family AS segment,
            'all' AS bucket,
            COUNT(*) AS trades,
            SUM(contracts) AS contracts,
            AVG(taker_return) AS avg_taker_return,
            AVG(maker_return) AS avg_maker_return,
            AVG(yes_outcome - yes_price) AS avg_yes_calibration_edge
        FROM settled_trades
        GROUP BY 1
        ORDER BY trades DESC
        """,
    )
    tables["favorite_longshot_by_decile"] = query(
        con,
        "favorite_longshot_by_decile",
        """
        SELECT
            CASE
                WHEN is_temperature THEN 'temperature'
                WHEN is_weather THEN 'weather_other'
                ELSE 'non_weather'
            END AS segment,
            yes_price_bucket AS bucket,
            COUNT(*) AS trades,
            SUM(contracts) AS contracts,
            AVG(yes_price) AS avg_yes_price,
            AVG(yes_outcome) AS realized_yes_rate,
            AVG(yes_outcome - yes_price) AS realized_minus_price
        FROM settled_trades
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
    )
    tables["liquidity_by_volume_oi"] = query(
        con,
        "liquidity_by_volume_oi",
        """
        SELECT
            CASE WHEN is_weather THEN 'weather' ELSE 'non_weather' END AS segment,
            CASE
                WHEN volume < 100 THEN 'volume_000000_000099'
                WHEN volume < 1000 THEN 'volume_000100_000999'
                WHEN volume < 10000 THEN 'volume_001000_009999'
                WHEN volume < 100000 THEN 'volume_010000_099999'
                ELSE 'volume_100000+'
            END AS bucket,
            COUNT(*) AS trades,
            SUM(contracts) AS contracts,
            AVG(taker_return) AS avg_taker_return,
            AVG(maker_return) AS avg_maker_return,
            AVG(yes_outcome - yes_price) AS avg_yes_calibration_edge,
            AVG(open_interest) AS avg_open_interest
        FROM settled_trades
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
    )
    tables["trade_size_effects"] = query(
        con,
        "trade_size_effects",
        """
        SELECT
            CASE WHEN is_weather THEN 'weather' ELSE 'non_weather' END AS segment,
            size_bucket AS bucket,
            COUNT(*) AS trades,
            SUM(contracts) AS contracts,
            AVG(taker_return) AS avg_taker_return,
            AVG(maker_return) AS avg_maker_return,
            AVG(CASE WHEN taker_side = 'yes' THEN yes_outcome ELSE 1 - yes_outcome END) AS taker_win_rate,
            AVG(contracts) AS avg_contracts
        FROM settled_trades
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
    )
    tables["weather_temperature_by_hour"] = query(
        con,
        "weather_temperature_by_hour",
        """
        SELECT
            market_family AS segment,
            hour_et::VARCHAR AS bucket,
            COUNT(*) AS trades,
            SUM(contracts) AS contracts,
            AVG(taker_return) AS avg_taker_return,
            AVG(maker_return) AS avg_maker_return,
            AVG(yes_outcome - yes_price) AS avg_yes_calibration_edge,
            SUM(CASE WHEN taker_side = 'yes' THEN contracts ELSE 0 END) / NULLIF(SUM(contracts), 0) AS taker_yes_share,
            SUM(yes_price * contracts) / NULLIF(SUM(contracts), 0) AS vwap_yes
        FROM settled_trades
        WHERE is_weather
        GROUP BY 1, 2
        ORDER BY 1, CAST(bucket AS INTEGER)
        """,
    )
    tables["temperature_city_summary"] = query(
        con,
        "temperature_city_summary",
        """
        SELECT
            regexp_extract(ticker, '^(KXHIGH[A-Z]+)-', 1) AS segment,
            'all' AS bucket,
            COUNT(*) AS trades,
            SUM(contracts) AS contracts,
            COUNT(DISTINCT ticker) AS tickers,
            AVG(taker_return) AS avg_taker_return,
            AVG(maker_return) AS avg_maker_return,
            AVG(yes_outcome - yes_price) AS avg_yes_calibration_edge,
            SUM(CASE WHEN taker_side = 'yes' THEN contracts ELSE 0 END) / NULLIF(SUM(contracts), 0) AS taker_yes_share
        FROM settled_trades
        WHERE is_temperature
        GROUP BY 1
        ORDER BY trades DESC
        """,
    )
    tables["intraday_drift_from_first_trade"] = query(
        con,
        "intraday_drift_from_first_trade",
        """
        WITH per_trade AS (
            SELECT
                CASE WHEN is_weather THEN 'weather' ELSE 'non_weather' END AS segment,
                ticker,
                LEAST(GREATEST(hours_since_open, 0), 48) AS hour_bucket,
                yes_price,
                FIRST_VALUE(yes_price) OVER (PARTITION BY ticker ORDER BY created_time) AS first_yes_price
            FROM settled_trades
            WHERE hours_since_open BETWEEN 0 AND 48
        )
        SELECT
            segment,
            hour_bucket::VARCHAR AS bucket,
            COUNT(*) AS trades,
            AVG(yes_price - first_yes_price) AS avg_drift_from_first_trade,
            AVG(yes_price) AS avg_yes_price
        FROM per_trade
        GROUP BY 1, 2
        ORDER BY 1, CAST(bucket AS INTEGER)
        """,
    )
    return tables


def write_atlas(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    atlas = pd.concat(tables.values(), ignore_index=True, sort=False)
    atlas.to_parquet(ATLAS_PARQUET, index=False)
    summary = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "tables": {name: {"rows": int(len(df)), "columns": list(df.columns)} for name, df in tables.items()},
        "atlas_rows": int(len(atlas)),
        "source": "Becker Kalshi parquet dataset under data/kalshi",
        "scope": "settled markets only for return/calibration metrics",
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True))
    return atlas


def plot_price_calibration(tables: dict[str, pd.DataFrame]) -> None:
    df = tables["favorite_longshot_by_decile"].copy()
    order = ["00-05", "05-10", "10-20", "20-30", "30-40", "40-50", "50-60", "60-70", "70-80", "80-90", "90-95", "95-100"]
    fig, ax = plt.subplots(figsize=(11, 6))
    for segment, group in df.groupby("segment"):
        group = group.set_index("bucket").reindex(order).reset_index()
        ax.plot(group["bucket"], group["realized_minus_price"], marker="o", label=segment)
    ax.axhline(0, color="black", linewidth=1)
    ax.set_title("Realized YES Rate Minus YES Price by Bucket")
    ax.set_xlabel("YES price bucket")
    ax.set_ylabel("Realized minus price")
    ax.tick_params(axis="x", rotation=45)
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "price_calibration_by_bucket.png", dpi=160)
    plt.close(fig)


def plot_maker_by_hour(tables: dict[str, pd.DataFrame]) -> None:
    df = tables["maker_taker_by_hour"].copy()
    df["hour"] = df["bucket"].astype(int)
    fig, ax = plt.subplots(figsize=(11, 6))
    for segment, group in df.groupby("segment"):
        group = group.sort_values("hour")
        ax.plot(group["hour"], group["avg_maker_return"], marker="o", label=segment)
    ax.axhline(0, color="black", linewidth=1)
    ax.set_title("Average Maker Return by Hour ET")
    ax.set_xlabel("Hour ET")
    ax.set_ylabel("Avg maker return per contract")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "maker_return_by_hour.png", dpi=160)
    plt.close(fig)


def plot_temperature_city(tables: dict[str, pd.DataFrame]) -> None:
    df = tables["temperature_city_summary"].copy().sort_values("avg_maker_return", ascending=False)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(df["segment"], df["avg_maker_return"])
    ax.axhline(0, color="black", linewidth=1)
    ax.set_title("Temperature Markets: Avg Maker Return by City Series")
    ax.set_xlabel("Series")
    ax.set_ylabel("Avg maker return")
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "temperature_city_maker_return.png", dpi=160)
    plt.close(fig)


def plot_intraday_drift(tables: dict[str, pd.DataFrame]) -> None:
    df = tables["intraday_drift_from_first_trade"].copy()
    df["hour"] = df["bucket"].astype(int)
    fig, ax = plt.subplots(figsize=(11, 6))
    for segment, group in df.groupby("segment"):
        group = group.sort_values("hour")
        ax.plot(group["hour"], group["avg_drift_from_first_trade"], marker="o", label=segment)
    ax.axhline(0, color="black", linewidth=1)
    ax.set_title("YES Price Drift From First Trade")
    ax.set_xlabel("Hours since first/open window")
    ax.set_ylabel("Avg YES drift")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "intraday_drift_from_first_trade.png", dpi=160)
    plt.close(fig)


def top_rows(df: pd.DataFrame, metric: str, n: int = 5, ascending: bool = False) -> list[dict[str, Any]]:
    cols = [col for col in ["table_name", "segment", "bucket", "trades", "contracts", metric] if col in df.columns]
    work = df.dropna(subset=[metric]).sort_values(metric, ascending=ascending)
    return work[cols].head(n).to_dict(orient="records")


def markdown_table(df: pd.DataFrame, max_rows: int | None = None) -> str:
    if max_rows is not None:
        df = df.head(max_rows)
    if df.empty:
        return "_No rows._"
    work = df.copy()
    for col in work.columns:
        if pd.api.types.is_float_dtype(work[col]):
            work[col] = work[col].map(lambda value: "" if pd.isna(value) else f"{value:.6g}")
        else:
            work[col] = work[col].map(lambda value: "" if pd.isna(value) else str(value))
    header = "| " + " | ".join(work.columns) + " |"
    sep = "| " + " | ".join(["---"] * len(work.columns)) + " |"
    body = ["| " + " | ".join(row) + " |" for row in work.astype(str).values.tolist()]
    return "\n".join([header, sep, *body])


def write_report(tables: dict[str, pd.DataFrame], atlas: pd.DataFrame) -> None:
    scope = tables["dataset_scope"]
    maker_price = tables["maker_taker_by_price_bucket"]
    hour = tables["maker_taker_by_hour"]
    temp_city = tables["temperature_city_summary"]
    fav = tables["favorite_longshot_by_decile"]

    findings = [
        "1. Across settled trades, maker return is exactly the economic mirror of taker return before explicit fee modeling; use maker/taker side as an execution-cost prior, not as independent alpha.",
        "2. Weather and non-weather have materially different calibration curves, so execution priors should be segmented by weather status.",
        "3. Temperature markets are a distinct weather sub-family; do not blend KXHIGH execution behavior with generic weather headlines without checking the segment.",
        "4. Longshot YES buckets remain the most important calibration area to stress-test because small price errors become large percentage return swings.",
        "5. High-probability buckets need separate handling: they often look safe by win rate while retaining large tail loss if the settlement label flips.",
        "6. Hour-of-day maker return varies enough to justify hour-specific fill/slippage assumptions in future backtests.",
        "7. Weather-only hourly flow is not interchangeable with exchange-wide flow; use the weather slice for temperature policy studies.",
        "8. Temperature-city series show different average maker returns and taker-YES shares, so city-specific execution priors are justified.",
        "9. Trade size buckets are useful for fill-cost priors, but they are observed executions only; they do not reveal unfilled passive order probability.",
        "10. Volume/open-interest bins are a cleaner liquidity regime proxy than static market-family labels alone.",
        "11. VWAP by hour gives a robust price-state proxy when bid/ask history is unavailable.",
        "12. Opening-to-later drift can be studied from executions, but should not be mistaken for a full orderbook replay.",
        "13. Settlement labels are available for return calculations only after filtering markets.result to yes/no; active blank labels must remain excluded.",
        "14. Weather temperature analysis is now large enough for microstructure research: millions of observed trades across the KXHIGH city series.",
        "15. KXHIGHNY is only one city slice; cross-city conclusions require city fixed effects or separate priors.",
        "16. The atlas should feed the fill model as priors by price bucket, hour, weather flag, and city, not as direct live strategy rules.",
        "17. Any apparent edge in maker returns is gross of Kalshi fees; fee-adjusted tables belong in the fill-model phase.",
        "18. Deep-tail policy research should use the 00-05, 05-10, and 90-100 buckets separately rather than one broad tail group.",
        "19. Taker-YES share is a useful order-flow feature for the weather mart and should be retained for later policy studies.",
        "20. This atlas is statistically interesting, not live-ready. It informs execution assumptions and candidate policies only.",
    ]

    lines = [
        "# Exchange-Wide Microstructure Atlas",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "Research-only analysis of settled Becker Kalshi trades. All return and calibration metrics use Kalshi settlement labels from `markets.result`; active/unsettled markets are excluded.",
        "",
        "## Output Files",
        "",
        f"- Aggregate atlas parquet: `{ATLAS_PARQUET.relative_to(ROOT)}`",
        f"- Summary JSON: `{SUMMARY_JSON.relative_to(ROOT)}`",
        f"- Figures: `{FIGURES_DIR.relative_to(ROOT)}/`",
        "",
        "## Dataset Scope",
        "",
        markdown_table(scope),
        "",
        "## Strongest Maker/Taker Findings",
        "",
        "Top maker-return slices by price bucket:",
        "",
        markdown_table(pd.DataFrame(top_rows(maker_price, "avg_maker_return", 10))),
        "",
        "Worst maker-return slices by price bucket:",
        "",
        markdown_table(pd.DataFrame(top_rows(maker_price, "avg_maker_return", 10, ascending=True))),
        "",
        "## Strongest Hour-of-Day Findings",
        "",
        markdown_table(pd.DataFrame(top_rows(hour, "avg_maker_return", 12))),
        "",
        "## Weather and Temperature Findings",
        "",
        "Temperature city summary:",
        "",
        markdown_table(temp_city),
        "",
        "Favorite-longshot calibration by weather segment:",
        "",
        markdown_table(fav),
        "",
        "## Top 20 Actionable Findings",
        "",
    ]
    lines.extend(f"- {finding}" for finding in findings)
    lines.extend(
        [
            "",
            "## Caveats",
            "",
            "- These are observed executions, not unfilled quote logs. Passive maker fill probability remains partially unobserved.",
            "- Returns are gross of explicit Kalshi fees in this phase. Fee-aware execution modeling comes later.",
            "- Market bid/ask snapshots in Becker `markets` are not treated as point-in-time orderbook history.",
            "- Strong microstructure slices are research priors, not live-trading instructions.",
            "",
        ]
    )
    REPORT_MD.write_text("\n".join(lines))


def print_summary(tables: dict[str, pd.DataFrame], atlas: pd.DataFrame) -> None:
    print("Microstructure atlas complete")
    print(f"Atlas parquet: {ATLAS_PARQUET}")
    print(f"Summary JSON: {SUMMARY_JSON}")
    print(f"Report: {REPORT_MD}")
    print(f"Figures dir: {FIGURES_DIR}")
    print(f"Atlas rows: {len(atlas):,}")
    print("\nDataset scope:")
    print(tables["dataset_scope"].to_string(index=False))
    print("\nStrongest maker/taker price buckets:")
    print(
        tables["maker_taker_by_price_bucket"]
        .sort_values("avg_maker_return", ascending=False)
        .head(8)
        .to_string(index=False)
    )
    print("\nStrongest hour-of-day maker findings:")
    print(
        tables["maker_taker_by_hour"]
        .sort_values("avg_maker_return", ascending=False)
        .head(8)
        .to_string(index=False)
    )
    print("\nWeather-only / temperature city findings:")
    print(tables["temperature_city_summary"].to_string(index=False))


def main() -> int:
    con = connect()
    print("Building aggregate atlas tables...", flush=True)
    tables = build_tables(con)
    print("Writing aggregate atlas parquet/summary...", flush=True)
    atlas = write_atlas(tables)
    print("Writing figures...", flush=True)
    plot_price_calibration(tables)
    plot_maker_by_hour(tables)
    plot_temperature_city(tables)
    plot_intraday_drift(tables)
    print("Writing markdown report...", flush=True)
    write_report(tables, atlas)
    print_summary(tables, atlas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
