"""Conservative original-record preflight for new LONG-only v3 PAPER research.

A locally pinned replay manifest is NOT a venue completeness attestation.
Refuse any recorded source gap or missing per-market forward L2 observation.
A 72h calendar manifest or a late non-L2 record must not mature the trial.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Final

from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayManifest, ReplayRecord, SourceRecordKind

ZERO_GAP_POLICY: Final = "reject_every_original_gap_in_entire_replayed_warmup_and_forward_window"
MAX_FORWARD_L2_SILENCE_MS: Final = 5 * 60 * 1000


class FreshLongTrendSourceError(ValueError):
    """V3 source is insufficient for even a locally accountable trial."""


def audit_fresh_long_trend_original_records(
    records: Sequence[ReplayRecord],
    *,
    manifest: ReplayManifest,
    selected_markets: Sequence[MarketId],
    forward_not_before_ms: int,
) -> dict[str, object]:
    """Prove only local per-market L2 span/record parity, not venue origin.

    The replay has already passed its independently supplied manifest ID,
    segment SHA-256s, recorder row counts and original L2 parser checks.
    We additionally refuse *every* original DATA_GAP (including warmup),
    missing manifest gap references, absent forward L2 for even one selected
    market, or a record timestamp outside the pinned manifest.
    """
    gap_refs: object = getattr(manifest, "gap_refs", None)
    if not isinstance(gap_refs, tuple) or any(
        not isinstance(ref, str) for ref in gap_refs
    ):
        raise FreshLongTrendSourceError("source gap manifest identity missing")
    if gap_refs:
        raise FreshLongTrendSourceError("source manifest declares unresolved gaps")
    markets = tuple(sorted(m.canonical for m in selected_markets))
    if not markets or len(set(markets)) != len(markets):
        raise FreshLongTrendSourceError("original market cohort invalid")
    if not records:
        raise FreshLongTrendSourceError("empty source")
    observed: dict[str, tuple[int, int, int]] = {
        market: (0, 0, 0) for market in markets
    }
    # A caller cannot replay the same original ZIP, retain only the markets
    # that later looked profitable, and label the reduced cohort an
    # independently matched account. All first-seen market observations
    # in the original forward recorder determine the universe to replay.
    all_forward_market_sources: set[str] = set()
    all_forward_l2_sources: set[str] = set()
    digest = hashlib.sha256()
    last_available = -1
    ordinal_count = 0
    for original_index, record in enumerate(records, start=1):
        ordinal = record.source_receive_ordinal
        if ordinal is not None:
            ordinal_count += 1
            if ordinal != original_index:
                raise FreshLongTrendSourceError(
                    "original source received order differs from replay ordinal"
                )
        if (
            record.available_at_ms < manifest.start_ms
            or record.available_at_ms > manifest.end_ms
            or record.available_at_ms < last_available
        ):
            raise FreshLongTrendSourceError("source time out of manifest or order")
        last_available = record.available_at_ms
        if record.record_kind is SourceRecordKind.DATA_GAP:
            raise FreshLongTrendSourceError(
                "source contains original received DATA_GAP: reject entire replay"
            )
        if record.record_kind is not SourceRecordKind.NORMALIZED_EVENT:
            raise FreshLongTrendSourceError("unexpected source record kind")
        if (
            record.market is not None
            and record.available_at_ms >= forward_not_before_ms
        ):
            all_forward_market_sources.add(record.market)
            if record.event_kind == "l2_book":
                all_forward_l2_sources.add(record.market)
        line = json.dumps({
            "record_kind": record.record_kind.value,
            "available_at_ms": record.available_at_ms,
            "source": record.source,
            "schema_version": record.schema_version,
            "market": record.market,
            "exchange_time_ms": record.exchange_time_ms,
            "event_key": record.event_key,
            "event_kind": record.event_kind,
            "payload_json": record.payload_json,
            "source_receive_ordinal": record.source_receive_ordinal,
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False).encode("utf-8")
        digest.update(line)
        digest.update(b"\n")
        if (
            record.event_kind == "l2_book"
            and record.market in observed
            and record.available_at_ms >= forward_not_before_ms
        ):
            first, previous, count = observed[record.market]
            if (
                (count == 0 and record.available_at_ms
                 > forward_not_before_ms + MAX_FORWARD_L2_SILENCE_MS)
                or (count > 0 and
                    record.available_at_ms - previous > MAX_FORWARD_L2_SILENCE_MS)
            ):
                raise FreshLongTrendSourceError(
                    "forward original L2 market drought exceeds five-minute limit"
                )
            observed[record.market] = (
                first if count else record.available_at_ms,
                record.available_at_ms,
                count + 1,
            )
    if ordinal_count not in (0, len(records)):
        raise FreshLongTrendSourceError(
            "mixed original source ordinals cannot prove receive-time order"
        )
    absent = [market for market, (_, _, count) in observed.items() if count == 0]
    if absent:
        raise FreshLongTrendSourceError(
            "source missing post-embargo L2 on selected markets: "
            + ",".join(absent)
        )
    unexpected = sorted(all_forward_market_sources - set(markets))
    extra_l2 = sorted(all_forward_l2_sources - set(markets))
    if unexpected or extra_l2:
        raise FreshLongTrendSourceError(
            "posthoc selected-market subset omits original forward source: "
            + ",".join(unexpected or extra_l2)
        )
    # A challenger holding a stale market cannot count time passing on a
    # different active market as a shared, independent comparison window.
    common_end = min(last for _, last, _ in observed.values())
    return {
        "schema": "v3-original-local-common-market-l2-horizon-v1",
        "record_count": len(records),
        "local_canonical_record_stream_sha256": digest.hexdigest(),
        "complete_original_source_receive_ordinals_verified": (
            ordinal_count == len(records)
        ),
        "original_market_count": len(markets),
        "all_original_forward_market_count": len(all_forward_market_sources),
        "all_original_forward_l2_market_count": len(all_forward_l2_sources),
        "selected_market_covers_full_original_forward_universe": True,
        "selected_market_first_l2_at_ms": {
            market: first for market, (first, _, _) in observed.items()
        },
        "selected_market_last_l2_at_ms": {
            market: last for market, (_, last, _) in observed.items()
        },
        "selected_market_post_embargo_l2_counts": {
            market: count for market, (_, _, count) in observed.items()
        },
        "last_record_available_at_ms": last_available,
        "common_selected_market_l2_end_ms": common_end,
        "common_l2_forward_elapsed_ms": common_end - forward_not_before_ms,
        "maximum_allowed_original_l2_silence_ms": MAX_FORWARD_L2_SILENCE_MS,
        "every_market_has_initial_l2_and_no_observed_5min_drought": True,
        "recorded_source_gap_count": 0,
        "source_gap_policy": ZERO_GAP_POLICY,
        "local_manifest_and_record_validation_only": True,
        "original_exchange_feed_independently_authenticated": False,
        "continuous_l2_without_unrecorded_gaps_certified": False,
        "independent_forward_profitability_certified": False,
        "promotion_authority": False,
        "execution_authority": False,
    }
