from __future__ import annotations

from cocomelon.research.cadence_context_walkforward import (
    DEFAULT_WALK_FORWARD_WINDOW_ROWS,
    CadenceContextWalkForwardConfig,
)


def test_default_walk_forward_window_is_frozen() -> None:
    config = CadenceContextWalkForwardConfig()

    assert DEFAULT_WALK_FORWARD_WINDOW_ROWS == 300
    assert config.window_rows == 300
