from sqlmodel import Session, select

from app.infrastructure.serialization import dump_json
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.models.task import TaskRun
from app.services.image_generation import image_generation_service
from app.services.rendering import scene_renderer
from app.services.storyboard import scene_workspace_service
from app.shared.time import utc_now_iso
from app.workflows.engine import StageChanged


SCENE_IMAGE_WORKFLOW_ID = "scene_image_regeneration"
SCENE_PREVIEW_WORKFLOW_ID = "scene_preview_render"


def run_scene_image_job(
    session: Session, project: Project, current_stage: str,
    _include_video: bool, on_stage_changed: StageChanged,
) -> None:
    task = _running_task(session, project.id, SCENE_IMAGE_WORKFLOW_ID)
    if current_stage != "generate":
        raise ValueError(f"Unknown Scene image Job stage: {current_stage}")
    task.progress = 5
    session.add(task)
    session.commit()
    result = image_generation_service.regenerate_scene_images(
        session,
        project,
        _scene_id(task),
        regeneration_id=task.id,
    )
    scene = session.get(VisualScene, _scene_id(task))
    if scene:
        scene_workspace_service.invalidate_scene_outputs(project, scene)
    task.result_json = dump_json(result)
    task.progress = 100
    task.updated_at = utc_now_iso()
    session.add(task)
    session.commit()
    on_stage_changed("completed")


def run_scene_preview_job(
    session: Session, project: Project, current_stage: str,
    _include_video: bool, on_stage_changed: StageChanged,
) -> None:
    task = _running_task(session, project.id, SCENE_PREVIEW_WORKFLOW_ID)
    if current_stage != "render":
        raise ValueError(f"Unknown Scene preview Job stage: {current_stage}")
    scene = session.get(VisualScene, _scene_id(task))
    if not scene or scene.project_id != project.id:
        raise ValueError("Scene not found")
    task.progress = 10
    session.add(task)
    session.commit()
    result = scene_renderer.render_scene(session, project, scene)
    task.result_json = dump_json(result)
    task.progress = 100
    task.updated_at = utc_now_iso()
    session.add(task)
    session.commit()
    on_stage_changed("completed")


def _running_task(session: Session, project_id: str, workflow: str) -> TaskRun:
    task = session.exec(
        select(TaskRun).where(
            TaskRun.project_id == project_id,
            TaskRun.workflow == workflow,
            TaskRun.status == "running",
        )
    ).first()
    if not task:
        raise RuntimeError("Running Job record not found")
    return task


def _scene_id(task: TaskRun) -> str:
    if not task.scene_id:
        raise ValueError("Scene Job is missing scene_id")
    return task.scene_id
