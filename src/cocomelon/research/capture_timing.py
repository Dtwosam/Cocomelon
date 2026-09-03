from __future__ import annotations

import time
from collections.abc import Callable

from cocomelon.evidence.epochs import DECISION_INTERVAL_MS

RESEARCH_CAPTURE_DECISION_GRACE_MS = 30_000
RESEARCH_CAPTURE_DECISION_LEAD_MS = 180_000
RESEARCH_CAPTURE_SOURCE_PREFIX = "research-mainnet-"
_RESEARCH_CAPTURE_PHASE_MS = (
    RESEARCH_CAPTURE_DECISION_GRACE_MS - RESEARCH_CAPTURE_DECISION_LEAD_MS
) % DECISION_INTERVAL_MS


def research_capture_wait_ms(now_ms: int) -> int:
    """Return the outcome-blind wait to the next fixed research capture phase."""
    if now_ms < 0:
        raise ValueError("now_ms must be non-negative")
    remainder_ms = now_ms % DECISION_INTERVAL_MS
    return (_RESEARCH_CAPTURE_PHASE_MS - remainder_ms) % DECISION_INTERVAL_MS


def maybe_wait_for_research_capture_phase(
    source_id: str | None,
    *,
    now_ms: int | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    """Align only trusted research captures to the fixed decision-relative phase."""
    if not source_id or not source_id.startswith(RESEARCH_CAPTURE_SOURCE_PREFIX):
        return 0
    resolved_now_ms = time.time_ns() // 1_000_000 if now_ms is None else now_ms
    wait_ms = research_capture_wait_ms(resolved_now_ms)
    if wait_ms:
        sleeper(wait_ms / 1_000)
    return wait_ms
