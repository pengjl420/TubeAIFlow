from pathlib import Path
import unicodedata

from app.config import get_settings
from app.models.project import Project
from app.models.segment import Segment
from app.services import timeline_service, translate_service
from app.services.subtitle_splitter import split_timed_subtitle_cues
from app.utils.project_paths import (
    ensure_project_dirs,
    get_final_en_srt_path,
    get_final_srt_path,
    get_output_stem,
    get_project_work_dir,
)
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

    cues = build_chinese_subtitle_cues(segments)

    stem = get_output_stem(project)
    work_path = base_dir / "subtitles" / f"{stem}.srt"
    _write_srt(work_path, [(item["start"], item["end"], item["text_zh"]) for item in cues])

    final_path = get_final_srt_path(project, get_settings().workspace_dir)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_text(work_path.read_text(encoding="utf-8"), encoding="utf-8")
    return final_path


def create_full_srt_with_cues(project: Project, segments: list[Segment]) -> tuple[Path, list[dict]]:
    path = create_full_srt(project, segments)
    return path, build_chinese_subtitle_cues(segments)


def build_chinese_subtitle_cues(segments: list[Segment]) -> list[dict]:
    current = 0.0
    cues = []
    cue_index = 1
    for segment in segments:
        if segment.duration is None:
            raise ValueError(f"Segment {segment.segment_id} has no audio duration")
        start = current
        end = start + float(segment.duration)
        for cue_start, cue_end, cue_text in split_timed_subtitle_cues(segment.text_zh, start, end, "zh"):
            clean_text = _clean_srt_text(cue_text)
            if not clean_text:
                continue
            cues.append(
                {
                    "cue_id": f"{cue_index:04d}",
                    "segment_id": segment.segment_id,
                    "start": cue_start,
                    "end": cue_end,
                    "text_zh": clean_text,
                }
            )
            cue_index += 1
        current = end
    return cues


def create_english_srt(project: Project) -> Path:
    timeline = timeline_service.load_timeline(project)
    zh_cues = []
    cue_index = 1
    for item in timeline.get("segments", []):
        for cue_start, cue_end, cue_text in split_timed_subtitle_cues(
            str(item.get("text_zh") or ""),
            float(item["start"]),
            float(item["end"]),
            "zh",
        ):
            zh_cues.append(
                {
                    "cue_id": f"{cue_index:04d}",
                    "segment_id": item.get("segment_id"),
                    "start": cue_start,
                    "end": cue_end,
                    "text_zh": _clean_srt_text(cue_text),
                }
            )
            cue_index += 1
    translations = translate_service.load_cue_translation(project)
    return create_english_srt_from_chinese_cues(project, zh_cues, translations)


def create_english_srt_from_chinese_cues(project: Project, zh_cues: list[dict], translations: dict[str, str]) -> Path:
    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(base_dir)

    cues = []
    for cue in zh_cues:
        cue_id = str(cue.get("cue_id") or "").strip()
        text_en = translations.get(cue_id, "").strip()
        if not cue_id or not text_en:
            raise ValueError(f"Missing English translation for subtitle cue {cue_id or '<unknown>'}")
        cues.append((float(cue["start"]), float(cue["end"]), text_en))

    stem = get_output_stem(project)
    work_path = base_dir / "subtitles" / f"{stem}_en.srt"
    _write_srt(work_path, cues, remove_punctuation=False)

    final_path = get_final_en_srt_path(project, get_settings().workspace_dir)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_text(work_path.read_text(encoding="utf-8"), encoding="utf-8")
    return final_path


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
