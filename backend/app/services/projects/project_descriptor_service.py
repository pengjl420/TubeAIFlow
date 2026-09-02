from app.config import get_settings
from app.infrastructure.atomic_files import write_json_atomic
from app.infrastructure.project_layout import (
    get_project_work_dir,
    load_project_config,
    load_project_config_model,
)
from app.models.project import Project


PROJECT_FORMAT_VERSION = 1


def write_project_descriptor(project: Project) -> None:
    config = load_project_config(project)
    core = load_project_config_model(project)
    root = get_project_work_dir(project, get_settings().workspace_dir)
    write_json_atomic(
        root / "project.json",
        {
            "format_version": PROJECT_FORMAT_VERSION,
            "product": "TubeAiFolw",
            "project": {
                "id": project.id,
                "name": project.name,
                "status": project.status,
                "root_path": str(root),
                "source_language": core.voice_language,
                "script_path": project.script_raw_path,
                "fps": core.fps,
                "width": core.width,
                "height": core.height,
                "aspect_ratio": core.aspect_ratio,
                "locked": core.locked,
                "created_at": project.created_at,
                "updated_at": project.updated_at,
            },
            "settings": {
                key: value
                for key, value in config.items()
                if not key.lower().endswith(("_api_key", "_token", "_secret", "_password"))
            },
        },
    )
