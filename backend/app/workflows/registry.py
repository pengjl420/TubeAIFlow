from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlmodel import Session

from app.models.project import Project
from app.domain.states import ResourceClass
from app.workflows.engine import StageChanged


WorkflowRunner = Callable[[Session, Project, str, bool, StageChanged], None]
InitialStageResolver = Callable[[Session, Project, bool], str]
ResourceClassResolver = Callable[[str], ResourceClass]


@dataclass(frozen=True, slots=True)
class WorkflowRuntime:
    id: str
    stages: frozenset[str]
    video_stages: frozenset[str]
    produces_video: bool
    run: WorkflowRunner
    initial_stage: InitialStageResolver
    resource_class: ResourceClassResolver


class WorkflowRegistry:
    """Executable workflow registry shared by queueing and worker dispatch."""

    def __init__(self) -> None:
        self._workflows: dict[str, WorkflowRuntime] = {}

    def register(self, runtime: WorkflowRuntime) -> None:
        if runtime.id in self._workflows:
            raise ValueError(f"Workflow is already registered: {runtime.id}")
        self._workflows[runtime.id] = runtime

    def get(self, workflow_id: str) -> WorkflowRuntime:
        try:
            return self._workflows[workflow_id]
        except KeyError as exc:
            raise ValueError(f"Unknown workflow: {workflow_id}") from exc

    def list(self) -> list[WorkflowRuntime]:
        return sorted(self._workflows.values(), key=lambda item: item.id)

    def is_video_stage(self, workflow_id: str, stage: str) -> bool:
        runtime = self._workflows.get(workflow_id)
        return bool(runtime and stage in runtime.video_stages)


workflow_registry = WorkflowRegistry()
