import json
from pathlib import Path

from sqlmodel import Session, select

from app.config import get_settings
from app.models.project import Project
from app.models.segment import Segment
from app.utils.project_paths import ensure_project_dirs, get_output_stem, get_project_work_dir


def save_empty_translation(session: Session, project: Project) -> Path:
    segments = session.exec(
        select(Segment)
        .where(Segment.project_id == project.id)
        .order_by(Segment.segment_index)
    ).all()
    data = [
        {
            "segment_id": segment.segment_id,
            "text_zh": segment.text_zh,
            "text_en": segment.text_en or "",
        }
        for segment in segments
    ]
    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(base_dir)
    translation_dir = base_dir / "translation"
    translation_dir.mkdir(parents=True, exist_ok=True)
    output_path = translation_dir / f"{get_output_stem(project)}_translation.json"
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path
