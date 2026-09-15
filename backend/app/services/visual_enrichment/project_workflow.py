from __future__ import annotations

import json
import logging
from pathlib import Path

from PIL import Image
from sqlmodel import Session, select

from app.config import get_settings
from app.infrastructure.atomic_files import write_json_atomic, write_text_atomic
from app.infrastructure.project_layout import (
    get_final_srt_path,
    get_project_work_dir,
    load_project_config,
)
from app.infrastructure.serialization import stable_json_hash
from app.models.media import GeneratedImageVariant
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.schemas.storyboard import StoryboardContent, StoryboardVisualBrief
from app.services.image_generation import image_generation_service
from app.services.visual_enrichment.models import VisualPlan
from app.services.visual_enrichment.pipeline import PROJECT_ROOT, VisualEnrichmentPipeline
from app.shared.time import utc_now_iso


logger = logging.getLogger(__name__)
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "production_5060ti.yaml"
WORKFLOW_VERSION = "advanced_visual_pipeline_v1"


def enrich_project_visuals(session: Session, project: Project) -> dict:
    """Run the advanced local visual pipeline inside the persisted project workflow.

    ``auto`` is deliberately failure-tolerant so installations without the optional
    BGE/FLUX/Qwen3-VL stack continue with the built-in SDXL path. ``advanced`` is
    strict and surfaces setup/runtime failures to the durable Job.
    """
    config = load_project_config(project)
    mode = str(config.get("visual_enrichment_mode") or "auto").strip().lower()
    if mode == "basic":
        return _write_status(project, {"status": "skipped", "mode": mode})
    if mode not in {"auto", "advanced"}:
        raise ValueError(f"Unsupported visual enrichment mode: {mode}")

    configured_path = str(config.get("visual_enrichment_config_path") or "").strip()
    config_path = Path(configured_path).expanduser() if configured_path else DEFAULT_CONFIG_PATH
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    config_path = config_path.resolve()
    try:
        _prepare_inputs(project)
        pipeline = VisualEnrichmentPipeline(
            get_project_work_dir(project, get_settings().workspace_dir),
            config_path,
            resume=True,
        )
        try:
            outputs = {}
            outputs.update(pipeline.run_ingest())
            outputs.update(pipeline.run_semantic())
            outputs.update(pipeline.run_plan())
            outputs.update(pipeline.run_generate())
            outputs.update(pipeline.run_qc())
        finally:
            pipeline.close()
        imported = _import_outputs(
            session,
            project,
            provider=pipeline.image.name,
            model_name=str(
                pipeline.config.get("image", {}).get("default_model", "local-image-model")
            ),
        )
        return _write_status(
            project,
            {
                "status": "completed",
                "mode": mode,
                "config_path": str(config_path),
                "outputs": outputs,
                **imported,
            },
        )
    except Exception as exc:
        report = _write_status(
            project,
            {
                "status": "fallback" if mode == "auto" else "failed",
                "mode": mode,
                "config_path": str(config_path),
                "error": str(exc),
            },
        )
        if mode == "advanced":
            raise
        logger.warning("Advanced visual enrichment unavailable; using local SDXL fallback: %s", exc)
        return report


def _prepare_inputs(project: Project) -> None:
    if not project.script_clean_path:
        raise ValueError("Project has no cleaned transcript")
    script_path = Path(project.script_clean_path).expanduser().resolve()
    srt_path = get_final_srt_path(project, get_settings().workspace_dir)
    if not script_path.is_file():
        raise ValueError("Project cleaned transcript does not exist")
    if not srt_path.is_file():
        raise ValueError("Project SRT does not exist")
    input_dir = get_project_work_dir(project, get_settings().workspace_dir) / "input"
    write_text_atomic(input_dir / "transcript.txt", script_path.read_text(encoding="utf-8-sig"))
    write_text_atomic(input_dir / "subtitles.srt", srt_path.read_text(encoding="utf-8-sig"))


