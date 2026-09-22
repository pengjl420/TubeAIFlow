from __future__ import annotations

import json
import io
from pathlib import Path
from typing import Any

import yaml

from app.services.visual_enrichment.ingest import build_canonical_timeline
from app.services.visual_enrichment.models import (
    CanonicalSegment,
    Chapter,
    OverlayTimeline,
    SemanticScene,
    VisualCandidate,
    VisualPlan,
)
from app.services.visual_enrichment.planning import build_overlay_timeline
from app.services.visual_enrichment.providers import (
    BgeM3OnnxEmbeddingProvider,
    ComfyUIImageProvider,
    LlamaCppLLMProvider,
    MockEmbeddingProvider,
    MockImageProvider,
    MockLLMProvider,
    MockVisionProvider,
    Qwen3VLVisionProvider,
)
from app.services.visual_enrichment.selection import build_candidates
from app.services.visual_enrichment.visual_strategy import visual_strategy_registry
from app.services.visual_enrichment.semantic import build_chapters, segment_scenes
from app.services.visual_enrichment.storage import ArtifactStore, GenerationHistory, sha256_bytes


STAGE_ORDER = ("ingest", "semantic", "plan", "generate", "qc", "timeline", "render")
PROJECT_ROOT = Path(__file__).resolve().parents[4]


