from __future__ import annotations

import inspect

from cocomelon.research.evaluator import evaluate_research_checkpoint


def test_checkpoint_evaluator_exposes_no_policy_override() -> None:
    parameters = inspect.signature(evaluate_research_checkpoint).parameters

    assert "policy" not in parameters
