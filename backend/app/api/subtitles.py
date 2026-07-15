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
def create_zh_srt(
    project_id: str,
    include_translation: bool = True,
    session: Session = Depends(get_session),
) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail={"success": False, "error": "Project not found"})
    try:
        project = project_service.ensure_output_filename(session, project)
        segments = timeline_service.build_timeline(session, project)["segments"]
        zh_path, zh_cues = srt_service.create_full_srt_with_cues(project, _load_segments_for_srt(session, project.id))
        translation_path = None
        translated_path = None
        target_language = None
        if include_translation:
            translation_path, translations, target_language = translate_service.translate_subtitle_cues(project, zh_cues)
            translated_path = srt_service.create_translated_srt(
                project, zh_cues, translations, target_language
            )
            project.status = f"{target_language}_subtitle_created"
        else:
            project.status = "zh_subtitle_created"
        project.updated_at = datetime.utcnow().isoformat()
        session.add(project)
        session.commit()
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail={"success": False, "error": str(exc)}) from exc
    return {
        "success": True,
        "data": {
            "zh_path": str(zh_path),
            "en_path": str(translated_path) if target_language == "en" else None,
            "translated_path": str(translated_path) if translated_path else None,
            "target_language": target_language,
            "translation_path": str(translation_path) if translation_path else None,
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
