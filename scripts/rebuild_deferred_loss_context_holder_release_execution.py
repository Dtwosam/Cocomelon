from __future__ import annotations

import argparse
import json
from pathlib import Path

from cocomelon.research.deferred_loss_context_holder_release_execution import (
    write_deferred_loss_context_holder_release_execution,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("state_root")
    parser.add_argument("--output")
    args = parser.parse_args()

    output = (
        Path(args.output)
        if args.output
        else Path(args.state_root)
        / "loss-context-holder-release-execution-summary.json"
    )
    write_deferred_loss_context_holder_release_execution(
        args.state_root,
        output_path=output,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    print(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
