from datetime import UTC, datetime


def utc_now_iso() -> str:
    """Return a timezone-aware UTC timestamp for persisted records."""
    return datetime.now(UTC).isoformat()


def elapsed_seconds(started_at: str | None, finished_at: str | None = None) -> float | None:
    """Return wall-clock seconds after the task actually started, excluding queue wait."""
    if not started_at:
        return None
    try:
        started = datetime.fromisoformat(started_at)
        finished = datetime.fromisoformat(finished_at) if finished_at else datetime.now(UTC)
    except (TypeError, ValueError):
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=UTC)
    return round(max(0.0, (finished - started).total_seconds()), 3)


def seconds_to_srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours = milliseconds // 3600000
    milliseconds %= 3600000
    minutes = milliseconds // 60000
    milliseconds %= 60000
    secs = milliseconds // 1000
    ms = milliseconds % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"
