# Win-Rate Improvement Playbook

Generated: 2026-04-26T15:08:35.409666-04:00

## Immediate

1. Keep live threshold frozen; do not promote wallet-derived changes directly to live.
2. Add research/paper diagnostics for event-level ladder state and bracket-family split.
3. Keep TAIL_NO suspended in paper until stricter evidence exists; continue logging candidates.
4. Preserve execution-margin paper filters; core is fragile under fill stress.

## Next Sprint

1. Add Polymarket subgraph/on-chain backfill to escape the public API cap.
2. Build available-market universe baseline for true selection edge.
3. Add Kalshi paper logs for proposed/unfilled/cancelled orders.
4. Add recent same-market flow features to research mart.

## Medium-Term

1. Build event-level exposure accounting for grouped/ladder-like structures.
2. Split calibration/policy for central vs wing/exact/tail structures.
3. Validate whether extreme-price behavior improves EV on Kalshi after fees and fill stress.

## Future Paper/Live Candidate

1. A ladder-aware deep-tail/wing sleeve may be a paper candidate after backfilled evidence and own fill logs.
2. Selective central tightening may improve win rate if forward paper confirms central underperformance.

## What NOT To Change Yet

- Do not change live threshold.
- Do not touch live execution or scheduler.
- Do not claim exact maker/taker patterns from Polymarket public trades.
- Do not copy Polymarket station-specific behavior into KXHIGHNY without station conversion.
