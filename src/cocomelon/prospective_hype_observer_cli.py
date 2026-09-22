from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.config import ExecutionMode, Settings
from cocomelon.hyperliquid.client import InfoClient
from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
)
from cocomelon.research.prospective_context_evidence import ProspectiveEvidenceStore
from cocomelon.research.prospective_context_report import (
    HYPE_PROSPECTIVE_VALIDATION_V1,
)
from cocomelon.research.prospective_hype_observer import (
    ProspectivePublicReader,
    run_prospective_observer_cycle,
)
from cocomelon.util.time import utc_now_ms


def _emit(payload: dict[str, object], *, stream: TextIO | None = None) -> None:
    target = sys.stdout if stream is None else stream
    print(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ),
        file=target,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-prospective-hype-observer",
        description=(
            "Record one research-only prospective HYPE context observation "
            "and settle due exact-horizon outcomes"
        ),
    )
    parser.add_argument("--root", required=True, type=Path)
    return parser


def prospective_hype_observer_payload(
    settings: Settings,
    *,
    root: Path,
    reader: ProspectivePublicReader | None = None,
    clock_ms: Callable[[], int] = utc_now_ms,
) -> dict[str, object]:
    if settings.execution_mode is not ExecutionMode.PAPER:
        raise ValueError("prospective HYPE observer requires paper execution mode")

    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    source = reader or InfoClient(settings)
    store = ProspectiveEvidenceStore(root, spec=spec)
    plan = HYPE_PROSPECTIVE_VALIDATION_V1
    result = run_prospective_observer_cycle(
        source,
        store=store,
        clock_ms=clock_ms,
        spec=spec,
        validation_end_ms=plan.validation_end_ms,
    )
    observation = result.observation
    return {
        "command": "prospective-hype-observer",
        "execution_mode": settings.execution_mode.value,
        "api_url": settings.api_url,
        "candidate_id": spec.candidate_id,
        "candidate_spec_id": spec.spec_id,
        "campaign_id": store.manifest.campaign_id,
        "evidence_class": store.manifest.evidence_class,
        "promotion_eligible": store.manifest.promotion_eligible,
        "validation_not_before_ms": spec.validation_not_before_ms,
        "validation_plan_id": plan.plan_id,
        "validation_end_ms": plan.validation_end_ms,
        "finalization_not_before_ms": plan.finalization_not_before_ms,
        "observation": {
            "status": observation.status,
            "as_of_ms": observation.as_of_ms,
            "anchor_end_ms": observation.anchor_end_ms,
            "raw_direction": (
                None
                if observation.raw_direction is None
                else observation.raw_direction.value
            ),
            "effective_direction": (
                None
                if observation.effective_direction is None
                else observation.effective_direction.value
            ),
            "context_state_1h": observation.context_state_1h,
            "observation_id": observation.observation_id,
            "created": observation.created,
        },
        "settled_outcome_ids": tuple(
            outcome.outcome_id for outcome in result.settlements.settled
        ),
        "missing_target_observation_ids": (
            result.settlements.missing_target_observation_ids
        ),
        "observation_count": len(store.iter_observations()),
        "outcome_count": len(store.iter_outcomes()),
        "state_digest": store.state_digest,
        "root": str(root),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = prospective_hype_observer_payload(
            Settings.from_env(),
            root=args.root,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
