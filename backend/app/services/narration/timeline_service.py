import json
from pathlib import Path

from sqlmodel import Session, select

from app.config import get_settings
from app.models.project import Project
from app.models.narration import Segment
from app.infrastructure.project_layout import ensure_project_dirs, get_output_stem, get_project_work_dir


def build_timeline(session: Session, project: Project, gap_seconds: float = 0.0) -> dict:
    if gap_seconds < 0:
        raise ValueError("Timeline gap cannot be negative")
    segments = session.exec(
        select(Segment)
        .where(Segment.project_id == project.id)
        .order_by(Segment.segment_index)
    ).all()
    current = 0.0
    timeline_segments = []
    for segment in segments:
        if segment.duration is None:
            raise ValueError(f"Segment {segment.segment_id} has no audio duration")
        start = current
        end = start + segment.duration
        segment.start_time = round(start, 3)
        segment.end_time = round(end, 3)
        session.add(segment)
        timeline_segments.append(
            {
                "segment_id": segment.segment_id,
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(segment.duration, 3),
                "text_zh": segment.text_zh,
            }
        )
        current = end + gap_seconds

    data = {"segments": timeline_segments}
    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(base_dir)
    timeline_dir = base_dir / "timeline"
    timeline_dir.mkdir(parents=True, exist_ok=True)
    (timeline_dir / f"{get_output_stem(project)}_timeline.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    session.commit()
    return data


def load_timeline(project: Project) -> dict:
    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    path = base_dir / "timeline" / f"{get_output_stem(project)}_timeline.json"
    if not path.exists():
        legacy_path = base_dir / "timeline" / "timeline.json"
        path = legacy_path if legacy_path.exists() else path
    if not Path(path).exists():
        raise ValueError("timeline.json does not exist")
    return json.loads(Path(path).read_text(encoding="utf-8"))
