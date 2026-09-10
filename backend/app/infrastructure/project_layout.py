import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from app.models.project import Project
from app.infrastructure.file_storage import project_dir
from app.infrastructure.serialization import load_json_object
from app.schemas.project_config import ProjectConfig


_PROJECT_CONFIG_OVERRIDES: ContextVar[dict[str, dict] | None] = ContextVar(
    "tubeaifolw_project_config_overrides", default=None
)


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


def get_final_fcpxml_path(project: Project, workspace_dir: Path) -> Path:
    return get_project_output_dir(project, workspace_dir) / f"{get_output_stem(project)}.fcpxml"


def get_final_premiere_xml_path(project: Project, workspace_dir: Path) -> Path:
    return (
        get_project_output_dir(project, workspace_dir) / f"{get_output_stem(project)}.premiere.xml"
    )


def get_final_prproj_path(project: Project, workspace_dir: Path) -> Path:
    return get_project_output_dir(project, workspace_dir) / f"{get_output_stem(project)}.prproj"


def ensure_project_dirs(base_dir: Path) -> None:
    for relative in [
        "input",
        "input/source",
        "segments",
        "audio/segments",
        "subtitles",
        "timeline",
        "logs",
        "scenes",
        "assets/local",
        "assets/stock",
        "assets/generated",
        "assets/imported",
        "cache",
        "storyboard",
        "media/generated_images",
        "media",
        "renders/scenes",
        "renders/preview",
        "renders/final",
        "reports",
        "exports",
        ".backup",
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
    overrides = _PROJECT_CONFIG_OVERRIDES.get()
    if overrides and project.id in overrides:
        return dict(overrides[project.id])
    return load_json_object(project.config_json)


def load_project_config_model(project: Project) -> ProjectConfig:
    return ProjectConfig.model_validate(load_project_config(project))


@contextmanager
def use_project_config_snapshot(project_id: str, values: dict | None) -> Iterator[None]:
    current = dict(_PROJECT_CONFIG_OVERRIDES.get() or {})
    if values is not None:
        current[project_id] = dict(values)
    token = _PROJECT_CONFIG_OVERRIDES.set(current or None)
    try:
        yield
    finally:
        _PROJECT_CONFIG_OVERRIDES.reset(token)
