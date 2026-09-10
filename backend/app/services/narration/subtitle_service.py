import math
import re
import unicodedata
from sqlalchemy import delete
from sqlmodel import Session, select

from app.config import get_settings
from app.infrastructure.file_storage import project_dir
from app.infrastructure.project_layout import ensure_project_dirs
from app.models.narration import Segment
from app.models.media import GeneratedImageVariant, SceneAssignment
from app.models.project import Project
from app.models.storyboard import SceneRevision, SubtitleCue, VisualScene
from app.shared.time import utc_now_iso


_TIMESTAMP_PATTERN = re.compile(
    r"^(?P<hours>\d{1,3}):(?P<minutes>[0-5]\d):(?P<seconds>[0-5]\d)[,.](?P<milliseconds>\d{3})$"
)
_TIMING_PATTERN = re.compile(r"^(?P<start>\S+)\s*-->\s*(?P<end>\S+)(?:\s+.*)?$")
MAX_SRT_CHARACTERS = 2_000_000


def build_segment_cues(
    project_id: str,
    segments: list[Segment],
    *,
    max_display_units: int = 22,
    min_duration_ms: int = 1000,
    max_duration_ms: int = 6000,
) -> list[dict]:
    """Split narration segments into readable cues while preserving their real duration."""
    cue_values: list[dict] = []
    current_ms = 0
    for segment in segments:
        if segment.duration is None:
            raise ValueError(f"Segment {segment.segment_id} has no audio duration")
        start_ms = (
            int(round(float(segment.start_time) * 1000))
            if segment.start_time is not None
            else current_ms
        )
        end_ms = (
            int(round(float(segment.end_time) * 1000))
            if segment.end_time is not None
            else start_ms + int(round(float(segment.duration) * 1000))
        )
        if end_ms <= start_ms:
            raise ValueError(f"Segment {segment.segment_id} has an invalid audio duration")

        text = re.sub(r"\s+", " ", segment.text).strip()
        if text:
            desired_count = max(1, math.ceil((end_ms - start_ms) / max_duration_ms))
            chunks = split_subtitle_text(text, max_display_units, desired_count)
            chunks = _merge_chunks_for_minimum_duration(
                chunks,
                end_ms - start_ms,
                min_duration_ms,
            )
            timings = _allocate_cue_times(
                chunks,
                start_ms,
                end_ms,
                min_duration_ms=min_duration_ms,
                max_duration_ms=max_duration_ms,
            )
            for cue_index, (chunk, (cue_start, cue_end)) in enumerate(
                zip(chunks, timings, strict=True), start=1
            ):
                cue_values.append(
                    {
                        "id": f"{project_id}:sub_{segment.segment_id}_{cue_index:02d}",
                        "source_segment_id": segment.id,
                        "cue_index": cue_index,
                        "start_ms": cue_start,
                        "end_ms": cue_end,
                        "text": chunk,
                    }
                )
        current_ms = end_ms
    return cue_values


def split_subtitle_text(text: str, max_display_units: int, desired_count: int = 1) -> list[str]:
    """Split at natural punctuation near the target width, falling back to character width."""
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    total_units = display_units(normalized)
    target_units = min(
        float(max_display_units),
        max(1.0, total_units / max(1, desired_count)),
    )
    chunks: list[str] = []
    remaining = normalized
    while display_units(remaining) > max_display_units or len(chunks) + 1 < desired_count:
        remaining_count = max(1, desired_count - len(chunks))
        target = min(target_units, display_units(remaining) / remaining_count)
        split_at = _find_split_index(remaining, target, max_display_units)
        if split_at <= 0 or split_at >= len(remaining):
            break
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return [chunk for chunk in chunks if chunk]


def display_units(text: str) -> float:
    return sum(_character_display_units(character) for character in text)


def _character_display_units(character: str) -> float:
    if character.isspace():
        return 0.25
    if unicodedata.east_asian_width(character) in {"W", "F"}:
        return 1.0
    if character.isascii():
        return 0.5
    return 1.0


def spoken_weight(text: str) -> float:
    weight = 0.0
    for character in text:
        if character in "。！？!?":
            weight += 0.6
        elif character in "；;：:":
            weight += 0.4
        elif character in "，,、":
            weight += 0.25
        elif character.isspace():
            continue
        elif character.isascii() and character.isalpha():
            weight += 0.45
        elif character.isascii() and character.isdigit():
            weight += 0.8
        else:
            weight += 1.0
    return max(weight, 0.1)


