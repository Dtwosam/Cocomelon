from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.deferred_early_exit_chart_integrity import (
    rebuild_deferred_early_exit_chart_integrity,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile frozen early/late book-filled exits with the "
            "complete journal and independently recorded mark coverage"
        ),
    )
    parser.add_argument("state_root", type=Path)
    args = parser.parse_args(argv)
    output = rebuild_deferred_early_exit_chart_integrity(args.state_root)
    report = json.loads(output.read_text(encoding="utf-8"))
    print(json.dumps({
        "path": str(output),
        "matched_trades": report["matched_forward_trades"],
        "clean_mark_paths": report["verified_clean_chart_trades"],
        "missing_paths": len(report["missing_chart_trade_ids"]),
        "gapped_paths": len(report["known_data_gap_trade_ids"]),
        "incomplete_paths": len(report["incomplete_chart_trade_ids"]),
        "clean_evidence": report["chart_integrity_complete"],
        "conditional_economic_screen": report[
            "economic_screen_with_chart_integrity"
        ],
        "execution_authority": report["execution_authority"],
        "promotion_authority": report["promotion_authority"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
