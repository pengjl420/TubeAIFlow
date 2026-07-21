import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session

from app.config import get_settings
from app.database import get_session
from app.infrastructure.file_storage import ensure_inside_any, project_dir
from app.infrastructure.project_layout import (
    get_final_audio_path,
    get_final_fcpxml_path,
    get_final_srt_path,
    get_final_video_path,
    get_legacy_project_work_dir,
    get_output_stem,
    get_project_output_dir,
    get_project_work_dir,
)
from app.services.projects import native_dialog_service, project_service


logger = logging.getLogger(__name__)
router = APIRouter(tags=["projects"])


class ScriptRequest(BaseModel):
    text: str


class OutputSettingsRequest(BaseModel):
    output_dir: str
    output_filename: str


class ProjectSettingsRequest(BaseModel):
    name: str
    output_dir: str
    output_filename: str = ""
    media_video_dir: str = ""
    include_video: bool = False
    video_mode: str | None = None
    semantic_review_mode: str | None = None
    video_output_format: str | None = project_service.VIDEO_OUTPUT_FCPXML
    tts_engine: str = project_service.DEFAULT_TTS_ENGINE
    reference_audio_text: str = ""
    voice_profile_id: str = ""
    storyboard_transition_enabled: bool = True
    segmentation_mode: str = project_service.SEGMENTATION_MODE_NEWLINE
    storyboard_mode: str = project_service.STORYBOARD_MODE_AI


class DirectoryPickerRequest(BaseModel):
    initial_path: str | None = None
    title: str = "选择文件夹"


def ok(data) -> dict:
    return {"success": True, "data": data}


def fail(message: str, status_code: int = 400) -> None:
    raise HTTPException(status_code=status_code, detail={"success": False, "error": message})


@router.get("/projects")
def list_projects(session: Session = Depends(get_session)) -> dict:
    return ok(project_service.list_projects(session))


@router.post("/projects")
def create_project(
    name: str = Form(...),
    reference_audio: UploadFile | None = File(None),
    output_dir: str = Form(r"D:\video_darft"),
    output_filename: str = Form(""),
    media_video_dir: str = Form(""),
    include_video: bool = Form(False),
    video_mode: str | None = Form(None),
    semantic_review_mode: str | None = Form(None),
    video_output_format: str | None = Form(project_service.VIDEO_OUTPUT_FCPXML),
    tts_engine: str = Form(project_service.DEFAULT_TTS_ENGINE),
    reference_audio_text: str = Form(""),
    voice_profile_id: str = Form(""),
    storyboard_transition_enabled: bool = Form(True),
    segmentation_mode: str = Form(project_service.SEGMENTATION_MODE_NEWLINE),
    storyboard_mode: str = Form(project_service.STORYBOARD_MODE_AI),
    session: Session = Depends(get_session),
) -> dict:
    if not name.strip():
        fail("Project name is required")
    if not voice_profile_id.strip() and reference_audio is None:
        fail("请选择已配置的系统音色")
    try:
        normalized_tts_engine = tts_engine.strip().lower()
        if normalized_tts_engine not in project_service.SUPPORTED_TTS_ENGINES:
            fail("Unsupported TTS engine")
        project = project_service.create_project(
            session,
            name.strip(),
        )
        project = project_service.update_project_settings(
            session,
            project,
            name.strip(),
            output_dir,
            output_filename,
            media_video_dir,
            normalized_tts_engine,
            reference_audio_text,
            include_video,
            voice_profile_id,
            video_mode,
            semantic_review_mode,
            video_output_format,
            storyboard_transition_enabled,
            segmentation_mode,
            storyboard_mode,
        )
        if voice_profile_id.strip():
            return ok(project)
        return ok(project_service.save_reference_audio(
                session,
                project,
                reference_audio.file,
                reference_audio.filename or "reference.wav",
            ))
    except (OSError, ValueError) as exc:
        if "project" in locals():
            session.delete(project)
            session.commit()
        logger.exception("Failed to create project with reference audio")
        fail(str(exc))


@router.get("/projects/{project_id}")
def get_project(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        fail("Project not found", 404)
    return ok(project_service.get_project_response(session, project))


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        fail("项目不存在", 404)
    try:
        return ok(project_service.delete_project(session, project))
    except ValueError as exc:
        fail(str(exc), 409)
    except OSError as exc:
        logger.exception("Failed to recycle files for project %s", project_id)
        fail(f"项目文件移入回收站失败：{exc}", 500)


@router.get("/projects/{project_id}/outputs")
def get_project_outputs(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        fail("Project not found", 404)

    output_root = get_project_output_dir(project, get_settings().workspace_dir)
    work_dir = get_project_work_dir(project, get_settings().workspace_dir)
    final_audio_path = get_final_audio_path(project, get_settings().workspace_dir)
    final_srt_path = get_final_srt_path(project, get_settings().workspace_dir)
    final_video_path = get_final_video_path(project, get_settings().workspace_dir)
    final_fcpxml_path = get_final_fcpxml_path(project, get_settings().workspace_dir)
    output_files = []
    seen_paths: set[Path] = set()
    if work_dir.is_dir():
        for path in sorted(work_dir.rglob("*")):
            if not path.is_file():
                continue
            seen_paths.add(path.resolve())
            stat = path.stat()
            output_files.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "relative_path": str(path.relative_to(work_dir)),
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                }
            )
    for final_path in (final_audio_path, final_video_path, final_fcpxml_path, final_srt_path):
        if not final_path.is_file() or final_path.resolve() in seen_paths:
            continue
        stat = final_path.stat()
        output_files.append(
            {
                "name": final_path.name,
                "path": str(final_path),
                "relative_path": final_path.name,
                "size": stat.st_size,
                "modified_at": stat.st_mtime,
            }
        )
    return ok({
        "output_dir": str(output_root),
        "work_dir": str(work_dir),
        "final_audio_path": str(final_audio_path),
        "final_srt_path": str(final_srt_path),
        "final_video_path": str(final_video_path),
        "final_fcpxml_path": str(final_fcpxml_path),
        "final_audio_exists": final_audio_path.is_file(),
        "final_srt_exists": final_srt_path.is_file(),
        "final_video_exists": final_video_path.is_file(),
        "final_fcpxml_exists": final_fcpxml_path.is_file(),
        "files": output_files,
    })


