from __future__ import annotations

import sys
from collections.abc import Iterator
from typing import BinaryIO

from stream_unzip import stream_unzip

CHUNK_SIZE = 1024 * 1024


class StreamZipError(RuntimeError):
    pass


def _source_chunks(source: BinaryIO) -> Iterator[bytes]:
    while True:
        chunk = source.read(CHUNK_SIZE)
        if not chunk:
            return
        yield chunk


def stream_member(
    expected_name: str,
    source: BinaryIO,
    output: BinaryIO,
) -> None:
    expected_name_bytes = expected_name.encode("utf-8")
    member_count = 0
    output_size = 0

    for member_name, _member_size, chunks in stream_unzip(
        _source_chunks(source)
    ):
        member_count += 1
        if member_count != 1 or member_name != expected_name_bytes:
            raise StreamZipError(
                "unexpected ZIP member: "
                f"{member_name!r}; expected only {expected_name_bytes!r}"
            )
        for chunk in chunks:
            output.write(chunk)
            output_size += len(chunk)

    if member_count == 0:
        raise StreamZipError("ZIP archive contains no members")
    if output_size == 0:
        raise StreamZipError("ZIP member is empty")
    output.flush()


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1]:
        print(
            f"usage: {sys.argv[0]} <expected-member-name>",
            file=sys.stderr,
        )
        return 2
    try:
        stream_member(
            sys.argv[1],
            sys.stdin.buffer,
            sys.stdout.buffer,
        )
    except Exception as exc:
        print(
            f"stream ZIP member failed: {exc}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
