import json
import logging
import threading

from sqlmodel import Session, select

from app.database import engine
from app.models.batch_item import BatchItem
from app.models.batch_job import BatchJob
from app.models.project import Project
from app.services import batch_service, generation_service
from app.utils.time_utils import utc_now_iso


logger = logging.getLogger(__name__)
_worker_thread: threading.Thread | None = None
_worker_lock = threading.Lock()
_wake_event = threading.Event()


def start_worker() -> None:
    global _worker_thread
    with _worker_lock:
        if _worker_thread and _worker_thread.is_alive():
            _wake_event.set()
            return
        _worker_thread = threading.Thread(target=_worker_loop, name="batch-worker", daemon=True)
        _worker_thread.start()
    _wake_event.set()


def wake_worker() -> None:
    start_worker()
    _wake_event.set()


def recover_and_start_worker() -> None:
    with Session(engine) as session:
        for item in session.exec(select(BatchItem).where(BatchItem.status == "running")).all():
            item.status = "pending"
            item.error_message = "后端重启，任务将从当前阶段重新执行"
            item.updated_at = utc_now_iso()
            session.add(item)
        for batch in session.exec(select(BatchJob).where(BatchJob.status == "running")).all():
            batch.status = "queued"
            batch.updated_at = utc_now_iso()
            session.add(batch)
        session.commit()
    start_worker()


def process_next_item() -> bool:
    with Session(engine) as session:
        batch = session.exec(
            select(BatchJob)
            .where(BatchJob.status.in_(["queued", "running"]))
            .order_by(BatchJob.created_at)
        ).first()
        if not batch:
            return False

        item = session.exec(
            select(BatchItem)
            .where(BatchItem.batch_id == batch.id, BatchItem.status == "pending")
            .order_by(BatchItem.order_index)
        ).first()
        if not item:
            _finish_batch(session, batch)
            return True

        now = utc_now_iso()
        batch.status = "running"
        batch.started_at = batch.started_at or now
        batch.updated_at = now
        item.status = "running"
        item.started_at = item.started_at or now
        item.error_message = None
        item.updated_at = now
        session.add(batch)
        session.add(item)
        session.commit()

        project = session.get(Project, item.project_id)
        if not project:
            _fail_item(session, batch, item, "项目不存在")
            return True

        config = _load_config(batch)

        def update_stage(stage: str) -> None:
            item.current_stage = stage
            item.updated_at = utc_now_iso()
            session.add(item)
            session.commit()

        try:
            generation_service.run_project_generation(
                session,
                project,
                item.current_stage,
                bool(config.get("include_video", True)),
                update_stage,
            )
        except Exception as exc:
            logger.exception("Batch item %s failed at stage %s", item.id, item.current_stage)
            _fail_item(session, batch, item, str(exc))
            return True

        item.status = "completed"
        item.current_stage = "completed"
        item.finished_at = utc_now_iso()
        item.updated_at = item.finished_at
        session.add(item)
        session.commit()
        session.expire_all()
        batch = session.get(BatchJob, batch.id)
        if batch:
            _update_batch_after_item(session, batch)
        return True


def _worker_loop() -> None:
    while True:
        _wake_event.wait(timeout=2)
        _wake_event.clear()
        while process_next_item():
            pass


def _fail_item(
    session: Session,
    batch: BatchJob,
    item: BatchItem,
    error: str,
) -> None:
    now = utc_now_iso()
    item.status = "failed"
    item.error_message = error[-4000:] or "生成失败"
    item.finished_at = now
    item.updated_at = now
    project = session.get(Project, item.project_id)
    if project:
        project.status = "failed"
        project.updated_at = now
        session.add(project)
    session.add(item)
    session.commit()
    session.expire_all()
    refreshed = session.get(BatchJob, batch.id)
    if not refreshed:
        return
    batch_service.refresh_counts(session, refreshed)
    config = _load_config(refreshed)
    if not bool(config.get("continue_on_error", True)):
        refreshed.status = "paused"
        refreshed.updated_at = now
        session.add(refreshed)
        session.commit()
        return
    _update_batch_after_item(session, refreshed)


def _update_batch_after_item(session: Session, batch: BatchJob) -> None:
    batch_service.refresh_counts(session, batch)
    pending = session.exec(
        select(BatchItem).where(BatchItem.batch_id == batch.id, BatchItem.status == "pending")
    ).first()
    if pending:
        if batch.status != "paused":
            batch.status = "running"
    else:
        batch.status = "completed_with_errors" if batch.failed else "completed"
        batch.finished_at = utc_now_iso()
    batch.updated_at = utc_now_iso()
    session.add(batch)
    session.commit()


def _finish_batch(session: Session, batch: BatchJob) -> None:
    batch_service.refresh_counts(session, batch)
    batch.status = "completed_with_errors" if batch.failed else "completed"
    batch.finished_at = utc_now_iso()
    batch.updated_at = batch.finished_at
    session.add(batch)
    session.commit()


def _load_config(batch: BatchJob) -> dict:
    try:
        data = json.loads(batch.config_json)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