@router.get("/projects/{project_id}/outputs/file")
def get_project_output_file(
    project_id: str,
    path: str,
    download: bool = False,
    session: Session = Depends(get_session),
) -> FileResponse:
    """Preview or download a project artifact after validating its output boundary."""
    project = project_service.get_project(session, project_id)
    if not project:
        fail("Project not found", 404)
    requested = Path(path).expanduser().resolve()
    output_root = get_project_output_dir(project, get_settings().workspace_dir).resolve()
    work_dir = get_project_work_dir(project, get_settings().workspace_dir).resolve()
    try:
        ensure_inside_any(requested, [output_root, work_dir])
    except ValueError:
        fail("Requested file is outside the project output directory", 403)
    if not requested.is_file():
        fail("Output file not found", 404)
    return FileResponse(
        requested,
        filename=requested.name if download else None,
        content_disposition_type="attachment" if download else "inline",
    )


@router.post("/projects/{project_id}/output-settings")
def save_output_settings(
    project_id: str,
    payload: OutputSettingsRequest,
    session: Session = Depends(get_session),
) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        fail("Project not found", 404)
    if not project_service.is_project_editable(project):
        fail("只有未开始生成的项目可以修改", 409)
    try:
        return ok(project_service.update_output_settings(
            session,
            project,
            payload.output_dir,
            payload.output_filename,
        ))
    except ValueError as exc:
        logger.exception("Failed to save output settings for project %s", project_id)
        fail(str(exc))


@router.put("/projects/{project_id}/settings")
def save_project_settings(
    project_id: str,
    payload: ProjectSettingsRequest,
    session: Session = Depends(get_session),
) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        fail("Project not found", 404)
    if not project_service.is_project_editable(project):
        fail("只有未开始生成的项目可以修改", 409)
    try:
        return ok(project_service.update_project_settings(
            session,
            project,
            payload.name,
            payload.output_dir,
            payload.output_filename,
            payload.media_video_dir,
            payload.tts_engine,
            payload.reference_audio_text,
            payload.include_video,
            payload.voice_profile_id,
            payload.video_mode,
            payload.semantic_review_mode,
            payload.video_output_format,
            payload.storyboard_transition_enabled,
            payload.segmentation_mode,
            payload.storyboard_mode,
        ))
    except (OSError, ValueError) as exc:
        logger.exception("Failed to save settings for project %s", project_id)
        fail(str(exc))


@router.post("/projects/select-directory")
def select_directory(payload: DirectoryPickerRequest) -> dict:
    try:
        selected = native_dialog_service.select_directory(payload.initial_path, payload.title)
        return ok({"path": selected})
    except (OSError, RuntimeError) as exc:
        logger.exception("Failed to open the system directory picker")
        fail(str(exc), 500)


@router.get("/projects/{project_id}/reference-audio")
def get_reference_audio(project_id: str, session: Session = Depends(get_session)) -> FileResponse:
    project = project_service.get_project(session, project_id)
    if not project:
        fail("Project not found", 404)
    if not project.reference_audio_path:
        fail("Project has no reference audio configured", 404)
    try:
        audio_path = ensure_inside_any(
            Path(project.reference_audio_path),
            [
                get_project_work_dir(project, get_settings().workspace_dir),
                get_legacy_project_work_dir(project, get_settings().workspace_dir),
                project_dir(get_settings().workspace_dir, project_id),
                get_settings().workspace_dir / "voices",
            ],
        )
    except ValueError as exc:
        logger.exception("Invalid reference audio path for project %s", project_id)
        fail(str(exc))
    if not audio_path.is_file():
        fail("Project reference audio file does not exist", 404)
    return FileResponse(audio_path)


@router.post("/projects/{project_id}/script")
def save_script(project_id: str, payload: ScriptRequest, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        fail("Project not found", 404)
    try:
        project = project_service.ensure_output_filename(session, project)
        return ok(project_service.save_script(session, project, payload.text))
    except ValueError as exc:
        logger.exception("Failed to save script for project %s", project_id)
        fail(str(exc))


@router.post("/projects/{project_id}/reference-audio")
def save_reference_audio(
    project_id: str,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        fail("Project not found", 404)
    try:
        project = project_service.ensure_output_filename(session, project)
        return ok(
            project_service.save_reference_audio(
                session, project, file.file, file.filename or "reference.wav"
            )
        )
    except ValueError as exc:
        logger.exception("Failed to save reference audio for project %s", project_id)
        fail(str(exc))


@router.post("/projects/{project_id}/segments")
def create_segments(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        fail("Project not found", 404)
    try:
        project = project_service.ensure_output_filename(session, project)
        return ok(project_service.create_segments(session, project))
    except (RuntimeError, ValueError) as exc:
        logger.exception("Failed to create segments for project %s", project_id)
        fail(str(exc))
