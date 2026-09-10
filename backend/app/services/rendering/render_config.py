from app.infrastructure.project_layout import load_project_config
from app.models.project import Project
from app.schemas.render import ProjectRenderConfig


def get_project_render_config(project: Project) -> ProjectRenderConfig:
    """Return validated render settings while accepting existing flat project configs."""
    project_config = load_project_config(project)
    raw = project_config.get("render")
    if not isinstance(raw, dict):
        raw = {}
    video = raw.get("video") if isinstance(raw.get("video"), dict) else {}
    policy = raw.get("policy") if isinstance(raw.get("policy"), dict) else {}
    return ProjectRenderConfig.model_validate({"video": video, "policy": policy})
