import json
import tempfile
import unittest
from pathlib import Path

from app.services.visual_enrichment.models import (
    CanonicalSegment,
    Chapter,
    OverlayTimeline,
    SemanticScene,
    VisualCandidate,
    VisualPlan,
)
from app.services.visual_enrichment.pipeline import VisualEnrichmentPipeline


class PipelineTests(unittest.TestCase):
    def test_checked_in_visual_plan_example_matches_domain_schema(self) -> None:
        example_path = Path(__file__).resolve().parents[3] / "examples" / "visual_plan.example.json"
        VisualPlan.model_validate_json(example_path.read_text(encoding="utf-8"))

    def test_dry_run_creates_schema_valid_artifacts_and_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "demo"
            input_dir = project / "input"
            input_dir.mkdir(parents=True)
            input_dir.joinpath("transcript.txt").write_text(
                "第一段说明变化。第二段说明成本。最后给出稳定流程。", encoding="utf-8"
            )
            input_dir.joinpath("subtitles.srt").write_text(
                "1\n00:00:00,000 --> 00:00:06,000\n第一段说明变化。\n\n"
                "2\n00:00:06,000 --> 00:00:12,000\n第二段说明成本。\n\n"
                "3\n00:00:12,000 --> 00:00:18,000\n最后给出稳定流程。\n",
                encoding="utf-8",
            )
            outputs = VisualEnrichmentPipeline(project, dry_run=True, resume=True).run()
            required = {
                "canonical_timeline.jsonl", "chapters.json", "scenes.json",
                "visual_candidates.json", "visual_plan.json", "overlay_timeline.json",
            }
            self.assertTrue(required.issubset(outputs))

            canonical_path = Path(outputs["canonical_timeline.jsonl"])
            for line in canonical_path.read_text(encoding="utf-8").splitlines():
                CanonicalSegment.model_validate_json(line)
            validators = {
                "chapters.json": Chapter,
                "scenes.json": SemanticScene,
                "visual_candidates.json": VisualCandidate,
            }
            for name, model in validators.items():
                for item in json.loads(Path(outputs[name]).read_text(encoding="utf-8")):
                    model.model_validate(item)
            VisualPlan.model_validate_json(Path(outputs["visual_plan.json"]).read_text(encoding="utf-8"))
            OverlayTimeline.model_validate_json(
                Path(outputs["overlay_timeline.json"]).read_text(encoding="utf-8")
            )

            before = canonical_path.stat().st_mtime_ns
            VisualEnrichmentPipeline(project, dry_run=True, resume=True).run()
            self.assertEqual(canonical_path.stat().st_mtime_ns, before)
