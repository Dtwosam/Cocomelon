from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

from cocomelon.config import Settings
from cocomelon.hyperliquid.capture import capture_public_fixtures
from cocomelon.hyperliquid.client import InfoClient
from cocomelon.util.time import utc_now_ms


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture public Hyperliquid Phase 2 fixtures")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=3)
    parser.add_argument("--emit-log-fixtures", action="store_true")
    args = parser.parse_args()

    output_dir: Path = args.output_dir
    manifest = capture_public_fixtures(
        InfoClient(Settings.from_env()),
        output_dir,
        now_ms=utc_now_ms(),
        sample_size=args.sample_size,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))

    if args.emit_log_fixtures:
        for name in manifest["files"]:
            path = output_dir / str(name)
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            print(f"COCOMELON_FIXTURE_BEGIN {name}")
            print(encoded)
            print(f"COCOMELON_FIXTURE_END {name}")


if __name__ == "__main__":
    main()
