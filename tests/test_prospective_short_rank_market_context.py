from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.market import (
    MarketId, PerpMarketContext, PerpMarketMeta, PerpMarketSnapshot,
)
from cocomelon.evidence.recording import _startup_ranks
from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshot,
)
from cocomelon.research.prospective_short_rank_full_features import (
    OriginalRankFeatureInputBatch,
    OriginalRankInputBatchError,
)
from cocomelon.research.prospective_short_rank_market_context import (
    OriginalRankEligibilityContextBatch,
    OriginalRankEligibilityContextError,
    OriginalRankEligibilityContextStore,
    replay_recorded_rank_eligibility,
)

OBSERVED = 1_790_080_000_000
D = Decimal


def _market(
    market: str, *,
    is_delisted: bool = False,
    max_leverage: int = 20,
    mid_px: str = "100",
    received_at_ms: int = OBSERVED - 100,
    oi: str = "100000",
    volume: str = "1000000",
) -> PerpMarketSnapshot:
    key = MarketId("", market)
    return PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=key, wire_name=market, sz_decimals=4,
            max_leverage=max_leverage, margin_table_id=None,
            only_isolated=False, is_delisted=is_delisted, margin_mode=None,
        ),
        context=PerpMarketContext(
            market=key, mark_px=D("100"),
            mid_px=D(mid_px), oracle_px=D("100"),
            funding=D("0.0001"), open_interest=D(oi),
            day_ntl_vlm=D(volume), premium=D("0.005"),
            prev_day_px=D("98"),
        ),
        source="hyperliquid-mainnet-info",
        received_at_ms=received_at_ms,
        schema_version=1,
    )


def _sources() -> tuple[
    FirstSeenRankSnapshot, OriginalRankFeatureInputBatch,
    OriginalRankEligibilityContextBatch, dict[str, PerpMarketSnapshot],
]:
    markets = {
        "BTC": _market("BTC", volume="2000000", oi="200000"),
        "ETH": _market("ETH", is_delisted=True),
        "SOL": _market("SOL", max_leverage=0),
        "AAVE": _market("AAVE", mid_px="102"),
    }
    features, ranks = _startup_ranks(markets, as_of_ms=OBSERVED)
    rank = FirstSeenRankSnapshot.from_observation(
        observed_at_ms=OBSERVED,
        captured_at_ms=OBSERVED + 20,
        features=features,
        ranks=ranks,
    )
    full = OriginalRankFeatureInputBatch.from_original_rank(rank, features)
    context = OriginalRankEligibilityContextBatch.from_original_rank(rank, markets)
    return rank, full, context, markets


def test_real_production_rankable_universe_can_be_replayed_from_context() -> None:
    rank, features, context, _ = _sources()
    assert len(rank.ranks) == 2
    result = replay_recorded_rank_eligibility(
        rank=rank, feature_inputs=features, context=context,
    )
    assert result["original_rank_membership_from_recorded_context_recomputed"]
    assert result["recorded_context_markets_examined"] == 4
    assert result["rankable_markets_from_recorded_context"] == 2
    assert result["original_market_context_independently_authenticated"] is False
    assert result["profitable_risk_matched_account_certified"] is False
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False


