from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.deferred_correlation_holder_release_execution import (
    write_deferred_correlation_holder_release_execution,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild exact correlation-holder release execution economics "
            "after the successor paper worker has already been dispatched."
        )
    )
    parser.add_argument("state_root", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = write_deferred_correlation_holder_release_execution(
        args.state_root,
        output_path=args.output,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "output": str(output),
                "captured_release_books": payload[
                    "captured_release_books"
                ],
                "exact_execution_config_records": payload[
                    "exact_execution_config_records"
                ],
                "unbound_execution_config_records": payload[
                    "unbound_execution_config_records"
                ],
                "full_release_fills": payload["full_release_fills"],
                "partial_release_fills": payload[
                    "partial_release_fills"
                ],
                "no_release_fills": payload["no_release_fills"],
                "fully_closed_terminal_contribution": payload[
                    "fully_closed_terminal_contribution"
                ],
                "deferred_post_handoff_rebuild": payload[
                    "deferred_post_handoff_rebuild"
                ],
                "execution_authority": payload[
                    "execution_authority"
                ],
                "changes_risk_limits": payload["changes_risk_limits"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
