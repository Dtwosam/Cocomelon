# Offline pairing of two independently pinned forward sources

`run_rank_archive_bound_short_rank_paired_replay` is the first read-only bridge that consumes **both** the exact recorder source archive and a complete `FirstSeenRankSnapshotStore` archived by the original paper worker, before creating two independent `PaperExecutionAdapter` paper accounts.

## Deterministic rules

1. Revalidate every JSONL source segment against a separately supplied full `ReplayManifest` identity (bytes, SHA256, partitions, received times, row counts, all gaps). No silent clipping. Source must include recorded L2 evidence.
2. Require a separate, independently supplied 64-character rank archive state SHA256. Re-read and validate all append-only snapshot records, exact canonical filenames/bytes, ranks, feature lineage, observed and captured clocks. Reject changed, additional or symlinked source records, incomplete temporary files, unsupported times outside manifest, and an archive with no forward captures.
3. Freeze the verified rank snapshots as an in-memory tuple for both account lanes. The rank provider uses only the **latest complete snapshot captured strictly before the decision**; it never searches older snapshots when the latest excludes a market, and never accepts same-millisecond or future ranks. The frozen candidate filters only SHORT breakout ranks >3; all other trades flow through the ordinary, independent baseline risk, simulated fill, stop, fee and funding engines.
4. Reject a paper output root that overlaps either evidence source, refuse reuse of any paper account SQLite directory, and return two separate after-cost account reports plus local source receipts with both pins.

## Honest evidence boundary

An archive/state digest created by the caller is **not** proof that the original worker produced that archive or that all real Hyperliquid mainnet sources were preserved. Full rank-snapshot file verification does not independently validate how their input feature snapshots were derived from the market recorder. Neither rank/microstructure source origin nor all trading gaps, terminal position maturity, cross-worker checkpoint continuity, and fixed-window profitability are yet certified. `source_manifest_independently_authenticated=false`, `rank_witness_source_independently_authenticated=false`, `full_account_trial=false`, `ready_for_review=false`, `execution_authority=false` and `promotion_authority=false` remain unaltered.

The test fixture uses synthetic two-row market data and a synthetic ranked universe; it proves reproducible plumbing and fail-closed checks, **not** an economic advantage. Do not promote any strategy from these unit tests. In particular, never reset or relabel the negative signed frozen v5 paired-account outcome.

## Remaining action

Consume the latest genuine original completed worker artifact and its separate first-seen rank cohort (from the worker running `113940c` or newer), verify independently authenticated run/attempt/head/digest plus complete market-source record history and all missing data gaps, then run this paired trial from the frozen prospective start with actual independently persisted accounts. Add signed fixed-window maturity and equal-risk/account reconciliation, including unresolved funding, open positions and data-gap failures.

Original live-order authority stays disabled; paper risk limits, stop management, and histories unchanged.
