import re
from pathlib import Path

from sqlalchemy import delete
from sqlmodel import Session, select

from app.config import get_settings
from app.infrastructure.file_storage import project_dir
from app.infrastructure.project_layout import ensure_project_dirs
from app.models.narration import Segment
from app.models.project import Project
from app.models.storyboard import SubtitleCue, VisualScene
from app.shared.time import utc_now_iso


_TIMESTAMP_PATTERN = re.compile(
    r"^(?P<hours>\d{1,3}):(?P<minutes>[0-5]\d):(?P<seconds>[0-5]\d)[,.](?P<milliseconds>\d{3})$"
)
_TIMING_PATTERN = re.compile(r"^(?P<start>\S+)\s*-->\s*(?P<end>\S+)(?:\s+.*)?$")
MAX_SRT_CHARACTERS = 2_000_000


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


def sync_segment_cues(session: Session, project: Project, segments: list[Segment]) -> bool:
    current_ms = 0
    cue_values = []
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
        cue_values.append(
            {
                "id": f"{project.id}:sub_{segment.segment_id}_01",
                "source_segment_id": segment.id,
                "cue_index": 1,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "text": segment.text.strip(),
            }
        )
        current_ms = end_ms
    return replace_project_cues(session, project.id, cue_values)


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
