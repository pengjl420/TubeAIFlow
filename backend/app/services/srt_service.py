from pathlib import Path
import unicodedata

from app.config import get_settings
from app.models.project import Project
from app.models.segment import Segment
from app.services.subtitle_splitter import split_timed_subtitle_cues
from app.utils.project_paths import ensure_project_dirs, get_final_srt_path, get_output_stem, get_project_work_dir
from app.utils.time_utils import seconds_to_srt_time


def create_segment_srt(project: Project, segment: Segment) -> Path:
    if segment.duration is None:
        raise ValueError(f"Segment {segment.segment_id} has no audio duration")

    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(base_dir)
    output_path = base_dir / "subtitles" / "segments" / f"{segment.segment_id}.srt"
    cues = split_timed_subtitle_cues(segment.text_zh, 0.0, float(segment.duration), "zh")
    _write_srt(output_path, cues)
    return output_path


def create_full_srt(project: Project, segments: list[Segment]) -> Path:
    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(base_dir)

    current = 0.0
    cues = []
    for segment in segments:
        if segment.duration is None:
            raise ValueError(f"Segment {segment.segment_id} has no audio duration")
        start = current
        end = start + float(segment.duration)
        cues.extend(split_timed_subtitle_cues(segment.text_zh, start, end, "zh"))
        current = end

    stem = get_output_stem(project)
    work_path = base_dir / "subtitles" / f"{stem}.srt"
    _write_srt(work_path, cues)

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
    return "".join(char for char in normalized if not unicodedata.category(char).startswith("P")).strip()
