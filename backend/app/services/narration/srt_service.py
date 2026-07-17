from pathlib import Path
import unicodedata

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


def create_segment_srt(project: Project, segment: Segment) -> Path:
    if segment.duration is None:
        raise ValueError(f"Segment {segment.segment_id} has no audio duration")

    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(base_dir)
    output_path = base_dir / "subtitles" / "segments" / f"{segment.segment_id}.srt"
    # A transcript line is the atomic TTS and subtitle unit. Do not estimate
    # timings for smaller text fragments inside an already generated WAV.
    cues = [(0.0, float(segment.duration), segment.text_zh)]
    _write_srt(output_path, cues, remove_punctuation=False)
    return output_path


def create_full_srt(project: Project, segments: list[Segment]) -> Path:
    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(base_dir)

    cues = build_chinese_subtitle_cues(segments)

    stem = get_output_stem(project)
    work_path = base_dir / "subtitles" / f"{stem}.srt"
    _write_srt(
        work_path,
        [(item["start"], item["end"], item["text_zh"]) for item in cues],
        remove_punctuation=False,
    )

    final_path = get_final_srt_path(project, get_settings().workspace_dir)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_text(work_path.read_text(encoding="utf-8"), encoding="utf-8")
    return final_path


def build_chinese_subtitle_cues(segments: list[Segment]) -> list[dict]:
    current = 0.0
    cues = []
    for segment in segments:
        if segment.duration is None:
            raise ValueError(f"Segment {segment.segment_id} has no audio duration")
        start = current
        end = start + float(segment.duration)
        clean_text = _clean_srt_text(segment.text_zh, remove_punctuation=False)
        if clean_text:
            cues.append(
                {
                    "cue_id": segment.segment_id,
                    "segment_id": segment.segment_id,
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "text_zh": clean_text,
                }
            )
        current = end
    return cues


def _write_srt(path: Path, cues: list[tuple[float, float, str]], remove_punctuation: bool = True) -> None:
    blocks = []
    for index, (start, end, text) in enumerate(cues, start=1):
        clean_text = _clean_srt_text(text, remove_punctuation=remove_punctuation)
        blocks.append(
            f"{index}\n"
            f"{seconds_to_srt_time(start)} --> {seconds_to_srt_time(end)}\n"
            f"{clean_text}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def _clean_srt_text(text: str, remove_punctuation: bool = True) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not remove_punctuation:
        return normalized.replace("\\N", "\n").strip()
    return "".join(char for char in normalized if not unicodedata.category(char).startswith("P")).strip()
