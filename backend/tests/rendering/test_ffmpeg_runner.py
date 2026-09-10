from unittest.mock import Mock

import pytest

from app.services.rendering.ffmpeg_runner import run_with_encoder_fallback


def test_hardware_encoder_failure_retries_with_libx264() -> None:
    runner = Mock(side_effect=[RuntimeError("NVENC device unavailable"), None])
    args = ["-y", "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "21", "out.mp4"]

    selected = run_with_encoder_fallback(args, "project", runner)

    assert selected == "libx264"
    fallback = runner.call_args_list[1].args[0]
    assert fallback[fallback.index("-c:v") + 1] == "libx264"
    assert fallback[fallback.index("-preset") + 1] == "veryfast"
    assert "-cq" not in fallback
    assert "-crf" in fallback


def test_software_encoder_failure_is_not_retried() -> None:
    runner = Mock(side_effect=RuntimeError("encode failed"))

    with pytest.raises(RuntimeError, match="encode failed"):
        run_with_encoder_fallback(["-c:v", "libx264", "out.mp4"], "project", runner)

    runner.assert_called_once()
