from __future__ import annotations

from sqlmodel import Session

from app.models.project import Project
from app.workflows.engine import StageChanged
from app.workflows.registry import WorkflowRuntime, workflow_registry


NARRATION_WORKFLOW_ID = "narration_generation"
VIDEO_WORKFLOW_ID = "video_synthesis"


def ensure_builtin_workflows_registered() -> None:
    """Register built-ins lazily to keep workflow modules free of import cycles."""
    registered = {item.id for item in workflow_registry.list()}
    if NARRATION_WORKFLOW_ID not in registered:
        from app.workflows import video_synthesis

        workflow_registry.register(
            WorkflowRuntime(
                id=NARRATION_WORKFLOW_ID,
                stages=frozenset(
                    {
                        "segmenting",
                        "tts",
                        "audio_merge",
                        "subtitles",
                        "video",
                        *video_synthesis.STAGES,
                    }
                ),
                video_stages=frozenset({"video", *video_synthesis.STAGES}),
                produces_video=False,
                run=_run_narration_workflow,
                initial_stage=_initial_narration_stage,
            )
        )
    if VIDEO_WORKFLOW_ID not in registered:
        from app.workflows import video_synthesis

        workflow_registry.register(
            WorkflowRuntime(
                id=VIDEO_WORKFLOW_ID,
                stages=frozenset(video_synthesis.STAGES),
                video_stages=frozenset(video_synthesis.STAGES),
                produces_video=True,
                run=_run_video_workflow,
                initial_stage=_initial_video_stage,
            )
        )


def get_workflow_runtime(workflow_id: str) -> WorkflowRuntime:
    ensure_builtin_workflows_registered()
    return workflow_registry.get(workflow_id)


def _run_narration_workflow(
    session: Session,
    project: Project,
    current_stage: str,
    include_video: bool,
    on_stage_changed: StageChanged,
) -> None:
    from app.workflows import narration_generation

    narration_generation.run_project_generation(
        session, project, current_stage, include_video, on_stage_changed
    )


def _initial_narration_stage(
    session: Session, project: Project, include_video: bool
) -> str:
    from app.workflows import narration_generation

    return narration_generation.initial_stage(session, project, include_video)


def _run_video_workflow(
    session: Session,
    project: Project,
    current_stage: str,
    _include_video: bool,
    on_stage_changed: StageChanged,
) -> None:
    from app.workflows import video_synthesis

    video_synthesis.run_video_synthesis(
        session, project, current_stage, on_stage_changed
    )


def _initial_video_stage(
    session: Session, project: Project, _include_video: bool
) -> str:
    from app.workflows import video_synthesis

    return video_synthesis.initial_stage(session, project.id)
