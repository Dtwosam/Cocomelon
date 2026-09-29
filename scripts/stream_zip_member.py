from __future__ import annotations

import binascii
import struct
import sys
import zlib
from typing import BinaryIO

LOCAL_FILE_HEADER_SIGNATURE = 0x04034B50
DATA_DESCRIPTOR_SIGNATURE = 0x08074B50
DATA_DESCRIPTOR_SIGNATURE_BYTES = b"PK\x07\x08"
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


def _write_payload(
    output: BinaryIO,
    payload: bytes,
    *,
    crc: int,
    output_size: int,
) -> tuple[int, int]:
    if not payload:
        return crc, output_size
    output.write(payload)
    return (
        binascii.crc32(payload, crc) & 0xFFFFFFFF,
        output_size + len(payload),
    )


def _stream_stored_descriptor_member(
    buffered: _BufferedSource,
    output: BinaryIO,
) -> tuple[int, int, int]:
    pending = bytearray()
    crc = 0
    output_size = 0
    descriptor_size = 24
    signature_keep = len(DATA_DESCRIPTOR_SIGNATURE_BYTES) - 1

    while True:
        if len(pending) < descriptor_size:
            chunk = buffered.read(CHUNK_SIZE)
            if chunk:
                pending.extend(chunk)
            elif not pending:
                raise StreamZipError(
                    "stored ZIP64 data-descriptor member ended prematurely"
                )

        candidate_at = pending.find(DATA_DESCRIPTOR_SIGNATURE_BYTES)
        if candidate_at < 0:
            if not pending:
                raise StreamZipError(
                    "stored ZIP64 data descriptor is missing"
                )
            emit_count = max(0, len(pending) - signature_keep)
            if emit_count == 0:
                chunk = buffered.read(CHUNK_SIZE)
                if not chunk:
                    raise StreamZipError(
                        "stored ZIP64 data descriptor is missing"
                    )
                pending.extend(chunk)
                continue
            payload = bytes(pending[:emit_count])
            del pending[:emit_count]
            crc, output_size = _write_payload(
                output,
                payload,
                crc=crc,
                output_size=output_size,
            )
            continue

        if candidate_at:
            payload = bytes(pending[:candidate_at])
            del pending[:candidate_at]
            crc, output_size = _write_payload(
                output,
                payload,
                crc=crc,
                output_size=output_size,
            )

        while len(pending) < descriptor_size:
            chunk = buffered.read(CHUNK_SIZE)
            if not chunk:
                raise StreamZipError(
                    "stored ZIP64 data descriptor is truncated"
                )
            pending.extend(chunk)

        expected_crc = struct.unpack("<I", pending[4:8])[0]
        compressed_size = struct.unpack("<Q", pending[8:16])[0]
        uncompressed_size = struct.unpack("<Q", pending[16:24])[0]
        if (
            expected_crc == crc
            and compressed_size == output_size
            and uncompressed_size == output_size
        ):
            del pending[:descriptor_size]
            buffered.prepend(bytes(pending))
            output.flush()
            return crc, output_size, expected_crc

        # The signature can legally occur inside a stored payload. Emit one
        # byte and search again so overlapping candidate signatures remain
        # detectable while CRC and byte count continue to describe only
        # confirmed payload bytes.
        payload = bytes(pending[:1])
        del pending[:1]
        crc, output_size = _write_payload(
            output,
            payload,
            crc=crc,
            output_size=output_size,
        )


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
    zip64_size_placeholders = (
        compressed_size == UINT32_MAX
        or uncompressed_size == UINT32_MAX
    )
    compressed_size, uncompressed_size = _member_sizes(
        compressed_size,
        uncompressed_size,
        extra,
    )

    descriptor_consumed = False
    descriptor_expected_crc: int | None = None
    if (
        method == STORED_METHOD
        and flags & 0x8
        and zip64_size_placeholders
        and compressed_size == 0
        and uncompressed_size == 0
    ):
        (
            crc,
            output_size,
            descriptor_expected_crc,
        ) = _stream_stored_descriptor_member(
            buffered,
            output,
        )
        descriptor_consumed = True
    elif method == STORED_METHOD:
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

    if descriptor_consumed:
        if descriptor_expected_crc is None:
            raise StreamZipError(
                "stored ZIP64 descriptor CRC is missing"
            )
        expected_crc = descriptor_expected_crc
    elif flags & 0x8:
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
