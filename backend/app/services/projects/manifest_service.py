import json
from datetime import datetime
from pathlib import Path

from app.config import get_settings
from app.models.project import Project
from app.infrastructure.project_layout import (
    ensure_project_dirs,
    get_final_srt_path,
    get_final_fcpxml_path,
    get_final_premiere_xml_path,
    get_final_prproj_path,
    get_final_video_path,
    get_output_stem,
    get_project_work_dir,
)


def create_manifest(project: Project) -> Path:
    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(base_dir)
    stem = get_output_stem(project)
    manifest = {
        "project_id": project.id,
        "name": project.name,
        "status": project.status,
        "created_at": project.created_at,
        "exported_at": datetime.utcnow().isoformat(),
        "paths": {
            "script_raw": project.script_raw_path,
            "script_clean": project.script_clean_path,
            "reference_audio": project.reference_audio_path,
            "audio": str(base_dir / "audio"),
            "subtitles": str(base_dir / "subtitles"),
            "final_srt": str(get_final_srt_path(project, get_settings().workspace_dir)),
            "final_video": str(get_final_video_path(project, get_settings().workspace_dir)),
            "final_fcpxml": str(get_final_fcpxml_path(project, get_settings().workspace_dir)),
            "final_premiere_xml": str(
                get_final_premiere_xml_path(project, get_settings().workspace_dir)
            ),
            "final_prproj": str(get_final_prproj_path(project, get_settings().workspace_dir)),
            "timeline": str(base_dir / "timeline" / f"{stem}_timeline.json"),
            "selected_videos": str(base_dir / "video" / "selected_videos.json"),
        },
    }
    output_path = base_dir / f"{stem}_manifest.json"
    output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path