def _find_split_index(text: str, target_units: float, max_units: int) -> int:
    candidates: list[tuple[int, float, int]] = []
    fallback_candidates: list[tuple[int, float]] = []
    fallback_index = 0
    units = 0.0
    for index, character in enumerate(text, start=1):
        units += _character_display_units(character)
        if units > max_units:
            break
        fallback_index = index
        fallback_candidates.append((index, units))
        priority = _break_priority(character)
        if priority and index < len(text):
            candidates.append((index, units, priority))
    minimum_natural_width = min(target_units * 0.55, max(1.0, target_units - 2))
    natural = [item for item in candidates if item[1] >= minimum_natural_width]
    if natural:
        return max(
            natural,
            key=lambda item: (item[2], -abs(item[1] - target_units)),
        )[0]
    if fallback_index <= 0:
        return 1
    return min(fallback_candidates, key=lambda item: abs(item[1] - target_units))[0]


def _break_priority(character: str) -> int:
    if character in "。！？!?":
        return 4
    if character in "；;：:":
        return 3
    if character in "，,、":
        return 2
    if character.isspace():
        return 1
    return 0


def _merge_chunks_for_minimum_duration(
    chunks: list[str], duration_ms: int, min_duration_ms: int
) -> list[str]:
    result = list(chunks)
    while len(result) > 1:
        timings = _allocate_cue_times(result, 0, duration_ms)
        short_index = next(
            (index for index, (start, end) in enumerate(timings) if end - start < min_duration_ms),
            None,
        )
        if short_index is None:
            break
        if short_index == 0:
            merge_at = 0
        elif short_index == len(result) - 1:
            merge_at = short_index - 1
        else:
            previous_width = display_units(
                _join_chunks(result[short_index - 1], result[short_index])
            )
            next_width = display_units(_join_chunks(result[short_index], result[short_index + 1]))
            merge_at = short_index - 1 if previous_width <= next_width else short_index
        result[merge_at : merge_at + 2] = [_join_chunks(result[merge_at], result[merge_at + 1])]
    return result


def _join_chunks(first: str, second: str) -> str:
    first_character = first[-1:]
    second_character = second[:1]
    separator = (
        " "
        if first_character.isalnum()
        and second_character.isalnum()
        and (first_character.isascii() or second_character.isascii())
        else ""
    )
    return f"{first}{separator}{second}"


def _allocate_cue_times(
    chunks: list[str],
    start_ms: int,
    end_ms: int,
    *,
    min_duration_ms: int = 0,
    max_duration_ms: int | None = None,
) -> list[tuple[int, int]]:
    weights = [spoken_weight(chunk) for chunk in chunks]
    total_weight = sum(weights)
    duration_ms = end_ms - start_ms
    boundaries = [start_ms]
    cumulative = 0.0
    constraints_are_feasible = duration_ms >= len(chunks) * min_duration_ms and (
        max_duration_ms is None or duration_ms <= len(chunks) * max_duration_ms
    )
    for index, weight in enumerate(weights[:-1], start=1):
        cumulative += weight
        boundary = start_ms + round(duration_ms * cumulative / total_weight)
        if constraints_are_feasible:
            remaining = len(chunks) - index
            lower_bound = boundaries[-1] + min_duration_ms
            if max_duration_ms is not None:
                lower_bound = max(lower_bound, end_ms - remaining * max_duration_ms)
            upper_bound = end_ms - remaining * min_duration_ms
            if max_duration_ms is not None:
                upper_bound = min(upper_bound, boundaries[-1] + max_duration_ms)
            boundary = min(max(boundary, lower_bound), upper_bound)
        boundaries.append(boundary)
    boundaries.append(end_ms)
    return list(zip(boundaries, boundaries[1:], strict=False))


