"""Prevent a new Cocomelon chat from missing the economic objective."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs/PROFITABILITY_PRIORITY.md"
ENTRY_POINTS = (
    "README.md",
    "AGENTS.md",
    "docs/STATUS.md",
    "docs/CHATGPT_PROJECT_SOURCE.md",
    "docs/BUILD_ORDER.md",
    "docs/MASTER_SPEC.md",
    "docs/DECISIONS.md",
)


@pytest.mark.parametrize("path", ENTRY_POINTS)
def test_proven_profitability_handoff_is_visible_in_primary_documents(
    path: str,
) -> None:
    source = (ROOT / path).read_text(encoding="utf-8")
    assert "PROFITABILITY_PRIORITY.md" in source
    assert "paper" in source.lower()
    assert "profit" in source.lower()


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "AGENTS.md",
        "docs/STATUS.md",
        "docs/CHATGPT_PROJECT_SOURCE.md",
    ],
)
def test_new_chat_sees_profitability_priority_at_top(path: str) -> None:
    lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
    assert any("PROFITABILITY_PRIORITY.md" in line for line in lines[:55])


def test_readme_read_first_points_to_profitability_handoff() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    first = readme.split("## Read first", 1)[1].split("\n## ", 1)[0]
    assert first.splitlines()[2].startswith(
        "1. [`docs/PROFITABILITY_PRIORITY.md`]"
    )
    assert "Phase 1 — Python foundation and domain contracts — is active" not in readme


def test_canonical_profitability_guide_preserves_account_provenance() -> None:
    source = GUIDE.read_text(encoding="utf-8")
    for required in (
        "2026-10-09 23:40:16 UTC",
        "38002307902",
        "155",
        "$9,682.45",
        "-$317.55",
        "NO PROFITABLE EDGE VERIFIED",
        "prospective-short-breakout-only-top3-v1",
        "loss-context-paired-portfolio-shadow-scoped-v2",
        "risk_rejected_integrity_clean",
        "Issue #469",
        "same-window",
        "funding",
        "slippage",
        "LIVE",
        "Fail closed",
    ):
        assert required.lower() in source.lower(), required


def test_immutable_economic_gates_remain_explicit() -> None:
    source = GUIDE.read_text(encoding="utf-8")
    assert "40-trade" in source
    assert "no automatic" in source.lower()
    assert "original trades" in source
    assert "paper-only" in source.lower()


def test_locked_profit_first_decision_is_appended() -> None:
    decisions = (ROOT / "docs/DECISIONS.md").read_text(encoding="utf-8")
    assert decisions.count("## D-090 —") == 1
    assert "profitability" in decisions.split("## D-090 —", 1)[1].lower()
    assert "live" in decisions.split("## D-090 —", 1)[1].lower()
