# SHORT rank first-seen feature-source closure

## Actual authenticated local source comparison

The original paper worker `38162541394` published two distinct evidence archives:

- First-seen rank source artifact `11711759572`: original GitHub outer sha256 `c2f1527724ac12b19029717ca57be5a0ce4de4aec318af2dce46cec14afc5189`. Its **374 fully locally hash-verified ranks** each reference **234 market feature snapshot IDs** (87,516 references).
- Separate decision-learning source artifact `11711789549`: original GitHub outer sha256 `9d285411e828050d8a0eda8e263af037d03c7bd1df3e9d4afa654f400730e7c4`. Its `learning-features/records` includes **25,466 saved feature snapshots**, while `learning-decisions/records` holds **25,909 decision facts**.

The exact 24-hex snapshot-id membership comparison showed **0 matches among the 87,516 first-seen rank feature references** (all unique) against the 25,466 saved learning-feature IDs. This is a **feature lineage coverage failure** for independently reconstructing the *rank* input, **not** a claim that those first-seen ranks are invented or that a market feed was false. The learning-feature writer samples decision features at different times from the rank refresh writer; the learning archive is not known to carry the exact full coarse-rank feature population.

The rank-source SHA256 proves immutable *rank claims*, not the full features they were computed from. Feature IDs alone cannot be inverted back into price, funding, OI, volume, trend, order-book, regime, and feature age values. Even a coincident learning-feature market/timestamp is not enough: the full `FeatureSnapshot.snapshot_id` must match.

## Strict read-only verification

`prospective_short_rank_feature_source.py` accepts fully verified immutable rank snapshots and a map of verified `LearningFeatureSnapshotStore` records. It demands exact, internally recomputed feature ID, market, source-received clock and feature as-of time no later than the rank observation. It counts every source reference, unique snapshot IDs, missing markets and a bounded sample of unmatched IDs. The `require_full_rank_feature_source_closure` form fails closed if any original ranking input is missing; no omitted snapshot can be considered a certified prospective saved trade.

Passing local source closure, if it ever does, **still does not prove GitHub-API origin, underlying Hyperliquid mainnet L2/gap completeness, an independent market source, risk-matched paper account profitability, or execution authority.** Those remain separate explicit negative flags. This work does not change frozen SHORT rank>3 decisions, the 300s age boundary, the original paper worker, stop or risk controls, original account history, frozen losing v5 trial or LIVE=false.

## Missing prospective producer evidence

A future completed-worker sealed source must preserve the **actual full ranking input feature payloads** (or source-authenticated equivalent) contemporaneously with the rank computation so an independent reviewer can recompute each input ID and, eventually, the ordinal ranking. Selectively copying the current decision-learning subset cannot fill this gap. Old ranking input payloads cannot be backfilled by guessing historical features. Preserve the entire original research result and treat this blocker separately from the observed rank-capture timing gaps.
