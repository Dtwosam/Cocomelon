from __future__ import annotations

import json
from pathlib import Path

from cocomelon.research.bootstrap import ensure_bootstrap_candidate
from cocomelon.research.registry import ResearchRegistry


def test_bootstrap_candidate_includes_planned_risk_per_trade(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        candidate = ensure_bootstrap_candidate(
            registry,
            candidate_id="scheduled-research-root",
            code_revision="a" * 40,
        )
    finally:
        registry.close()

    risk_config = json.loads(candidate.risk_config_json)
    assert risk_config["risk_per_trade"] == "0.0025"
