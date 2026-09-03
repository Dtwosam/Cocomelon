from __future__ import annotations

from cocomelon.evidence.epochs import DECISION_INTERVAL_MS

RESEARCH_CAPTURE_DECISION_GRACE_MS = 30_000
RESEARCH_CAPTURE_DECISION_LEAD_MS = 180_000
_RESEARCH_CAPTURE_PHASE_MS = (
    RESEARCH_CAPTURE_DECISION_GRACE_MS - RESEARCH_CAPTURE_DECISION_LEAD_MS
) % DECISION_INTERVAL_MS


def research_capture_wait_ms(now_ms: int) -> int:
    """Return the outcome-blind wait to the next fixed research capture phase."""
    if now_ms < 0:
        raise ValueError("now_ms must be non-negative")
    remainder_ms = now_ms % DECISION_INTERVAL_MS
    return (_RESEARCH_CAPTURE_PHASE_MS - remainder_ms) % DECISION_INTERVAL_MS
