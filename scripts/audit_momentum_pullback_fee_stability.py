from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.momentum_pullback_fee_stability import (
    MomentumPullbackFeeStressError,
    audit_momentum_pullback_optimistic_fee_stability,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "RESEARCH ONLY: stress exact frozen original pullback markouts "
            "under optimistically perfect mark-priced IOC fills plus fees."
        ),
    )
    parser.add_argument("summary_json", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args(argv)
    # Preserve the exact immutable research input fingerprint. A local digest
    # is not independent authentication of its GitHub artifact or original
    # market-source completeness.
    try:
        original = args.summary_json.read_bytes()
        raw = json.loads(original)
        if not isinstance(raw, dict):
            raise MomentumPullbackFeeStressError(
                "original source summary must be an object"
            )
        receipt = audit_momentum_pullback_optimistic_fee_stability(raw)
    except (OSError, ValueError, MomentumPullbackFeeStressError) as exc:
        parser.error(str(exc))
    receipt["local_source_summary_sha256"] = hashlib.sha256(original).hexdigest()
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "candidate_id": receipt["candidate_id"],
        "observed_original_admissions": receipt["observed_original_admissions"],
        "positive_absolute_after_cost_equity_verified": False,
        "promotion_authority": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
