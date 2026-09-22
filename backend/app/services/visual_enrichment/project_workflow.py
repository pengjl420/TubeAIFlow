from __future__ import annotations

import json
import hashlib
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
from app.models.storyboard import SubtitleCue, VisualScene
from app.schemas.storyboard import StoryboardContent, StoryboardVisualBrief
from app.services.image_generation import image_generation_service
from app.services.visual_enrichment.models import SemanticScene, VisualPlan
from app.services.visual_enrichment.pipeline import PROJECT_ROOT, VisualEnrichmentPipeline
from app.services.visual_enrichment.visual_strategy import (
    load_anime_generation_profile,
    stable_visual_beat_id,
    visual_strategy_registry,
)
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
    visual_generation_mode = str(
        config.get("visual_generation_mode") or "curated"
    ).strip().lower()
    if mode not in {"auto", "advanced", "basic"}:
        raise ValueError(f"Unsupported visual enrichment mode: {mode}")
    strategy = visual_strategy_registry.get(visual_generation_mode)
    visual_generation_mode = strategy.metadata.id
    strategy_scene_count = 0
    if visual_generation_mode == "anime_full_coverage" and session is not None:
        strategy_scene_count = len(_formal_anime_scenes(session, project))
    if mode == "basic":
        return _write_status(
            project,
            {
                "status": "skipped",
                "mode": mode,
                "visual_generation_mode": visual_generation_mode,
                "strategy_scene_count": strategy_scene_count,
            },
        )
    if (
        visual_generation_mode == "anime_full_coverage"
        and strategy_scene_count == 0
        and session is not None
    ):
        has_scenes = session.exec(
            select(VisualScene.id).where(VisualScene.project_id == project.id).limit(1)
        ).first()
        if has_scenes is not None:
            return _write_status(
                project,
                {
                    "status": "skipped",
                    "mode": mode,
                    "visual_generation_mode": visual_generation_mode,
                    "strategy_scene_count": 0,
                    "reason": "all_visuals_locked",
                },
            )

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
            visual_generation_mode=visual_generation_mode,
            anime_scenes=(
                _formal_anime_scenes(session, project)
                if visual_generation_mode == "anime_full_coverage"
                else None
            ),
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
                "visual_generation_mode": visual_generation_mode,
                "config_path": str(config_path),
                "outputs": outputs,
                "strategy_scene_count": strategy_scene_count,
                **imported,
            },
        )
    except Exception as exc:
        report = _write_status(
            project,
            {
                "status": "fallback" if mode == "auto" else "failed",
                "mode": mode,
                "visual_generation_mode": visual_generation_mode,
                "config_path": str(config_path),
                "strategy_scene_count": strategy_scene_count,
                "error": str(exc),
            },
        )
        if mode == "advanced":
            raise
        logger.warning("Advanced visual enrichment unavailable; using local SDXL fallback: %s", exc)
        return report