def _import_outputs(
    session: Session, project: Project, *, provider: str, model_name: str
) -> dict:
    root = get_project_work_dir(project, get_settings().workspace_dir)
    plan = VisualPlan.model_validate_json(
        (root / "work" / "04_plan" / "visual_plan.json").read_text(encoding="utf-8")
    )
    generations = json.loads(
        (root / "work" / "05_assets" / "generated" / "generations.json").read_text(
            encoding="utf-8"
        )
    )
    qc = json.loads((root / "work" / "06_qc" / "image_qc.json").read_text(encoding="utf-8"))
    approved = {str(item.get("visual_id")) for item in qc if item.get("approved") is True}
    output_by_visual: dict[str, Path] = {}
    for item in generations:
        visual_id = str(item.get("visual_id") or "")
        path = Path(str(item.get("path") or ""))
        if visual_id in approved and visual_id not in output_by_visual and path.is_file():
            output_by_visual[visual_id] = path.resolve()

    scenes = list(
        session.exec(
            select(VisualScene)
            .where(VisualScene.project_id == project.id)
            .order_by(VisualScene.scene_index)
        ).all()
    )
    imported = 0
    enriched = 0
    used_scene_ids: set[str] = set()
    for visual in sorted(plan.visuals, key=lambda item: (-_priority(item.priority), item.start_ms)):
        scene = _best_scene(scenes, visual.start_ms, visual.end_ms, used_scene_ids)
        if scene is None or scene.locked_visual:
            continue
        storyboard = StoryboardContent.model_validate_json(scene.storyboard_json or "{}")
        storyboard.visual_summary = visual.core_claim
        storyboard.visual_type = visual.visual_type.value
        storyboard.scene_category = visual.visual_purpose
        storyboard.mood = visual.visual_brief.mood
        storyboard.primary_query = visual.visual_brief.subject
        storyboard.must_include = list(visual.visual_brief.must_include)
        storyboard.avoid = list(visual.visual_brief.must_avoid)
        storyboard.fact_risk = visual.fact_risk
        storyboard.visual_brief = StoryboardVisualBrief(
            **visual.visual_brief.model_dump(),
            camera="stable documentary camera",
        )
        storyboard.image_prompt = visual.prompt
        storyboard.negative_prompt = visual.negative_prompt
        scene.storyboard_json = storyboard.model_dump_json()
        scene.confidence = max(scene.confidence or 0, 0.8)
        scene.updated_at = utc_now_iso()
        session.add(scene)
        enriched += 1
        used_scene_ids.add(scene.id)

        image_path = output_by_visual.get(visual.visual_id)
        if image_path is None:
            continue
        with Image.open(image_path) as image:
            width, height = image.size
        variant_id = f"{scene.id}:advanced:{visual.visual_id}"
        variant = session.get(GeneratedImageVariant, variant_id) or GeneratedImageVariant(
            id=variant_id,
            project_id=project.id,
            scene_id=scene.id,
            variant_index=0,
            path=str(image_path),
            prompt=visual.prompt,
            negative_prompt=visual.negative_prompt,
            model_path=provider,
            model_name=model_name,
            workflow_version=WORKFLOW_VERSION,
            input_signature=stable_json_hash(visual.model_dump(mode="json")),
            seed=visual.generation.seed_base,
            width=width,
            height=height,
            steps=0,
            guidance_scale=0,
        )
        variant.path = str(image_path)
        variant.status = "completed"
        variant.error_message = None
        variant.updated_at = utc_now_iso()
        session.add(variant)
        session.flush()
        image_generation_service.register_generated_variant(
            session, project, variant, provider=provider
        )
        imported += 1
    session.commit()
    return {"enriched_scene_count": enriched, "imported_image_count": imported}


def _best_scene(
    scenes: list[VisualScene], start_ms: int, end_ms: int, excluded: set[str]
) -> VisualScene | None:
    candidates = [scene for scene in scenes if scene.id not in excluded]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda scene: max(0, min(scene.end_ms, end_ms) - max(scene.start_ms, start_ms)),
    )


def _priority(value: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(value, 0)


def _write_status(project: Project, payload: dict) -> dict:
    path = (
        get_project_work_dir(project, get_settings().workspace_dir)
        / "reports"
        / "advanced_visual_enrichment.json"
    )
    write_json_atomic(path, payload)
    return {**payload, "report_path": str(path)}
