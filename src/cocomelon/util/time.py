from time import time_ns


def utc_now_ms() -> int:
    return time_ns() // 1_000_000
