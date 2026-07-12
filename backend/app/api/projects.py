import logging
import string
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session

from app.config import get_settings
from app.database import get_session
from app.services import project_service
from app.utils.file_utils import ensure_inside_workspace, project_dir
from app.utils.project_paths import get_final_audio_path, get_final_video_path, get_project_output_dir, get_project_work_dir


logger = logging.getLogger(__name__)
router = APIRouter(tags=["projects"])


class ScriptRequest(BaseModel):
    text: str


class OutputSettingsRequest(BaseModel):
    output_dir: str
    output_filename: str


class DirectoryListRequest(BaseModel):
    path: str | None = None


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
    reference_audio: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict:
    if not name.strip():
        fail("Project name is required")
    try:
        project = project_service.create_project(session, name.strip())
        return ok(
            project_service.save_reference_audio(
                session,
                project,
                reference_audio.file,
                reference_audio.filename or "reference.wav",
            )
        )
    except ValueError as exc:
        logger.exception("Failed to create project with reference audio")
        fail(str(exc))


@router.get("/projects/{project_id}")
def get_project(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        fail("Project not found", 404)
    return ok(project)


@router.get("/projects/{project_id}/outputs")
def get_project_outputs(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        fail("Project not found", 404)

    output_root = get_project_output_dir(project, get_settings().workspace_dir)
    work_dir = get_project_work_dir(project, get_settings().workspace_dir)
    final_audio_path = get_final_audio_path(project, get_settings().workspace_dir)
    final_video_path = get_final_video_path(project, get_settings().workspace_dir)
    output_files = []
    if work_dir.is_dir():
        for path in sorted(work_dir.rglob("*")):
            if not path.is_file():
                continue
            stat = path.stat()
            output_files.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "relative_path": str(path.relative_to(output_root)),
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                }
            )
    if final_audio_path.is_file():
        stat = final_audio_path.stat()
        output_files.append(
            {
                "name": final_audio_path.name,
                "path": str(final_audio_path),
                "relative_path": final_audio_path.name,
                "size": stat.st_size,
                "modified_at": stat.st_mtime,
            }
        )
    if final_video_path.is_file():
        stat = final_video_path.stat()
        output_files.append(
            {
                "name": final_video_path.name,
                "path": str(final_video_path),
                "relative_path": final_video_path.name,
                "size": stat.st_size,
                "modified_at": stat.st_mtime,
            }
        )

    return ok({
        "output_dir": str(output_root),
        "work_dir": str(work_dir),
        "final_audio_path": str(final_audio_path),
        "final_video_path": str(final_video_path),
        "files": output_files,
    })


@router.post("/projects/{project_id}/output-settings")
def save_output_settings(
    project_id: str,
    payload: OutputSettingsRequest,
    session: Session = Depends(get_session),
) -> dict:
    project = project_service.get_project(session, project_id)
    if not project:
        fail("Project not found", 404)
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


@router.post("/projects/directories")
def list_directories(payload: DirectoryListRequest) -> dict:
    if payload.path:
        current = Path(payload.path).expanduser().resolve()
    else:
        current = get_settings().workspace_dir.resolve()

    roots = [f"{drive}:\\" for drive in string.ascii_uppercase if Path(f"{drive}:\\").exists()]
    if not current.exists() or not current.is_dir():
        fail("Directory does not exist", 404)

    directories = []
    try:
        for child in current.iterdir():
            if child.is_dir():
                directories.append({"name": child.name, "path": str(child.resolve())})
    except OSError as exc:
        logger.exception("Failed to list directory %s", current)
        fail(str(exc))

    parent = current.parent if current.parent != current else None
    return ok(
        {
            "current": str(current),
            "parent": str(parent) if parent else None,
            "roots": roots,
            "directories": sorted(directories, key=lambda item: item["name"].lower()),
        }
    )


@router.get("/projects/{project_id}/reference-audio")
def get_reference_audio(project_id: str, session: Session = Depends(get_session)) -> FileResponse:
    project = project_service.get_project(session, project_id)
    if not project:
        fail("Project not found", 404)
    if not project.reference_audio_path:
        fail("Project has no reference audio configured", 404)
    try:
        audio_path = Path(project.reference_audio_path)
        try:
            audio_path = ensure_inside_workspace(
                audio_path,
                get_project_work_dir(project, get_settings().workspace_dir),
            )
        except ValueError:
            audio_path = ensure_inside_workspace(
                audio_path,
                project_dir(get_settings().workspace_dir, project_id),
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
    except ValueError as exc:
        logger.exception("Failed to create segments for project %s", project_id)
        fail(str(exc))
