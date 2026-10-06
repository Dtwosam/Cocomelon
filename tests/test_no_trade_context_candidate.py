from __future__ import annotations

import json
from pathlib import Path

from cocomelon.domain.strategy import Direction
from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)
from cocomelon.research.no_trade_context_candidate import (
    NoTradeContextCandidateError,
    verify_no_trade_context_candidate_freeze,
)

SOURCE = Path(
    "research/no_trade_context_candidates/"
    "mon-normal-short-1h-v1-source.json"
)
FREEZE = Path(
    "research/no_trade_context_candidates/"
    "mon-normal-short-1h-v1.json"
)


def test_mon_candidate_freeze_is_canonical_and_prospective() -> None:
    freeze = verify_no_trade_context_candidate_freeze(
        FREEZE,
        selection_record_path=SOURCE,
    )

    assert freeze.candidate_id == (
        "2f72dd8fcb0b8cef3a4eb991d472a0e9c50f550954d1b3d8a0ddd3d6fe1cfd23"
    )
    assert freeze.dimensions == ("market", "volatility_regime")
    assert freeze.values == ("MON", "normal")
    assert freeze.direction is Direction.SHORT
    assert freeze.horizon_ms == 3_600_000
    assert freeze.threshold_bps == 50
    assert freeze.validation_material_outcomes == 25
    assert freeze.validation_block_outcomes == (8, 8, 9)
    assert freeze.prospective_not_before_ms == (
        freeze.frozen_at_ms + MIN_PROSPECTIVE_EMBARGO_MS
    )
    assert freeze.prospective_not_before_ms > freeze.source_forward_as_of_ms
    assert freeze.prospective_only is True
    assert freeze.paper_only is True
    assert freeze.research_only is True
    assert freeze.promotion_eligible is False
    assert freeze.execution_ready is False


def test_candidate_freeze_rejects_tampered_selection_source(
    tmp_path: Path,
) -> None:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    payload["validated_candidate_count"] = 2
    tampered = tmp_path / "source.json"
    tampered.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    try:
        verify_no_trade_context_candidate_freeze(
            FREEZE,
            selection_record_path=tampered,
        )
    except NoTradeContextCandidateError as exc:
        assert "SELECTION_ID_MISMATCH" in str(exc)
    else:
        raise AssertionError("tampered source must fail closed")
