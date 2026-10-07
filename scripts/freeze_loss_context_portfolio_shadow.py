from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    write_loss_context_portfolio_shadow_freeze,
)


def _load_object(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(
        isinstance(key, str) for key in raw
    ):
        raise ValueError("composition payload must be an object")
    return cast(dict[str, object], raw)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--composition", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--frozen-at-ms", required=True, type=int)
    parser.add_argument("--source-paper-run-id", required=True, type=int)
    parser.add_argument("--source-paper-run-attempt", required=True, type=int)
    parser.add_argument("--source-paper-head-sha", required=True)
    args = parser.parse_args()

    freeze, created = write_loss_context_portfolio_shadow_freeze(
        _load_object(Path(args.composition)),
        output_path=Path(args.output),
        frozen_at_ms=args.frozen_at_ms,
        source_paper_run_id=args.source_paper_run_id,
        source_paper_run_attempt=args.source_paper_run_attempt,
        source_paper_head_sha=args.source_paper_head_sha,
    )
    print(
        json.dumps(
            {
                "candidate_id": freeze.candidate_id,
                "created": created,
                "horizons_ms": freeze.horizons_ms,
                "prospective_not_before_ms": (
                    freeze.prospective_not_before_ms
                ),
                "research_only": freeze.research_only,
                "execution_authority": freeze.execution_authority,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
