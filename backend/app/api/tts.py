import json

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_session
from app.models.segment import Segment
from app.services import project_service, task_control, tts_service
from app.utils.project_paths import get_project_work_dir


router = APIRouter(tags=["tts"])


@router.post("/projects/{project_id}/tts/start")
def start_tts(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    try:
        with task_control.controlled(project_id, "tts"):
            data = tts_service.generate_project_tts(session, project)
        return {"success": True, "data": data}
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": str(exc)},
        ) from exc


@router.post("/projects/{project_id}/tts/retry-failed")
def retry_failed(project_id: str, session: Session = Depends(get_session)) -> dict:
    return start_tts(project_id, session)


@router.post("/projects/{project_id}/tts/regenerate/{segment_id}")
def regenerate_segment(project_id: str, segment_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    segment = session.exec(
        select(Segment).where(
            Segment.project_id == project_id,
            Segment.segment_id == segment_id,
        )
    ).first()
    if not segment:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Segment not found"})
    try:
        project = project_service.ensure_output_filename(session, project)
        with task_control.controlled(project_id, "tts"):
            data = tts_service.regenerate_segment_tts(session, project, segment)
        return {"success": True, "data": data}
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": str(exc)},
        ) from exc


@router.get("/projects/{project_id}/tts/status")
def tts_status(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    segments = session.exec(
        select(Segment)
        .where(Segment.project_id == project_id)
        .order_by(Segment.segment_index)
    ).all()
    progress = _read_progress(project)
    live_segments = _build_live_segments(project, segments, progress)
    data = {
        "total": len(segments),
        "completed": sum(1 for item in live_segments if item["status"] == "completed"),
        "failed": sum(1 for item in live_segments if item["status"] == "failed"),
        "pending": sum(1 for item in live_segments if item["status"] in {"pending", "tts_running"}),
        "project_status": project.status,
        "progress": progress,
        "segments": live_segments,
    }
    return {"success": True, "data": data}


def _read_progress(project) -> dict | None:
    progress_path = get_project_work_dir(project, get_settings().workspace_dir) / "logs" / "tts_progress.json"
    if not progress_path.is_file():
        return None
    try:
        return json.loads(progress_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _build_live_segments(project, segments: list[Segment], progress: dict | None) -> list[dict]:
    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    result_by_id = {}
    if progress:
        result_by_id = {
            item.get("segment_id"): item
            for item in progress.get("segment_results", [])
            if item.get("segment_id")
        }
    current_segment_id = progress.get("current_segment_id") if progress else None
    batch_segment_ids = set(progress.get("segment_ids", [])) if progress else set()
    progress_running = progress.get("status") == "running" if progress else False

    live_segments = []
    for segment in segments:
        item = {
            "segment_id": segment.segment_id,
            "status": segment.status,
            "audio_path": segment.audio_path,
            "duration": segment.duration,
            "error_message": segment.error_message,
            "updated_at": segment.updated_at,
        }
        result = result_by_id.get(segment.segment_id)
        output_path = base_dir / "audio" / "segments" / f"{segment.segment_id}.wav"
        if result:
            if result.get("success"):
                item["status"] = "completed"
                item["audio_path"] = str(output_path) if output_path.exists() else segment.audio_path
                if output_path.exists():
                    item["updated_at"] = str(output_path.stat().st_mtime_ns)
                item["error_message"] = None
            else:
                item["status"] = "failed"
                item["error_message"] = result.get("error") or "TTS engine did not create an audio file"
        elif segment.segment_id == current_segment_id:
            item["status"] = "tts_running"
            item["error_message"] = None
        elif progress_running and segment.segment_id in batch_segment_ids:
            item["status"] = "pending"
            item["error_message"] = None
        live_segments.append(item)
    return live_segments
