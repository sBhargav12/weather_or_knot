# Becker Kalshi Dataset Inventory

Generated: 2026-04-26T05:12:53.315028+00:00

## Verification

- Release chunk checksums: passed via `shasum -a 256 -c release_assets/SHA256SUMS.txt`.
- Reconstructed archive: `release_assets/john-becker-kalshi-dataset.tar.zst`.
- Archive integrity: passed via `zstd -t`.
- Extracted tree: `data/kalshi`.

## Commands Run

- `sed -n '1,420p' CLAUDE.md`
- `shasum -a 256 -c release_assets/SHA256SUMS.txt`
- `cat release_assets/john-becker-kalshi-dataset.tar.zst.part-* > release_assets/john-becker-kalshi-dataset.tar.zst && zstd -t release_assets/john-becker-kalshi-dataset.tar.zst`
- `zstd -dc release_assets/john-becker-kalshi-dataset.tar.zst | tar -xf -`
- `.venv/bin/python research/becker_inventory.py`

## Inventory Summary

- Top-level directories: markets, trades
- Total parquet files: 7,983
- Total parquet size: 3.9GB

| Folder | Files | Rows | Size | Unique tickers | Unique event tickers | Created min | Created max |
|---|---:|---:|---:|---:|---:|---|---|
| trades | 7,214 | 72,134,741 | 3.3GB | 586,025 | n/a | 2021-06-30 16:09:14.185137-04:00 | 2025-11-25 17:00:15.194245-05:00 |
| markets | 769 | 7,682,445 | 568.7MB | 7,682,445 | 1,197,300 | 2021-06-30 09:46:45.154903-04:00 | 2025-11-23 13:51:48.656951-05:00 |

## Data Quality Checks

### trades

- Corrupt shards: 0
- Schema variants: 1
- Range gaps: 0
- Range overlaps: 0
- duplicate trade_id groups: 0

### markets

- Corrupt shards: 0
- Schema variants: 1
- Range gaps: 0
- Range overlaps: 0
- duplicate ticker + _fetched_at groups: 0

## Schema Summary

### trades

- Schema variants: 1

- Variant 1: 7,214 files. Columns: `trade_id, ticker, count, yes_price, no_price, taker_side, created_time, _fetched_at`

### markets

- Schema variants: 1

- Variant 1: 769 files. Columns: `ticker, event_ticker, market_type, title, yes_sub_title, no_sub_title, status, yes_bid, yes_ask, no_bid, no_ask, last_price, volume, volume_24h, open_interest, result, created_time, open_time, close_time, _fetched_at`

