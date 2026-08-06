from pathlib import Path
from types import SimpleNamespace

import pytest

from app.integrations.avatar import duix_client
from app.services.avatar.avatar_service import _chunk_bounds, _generation_window


def test_chunk_bounds_cover_long_audio_without_gaps() -> None:
    duration_ms = (47 * 60 + 13) * 1000

    bounds = _chunk_bounds(duration_ms, 60)

    assert bounds[0][0] == 0
    assert bounds[-1][1] == duration_ms
    assert all(left[1] == right[0] for left, right in zip(bounds, bounds[1:]))
    assert all(end > start for start, end in bounds)
    assert min(end - start for start, end in bounds) >= 30_000
    assert max(end - start for start, end in bounds) <= 90_000


def test_chunk_bounds_merge_tiny_tail() -> None:
    bounds = _chunk_bounds(125_000, 60)

    assert bounds == [(0, 60_000), (60_000, 125_000)]


def test_chunk_bounds_prefer_nearby_silence_centre() -> None:
    bounds = _chunk_bounds(
        190_000,
        60,
        [(58.0, 59.0), (121.0, 122.0)],
    )

    assert bounds == [(0, 58_500), (58_500, 121_500), (121_500, 190_000)]


def test_generation_window_adds_context_but_keeps_non_overlapping_core() -> None:
    first = _generation_window(0, 60_000, 125_000, 600)
    second = _generation_window(60_000, 125_000, 125_000, 600)

    assert first == (0, 60_600, 0, 60_000)
    assert second == (59_400, 125_000, 600, 65_600)


def test_chapter_bounds_use_five_to_ten_minute_silence_aligned_chunks() -> None:
    duration_ms = (47 * 60 + 13) * 1000
    silences = [
        (419.2, 420.0),
        (838.8, 839.6),
        (1261.0, 1262.0),
        (1680.0, 1681.0),
        (2102.0, 2103.0),
    ]

    bounds = _chunk_bounds(
        duration_ms,
        420,
        silences,
        minimum_seconds=300,
        maximum_seconds=600,
    )

    assert bounds[0][0] == 0
    assert bounds[-1][1] == duration_ms
    assert all(left[1] == right[0] for left, right in zip(bounds, bounds[1:]))
    assert all(300_000 <= end - start <= 600_000 for start, end in bounds)
    assert bounds[0][1] == 419_600


def test_duix_path_mapping_stays_inside_shared_root(monkeypatch, tmp_path: Path) -> None:
    settings = SimpleNamespace(
        duix_base_url="http://127.0.0.1:8383",
        duix_host_shared_dir=tmp_path,
        duix_container_shared_dir="/code/data",
        duix_poll_interval_seconds=1,
        duix_task_timeout_seconds=60,
    )
    monkeypatch.setattr(duix_client, "get_settings", lambda: settings)
    client = duix_client.DuixClient()
    source = tmp_path / "tasks" / "audio.wav"

    assert client.to_container_path(source) == "/code/data/tasks/audio.wav"
    assert client.to_host_path("/code/data/temp/result.mp4") == (tmp_path / "temp" / "result.mp4")
    assert client.to_host_path(
        "/taf-job-0001-r.mp4",
        expected_code="taf-job-0001",
    ) == (tmp_path / "temp" / "taf-job-0001-r.mp4")
    with pytest.raises(ValueError):
        client.to_container_path(tmp_path.parent / "outside.wav")
    with pytest.raises(ValueError):
        client.to_host_path("/tmp/result.mp4")
    with pytest.raises(ValueError):
        client.to_host_path("/another-job-r.mp4", expected_code="taf-job-0001")