class VisualEnrichmentPipeline:
    def __init__(
        self,
        project_dir: Path,
        config_path: Path | None = None,
        *,
        resume: bool = False,
        force: bool = False,
        dry_run: bool = False,
        visual_generation_mode: str | None = None,
        anime_scenes: list[SemanticScene] | None = None,
    ):
        self.project_dir = project_dir.resolve()
        self.project_id = self.project_dir.name
        self.config = self._load_config(config_path)
        configured_mode = str(
            visual_generation_mode
            or self.config.get("visual_generation", {}).get("mode", "curated")
        ).strip().lower()
        self.visual_generation_mode = visual_strategy_registry.get(
            configured_mode
        ).metadata.id
        self.anime_scenes = list(anime_scenes or [])
        self.resume = resume or bool(self.config.get("runtime", {}).get("resume", False))
        self.force = force
        self.dry_run = dry_run
        self.artifacts = ArtifactStore(self.project_dir)
        self.history = GenerationHistory(self.project_dir / "work" / "pipeline.db")
        self.llm, self.embedder, self.image, self.vision = self._build_providers()

    def close(self) -> None:
        self.history.close()

    def run(self, stage: str | None = None) -> dict[str, str]:
        if stage == "dry-run":
            stage = None
            self.dry_run = True
        stages = STAGE_ORDER if stage is None else (stage,)
        if any(item not in STAGE_ORDER for item in stages):
            raise ValueError(f"Unsupported stage: {stage}")
        outputs: dict[str, str] = {}
        try:
            for item in stages:
                outputs.update(getattr(self, f"run_{item}")())
            return outputs
        finally:
            self.close()

    def run_ingest(self) -> dict[str, str]:
        transcript_path = self._input_path("transcript.txt")
        srt_path = self._input_path("subtitles.srt")
        transcript = transcript_path.read_text(encoding="utf-8-sig")
        srt = srt_path.read_text(encoding="utf-8-sig")
        input_hash = self._hash_payload(transcript, srt, self.config.get("segmentation", {}))
        relative = "work/01_ingest/canonical_timeline.jsonl"
        if self._can_resume(relative, input_hash):
            timeline = self._read_jsonl(relative, CanonicalSegment)
        else:
            timeline = build_canonical_timeline(transcript, srt)
            self.artifacts.write_jsonl(relative, timeline)
            self.artifacts.record_input_hash(relative, input_hash)
        duration_ms = timeline[-1].end_ms
        report = {
            "project_id": self.project_id,
            "segments": len(timeline),
            "duration_ms": duration_ms,
            "audio_validation": "skipped_dry_run" if self.dry_run else "not_available",
        }
        report_path = self.artifacts.write_json("work/01_ingest/ingest_report.json", report)
        return {
            "canonical_timeline.jsonl": str(self.project_dir / relative),
            "ingest_report.json": str(report_path),
        }

    def run_semantic(self) -> dict[str, str]:
        timeline = self._load_timeline()
        config = self.config
        segmentation_cfg = self._segmentation_config()
        input_hash = self._hash_payload(
            [item.model_dump(mode="json") for item in timeline],
            config.get("semantic", {}),
            segmentation_cfg,
            self.visual_generation_mode,
            [scene.model_dump(mode="json") for scene in self.anime_scenes],
            self.llm.name,
            getattr(self.llm, "model", "deterministic-mock-v1"),
        )
        chapter_relative = "work/02_semantic/chapters.json"
        scene_relative = "work/02_semantic/scenes.json"
        candidate_relative = "work/03_candidates/visual_candidates.json"
        if self._can_resume(chapter_relative, input_hash) and self._can_resume(
            scene_relative, input_hash
        ):
            chapters = self._read_model_list(chapter_relative, Chapter)
            scenes = self._read_model_list(scene_relative, SemanticScene)
        else:
            semantic_cfg = config.get("semantic", {})
            chapters = build_chapters(
                timeline,
                self.llm,
                tuple(semantic_cfg.get("chunk_minutes", [2, 4])),
            )
            scenes = (
                self.anime_scenes
                if self.visual_generation_mode == "anime_full_coverage" and self.anime_scenes
                else segment_scenes(
                    timeline,
                    chapters,
                    target_scene_sec=tuple(segmentation_cfg.get("target_scene_sec", [8, 18])),
                    min_scene_sec=int(segmentation_cfg.get("min_scene_sec", 5)),
                    max_scene_sec=int(segmentation_cfg.get("max_scene_sec", 30)),
                )
            )
            self._write_model_list(chapter_relative, chapters, input_hash)
            self._write_model_list(scene_relative, scenes, input_hash)
            self.history.append(
                project_id=self.project_id,
                generation_type="semantic",
                provider=self.llm.name,
                model=str(getattr(self.llm, "model", "deterministic-mock-v1")),
                prompt="prompts/global_semantic.md + prompts/local_visual_analysis.md",
                input_data={"input_hash": input_hash},
                output_data={"chapters": len(chapters), "scenes": len(scenes)},
            )
        candidate_hash = self._hash_payload(
            input_hash, "candidate-scoring-v2", self.embedder.model_id
        )
        if self._can_resume(candidate_relative, candidate_hash):
            candidates = self._read_model_list(candidate_relative, VisualCandidate)
        else:
            embeddings = self.embedder.encode([scene.narration for scene in scenes])
            self._write_embeddings(embeddings)
            candidates = build_candidates(scenes, embeddings)
            self._write_model_list(candidate_relative, candidates, candidate_hash)
        return {
            "chapters.json": str(self.project_dir / chapter_relative),
            "scenes.json": str(self.project_dir / scene_relative),
            "visual_candidates.json": str(self.project_dir / candidate_relative),
        }

    def run_plan(self) -> dict[str, str]:
        timeline = self._load_timeline()
        candidates = self._read_model_list(
            "work/03_candidates/visual_candidates.json", VisualCandidate
        )
        selection = self.config.get("selection", {})
        duration_ms = timeline[-1].end_ms
        input_hash = self._hash_payload(
            [item.model_dump(mode="json") for item in candidates],
            selection,
            self.config.get("image", {}),
            self.config.get("anime", {}),
            self.visual_generation_mode,
        )
        relative = "work/04_plan/visual_plan.json"
        if self._can_resume(relative, input_hash):
            plan = VisualPlan.model_validate(self._read_json(relative))
        else:
            strategy = visual_strategy_registry.get(self.visual_generation_mode)
            plan = strategy.build_plan(
                project_id=self.project_id,
                duration_ms=duration_ms,
                candidates=candidates,
                config=self.config,
                provider=self.llm,
            )
            self.artifacts.write_json(relative, plan)
            self.artifacts.record_input_hash(relative, input_hash)
            self.history.append(
                project_id=self.project_id,
                generation_type="visual_plan",
                provider=self.llm.name,
                model=str(getattr(self.llm, "model", "deterministic-mock-v1")),
                prompt="prompts/visual_brief.md + prompts/image_prompt.md",
                input_data={"input_hash": input_hash},
                output_data=plan.model_dump(mode="json"),
            )
        return {"visual_plan.json": str(self.project_dir / relative)}

    def run_generate(self) -> dict[str, str]:
        plan = self._load_plan()
        relative = "work/05_assets/generated/generations.json"
        input_hash = self._hash_payload(
            plan.model_dump(mode="json"), self.image.name, "image-generation-v1"
        )
        if self._can_resume(relative, input_hash):
            return {"generations.json": str(self.project_dir / relative)}
        generations = []
        for visual in plan.visuals:
            request = {
                "visual_id": visual.visual_id,
                "prompt": visual.prompt,
                "negative_prompt": visual.negative_prompt,
                "seed": visual.generation.seed_base,
                "width": visual.generation.width,
                "height": visual.generation.height,
                "candidates": visual.generation.candidates,
            }
            outputs = self.image.generate(request)
            for output in outputs:
                output["visual_id"] = visual.visual_id
            generations.extend(outputs)
            self.history.append(
                project_id=self.project_id,
                generation_type=f"image:{visual.visual_id}",
                provider=self.image.name,
                model=str(
                    self.config.get("image", {}).get("default_model", "deterministic-mock-v1")
                ),
                prompt=visual.prompt,
                input_data=request,
                output_data={"outputs": outputs},
            )
        path = self.artifacts.write_json(relative, generations)
        self.artifacts.record_input_hash(relative, input_hash)
        return {"generations.json": str(path)}

    def run_qc(self) -> dict[str, str]:
        plan = self._load_plan()
        relative = "work/06_qc/image_qc.json"
        input_hash = self._hash_payload(
            plan.model_dump(mode="json"), self.vision.name, "vision-qc-v1"
        )
        if self._can_resume(relative, input_hash):
            return {"image_qc.json": str(self.project_dir / relative)}
        generation_path = self.project_dir / "work/05_assets/generated/generations.json"
        if not generation_path.is_file():
            self.run_generate()
        generated = json.loads(generation_path.read_text(encoding="utf-8"))
        by_visual = {
            item["visual_id"]: item["path"]
            for item in generated
            if item.get("visual_id") and item.get("path")
        }
        report = []
        for visual in plan.visuals:
            image_path = by_visual.get(visual.visual_id)
            if not image_path:
                report.append(
                    {"visual_id": visual.visual_id, "approved": False, "error": "missing image"}
                )
                continue
            report.append(
                {
                    "visual_id": visual.visual_id,
                    **self.vision.inspect(image_path, {"claim": visual.core_claim}),
                }
            )
        path = self.artifacts.write_json(relative, report)
        self.artifacts.record_input_hash(relative, input_hash)
        self.history.append(
            project_id=self.project_id,
            generation_type="image_qc",
            provider=self.vision.name,
            model=str(self.config.get("qc", {}).get("vision_model", "deterministic-mock-v1")),
            prompt="generated image semantic and artifact QC",
            input_data={"input_hash": input_hash},
            output_data={"results": report},
        )
        return {"image_qc.json": str(path)}

    def run_timeline(self) -> dict[str, str]:
        plan = self._load_plan()
        relative = "work/07_timeline/overlay_timeline.json"
        input_hash = self._hash_payload(plan.model_dump(mode="json"), "overlay-timeline-v1")
        if self._can_resume(relative, input_hash):
            OverlayTimeline.model_validate(self._read_json(relative))
            return {"overlay_timeline.json": str(self.project_dir / relative)}
        timeline = build_overlay_timeline(plan)
        OverlayTimeline.model_validate(timeline.model_dump(mode="json"))
        path = self.artifacts.write_json(relative, timeline)
        self.artifacts.record_input_hash(relative, input_hash)
        return {"overlay_timeline.json": str(path)}

    def run_render(self) -> dict[str, str]:
        timeline_path = self.project_dir / "work/07_timeline/overlay_timeline.json"
        if not timeline_path.is_file():
            self.run_timeline()
        relative = "work/08_render/render_report.json"
        input_hash = self._hash_payload(
            timeline_path.read_text(encoding="utf-8"), self.dry_run, "mock-render-v1"
        )
        if self._can_resume(relative, input_hash):
            return {"render_report.json": str(self.project_dir / relative)}
        report = {
            "project_id": self.project_id,
            "status": "dry_run" if self.dry_run else "mocked",
            "renderer": "mock",
            "message": "Phase 0-3 does not invoke FFmpeg rendering.",
        }
        path = self.artifacts.write_json(relative, report)
        self.artifacts.record_input_hash(relative, input_hash)
        return {"render_report.json": str(path)}

    def _load_timeline(self) -> list[CanonicalSegment]:
        relative = "work/01_ingest/canonical_timeline.jsonl"
        if not (self.project_dir / relative).is_file():
            self.run_ingest()
        return self._read_jsonl(relative, CanonicalSegment)

    def _load_plan(self) -> VisualPlan:
        relative = "work/04_plan/visual_plan.json"
        if not (self.project_dir / relative).is_file():
            if not (self.project_dir / "work/03_candidates/visual_candidates.json").is_file():
                self.run_semantic()
            self.run_plan()
        return VisualPlan.model_validate(self._read_json(relative))

    def _segmentation_config(self) -> dict:
        base = dict(self.config.get("segmentation", {}))
        if self.visual_generation_mode != "anime_full_coverage":
            return base
        anime = self.config.get("anime", {})
        base.update(
            {
                "target_scene_sec": anime.get("target_master_scene_sec", [8, 15]),
                "min_scene_sec": anime.get("min_master_scene_sec", 5),
                "max_scene_sec": anime.get("max_master_scene_sec", 15),
            }
        )
        return base

    def _input_path(self, name: str) -> Path:
        path = self.project_dir / "input" / name
        if not path.is_file():
            raise FileNotFoundError(f"Missing project input: {path}")
        return path

    def _can_resume(self, relative: str, input_hash: str) -> bool:
        return not self.force and self.resume and self.artifacts.is_current(relative, input_hash)

    def _read_json(self, relative: str) -> Any:
        return json.loads((self.project_dir / relative).read_text(encoding="utf-8"))

    def _read_model_list(self, relative: str, model_type):
        payload = self._read_json(relative)
        if not isinstance(payload, list):
            raise ValueError(f"Expected a JSON list in {relative}")
        return [model_type.model_validate(item) for item in payload]

    def _read_jsonl(self, relative: str, model_type):
        lines = (self.project_dir / relative).read_text(encoding="utf-8").splitlines()
        return [model_type.model_validate_json(line) for line in lines if line.strip()]

    def _write_model_list(self, relative: str, values: list, input_hash: str) -> None:
        validated = [type(value).model_validate(value.model_dump(mode="json")) for value in values]
        self.artifacts.write_json(relative, [item.model_dump(mode="json") for item in validated])
        self.artifacts.record_input_hash(relative, input_hash)

    def _write_embeddings(self, embeddings: list[list[float]]) -> None:
        import numpy as np

        stream = io.BytesIO()
        np.save(stream, np.asarray(embeddings, dtype=np.float32), allow_pickle=False)
        self.artifacts.write_bytes("work/02_semantic/embeddings.npy", stream.getvalue())

    def _build_providers(self):
        if self.dry_run:
            return (
                MockLLMProvider(),
                MockEmbeddingProvider(),
                MockImageProvider(),
                MockVisionProvider(),
            )
        semantic = self.config.get("semantic", {})
        embedding = self.config.get("embedding", {})
        image = self.config.get("image", {})
        qc = self.config.get("qc", {})
        llm_provider = LlamaCppLLMProvider(
            str(semantic.get("base_url", "http://127.0.0.1:18090")),
            model=str(semantic.get("model", "qwen3-8b-q4_k_m")),
            timeout_seconds=float(semantic.get("timeout_seconds", 180)),
        )
        embedding_provider = BgeM3OnnxEmbeddingProvider(
            self._config_path(embedding.get("model_path", "models/embedding/bge-m3-onnx")),
            max_length=int(embedding.get("max_length", 512)),
        )
        image_provider = ComfyUIImageProvider(
            str(image.get("base_url", "http://127.0.0.1:8188")),
            self._config_path(image.get("workflow_path", "workflows/flux2_klein_scene_api.json")),
            self.project_dir / "work/05_assets/generated",
            timeout_seconds=float(image.get("timeout_seconds", 900)),
        )
        vision_provider = Qwen3VLVisionProvider(
            self._config_path(qc.get("model_path", "models/vision/qwen3-vl-4b-instruct-fp8")),
            max_new_tokens=int(qc.get("max_new_tokens", 512)),
            semantic_match_min=int(qc.get("semantic_match_min", 4)),
            reject_random_text=bool(qc.get("reject_random_text", True)),
            reject_watermark=bool(qc.get("reject_watermark", True)),
            reject_unapproved_logo=bool(qc.get("reject_unapproved_logo", True)),
        )
        return llm_provider, embedding_provider, image_provider, vision_provider

    @staticmethod
    def _config_path(value: str | Path) -> Path:
        path = Path(value)
        return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()

    @staticmethod
    def _hash_payload(*values: Any) -> str:
        return sha256_bytes(json.dumps(values, ensure_ascii=False, sort_keys=True).encode("utf-8"))

    @staticmethod
    def _load_config(config_path: Path | None) -> dict:
        if config_path is None:
            return {}
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Pipeline config must be a YAML object")
        hardware = payload.get("hardware", {})
        if (
            hardware.get("parallel_large_models") is not False
            or int(hardware.get("max_gpu_jobs", 1)) != 1
        ):
            raise ValueError(
                "Phase 0-3 requires one serial GPU job and parallel_large_models=false"
            )
        return payload
