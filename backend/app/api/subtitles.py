from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.database import get_session
from app.services import project_service, srt_service, timeline_service, translate_service


router = APIRouter(tags=["subtitles"])


@router.post("/projects/{project_id}/timeline")
def create_timeline(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    return {"success": True, "data": timeline_service.build_timeline(session, project)}


@router.post("/projects/{project_id}/subtitles/zh")
def create_zh_srt(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    try:
        project = project_service.ensure_output_filename(session, project)
        segments = timeline_service.build_timeline(session, project)["segments"]
        zh_path, zh_cues = srt_service.create_full_srt_with_cues(project, _load_segments_for_srt(session, project.id))
        translation_path, translations = translate_service.translate_subtitle_cues_to_english(project, zh_cues)
        en_path = srt_service.create_english_srt_from_chinese_cues(project, zh_cues, translations)
        project.status = "en_subtitle_created"
        project.updated_at = datetime.utcnow().isoformat()
        session.add(project)
        session.commit()
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
    return {
        "success": True,
        "data": {
            "zh_path": str(zh_path),
            "en_path": str(en_path),
            "translation_path": str(translation_path),
            "segments": len(segments),
        },
    }


@router.post("/projects/{project_id}/subtitles/en")
def create_en_srt(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    try:
        project = project_service.ensure_output_filename(session, project)
        timeline_service.build_timeline(session, project)
        zh_path, zh_cues = srt_service.create_full_srt_with_cues(project, _load_segments_for_srt(session, project.id))
        translation_path, translations = translate_service.translate_subtitle_cues_to_english(project, zh_cues)
        srt_path = srt_service.create_english_srt_from_chinese_cues(project, zh_cues, translations)
        project.status = "en_subtitle_created"
        project.updated_at = datetime.utcnow().isoformat()
        session.add(project)
        session.commit()
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
    return {
        "success": True,
        "data": {
            "path": str(srt_path),
            "translation_path": str(translation_path),
        },
    }


def _load_segments_for_srt(session: Session, project_id: str):
    from sqlmodel import select

    from app.models.segment import Segment

    return session.exec(
        select(Segment)
        .where(Segment.project_id == project_id)
        .order_by(Segment.segment_index)
    ).all()
