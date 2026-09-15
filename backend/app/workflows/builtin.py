from __future__ import annotations

from sqlmodel import Session

from app.domain.states import ResourceClass
from app.models.project import Project
from app.workflows.engine import StageChanged
from app.workflows.registry import WorkflowRuntime, workflow_registry


NARRATION_WORKFLOW_ID = "narration_generation"
VIDEO_WORKFLOW_ID = "video_synthesis"
SCENE_IMAGE_WORKFLOW_ID = "scene_image_regeneration"
SCENE_PREVIEW_WORKFLOW_ID = "scene_preview_render"
SCENE_STORYBOARD_WORKFLOW_ID = "scene_storyboard_regeneration"
ASSET_SCAN_WORKFLOW_ID = "asset_library_scan"
QUALITY_CHECK_WORKFLOW_ID = "quality_check"


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
                        *video_synthesis.STAGES,
                    }
                ),
                video_stages=frozenset(video_synthesis.STAGES),
                produces_video=False,
                run=_run_narration_workflow,
                initial_stage=_initial_narration_stage,
                resource_class=_narration_resource_class,
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
                resource_class=_video_resource_class,
            )
        )
    registered = {item.id for item in workflow_registry.list()}
    if SCENE_IMAGE_WORKFLOW_ID not in registered:
        from app.workflows import scene_jobs

        workflow_registry.register(
            WorkflowRuntime(
                id=SCENE_IMAGE_WORKFLOW_ID,
                stages=frozenset({"generate"}),
                video_stages=frozenset({"generate"}),
                produces_video=False,
                run=scene_jobs.run_scene_image_job,
                initial_stage=lambda _session, _project, _include_video: "generate",
                resource_class=lambda _stage: ResourceClass.GPU,
            )
        )
    if SCENE_PREVIEW_WORKFLOW_ID not in registered:
        from app.workflows import scene_jobs

        workflow_registry.register(
            WorkflowRuntime(
                id=SCENE_PREVIEW_WORKFLOW_ID,
                stages=frozenset({"render"}),
                video_stages=frozenset({"render"}),
                produces_video=False,
                run=scene_jobs.run_scene_preview_job,
                initial_stage=lambda _session, _project, _include_video: "render",
                resource_class=lambda _stage: ResourceClass.FFMPEG,
            )
        )
    if SCENE_STORYBOARD_WORKFLOW_ID not in registered:
        from app.workflows import scene_jobs

        workflow_registry.register(
            WorkflowRuntime(
                id=SCENE_STORYBOARD_WORKFLOW_ID,
                stages=frozenset({"generate"}),
                video_stages=frozenset(),
                produces_video=False,
                run=scene_jobs.run_scene_storyboard_job,
                initial_stage=lambda _session, _project, _include_video: "generate",
                resource_class=lambda _stage: ResourceClass.API,
            )
        )
    registered = {item.id for item in workflow_registry.list()}
    if ASSET_SCAN_WORKFLOW_ID not in registered:
        from app.workflows import maintenance_jobs

        workflow_registry.register(
            WorkflowRuntime(
                id=ASSET_SCAN_WORKFLOW_ID,
                stages=frozenset({"scan"}),
                video_stages=frozenset(),
                produces_video=False,
                run=maintenance_jobs.run_asset_scan_job,
                initial_stage=lambda _session, _project, _include_video: "scan",
                resource_class=lambda _stage: ResourceClass.CPU,
            )
        )
    if QUALITY_CHECK_WORKFLOW_ID not in registered:
        from app.workflows import maintenance_jobs

        workflow_registry.register(
            WorkflowRuntime(
                id=QUALITY_CHECK_WORKFLOW_ID,
                stages=frozenset({"analyze"}),
                video_stages=frozenset(),
                produces_video=False,
                run=maintenance_jobs.run_quality_check_job,
                initial_stage=lambda _session, _project, _include_video: "analyze",
                resource_class=lambda _stage: ResourceClass.FFMPEG,
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


def _initial_narration_stage(session: Session, project: Project, include_video: bool) -> str:
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

    video_synthesis.run_video_synthesis(session, project, current_stage, on_stage_changed)


def _initial_video_stage(session: Session, project: Project, _include_video: bool) -> str:
    from app.workflows import video_synthesis

    return video_synthesis.initial_stage(session, project.id)


def _narration_resource_class(stage: str) -> ResourceClass:
    from app.workflows import narration_generation

    return narration_generation.resource_class(stage)


def _video_resource_class(stage: str) -> ResourceClass:
    from app.workflows import video_synthesis

    return video_synthesis.resource_class(stage)
