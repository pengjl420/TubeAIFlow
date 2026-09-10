from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, select

from app.config import get_settings
from app.infrastructure.project_layout import get_project_output_dir
from app.models.narration import Segment
from app.models.project import Project


GIB = 1024**3
RESERVED_FREE_BYTES = 2 * GIB


class InsufficientDiskSpaceError(RuntimeError):
    code = "INSUFFICIENT_DISK_SPACE"


@dataclass(frozen=True, slots=True)
class DiskPreflight:
    path: Path
    stage: str
    estimated_duration_seconds: float
    required_bytes: int
    available_bytes: int
    reserved_bytes: int = RESERVED_FREE_BYTES

    @property
    def sufficient(self) -> bool:
        return self.available_bytes >= self.required_bytes + self.reserved_bytes


def check_project_disk_space(
    session: Session,
    project: Project,
    stage: str,
) -> DiskPreflight:
    """Reject expensive work before it can fill the project volume."""
    output_dir = get_project_output_dir(project, get_settings().workspace_dir)
    disk_path = _existing_parent(output_dir)
    duration = _estimated_duration_seconds(session, project)
    required = _estimated_stage_bytes(stage, duration)
    available = shutil.disk_usage(disk_path).free
    result = DiskPreflight(
        path=disk_path,
        stage=stage,
        estimated_duration_seconds=duration,
        required_bytes=required,
        available_bytes=available,
    )
    if not result.sufficient:
        required_gib = (required + result.reserved_bytes) / GIB
        available_gib = available / GIB
        raise InsufficientDiskSpaceError(
            f"磁盘空间不足：阶段 {stage} 预计至少需要 {required_gib:.1f} GB，"
            f"当前仅剩 {available_gib:.1f} GB（{disk_path}）"
        )
    return result


def _estimated_duration_seconds(session: Session, project: Project) -> float:
    durations = session.exec(
        select(Segment.duration).where(
            Segment.project_id == project.id,
            Segment.duration.is_not(None),
        )
    ).all()
    measured = sum(max(0.0, float(value)) for value in durations if value is not None)
    if measured > 0:
        return measured
    if project.script_clean_path:
        path = Path(project.script_clean_path)
        try:
            characters = len(path.read_text(encoding="utf-8"))
        except OSError:
            characters = 0
        if characters:
            return max(60.0, characters / 260 * 60)
    return 60.0


def _estimated_stage_bytes(stage: str, duration_seconds: float) -> int:
    # Intermediate H.264 renders can coexist with the visual track and final
    # output. A conservative 12 Mbps working bitrate prevents late failures.
    video_bytes = duration_seconds * 12_000_000 / 8
    if stage in {"scene_render", "visual_track", "final_render", "video", "render"}:
        return max(1 * GIB, round(video_bytes * 2.5))
    if stage in {"image_generation", "generate"}:
        image_count = max(1, duration_seconds / 10)
        return max(1 * GIB, round(image_count * 6 * 1024**2))
    if stage in {"tts", "audio_merge", "subtitles"}:
        pcm_bytes = duration_seconds * 48_000 * 2 * 2
        return max(512 * 1024**2, round(pcm_bytes * 2.0))
    return 512 * 1024**2


def _existing_parent(path: Path) -> Path:
    candidate = path.expanduser().resolve()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate
