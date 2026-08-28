from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

APPLIER = Path("scripts/apply_v3_intake_diagnostics.py")


def _function(name: str) -> Any:
    namespace = runpy.run_path(str(APPLIER))
    return namespace.get(name)


def _legacy_report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "protocol": "v3-lifecycle-aware-mainnet",
        "source_run_id": 33131799366,
        "source_conclusion": "failure",
        "source_verified": False,
        "corpus_mutated": False,
        "reason": "source_workflow_not_successful",
        "economic_claim": "none",
        "live_orders": False,
    }


def test_legacy_failed_intake_can_be_enriched_from_safe_eligibility_probe() -> None:
    enrich = _function("_enrich_legacy_failed_report")
    summary = _function("_intake_summary")
    assert callable(enrich)
    assert callable(summary)

    probe = {
        "economic_ineligibility_reasons": [
            "replay_incomplete",
            "dataset_incomplete",
            "open_exposure",
        ],
        "replay_data_complete": False,
        "dataset_data_complete": False,
        "dataset_gap_refs_empty": True,
        "flat_replay": False,
        "network_access": False,
        "live_orders": False,
    }

    enriched = enrich(_legacy_report(), probe)
    assert summary(enriched) == (
        "rejected — replay_incomplete, dataset_incomplete, open_exposure"
    )


def test_legacy_failed_intake_does_not_trust_unwhitelisted_probe_reason() -> None:
    enrich = _function("_enrich_legacy_failed_report")
    summary = _function("_intake_summary")
    assert callable(enrich)
    assert callable(summary)

    probe = {
        "economic_ineligibility_reasons": ["profitable_trade_result"],
        "replay_data_complete": True,
        "dataset_data_complete": True,
        "dataset_gap_refs_empty": True,
        "flat_replay": True,
        "network_access": False,
        "live_orders": False,
    }

    enriched = enrich(_legacy_report(), probe)
    assert summary(enriched) == "rejected — diagnostic detail unavailable"
