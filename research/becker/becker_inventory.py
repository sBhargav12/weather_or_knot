#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data" / "kalshi"
RESEARCH_DIR = ROOT / "data" / "research"
REPORTS_DIR = ROOT / "reports"
INVENTORY_JSON = RESEARCH_DIR / "becker_inventory.json"
SCHEMA_JSON = RESEARCH_DIR / "becker_schema_summary.json"
REPORT_MD = REPORTS_DIR / "becker_dataset_inventory.md"

COMMANDS_RUN = [
    "sed -n '1,420p' CLAUDE.md",
    "shasum -a 256 -c release_assets/SHA256SUMS.txt",
    "cat release_assets/john-becker-kalshi-dataset.tar.zst.part-* > release_assets/john-becker-kalshi-dataset.tar.zst && zstd -t release_assets/john-becker-kalshi-dataset.tar.zst",
    "zstd -dc release_assets/john-becker-kalshi-dataset.tar.zst | tar -xf -",
    ".venv/bin/python research/becker_inventory.py",
]


def parquet_files(folder: Path) -> list[Path]:
    return sorted(folder.glob("*.parquet"))


def sizeof_fmt(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024 or unit == "TB":
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}TB"


def schema_fingerprint(schema: pq.ParquetSchema) -> tuple[tuple[str, str], ...]:
    return tuple((name, str(schema.column(i).physical_type)) for i, name in enumerate(schema.names))


def inspect_files(folder_name: str, files: list[Path]) -> dict[str, Any]:
    corrupt: list[dict[str, str]] = []
    row_count = 0
    schema_counts: Counter = Counter()
    schema_examples: dict[str, str] = {}
    file_rows: list[dict[str, Any]] = []

    for path in files:
        rel = str(path.relative_to(ROOT))
        try:
            meta = pq.ParquetFile(path).metadata
            rows = int(meta.num_rows)
            row_count += rows
            fp = schema_fingerprint(pq.ParquetFile(path).schema)
            fp_key = json.dumps(fp)
            schema_counts[fp_key] += 1
            schema_examples.setdefault(fp_key, rel)
            file_rows.append({"path": rel, "rows": rows, "size_bytes": path.stat().st_size})
        except Exception as exc:
            corrupt.append({"path": rel, "error": repr(exc)})

    return {
        "folder": folder_name,
        "file_count": len(files),
        "valid_file_count": len(files) - len(corrupt),
        "corrupt_file_count": len(corrupt),
        "size_bytes": sum(path.stat().st_size for path in files if path.exists()),
        "size_human": sizeof_fmt(sum(path.stat().st_size for path in files if path.exists())),
        "row_count_from_metadata": row_count,
        "schema_variant_count": len(schema_counts),
        "schema_variants": [
            {
                "variant_id": index + 1,
                "file_count": count,
                "example_file": schema_examples[key],
                "columns": [{"name": name, "physical_type": typ} for name, typ in json.loads(key)],
            }
            for index, (key, count) in enumerate(schema_counts.most_common())
        ],
        "corrupt_files": corrupt,
        "file_rows_sample": file_rows[:5],
    }


def detect_range_gaps(files: list[Path], prefix: str) -> dict[str, Any]:
    ranges = []
    pattern = re.compile(rf"{re.escape(prefix)}_(\d+)_(\d+)\.parquet$")
    for path in files:
        match = pattern.match(path.name)
        if match:
            ranges.append((int(match.group(1)), int(match.group(2)), path.name))
    ranges.sort()
    gaps = []
    overlaps = []
    prev_end = None
    prev_name = None
    for start, end, name in ranges:
        if prev_end is not None:
            if start > prev_end:
                gaps.append({"after": prev_name, "before": name, "missing_start": prev_end, "missing_end": start})
            elif start < prev_end:
                overlaps.append({"previous": prev_name, "current": name, "overlap_start": start, "previous_end": prev_end})
        prev_end = end
        prev_name = name
    return {
        "range_file_count": len(ranges),
        "min_start": ranges[0][0] if ranges else None,
        "max_end": ranges[-1][1] if ranges else None,
        "gap_count": len(gaps),
        "overlap_count": len(overlaps),
        "gaps_sample": gaps[:20],
        "overlaps_sample": overlaps[:20],
    }


def duckdb_scalar(con: duckdb.DuckDBPyConnection, sql: str) -> Any:
    return con.execute(sql).fetchone()[0]


