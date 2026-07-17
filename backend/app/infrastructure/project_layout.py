import json
import re
from pathlib import Path

from app.models.project import Project
from app.infrastructure.file_storage import project_dir


def get_project_output_dir(project: Project, workspace_dir: Path) -> Path:
    if project.output_dir:
        return Path(project.output_dir).expanduser().resolve()
    return project_dir(workspace_dir, project.id).resolve()


def get_project_work_dir(project: Project, workspace_dir: Path) -> Path:
    if not project.output_dir:
        return project_dir(workspace_dir, project.id).resolve()
    return get_project_output_dir(project, workspace_dir) / get_project_directory_name(project)


def get_legacy_project_work_dir(project: Project, workspace_dir: Path) -> Path:
    """Locate files produced before work data was separated from final exports."""
    return get_project_output_dir(project, workspace_dir) / get_output_stem(project)


def get_final_audio_path(project: Project, workspace_dir: Path) -> Path:
    return get_project_output_dir(project, workspace_dir) / f"{get_output_stem(project)}.wav"


def get_final_srt_path(project: Project, workspace_dir: Path) -> Path:
    return get_project_output_dir(project, workspace_dir) / f"{get_output_stem(project)}.srt"


def get_final_video_path(project: Project, workspace_dir: Path) -> Path:
    return get_project_output_dir(project, workspace_dir) / f"{get_output_stem(project)}.mp4"


def ensure_project_dirs(base_dir: Path) -> None:
    for relative in [
        "input",
        "segments",
        "audio/segments",
        "subtitles",
        "timeline",
        "logs",
        "storyboard",
        "media",
        "renders/scenes",
        "reports",
        "video/temp",
    ]:
        (base_dir / relative).mkdir(parents=True, exist_ok=True)


def get_output_stem(project: Project) -> str:
    config = load_project_config(project)
    configured = str(config.get("output_filename") or "").strip()
    return safe_filename_stem(configured or project.name or project.id)


def get_project_directory_name(project: Project) -> str:
    config = load_project_config(project)
    configured = str(config.get("project_directory_name") or "").strip()
    return safe_filename_stem(configured or project.name or project.id)


def safe_filename_stem(value: str) -> str:
    stem = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", value, flags=re.UNICODE).strip("._- ")
    return stem[:80] or "output"


def load_project_config(project: Project) -> dict:
    if not project.config_json:
        return {}
    try:
        data = json.loads(project.config_json)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
