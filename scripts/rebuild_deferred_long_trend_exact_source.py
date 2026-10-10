"""Rebuild authentic LONG-trend execution source after an upgrade handoff.

This runs only after the successor is dispatched and the full-stack summary
has been reconstructed from durable original stores. It cannot submit orders.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityStore,
)
from cocomelon.research.continuous_paper_opening_opportunity_paths import (
    DEFAULT_MAX_COMPLETION_LAG_MS,
    DEFAULT_MAX_PATH_AGE_MS,
    ContinuousPaperOpeningOpportunityPathStore,
)
from cocomelon.research.prospective_long_trend_carveout_execution_shadow_source import (
    prospective_long_trend_execution_shadow_source,
)

OUTPUT_FILENAME = "prospective-long-trend-execution-shadow-source.json"
FULL_STACK_FILENAME = "prospective-full-stack-forward-markout-summary.json"


class DeferredLongTrendSourceError(RuntimeError):
    pass


def _read_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeferredLongTrendSourceError(
            f"required authentic source missing or invalid: {path.name}"
        ) from exc
    if not isinstance(value, dict):
        raise DeferredLongTrendSourceError(
            f"required authentic source is not an object: {path.name}"
        )
    return value


def rebuild_deferred_long_trend_source(root: Path) -> dict[str, object]:
    session = _read_object(root / "session-summary.json")
    if session.get("exit_reason") != "upgrade_requested":
        raise DeferredLongTrendSourceError(
            "offline rebuild requires an upgrade-requested handoff"
        )

    summary = _read_object(root / FULL_STACK_FILENAME)
    if (
        summary.get("deferred_post_handoff_rebuild") is not True
        or summary.get("source_exit_reason") != "upgrade_requested"
    ):
        raise DeferredLongTrendSourceError(
            "same-handoff deferred full-stack rebuild is missing"
        )

    opportunities = ContinuousPaperOpeningOpportunityStore(
        root / "opening-opportunities"
    )
    paths = ContinuousPaperOpeningOpportunityPathStore(
        root / "opening-opportunity-paths",
        max_path_age_ms=DEFAULT_MAX_PATH_AGE_MS,
        max_completion_lag_ms=DEFAULT_MAX_COMPLETION_LAG_MS,
    )
    # ContinuousPaper's actual baseline runner uses this exact default
    # configuration at startup. Never substitute guessed prices, fills or fees.
    config = BaselineReplayConfig().execution
    payload = prospective_long_trend_execution_shadow_source(
        summary,
        tuple(opportunities.iter_records()),
        tuple(paths.iter_paths()),
        config,
    )
    output = dict(payload)
    # The producer's source_sha256 intentionally excludes these display fields.
    output["enabled"] = True
    output["error"] = None
    return output


def write_deferred_long_trend_source(root: Path) -> Path:
    payload = rebuild_deferred_long_trend_source(root)
    target = root / OUTPUT_FILENAME
    encoded = (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state_root", type=Path)
    args = parser.parse_args(argv)
    output = write_deferred_long_trend_source(args.state_root)
    payload = _read_object(output)
    print(
        json.dumps(
            {
                "output": str(output),
                "source_opportunity_count": payload["source_opportunity_count"],
                "execution_authority": payload["execution_authority"],
                "promotion_authority": payload["promotion_authority"],
                "research_only": payload["research_only"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
