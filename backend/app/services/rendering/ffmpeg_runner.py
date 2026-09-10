from __future__ import annotations

from collections.abc import Callable


HARDWARE_VIDEO_CODECS = frozenset(
    {"h264_nvenc", "hevc_nvenc", "h264_qsv", "hevc_qsv", "h264_amf", "hevc_amf"}
)


def run_with_encoder_fallback(
    args: list[str],
    project_id: str,
    runner: Callable[[list[str], str | None], None],
) -> str:
    """Retry a failed hardware encode once with portable libx264 settings."""
    codec = _option_value(args, "-c:v")
    try:
        runner(args, project_id)
        return codec or "unknown"
    except RuntimeError:
        if codec not in HARDWARE_VIDEO_CODECS:
            raise
    fallback = list(args)
    _replace_option(fallback, "-c:v", "libx264")
    _replace_option(fallback, "-preset", "veryfast")
    # Hardware encoders may use constant-quality options that libx264 does not
    # understand. Existing CRF values remain valid when present.
    for option in ("-cq", "-qp", "-global_quality"):
        _remove_option(fallback, option)
    if "-crf" not in fallback:
        fallback[-1:-1] = ["-crf", "20"]
    runner(fallback, project_id)
    return "libx264"


def _option_value(args: list[str], option: str) -> str | None:
    try:
        return args[args.index(option) + 1]
    except (ValueError, IndexError):
        return None


def _replace_option(args: list[str], option: str, value: str) -> None:
    try:
        args[args.index(option) + 1] = value
    except (ValueError, IndexError):
        args[-1:-1] = [option, value]


def _remove_option(args: list[str], option: str) -> None:
    while option in args:
        index = args.index(option)
        del args[index : min(index + 2, len(args))]
