"""Optional PAPER research hot-path plan reads must not repeatedly query SQLite."""
from __future__ import annotations

from typing import cast

import pytest

from cocomelon.continuous_paper import _ResearchOpeningPlanCache
from cocomelon.domain.execution import PaperOrderPlan


def test_positive_immutable_plan_is_shared_and_lru_bounded() -> None:
    plans = {name: cast(PaperOrderPlan, object()) for name in ("A", "B", "C")}
    calls: list[str] = []

    def load(plan_id: str) -> PaperOrderPlan | None:
        calls.append(plan_id)
        return plans.get(plan_id)

    cache = _ResearchOpeningPlanCache(load, max_entries=2)
    assert cache("A") is plans["A"]
    assert cache("A") is plans["A"]
    assert cache("B") is plans["B"]
    assert cache("A") is plans["A"]  # Refresh recency.
    assert calls == ["A", "B"]

    assert cache("C") is plans["C"]  # Evicts B, never A.
    assert cache("A") is plans["A"]
    assert calls == ["A", "B", "C"]
    assert cache("B") is plans["B"]
    assert calls == ["A", "B", "C", "B"]


def test_missing_plans_and_loader_errors_are_never_cached() -> None:
    found: dict[str, PaperOrderPlan] = {}
    calls: list[str] = []

    def load(plan_id: str) -> PaperOrderPlan | None:
        calls.append(plan_id)
        if plan_id == "corrupt":
            raise ValueError("persisted plan payload is unreadable")
        return found.get(plan_id)

    cache = _ResearchOpeningPlanCache(load, max_entries=1)
    assert cache("future") is None
    new_plan = cast(PaperOrderPlan, object())
    found["future"] = new_plan
    assert cache("future") is new_plan
    assert cache("future") is new_plan
    assert calls == ["future", "future"]

    for _ in range(2):
        with pytest.raises(ValueError, match="persisted plan payload is unreadable"):
            cache("corrupt")
    assert calls == ["future", "future", "corrupt", "corrupt"]


def test_cache_bound_rejects_invalid_values() -> None:
    for invalid in (0, -1, True):
        with pytest.raises(ValueError, match="bound must be positive"):
            _ResearchOpeningPlanCache(lambda _: None, max_entries=invalid)
