from pathlib import Path

from app.config import get_settings
from app.models.project import Project
from app.models.narration import Segment
from app.infrastructure.project_layout import (
    ensure_project_dirs,
    get_final_srt_path,
    get_output_stem,
    get_project_work_dir,
)
from app.shared.time import seconds_to_srt_time
from app.services.narration import subtitle_service


def create_full_srt(
    project: Project,
    segments: list[Segment],
    session=None,
) -> Path:
    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(base_dir)

    settings = get_settings()
    cues = subtitle_service.build_segment_cues(
        project.id,
        segments,
        max_display_units=settings.subtitle_max_display_units,
        min_duration_ms=settings.subtitle_min_cue_duration_ms,
        max_duration_ms=settings.subtitle_max_cue_duration_ms,
    )
    if session is not None:
        subtitle_service.replace_project_cues(session, project.id, cues)

    stem = get_output_stem(project)
    work_path = base_dir / "subtitles" / f"{stem}.srt"
    _write_srt(
        work_path,
        [(item["start_ms"] / 1000, item["end_ms"] / 1000, item["text"]) for item in cues],
    )

    final_path = get_final_srt_path(project, get_settings().workspace_dir)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_text(work_path.read_text(encoding="utf-8"), encoding="utf-8")
    return final_path


def _write_srt(path: Path, cues: list[tuple[float, float, str]]) -> None:
    blocks = []
    for index, (start, end, text) in enumerate(cues, start=1):
        clean_text = _clean_srt_text(text)
        blocks.append(
            f"{index}\n"
            f"{seconds_to_srt_time(start)} --> {seconds_to_srt_time(end)}\n"
            f"{clean_text}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def _clean_srt_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.replace("\\N", "\n").strip()
