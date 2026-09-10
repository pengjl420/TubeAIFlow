import unittest
from unittest.mock import Mock

from app.domain.states import ResourceClass
from app.schemas.project_config import ProjectConfig
from app.workflows import WorkflowContext, WorkflowGraph, WorkflowStep
from app.workflows.builtin import (
    NARRATION_WORKFLOW_ID,
    VIDEO_WORKFLOW_ID,
    SCENE_IMAGE_WORKFLOW_ID,
    SCENE_PREVIEW_WORKFLOW_ID,
    TIMELINE_PREVIEW_WORKFLOW_ID,
    FINAL_RENDER_WORKFLOW_ID,
    ensure_builtin_workflows_registered,
)
from app.workflows.registry import workflow_registry


class WorkflowArchitectureTests(unittest.TestCase):
    def test_builtin_workflows_are_executable_registrations(self) -> None:
        ensure_builtin_workflows_registered()

        self.assertEqual(
            {item.id for item in workflow_registry.list()},
            {
                NARRATION_WORKFLOW_ID,
                VIDEO_WORKFLOW_ID,
                SCENE_IMAGE_WORKFLOW_ID,
                SCENE_PREVIEW_WORKFLOW_ID,
                TIMELINE_PREVIEW_WORKFLOW_ID,
                FINAL_RENDER_WORKFLOW_ID,
            },
        )
        narration = workflow_registry.get(NARRATION_WORKFLOW_ID)
        self.assertIn("segmenting", narration.stages)
        self.assertIn("quality_check", narration.video_stages)
        self.assertEqual(narration.resource_class("tts"), ResourceClass.GPU)
        self.assertEqual(narration.resource_class("audio_merge"), ResourceClass.FFMPEG)

    def test_graph_executes_registered_steps_and_persists_each_transition(self) -> None:
        transitions: list[str] = []
        graph = WorkflowGraph(
            (
                WorkflowStep("one", lambda _context: "two"),
                WorkflowStep(
                    "two",
                    lambda _context: "completed",
                    resource_class=ResourceClass.FFMPEG,
                    depends_on=("one",),
                ),
            )
        )

        result = graph.execute(
            WorkflowContext(session=Mock(), project=Mock()), "one", transitions.append
        )

        self.assertEqual(result, "completed")
        self.assertEqual(transitions, ["two", "completed"])
        self.assertEqual(graph.step("two").resource_class, ResourceClass.FFMPEG)

    def test_graph_rejects_duplicate_persisted_stage_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique"):
            WorkflowGraph(
                (
                    WorkflowStep("same", lambda _context: "completed"),
                    WorkflowStep("same", lambda _context: "completed"),
                )
            )

    def test_project_config_validates_core_and_preserves_provider_extensions(self) -> None:
        config = ProjectConfig.model_validate({"fps": 60, "provider_custom": {"temperature": 0.2}})

        self.assertEqual(config.fps, 60)
        self.assertEqual(config.model_dump()["provider_custom"], {"temperature": 0.2})


if __name__ == "__main__":
    unittest.main()
