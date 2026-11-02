from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from PIL import Image
from sqlmodel import Session, select

from app.database import engine
from app.integrations.image_generation.seedream import (
    SeedreamClient,
    SeedreamResultUnknownError,
)
from app.models.visual_style import StyleTestRun
from app.services.visual_styles import style_asset_service, style_service
from app.shared.time import utc_now_iso


logger = logging.getLogger(__name__)
_worker_thread: threading.Thread | None = None
_worker_lock = threading.Lock()
_wake_event = threading.Event()


def _rows(run: StyleTestRun) -> list[dict]:
    try:
        values = json.loads(run.output_json or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return [dict(item) for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _save(session: Session, run: StyleTestRun, rows: list[dict]) -> None:
    run.output_json = json.dumps(rows, ensure_ascii=False, sort_keys=True)
    run.updated_at = utc_now_iso()
    session.add(run)
    session.commit()
    try:
        style_service.write_test_run_manifest(run)
    except OSError:
        logger.exception("Failed to write style test manifest for %s", run.id)


def _valid_image(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except (OSError, ValueError):
        return False


def _archive_completed_rows(session: Session, run: StyleTestRun, rows: list[dict]) -> None:
    for item in rows:
        if item.get("status") != "completed" or item.get("style_asset_id"):
            continue
        try:
            asset = style_asset_service.archive_style_test_candidate(
                session,
                run,
                Path(str(item["path"])),
                candidate_index=int(item.get("index") or 0),
            )
            item["style_asset_id"] = asset.id
        except (OSError, ValueError, LookupError):
            logger.exception("Failed to archive style test candidate for %s", run.id)


def recover_interrupted_runs(session: Session) -> int:
    """Recover only results that were atomically saved before shutdown.

    A submitting candidate without a valid local image is deliberately marked
    unknown. The provider may have accepted it, so requeueing could duplicate a
    paid generation.
    """

    runs = list(
        session.exec(select(StyleTestRun).where(StyleTestRun.status == "running")).all()
    )
    for run in runs:
        rows = _rows(run)
        has_unknown = False
        for item in rows:
            if item.get("status") != "submitting":
                continue
            path = Path(str(item.get("path") or ""))
            if _valid_image(path):
                item["status"] = "completed"
                item["error_code"] = None
                item["error_message"] = None
            else:
                has_unknown = True
                item["status"] = "unknown"
                item["error_code"] = "SEEDREAM_RESULT_UNKNOWN"
                item["error_message"] = (
                    "应用在远程请求期间中断，无法确认服务端是否已经生成；"
                    "为避免重复调用和重复计费，系统未自动重试"
                )
        completed = sum(item.get("status") == "completed" for item in rows)
        if has_unknown:
            run.status = "unknown"
            run.error_code = "SEEDREAM_RESULT_UNKNOWN"
            run.error_message = "存在结果未知的候选，请确认后再手动创建新的生成任务"
            run.finished_at = utc_now_iso()
        elif completed >= run.candidate_count:
            run.status = "completed"
            run.finished_at = utc_now_iso()
        else:
            run.status = "queued"
            run.started_at = None
        _archive_completed_rows(session, run, rows)
        _save(session, run, rows)
    return len(runs)


def process_next_run() -> bool:
    with Session(engine) as session:
        run = session.exec(
            select(StyleTestRun)
            .where(StyleTestRun.status == "queued")
            .order_by(StyleTestRun.created_at)
        ).first()
        if not run:
            return False

        rows = _rows(run)
        if not rows:
            run.status = "failed"
            run.error_code = "STYLE_TEST_STATE_INVALID"
            run.error_message = "风格测试候选状态缺失"
            run.finished_at = utc_now_iso()
            _save(session, run, rows)
            return True

        run.status = "running"
        run.started_at = run.started_at or utc_now_iso()
        run.error_code = None
        run.error_message = None
        _save(session, run, rows)

        provider_prompt = run.compiled_prompt
        if run.compiled_negative_prompt:
            provider_prompt += f"\n\nAVOID:\n{run.compiled_negative_prompt}"
        client = SeedreamClient(model_id=run.model_id)
        total_seconds = sum(
            float(item.get("generation_seconds") or 0)
            for item in rows
            if item.get("status") == "completed"
        )

        for item in rows:
            if item.get("status") == "completed":
                continue
            if item.get("status") != "queued":
                run.status = "unknown"
                run.error_code = "SEEDREAM_RESULT_UNKNOWN"
                run.error_message = "候选状态无法安全重试"
                run.finished_at = utc_now_iso()
                _save(session, run, rows)
                return True

            item["status"] = "submitting"
            item["error_code"] = None
            item["error_message"] = None
            _save(session, run, rows)
            try:
                seconds = client.generate(
                    prompt=provider_prompt,
                    output_path=Path(str(item["path"])),
                )
            except SeedreamResultUnknownError as exc:
                logger.warning("Style test %s result is unknown: %s", run.id, exc)
                item["status"] = "unknown"
                item["error_code"] = exc.code
                item["error_message"] = str(exc)
                run.status = "unknown"
                run.error_code = exc.code
                run.error_message = str(exc)
                run.finished_at = utc_now_iso()
                _save(session, run, rows)
                return True
            except Exception as exc:
                logger.exception("Style test %s failed", run.id)
                item["status"] = "failed"
                item["error_code"] = getattr(exc, "code", "STYLE_TEST_GENERATION_FAILED")
                item["error_message"] = str(exc)[-4000:]
                run.status = "failed"
                run.error_code = item["error_code"]
                run.error_message = item["error_message"]
                run.finished_at = utc_now_iso()
                _save(session, run, rows)
                return True
            else:
                item["status"] = "completed"
                item["generation_seconds"] = seconds
                total_seconds += seconds
                run.generation_seconds = total_seconds
                _archive_completed_rows(session, run, rows)
                _save(session, run, rows)

        run.status = "completed"
        run.finished_at = utc_now_iso()
        _archive_completed_rows(session, run, rows)
        _save(session, run, rows)
        return True


def wake_worker() -> None:
    global _worker_thread
    with _worker_lock:
        if not _worker_thread or not _worker_thread.is_alive():
            _worker_thread = threading.Thread(
                target=_worker_loop,
                name="style-test-worker",
                daemon=True,
            )
            _worker_thread.start()
    _wake_event.set()


def recover_and_start_worker() -> None:
    with Session(engine) as session:
        recover_interrupted_runs(session)
    wake_worker()


def _worker_loop() -> None:
    while True:
        _wake_event.wait(timeout=2)
        _wake_event.clear()
        try:
            while process_next_run():
                pass
        except Exception:
            logger.exception("Style test queue failed; it will retry")