def _formal_anime_scenes(session: Session, project: Project) -> list[SemanticScene]:
    """Derive stable visual beats while preserving the persisted Scene as parent truth."""
    scenes = list(
        session.exec(
            select(VisualScene)
            .where(VisualScene.project_id == project.id)
            .order_by(VisualScene.scene_index)
        ).all()
    )
    cues = list(
        session.exec(
            select(SubtitleCue)
            .where(SubtitleCue.project_id == project.id)
            .order_by(SubtitleCue.start_ms, SubtitleCue.cue_index)
        ).all()
    )
    cues_by_id = {cue.id: cue for cue in cues}
    profile = load_anime_generation_profile(project)
    target_ms = max(1, profile.target_beat_seconds[0]) * 1000
    max_ms = max(profile.target_beat_seconds[1], profile.target_beat_seconds[0]) * 1000
    result: list[SemanticScene] = []
    beat_index = 0
    for scene in scenes:
        if scene.locked_visual:
            continue
        try:
            subtitle_ids = json.loads(scene.subtitle_ids_json or "[]")
        except json.JSONDecodeError:
            subtitle_ids = []
        scene_cues = [
            cues_by_id[str(item)]
            for item in subtitle_ids
            if str(item) in cues_by_id
        ]
        persisted_segment_ids = [str(item) for item in subtitle_ids if str(item).strip()]
        groups: list[tuple[int, int, list[str], str]] = []
        if scene.end_ms - scene.start_ms <= max_ms:
            groups.append(
                (
                    scene.start_ms,
                    scene.end_ms,
                    [cue.id for cue in scene_cues] or persisted_segment_ids or [scene.id],
                    scene.narration,
                )
            )
        elif scene_cues:
            current: list[SubtitleCue] = []
            beat_start = scene.start_ms
            for cue in scene_cues:
                proposed = cue.end_ms - beat_start
                if current and proposed > max_ms:
                    beat_end = current[-1].end_ms
                    groups.append(
                        (
                            beat_start,
                            beat_end,
                            [item.id for item in current],
                            " ".join(item.text.replace("\n", " ") for item in current),
                        )
                    )
                    beat_start = beat_end
                    current = []
                current.append(cue)
                if cue.end_ms - beat_start >= target_ms:
                    groups.append(
                        (
                            beat_start,
                            cue.end_ms,
                            [item.id for item in current],
                            " ".join(item.text.replace("\n", " ") for item in current),
                        )
                    )
                    beat_start = cue.end_ms
                    current = []
            if current:
                groups.append(
                    (
                        beat_start,
                        scene.end_ms,
                        [item.id for item in current],
                        " ".join(item.text.replace("\n", " ") for item in current),
                    )
                )
            elif groups:
                start, _end, ids, narration = groups[-1]
                groups[-1] = (start, scene.end_ms, ids, narration)
        else:
            cursor = scene.start_ms
            while cursor < scene.end_ms:
                end = min(scene.end_ms, cursor + max_ms)
                groups.append((cursor, end, [scene.id], scene.narration))
                cursor = end

        for start_ms, end_ms, segment_ids, narration in groups:
            beat_index += 1
            result.append(SemanticScene(
                scene_id=stable_visual_beat_id(scene.id, start_ms, end_ms),
                parent_scene_id=scene.id,
                chapter_id="project_storyboard",
                start_ms=start_ms,
                end_ms=end_ms,
                segment_ids=segment_ids,
                narration=narration or scene.narration,
                boundary_strength=0.8,
                visualizability=0.8,
                importance=0.75,
                novelty=max(0.55, 0.82 - beat_index * 0.01),
                factual_density=0.55,
                rhetorical_salience=0.7,
                emotion_shift=0.5,
            ))
    return result


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
    complete_anime_scenes: set[str] | None = None
    if plan.strategy == "anime_full_coverage":
        planned_by_scene: dict[str, set[str]] = {}
        for visual in plan.visuals:
            planned_by_scene.setdefault(visual.scene_id, set()).add(visual.visual_id)
        complete_anime_scenes = {
            scene_id
            for scene_id, visual_ids in planned_by_scene.items()
            if visual_ids and visual_ids <= approved
        }
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
    scene_by_id = {scene.id: scene for scene in scenes}
    used_scene_ids: set[str] = set()
    ordered_visuals = (
        sorted(plan.visuals, key=lambda item: item.start_ms)
        if plan.strategy == "anime_full_coverage"
        else sorted(plan.visuals, key=lambda item: (-_priority(item.priority), item.start_ms))
    )
    beat_index_by_scene: dict[str, int] = {}
    for visual in ordered_visuals:
        scene = (
            scene_by_id.get(visual.scene_id)
            if plan.strategy == "anime_full_coverage"
            else _best_scene(scenes, visual.start_ms, visual.end_ms, used_scene_ids)
        )
        if scene is None or scene.locked_visual:
            continue
        if complete_anime_scenes is not None and scene.id not in complete_anime_scenes:
            continue
        if plan.strategy != "anime_full_coverage":
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
        visual_beat_id = visual.visual_beat_id or visual.visual_id
        variant = session.exec(
            select(GeneratedImageVariant).where(
                GeneratedImageVariant.project_id == project.id,
                GeneratedImageVariant.scene_id == scene.id,
                GeneratedImageVariant.visual_beat_id == visual_beat_id,
            )
        ).first()
        if variant is None and beat_index_by_scene.get(scene.id, 0) == 0:
            variant = session.exec(
                select(GeneratedImageVariant).where(
                    GeneratedImageVariant.project_id == project.id,
                    GeneratedImageVariant.scene_id == scene.id,
                    GeneratedImageVariant.variant_index == 0,
                    GeneratedImageVariant.visual_beat_id.is_(None),
                )
            ).first()
        beat_index = beat_index_by_scene.get(scene.id, 0)
        beat_index_by_scene[scene.id] = beat_index + 1
        if variant is None:
            variant = GeneratedImageVariant(
                id=f"{scene.id}:advanced:{hashlib.sha1(visual_beat_id.encode()).hexdigest()[:16]}",
                project_id=project.id,
                scene_id=scene.id,
                visual_beat_id=visual_beat_id,
                variant_index=beat_index,
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
        variant.visual_beat_id = visual_beat_id
        variant.variant_index = beat_index
        variant.prompt = visual.prompt
        variant.negative_prompt = visual.negative_prompt
        variant.model_path = provider
        variant.model_name = model_name
        variant.workflow_version = WORKFLOW_VERSION
        variant.input_signature = stable_json_hash(visual.model_dump(mode="json"))
        variant.seed = visual.generation.seed_base
        variant.width = width
        variant.height = height
        variant.steps = 0
        variant.guidance_scale = 0
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
    versioned_payload = {"schema_version": 1, **payload}
    write_json_atomic(path, versioned_payload)
    return {**versioned_payload, "report_path": str(path)}
