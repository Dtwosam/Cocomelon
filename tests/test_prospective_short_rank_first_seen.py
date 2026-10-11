from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from cocomelon.domain.features import FeatureSnapshot, OpportunityRank
from cocomelon.domain.market import MarketId
from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshot,
    FirstSeenRankSnapshotStore,
    ShortRankFirstSeenError,
)

BTC = MarketId("", "BTC")
ETH = MarketId("", "ETH")


def _features(at_ms: int) -> dict[str, FeatureSnapshot]:
    return {
        market.canonical: cast(
            FeatureSnapshot,
            SimpleNamespace(
                market=market,
                snapshot_id=f"{market.canonical}:feature:{at_ms}",
                source_received_at_ms=at_ms - 1,
                as_of_ms=at_ms,
            ),
        )
        for market in (BTC, ETH)
    }


def _rank(market: MarketId, ordinal: int) -> OpportunityRank:
    return OpportunityRank(
        market=market,
        ordinal=ordinal,
        score=Decimal("0.8") if ordinal == 1 else Decimal("0.7"),
        components=(),
        reason_codes=("observed-from-mainnet-features",),
    )


def _snapshot(
    at_ms: int,
    captured_ms: int,
    ranks: tuple[OpportunityRank, ...] | None = None,
) -> FirstSeenRankSnapshot:
    return FirstSeenRankSnapshot.from_observation(
        observed_at_ms=at_ms,
        captured_at_ms=captured_ms,
        features=_features(at_ms),
        ranks=(_rank(BTC, 1), _rank(ETH, 2)) if ranks is None else ranks,
    )


def test_witness_uses_actual_capture_after_rank_computation(
    tmp_path: Path,
) -> None:
    archive = FirstSeenRankSnapshotStore(tmp_path / "ranks")
    first = _snapshot(1_000, 1_050)
    assert archive.append(first) is True
    assert archive.append(first) is False
    assert archive.iter_records() == (first,)
    assert archive.witness_for_decision(BTC, 1_000) is None
    assert archive.witness_for_decision(BTC, 1_050) is None
    witness = archive.witness_for_decision(BTC, 1_051)
    assert witness is not None
    assert witness.ordinal == 1
    assert witness.observed_at_ms == 1_050
    assert archive.state_digest


def test_latest_complete_snapshot_omitting_market_cannot_resurrect_old_rank(
    tmp_path: Path,
) -> None:
    archive = FirstSeenRankSnapshotStore(tmp_path)
    archive.append(_snapshot(1_000, 1_050))
    archive.append(_snapshot(2_000, 2_050, (_rank(ETH, 1),)))
    assert archive.witness_for_decision(BTC, 2_051) is None
    assert archive.witness_for_decision(BTC, 2_040) is not None
    archive.append(_snapshot(3_000, 3_050, ()))
    assert archive.witness_for_decision(ETH, 3_051) is None


def test_changed_historical_snapshot_is_rejected_not_relabelled(
    tmp_path: Path,
) -> None:
    archive = FirstSeenRankSnapshotStore(tmp_path)
    archive.append(_snapshot(1_000, 1_050))
    changed = _snapshot(1_000, 1_050, (_rank(ETH, 1), _rank(BTC, 2)))
    with pytest.raises(ShortRankFirstSeenError, match="CONFLICT"):
        archive.append(changed)
    path = next((tmp_path / "snapshots").glob("*.json"))
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["ranks"][0]["ordinal"] = 2
    path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    with pytest.raises(ShortRankFirstSeenError):
        archive.iter_records()


def test_backfilled_rank_and_handoff_clock_regression_rejected(
    tmp_path: Path,
) -> None:
    archive = FirstSeenRankSnapshotStore(tmp_path)
    archive.append(_snapshot(1_000, 1_100))
    with pytest.raises(ShortRankFirstSeenError, match="backdated"):
        archive.append(_snapshot(999, 1_101))
    with pytest.raises(ShortRankFirstSeenError, match="backdated"):
        archive.append(_snapshot(1_001, 1_050))


def test_rank_must_have_complete_causal_feature_identity() -> None:
    with pytest.raises(ShortRankFirstSeenError, match="feature"):
        FirstSeenRankSnapshot.from_observation(
            observed_at_ms=1_000,
            captured_at_ms=1_001,
            features=_features(1_000),
            ranks=(_rank(MarketId("", "DOGE"), 1),),
        )
    with pytest.raises(ShortRankFirstSeenError, match="received after"):
        FirstSeenRankSnapshot.from_observation(
            observed_at_ms=1_000,
            captured_at_ms=1_001,
            features=_features(1_002),
            ranks=(_rank(BTC, 1),),
        )
    with pytest.raises(ShortRankFirstSeenError, match="contiguous"):
        _snapshot(1_000, 1_001, (_rank(BTC, 2),))
    with pytest.raises(ShortRankFirstSeenError, match="calculation"):
        _snapshot(1_000, 999)


def test_complete_record_digest_excludes_none_of_the_ranked_universe() -> None:
    original = _snapshot(1_000, 1_010)
    altered = _snapshot(1_000, 1_010, (_rank(ETH, 1),))
    assert original.snapshot_digest != altered.snapshot_digest
    restored = FirstSeenRankSnapshot.from_dict(original.to_dict())
    assert restored == original
    changed = original.to_dict()
    changed["captured_at_ms"] = 1_011
    with pytest.raises(ShortRankFirstSeenError, match="digest"):
        FirstSeenRankSnapshot.from_dict(changed)
