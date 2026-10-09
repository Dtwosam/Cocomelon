from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.deferred_long_entry_loss_attribution import (
    write_long_entry_loss_attribution,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile closed LONG and SHORT entry/exit loss attribution"
    )
    parser.add_argument("state_root", type=Path)
    options = parser.parse_args(argv)
    path = write_long_entry_loss_attribution(options.state_root)
    report = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps({
        "path": str(path),
        "closed_trades": report["source_trades"],
        "context_verified": report["verified_entry_context_trades"],
        "context_missing": report["missing_entry_context_trades"],
        "long_net_pnl": report["by_side"]["long"]["net_pnl"],
        "long_net_r": report["by_side"]["long"]["net_r"],
        "short_net_pnl": report["by_side"]["short"]["net_pnl"],
        "short_net_r": report["by_side"]["short"]["net_r"],
        "execution_authority": report["execution_authority"],
        "ready_for_review": report["ready_for_review"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
