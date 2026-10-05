from __future__ import annotations

import pytest

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.research.prospective_full_stack_forward_markout import (
    LONG_TREND_CARVEOUT_CANDIDATE_ID,
)
from cocomelon.research.prospective_long_trend_carveout_execution_shadow import (
    _sha256,
)
from cocomelon.research.prospective_long_trend_carveout_execution_shadow_source import (
    SCHEMA_VERSION,
    SOURCE_KIND,
    WEEKLY_DRAWDOWN_REASON,
    execution_config_payload,
)
from scripts.evaluate_prospective_long_trend_15m_exit import (
    _execution_config_from_durable_long_trend_source,
)


def _durable_source() -> dict[str, object]:
    config = execution_config_payload(PaperExecutionConfig())
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": SOURCE_KIND,
        "candidate_id": LONG_TREND_CARVEOUT_CANDIDATE_ID,
        "baseline_risk_reason": WEEKLY_DRAWDOWN_REASON,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_execution": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
        "durable_gate_required": True,
        "execution_config": config,
        "execution_config_sha256": _sha256(config),
        "source_sha256": "0" * 64,
    }


def test_durable_config_validation_does_not_require_old_source_digest() -> None:
    config = _execution_config_from_durable_long_trend_source(
        _durable_source()
    )

    assert config == PaperExecutionConfig()


def test_durable_config_validation_rejects_tampered_config_digest() -> None:
    source = _durable_source()
    config = source["execution_config"]
    assert isinstance(config, dict)
    config["latency_ms"] = 9_999

    with pytest.raises(
        ValueError,
        match="execution config digest mismatch",
    ):
        _execution_config_from_durable_long_trend_source(source)


def test_durable_config_validation_rejects_authority_drift() -> None:
    source = _durable_source()
    source["execution_authority"] = True

    with pytest.raises(
        ValueError,
        match="authority drift: execution_authority",
    ):
        _execution_config_from_durable_long_trend_source(source)