def parse_srt(content: str) -> list[dict]:
    normalized = content.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise ValueError("SRT 内容不能为空")
    if len(normalized) > MAX_SRT_CHARACTERS:
        raise ValueError("SRT 内容过大，最多支持 2,000,000 个字符")

    parsed: list[dict] = []
    for block_number, block in enumerate(re.split(r"\n\s*\n", normalized), start=1):
        lines = [line.rstrip() for line in block.split("\n")]
        if not lines:
            continue
        timing_line_index = 0 if "-->" in lines[0] else 1
        if timing_line_index >= len(lines):
            raise ValueError(f"第 {block_number} 个字幕块缺少时间轴")
        timing_match = _TIMING_PATTERN.match(lines[timing_line_index].strip())
        if not timing_match:
            raise ValueError(f"第 {block_number} 个字幕块时间轴格式错误")
        start_ms = _parse_timestamp(timing_match.group("start"), block_number)
        end_ms = _parse_timestamp(timing_match.group("end"), block_number)
        if end_ms <= start_ms:
            raise ValueError(f"第 {block_number} 个字幕块结束时间必须晚于开始时间")
        text = "\n".join(lines[timing_line_index + 1 :]).strip()
        if not text:
            raise ValueError(f"第 {block_number} 个字幕块文本不能为空")
        if parsed and start_ms < parsed[-1]["end_ms"]:
            raise ValueError(f"第 {block_number} 个字幕块与上一条字幕重叠")
        parsed.append({"start_ms": start_ms, "end_ms": end_ms, "text": text})

    if not parsed:
        raise ValueError("没有解析到有效的 SRT 字幕")
    return parsed


def import_srt(session: Session, project: Project, content: str) -> dict:
    parsed = parse_srt(content)
    cue_values = [
        {
            "id": f"{project.id}:sub_{index:04d}",
            "source_segment_id": "imported_srt",
            "cue_index": index,
            **item,
        }
        for index, item in enumerate(parsed, start=1)
    ]
    changed = replace_project_cues(session, project.id, cue_values)

    base_dir = project_dir(get_settings().workspace_dir, project.id)
    ensure_project_dirs(base_dir)
    output_path = base_dir / "subtitles" / "imported.srt"
    temp_path = output_path.with_suffix(".srt.tmp")
    temp_path.write_text(content.lstrip("\ufeff"), encoding="utf-8")
    temp_path.replace(output_path)
    return {
        "count": len(cue_values),
        "start_ms": cue_values[0]["start_ms"],
        "end_ms": cue_values[-1]["end_ms"],
        "changed": changed,
        "path": str(output_path),
        "cues": list_project_cues(session, project.id),
    }


def replace_project_cues(session: Session, project_id: str, cue_values: list[dict]) -> bool:
    existing = list_project_cues(session, project_id)
    comparable_existing = [
        {
            "id": item["id"],
            "source_segment_id": item["source_segment_id"],
            "cue_index": item["cue_index"],
            "start_ms": item["start_ms"],
            "end_ms": item["end_ms"],
            "text": item["text"],
        }
        for item in existing
    ]
    if comparable_existing == cue_values:
        return False

    scenes = list(
        session.exec(select(VisualScene).where(VisualScene.project_id == project_id)).all()
    )
    locked_indexes = [
        scene.scene_index
        for scene in scenes
        if scene.locked_text or scene.locked_audio or scene.locked_visual
    ]
    if locked_indexes:
        indexes = ", ".join(str(index) for index in sorted(locked_indexes))
        raise ValueError(f"Scene {indexes} is locked; unlock it before replacing subtitles")
    session.exec(delete(SceneAssignment).where(SceneAssignment.project_id == project_id))
    session.exec(
        delete(GeneratedImageVariant).where(GeneratedImageVariant.project_id == project_id)
    )
    session.exec(delete(SceneRevision).where(SceneRevision.project_id == project_id))
    session.exec(delete(VisualScene).where(VisualScene.project_id == project_id))
    session.exec(delete(SubtitleCue).where(SubtitleCue.project_id == project_id))
    now = utc_now_iso()
    for value in cue_values:
        session.add(SubtitleCue(project_id=project_id, created_at=now, updated_at=now, **value))
    session.commit()
    return True


def list_project_cues(session: Session, project_id: str) -> list[dict]:
    cues = session.exec(
        select(SubtitleCue)
        .where(SubtitleCue.project_id == project_id)
        .order_by(SubtitleCue.start_ms, SubtitleCue.cue_index)
    ).all()
    return [
        {
            "id": cue.id,
            "project_id": cue.project_id,
            "source_segment_id": cue.source_segment_id,
            "cue_index": cue.cue_index,
            "start_ms": cue.start_ms,
            "end_ms": cue.end_ms,
            "text": cue.text,
        }
        for cue in cues
    ]


def _parse_timestamp(value: str, block_number: int) -> int:
    match = _TIMESTAMP_PATTERN.match(value)
    if not match:
        raise ValueError(f"第 {block_number} 个字幕块时间戳格式错误：{value}")
    return (
        int(match.group("hours")) * 3_600_000
        + int(match.group("minutes")) * 60_000
        + int(match.group("seconds")) * 1000
        + int(match.group("milliseconds"))
    )