def duckdb_summary(con: duckdb.DuckDBPyConnection, relation_name: str, folder_glob: str, kind: str) -> dict[str, Any]:
    con.execute(
        f"""
        CREATE OR REPLACE VIEW {relation_name} AS
        SELECT *
        FROM read_parquet('{folder_glob}', union_by_name=true, filename=true)
        """
    )

    if kind == "trades":
        duplicate_trade_ids = duckdb_scalar(
            con,
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT trade_id
                FROM {relation_name}
                WHERE trade_id IS NOT NULL
                GROUP BY trade_id
                HAVING COUNT(*) > 1
            )
            """,
        )
        return {
            "row_count": duckdb_scalar(con, f"SELECT COUNT(*) FROM {relation_name}"),
            "unique_tickers": duckdb_scalar(con, f"SELECT COUNT(DISTINCT ticker) FROM {relation_name}"),
            "unique_trade_ids": duckdb_scalar(con, f"SELECT COUNT(DISTINCT trade_id) FROM {relation_name}"),
            "duplicate_trade_id_count": duplicate_trade_ids,
            "min_created_time": str(duckdb_scalar(con, f"SELECT MIN(created_time) FROM {relation_name}")),
            "max_created_time": str(duckdb_scalar(con, f"SELECT MAX(created_time) FROM {relation_name}")),
            "min_fetched_at": str(duckdb_scalar(con, f"SELECT MIN(_fetched_at) FROM {relation_name}")),
            "max_fetched_at": str(duckdb_scalar(con, f"SELECT MAX(_fetched_at) FROM {relation_name}")),
        }

    duplicate_market_versions = duckdb_scalar(
        con,
        f"""
        SELECT COUNT(*)
        FROM (
            SELECT ticker, _fetched_at
            FROM {relation_name}
            WHERE ticker IS NOT NULL AND _fetched_at IS NOT NULL
            GROUP BY ticker, _fetched_at
            HAVING COUNT(*) > 1
        )
        """,
    )
    return {
        "row_count": duckdb_scalar(con, f"SELECT COUNT(*) FROM {relation_name}"),
        "unique_tickers": duckdb_scalar(con, f"SELECT COUNT(DISTINCT ticker) FROM {relation_name}"),
        "unique_event_tickers": duckdb_scalar(con, f"SELECT COUNT(DISTINCT event_ticker) FROM {relation_name}"),
        "duplicate_ticker_fetched_at_count": duplicate_market_versions,
        "min_created_time": str(duckdb_scalar(con, f"SELECT MIN(created_time) FROM {relation_name}")),
        "max_created_time": str(duckdb_scalar(con, f"SELECT MAX(created_time) FROM {relation_name}")),
        "min_open_time": str(duckdb_scalar(con, f"SELECT MIN(open_time) FROM {relation_name}")),
        "max_open_time": str(duckdb_scalar(con, f"SELECT MAX(open_time) FROM {relation_name}")),
        "min_close_time": str(duckdb_scalar(con, f"SELECT MIN(close_time) FROM {relation_name}")),
        "max_close_time": str(duckdb_scalar(con, f"SELECT MAX(close_time) FROM {relation_name}")),
        "min_fetched_at": str(duckdb_scalar(con, f"SELECT MIN(_fetched_at) FROM {relation_name}")),
        "max_fetched_at": str(duckdb_scalar(con, f"SELECT MAX(_fetched_at) FROM {relation_name}")),
    }


def top_level_inventory() -> dict[str, Any]:
    top_dirs = sorted(path.name for path in DATA_ROOT.iterdir() if path.is_dir()) if DATA_ROOT.exists() else []
    all_files = sorted(DATA_ROOT.rglob("*.parquet")) if DATA_ROOT.exists() else []
    return {
        "data_root": str(DATA_ROOT.relative_to(ROOT)),
        "exists": DATA_ROOT.exists(),
        "top_level_directories": top_dirs,
        "total_parquet_count": len(all_files),
        "total_size_bytes": sum(path.stat().st_size for path in all_files),
        "total_size_human": sizeof_fmt(sum(path.stat().st_size for path in all_files)),
    }


def write_markdown(inventory: dict[str, Any], schema_summary: dict[str, Any]) -> None:
    lines = [
        "# Becker Kalshi Dataset Inventory",
        "",
        f"Generated: {inventory['generated_at_utc']}",
        "",
        "## Verification",
        "",
        "- Release chunk checksums: passed via `shasum -a 256 -c release_assets/SHA256SUMS.txt`.",
        "- Reconstructed archive: `release_assets/john-becker-kalshi-dataset.tar.zst`.",
        "- Archive integrity: passed via `zstd -t`.",
        "- Extracted tree: `data/kalshi`.",
        "",
        "## Commands Run",
        "",
    ]
    lines.extend(f"- `{command}`" for command in COMMANDS_RUN)
    lines.extend(
        [
            "",
            "## Inventory Summary",
            "",
            f"- Top-level directories: {', '.join(inventory['top_level']['top_level_directories'])}",
            f"- Total parquet files: {inventory['top_level']['total_parquet_count']:,}",
            f"- Total parquet size: {inventory['top_level']['total_size_human']}",
            "",
            "| Folder | Files | Rows | Size | Unique tickers | Unique event tickers | Created min | Created max |",
            "|---|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for folder in ["trades", "markets"]:
        meta = inventory["folders"][folder]["file_metadata"]
        duck = inventory["folders"][folder]["duckdb_summary"]
        lines.append(
            "| {folder} | {files:,} | {rows:,} | {size} | {tickers:,} | {events} | {min_created} | {max_created} |".format(
                folder=folder,
                files=meta["file_count"],
                rows=duck["row_count"],
                size=meta["size_human"],
                tickers=duck["unique_tickers"],
                events=f"{duck.get('unique_event_tickers', 0):,}" if folder == "markets" else "n/a",
                min_created=duck["min_created_time"],
                max_created=duck["max_created_time"],
            )
        )
    lines.extend(["", "## Data Quality Checks", ""])
    for folder in ["trades", "markets"]:
        meta = inventory["folders"][folder]["file_metadata"]
        ranges = inventory["folders"][folder]["range_continuity"]
        duck = inventory["folders"][folder]["duckdb_summary"]
        duplicate_label = (
            f"duplicate trade_id groups: {duck['duplicate_trade_id_count']:,}"
            if folder == "trades"
            else f"duplicate ticker + _fetched_at groups: {duck['duplicate_ticker_fetched_at_count']:,}"
        )
        lines.extend(
            [
                f"### {folder}",
                "",
                f"- Corrupt shards: {meta['corrupt_file_count']}",
                f"- Schema variants: {meta['schema_variant_count']}",
                f"- Range gaps: {ranges['gap_count']}",
                f"- Range overlaps: {ranges['overlap_count']}",
                f"- {duplicate_label}",
                "",
            ]
        )
    lines.extend(["## Schema Summary", ""])
    for folder, summary in schema_summary["folders"].items():
        lines.extend(
            [
                f"### {folder}",
                "",
                f"- Schema variants: {summary['schema_variant_count']}",
                "",
            ]
        )
        for variant in summary["schema_variants"]:
            columns = ", ".join(column["name"] for column in variant["columns"])
            lines.append(f"- Variant {variant['variant_id']}: {variant['file_count']:,} files. Columns: `{columns}`")
        lines.append("")
    REPORT_MD.write_text("\n".join(lines) + "\n")


def main() -> int:
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    trades_files = parquet_files(DATA_ROOT / "trades")
    markets_files = parquet_files(DATA_ROOT / "markets")

    inventory: dict[str, Any] = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "commands_run": COMMANDS_RUN,
        "top_level": top_level_inventory(),
        "folders": {},
    }
    schema_summary: dict[str, Any] = {"generated_at_utc": inventory["generated_at_utc"], "folders": {}}

    for folder, files, prefix in [
        ("trades", trades_files, "trades"),
        ("markets", markets_files, "markets"),
    ]:
        file_metadata = inspect_files(folder, files)
        inventory["folders"][folder] = {
            "file_metadata": file_metadata,
            "range_continuity": detect_range_gaps(files, prefix),
        }
        schema_summary["folders"][folder] = {
            "schema_variant_count": file_metadata["schema_variant_count"],
            "schema_variants": file_metadata["schema_variants"],
            "corrupt_files": file_metadata["corrupt_files"],
        }

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    inventory["folders"]["trades"]["duckdb_summary"] = duckdb_summary(
        con,
        "becker_trades",
        str((DATA_ROOT / "trades" / "*.parquet").relative_to(ROOT)),
        "trades",
    )
    inventory["folders"]["markets"]["duckdb_summary"] = duckdb_summary(
        con,
        "becker_markets",
        str((DATA_ROOT / "markets" / "*.parquet").relative_to(ROOT)),
        "markets",
    )

    INVENTORY_JSON.write_text(json.dumps(inventory, indent=2, sort_keys=True))
    SCHEMA_JSON.write_text(json.dumps(schema_summary, indent=2, sort_keys=True))
    write_markdown(inventory, schema_summary)

    print("Becker dataset inventory complete")
    print(f"Inventory JSON: {INVENTORY_JSON}")
    print(f"Schema JSON: {SCHEMA_JSON}")
    print(f"Markdown report: {REPORT_MD}")
    print(f"Total parquet files: {inventory['top_level']['total_parquet_count']:,}")
    for folder in ["trades", "markets"]:
        meta = inventory["folders"][folder]["file_metadata"]
        duck = inventory["folders"][folder]["duckdb_summary"]
        ranges = inventory["folders"][folder]["range_continuity"]
        print(
            f"{folder}: files={meta['file_count']:,}, rows={duck['row_count']:,}, "
            f"size={meta['size_human']}, corrupt={meta['corrupt_file_count']}, "
            f"schema_variants={meta['schema_variant_count']}, gaps={ranges['gap_count']}, "
            f"overlaps={ranges['overlap_count']}"
        )
        print(f"  created_time: {duck['min_created_time']} -> {duck['max_created_time']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
