from sqlmodel import Session, select

from app.infrastructure.serialization import dump_json
from app.models.project import Project
from app.models.task import TaskRun
from app.services.quality import qa_service
from app.services.visual_enrichment import asset_library_service
from app.shared.time import utc_now_iso
from app.workflows.engine import StageChanged


ASSET_SCAN_WORKFLOW_ID = "asset_library_scan"
QUALITY_CHECK_WORKFLOW_ID = "quality_check"


def run_asset_scan_job(
    session: Session,
    project: Project,
    current_stage: str,
    _include_video: bool,
    on_stage_changed: StageChanged,
) -> None:
    if current_stage != "scan":
        raise ValueError(f"Unknown asset scan Job stage: {current_stage}")
    task = _running_task(session, project.id, ASSET_SCAN_WORKFLOW_ID)
    _progress(session, task, 5)
    result = asset_library_service.scan_project_directory(session, project)
    _finish(session, task, result)
    on_stage_changed("completed")


def run_quality_check_job(
    session: Session,
    project: Project,
    current_stage: str,
    _include_video: bool,
    on_stage_changed: StageChanged,
) -> None:
    if current_stage != "analyze":
        raise ValueError(f"Unknown quality check Job stage: {current_stage}")
    task = _running_task(session, project.id, QUALITY_CHECK_WORKFLOW_ID)
    _progress(session, task, 5)
    result = qa_service.run_quality_check(session, project)
    _finish(session, task, result)
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


def _progress(session: Session, task: TaskRun, value: float) -> None:
    task.progress = value
    task.updated_at = utc_now_iso()
    session.add(task)
    session.commit()


def _finish(session: Session, task: TaskRun, result: dict) -> None:
    task.result_json = dump_json(result)
    task.progress = 100
    task.updated_at = utc_now_iso()
    session.add(task)
    session.commit()
