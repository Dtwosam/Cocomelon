from __future__ import annotations

import binascii
import struct
import sys
import zlib
from typing import BinaryIO

LOCAL_FILE_HEADER_SIGNATURE = 0x04034B50
DATA_DESCRIPTOR_SIGNATURE = 0x08074B50
ZIP64_EXTRA_ID = 0x0001
UINT32_MAX = 0xFFFFFFFF
STORED_METHOD = 0
DEFLATE_METHOD = 8
CHUNK_SIZE = 1024 * 1024


class StreamZipError(RuntimeError):
    pass


class _BufferedSource:
    def __init__(self, raw: BinaryIO) -> None:
        self.raw = raw
        self.pending = bytearray()

    def prepend(self, data: bytes) -> None:
        if data:
            self.pending[:0] = data

    def read(self, size: int) -> bytes:
        if size <= 0:
            return b""
        if self.pending:
            take = min(size, len(self.pending))
            result = bytes(self.pending[:take])
            del self.pending[:take]
            if take == size:
                return result
            return result + self.raw.read(size - take)
        return self.raw.read(size)

    def read_exact(self, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = self.read(remaining)
            if not chunk:
                raise StreamZipError("ZIP stream ended prematurely")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def drain(self) -> None:
        self.pending.clear()
        while self.raw.read(CHUNK_SIZE):
            pass


def _member_sizes(
    compressed_size: int,
    uncompressed_size: int,
    extra: bytes,
) -> tuple[int, int]:
    if (
        compressed_size != UINT32_MAX
        and uncompressed_size != UINT32_MAX
    ):
        return compressed_size, uncompressed_size

    offset = 0
    while offset < len(extra):
        if len(extra) - offset < 4:
            raise StreamZipError("ZIP extra field is truncated")
        field_id, field_size = struct.unpack(
            "<HH",
            extra[offset : offset + 4],
        )
        offset += 4
        field_end = offset + field_size
        if field_end > len(extra):
            raise StreamZipError("ZIP extra field is truncated")
        field = extra[offset:field_end]
        offset = field_end
        if field_id != ZIP64_EXTRA_ID:
            continue

        cursor = 0
        resolved_uncompressed = uncompressed_size
        resolved_compressed = compressed_size
        if uncompressed_size == UINT32_MAX:
            if len(field) - cursor < 8:
                raise StreamZipError(
                    "ZIP64 extra field is missing uncompressed size"
                )
            resolved_uncompressed = struct.unpack(
                "<Q",
                field[cursor : cursor + 8],
            )[0]
            cursor += 8
        if compressed_size == UINT32_MAX:
            if len(field) - cursor < 8:
                raise StreamZipError(
                    "ZIP64 extra field is missing compressed size"
                )
            resolved_compressed = struct.unpack(
                "<Q",
                field[cursor : cursor + 8],
            )[0]
        return resolved_compressed, resolved_uncompressed

    raise StreamZipError("ZIP64 size metadata is missing")


def _stream_stored_member(
    buffered: _BufferedSource,
    output: BinaryIO,
    *,
    compressed_size: int,
    uncompressed_size: int,
) -> tuple[int, int]:
    if compressed_size != uncompressed_size:
        raise StreamZipError(
            "stored ZIP member compressed/uncompressed sizes differ"
        )
    remaining = compressed_size
    crc = 0
    output_size = 0
    while remaining:
        chunk = buffered.read(min(CHUNK_SIZE, remaining))
        if not chunk:
            raise StreamZipError(
                "stored ZIP member ended prematurely"
            )
        output.write(chunk)
        crc = binascii.crc32(chunk, crc) & 0xFFFFFFFF
        output_size += len(chunk)
        remaining -= len(chunk)
    return crc, output_size


def stream_member(
    expected_name: str,
    source: BinaryIO,
    output: BinaryIO,
) -> None:
    buffered = _BufferedSource(source)
    header = buffered.read_exact(30)
    (
        signature,
        _version_needed,
        flags,
        method,
        _mod_time,
        _mod_date,
        header_crc,
        compressed_size,
        uncompressed_size,
        name_length,
        extra_length,
    ) = struct.unpack("<IHHHHHIIIHH", header)
    if signature != LOCAL_FILE_HEADER_SIGNATURE:
        raise StreamZipError(
            "ZIP stream does not start with a local file header"
        )
    if flags & 0x1:
        raise StreamZipError("encrypted ZIP members are unsupported")

    name = buffered.read_exact(name_length)
    try:
        member_name = name.decode(
            "utf-8" if flags & 0x800 else "cp437"
        )
    except UnicodeDecodeError as exc:
        raise StreamZipError("ZIP member name is invalid") from exc
    if member_name != expected_name:
        raise StreamZipError(
            "unexpected first ZIP member: "
            f"{member_name!r}; expected {expected_name!r}"
        )

    extra = buffered.read_exact(extra_length)
    compressed_size, uncompressed_size = _member_sizes(
        compressed_size,
        uncompressed_size,
        extra,
    )

    if method == STORED_METHOD:
        crc, output_size = _stream_stored_member(
            buffered,
            output,
            compressed_size=compressed_size,
            uncompressed_size=uncompressed_size,
        )
    elif method == DEFLATE_METHOD:
        inflater = zlib.decompressobj(-zlib.MAX_WBITS)
        crc = 0
        output_size = 0
        while not inflater.eof:
            chunk = buffered.read(CHUNK_SIZE)
            if not chunk:
                raise StreamZipError(
                    "deflated ZIP member ended prematurely"
                )
            decoded = inflater.decompress(chunk)
            if decoded:
                output.write(decoded)
                crc = binascii.crc32(decoded, crc) & 0xFFFFFFFF
                output_size += len(decoded)
            if inflater.eof:
                buffered.prepend(inflater.unused_data)
                break

        tail = inflater.flush()
        if tail:
            output.write(tail)
            crc = binascii.crc32(tail, crc) & 0xFFFFFFFF
            output_size += len(tail)
    else:
        raise StreamZipError(
            f"unsupported ZIP compression method: {method}"
        )
    output.flush()

    if flags & 0x8:
        first = struct.unpack(
            "<I",
            buffered.read_exact(4),
        )[0]
        expected_crc = (
            struct.unpack(
                "<I",
                buffered.read_exact(4),
            )[0]
            if first == DATA_DESCRIPTOR_SIGNATURE
            else first
        )
    else:
        expected_crc = header_crc

    if crc != expected_crc:
        raise StreamZipError(
            "ZIP member CRC mismatch: "
            f"expected {expected_crc:08x}, got {crc:08x}"
        )
    if output_size == 0:
        raise StreamZipError("ZIP member is empty")

    # Consume the descriptor sizes and central directory so the upstream
    # authenticated download can finish cleanly under shell pipefail.
    buffered.drain()


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
    except (OSError, StreamZipError, zlib.error) as exc:
        print(
            f"stream ZIP member failed: {exc}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
