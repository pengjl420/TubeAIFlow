from app.config import get_settings
from app.infrastructure.atomic_files import write_json_atomic
from app.infrastructure.project_layout import get_project_work_dir, load_project_config
from app.models.project import Project


PROJECT_FORMAT_VERSION = 1


def write_project_descriptor(project: Project) -> None:
    config = load_project_config(project)
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
                "source_language": config.get("voice_language", "zh-CN"),
                "script_path": project.script_raw_path,
                "fps": int(config.get("fps", 30)),
                "width": int(config.get("width", 1920)),
                "height": int(config.get("height", 1080)),
                "aspect_ratio": str(config.get("aspect_ratio", "16:9")),
                "locked": bool(config.get("locked", False)),
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
