from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from sqlmodel import Session

from app.models.project import Project
from app.domain.states import ResourceClass


@dataclass(frozen=True, slots=True)
class WorkflowContext:
    session: Session
    project: Project
    include_video: bool = False
    artifact_exists: Callable[[str], bool] | None = None


StepHandler = Callable[[WorkflowContext], str]
StageChanged = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    """One resumable unit with a stable persisted stage id."""

    id: str
    run: StepHandler
    resource_class: ResourceClass = ResourceClass.CPU
    depends_on: tuple[str, ...] = ()
    input_artifacts: tuple[str, ...] = ()
    output_artifacts: tuple[str, ...] = ()
    cacheable: bool = False
    cached_next_stage: str | None = None


class WorkflowGraph:
    """Small deterministic executor for persisted linear/branching workflow steps."""

    def __init__(self, steps: Iterable[WorkflowStep]) -> None:
        step_values = tuple(steps)
        self._steps = {step.id: step for step in step_values}
        if not self._steps:
            raise ValueError("Workflow must contain at least one step")
        if len(self._steps) != len(step_values):
            raise ValueError("Workflow step ids must be unique")
        known: set[str] = set()
        for step in step_values:
            missing = set(step.depends_on) - known
            if missing:
                raise ValueError(
                    f"Workflow step {step.id} has missing or forward dependencies: "
                    + ", ".join(sorted(missing))
                )
            if step.cacheable and step.output_artifacts and not step.cached_next_stage:
                raise ValueError(
                    f"Cacheable workflow step {step.id} must declare cached_next_stage"
                )
            known.add(step.id)

    @property
    def stages(self) -> frozenset[str]:
        return frozenset(self._steps)

    def step(self, stage: str) -> WorkflowStep:
        try:
            return self._steps[stage]
        except KeyError as exc:
            raise ValueError(f"Unknown workflow stage: {stage}") from exc

    def resource_class(self, stage: str) -> ResourceClass:
        return self.step(stage).resource_class

    def execute(
        self,
        context: WorkflowContext,
        current_stage: str,
        on_stage_changed: StageChanged,
    ) -> str:
        """Execute known steps until reaching a terminal or another workflow graph."""
        stage = current_stage
        while stage in self._steps:
            step = self._steps[stage]
            self._require_artifacts(context, step, step.input_artifacts, "input")
            if (
                step.cacheable
                and step.output_artifacts
                and all(self._artifact_exists(context, name) for name in step.output_artifacts)
            ):
                next_stage = step.cached_next_stage or ""
            else:
                next_stage = step.run(context)
                self._require_artifacts(context, step, step.output_artifacts, "output")
            if not next_stage or next_stage == stage:
                raise RuntimeError(f"Workflow step {stage} did not advance")
            on_stage_changed(next_stage)
            stage = next_stage
        return stage

    @staticmethod
    def _artifact_exists(context: WorkflowContext, name: str) -> bool:
        if context.artifact_exists is None:
            raise RuntimeError(f"Workflow has no artifact resolver for {name}")
        return bool(context.artifact_exists(name))

    @classmethod
    def _require_artifacts(
        cls,
        context: WorkflowContext,
        step: WorkflowStep,
        artifacts: tuple[str, ...],
        kind: str,
    ) -> None:
        missing = [name for name in artifacts if not cls._artifact_exists(context, name)]
        if missing:
            raise RuntimeError(
                f"Workflow step {step.id} is missing {kind} artifacts: " + ", ".join(missing)
            )
