from pathlib import Path

import pytest

from app.infrastructure.atomic_files import atomic_output_path


def test_atomic_output_publishes_only_after_success(tmp_path: Path) -> None:
    output = tmp_path / "final.mp4"
    output.write_bytes(b"old")

    with atomic_output_path(output) as temporary:
        temporary.write_bytes(b"new")
        assert output.read_bytes() == b"old"

    assert output.read_bytes() == b"new"


def test_atomic_output_preserves_previous_file_on_failure(tmp_path: Path) -> None:
    output = tmp_path / "final.mp4"
    output.write_bytes(b"old")

    with pytest.raises(RuntimeError, match="render failed"):
        with atomic_output_path(output) as temporary:
            temporary.write_bytes(b"partial")
            raise RuntimeError("render failed")

    assert output.read_bytes() == b"old"
    assert not list(tmp_path.glob("*.partial.mp4"))