@pytest.mark.parametrize("case", [
    "delisting", "leverage", "invalid_price", "context_age", "feature_cash",
])
def test_modified_context_or_feature_source_cannot_recreate_claimed_rank_set(
    case: str,
) -> None:
    rank, features, context, _ = _sources()
    snapshots = list(context.snapshots)
    # AAVE and BTC are actually rankable; self-consistent rewrites of their
    # provenance cannot make a falsely unrankable ranking eligible.
    index = next(i for i, row in enumerate(snapshots)
                 if row.meta.market.canonical == "AAVE")
    original = snapshots[index]
    if case == "delisting":
        snapshots[index] = replace(
            original, meta=replace(original.meta, is_delisted=True),
        )
    elif case == "leverage":
        snapshots[index] = replace(
            original, meta=replace(original.meta, max_leverage=0),
        )
    elif case == "invalid_price":
        snapshots[index] = replace(
            original, context=replace(original.context, oracle_px=None),
        )
    elif case == "context_age":
        snapshots[index] = replace(
            original, received_at_ms=OBSERVED - 70_000,
        )
        # Changing the receive timestamp also invalidates the parent rank.
        with pytest.raises(OriginalRankEligibilityContextError, match="disagrees"):
            replace(context, snapshots=tuple(snapshots)).bind_to(rank)
        return
    else:
        idx = next(i for i, feat in enumerate(features.features)
                   if feat.market.canonical == "AAVE")
        forged = list(features.features)
        forged[idx] = replace(
            forged[idx], day_notional_volume=D("1000010"),
        )
        edited = replace(features, features=tuple(forged))
        with pytest.raises(OriginalRankInputBatchError):
            replay_recorded_rank_eligibility(
                rank=rank, feature_inputs=edited, context=context,
            )
        return
    edited = replace(context, snapshots=tuple(snapshots))
    with pytest.raises(
        OriginalRankEligibilityContextError,
        match="cannot reproduce rank features|contradicts",
    ):
        replay_recorded_rank_eligibility(
            rank=rank, feature_inputs=features, context=edited,
        )


def test_immutable_market_context_store_preserves_original_bytes(
    tmp_path: Path,
) -> None:
    rank, full, context, markets = _sources()
    store = OriginalRankEligibilityContextStore(tmp_path / "market-context")
    assert store.append(context)
    assert not store.append(context)
    assert store.source_digest
    restored = OriginalRankEligibilityContextStore(tmp_path / "market-context")
    assert restored.iter_verified() == (context,)
    assert restored.source_digest == store.source_digest
    assert context.to_dict() == OriginalRankEligibilityContextBatch.from_dict(
        context.to_dict()
    ).to_dict()
    # A new rank with different original input cannot rewrite an old suffix.
    tampered = replace(
        context,
        snapshots=(
            replace(context.snapshots[0], source="not-original-source"),
            *context.snapshots[1:],
        ),
    )
    with pytest.raises(OriginalRankEligibilityContextError, match="conflicts"):
        restored.append(tampered)
    raw_file = next((tmp_path / "market-context" / "batches").glob("*.json"))
    raw = json.loads(raw_file.read_text(encoding="utf-8"))
    raw["snapshots"][0]["meta"]["is_delisted"] = True
    raw_file.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    with pytest.raises(OriginalRankEligibilityContextError):
        OriginalRankEligibilityContextStore(tmp_path / "market-context")


def test_old_rank_context_never_backfilled_or_reordered(tmp_path: Path) -> None:
    rank, full, context, markets = _sources()
    store = OriginalRankEligibilityContextStore(tmp_path / "contexts")
    future = replace(
        context, observed_at_ms=OBSERVED + 50_000,
        captured_at_ms=OBSERVED + 50_020,
    )
    assert store.append(future)
    with pytest.raises(
        OriginalRankEligibilityContextError, match="backdated",
    ):
        store.append(context)
    no_context = {key: value for key, value in markets.items() if key != "AAVE"}
    with pytest.raises(
        OriginalRankEligibilityContextError, match="missing original",
    ):
        OriginalRankEligibilityContextBatch.from_original_rank(rank, no_context)
    with pytest.raises(
        OriginalRankEligibilityContextError, match="disagrees",
    ):
        replace(context, rank_snapshot_digest="a" * 64).bind_to(rank)


def test_live_capture_path_keeps_eligibility_sidecar_separate_from_orders() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(
        encoding="utf-8",
    )
    assert "OriginalRankEligibilityContextStore(" in source
    assert "OriginalRankEligibilityContextBatch.from_original_rank(" in source
    assert "prospective-short-rank-market-context-error.json" in source
    assert "markets=snapshots" in source
    assert "markets=refreshed" in source
    assert source.count("capture_rank_first_seen(") == 4
    assert source.count("            markets=") >= 2
    assert '"execution_authority": False' in source
