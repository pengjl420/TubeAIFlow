from datetime import UTC, datetime


def utc_now_iso() -> str:
    """Return a timezone-aware UTC timestamp for persisted records."""
    return datetime.now(UTC).isoformat()


def seconds_to_ass_time(seconds: float) -> str:
    centiseconds = int(round(seconds * 100))
    hours = centiseconds // 360000
    centiseconds %= 360000
    minutes = centiseconds // 6000
    centiseconds %= 6000
    secs = centiseconds // 100
    cs = centiseconds % 100
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def seconds_to_srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours = milliseconds // 3600000
    milliseconds %= 3600000
    minutes = milliseconds // 60000
    milliseconds %= 60000
    secs = milliseconds // 1000
    ms = milliseconds % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"
