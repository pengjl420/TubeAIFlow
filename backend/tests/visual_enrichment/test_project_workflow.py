import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.project import Project
from app.services.visual_enrichment import project_workflow


def _project(root: Path, mode: str) -> Project:
    return Project(
        id="project-visual",
        name="Visual Project",
        output_dir=str(root),
        config_json=json.dumps(
            {
                "project_directory_name": "Visual Project",
                "visual_enrichment_mode": mode,
            }
        ),
    )


def test_auto_mode_records_fallback_when_advanced_stack_is_unavailable(tmp_path: Path) -> None:
    project = _project(tmp_path, "auto")
    with patch.object(
        project_workflow, "get_settings", return_value=SimpleNamespace(workspace_dir=tmp_path)
    ):
        report = project_workflow.enrich_project_visuals(None, project)  # type: ignore[arg-type]

    assert report["status"] == "fallback"
    assert "cleaned transcript" in report["error"]
    assert Path(report["report_path"]).is_file()


def test_advanced_mode_surfaces_setup_failure(tmp_path: Path) -> None:
    project = _project(tmp_path, "advanced")
    with (
        patch.object(
            project_workflow,
            "get_settings",
            return_value=SimpleNamespace(workspace_dir=tmp_path),
        ),
        pytest.raises(ValueError, match="cleaned transcript"),
    ):
        project_workflow.enrich_project_visuals(None, project)  # type: ignore[arg-type]


def test_basic_anime_mode_composes_style_without_mutating_storyboard(tmp_path: Path) -> None:
    from sqlmodel import Session, SQLModel, create_engine

    from app.models.storyboard import VisualScene
    from app.schemas.storyboard import StoryboardContent
    from app.services.visual_enrichment.visual_strategy import compose_image_prompts

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    project = _project(tmp_path, "basic")
    config = json.loads(project.config_json)
    config["visual_generation_mode"] = "anime_full_coverage"
    project.config_json = json.dumps(config)
    scene = VisualScene(
        id="scene-anime",
        project_id=project.id,
        scene_index=1,
        start_ms=0,
        end_ms=8_000,
        narration="人物穿过雨夜城市。",
        storyboard_json=json.dumps(
            {
                "visual_summary": "人物穿过雨夜城市",
                "visual_type": "cinematic_scene",
                "scene_category": "story",
                "mood": "tense",
                "shot_preference": "wide",
                "primary_query": "rainy city",
                "fallback_category": "city",
                "fallback_mood": "tense",
                "confidence": 0.8,
            },
            ensure_ascii=False,
        ),
    )
    with Session(engine) as session:
        session.add_all([project, scene])
        session.commit()
        original_storyboard = scene.storyboard_json
        report = project_workflow.enrich_project_visuals(session, project)
        session.refresh(scene)

    engine.dispose()
    assert report["strategy_scene_count"] == 1
    assert scene.storyboard_json == original_storyboard
    prompt, negative = compose_image_prompts(
        project,
        StoryboardContent.model_validate_json(scene.storyboard_json),
        "configured negative",
    )
    assert "SERIES ART DIRECTION" in prompt
    assert "3-6 seconds" in prompt
    assert "photorealistic" in negative
    config["visual_generation_mode"] = "curated"
    project.config_json = json.dumps(config)
    curated_prompt, _ = compose_image_prompts(
        project,
        StoryboardContent.model_validate_json(scene.storyboard_json),
        "configured negative",
    )
    assert "SERIES ART DIRECTION" not in curated_prompt
    assert "photorealistic" in curated_prompt


def test_anime_pipeline_uses_persisted_scene_ids_and_boundaries(tmp_path: Path) -> None:
    from sqlmodel import Session, SQLModel, create_engine

    from app.models.storyboard import VisualScene

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    project = _project(tmp_path, "auto")
    scenes = [
        VisualScene(
            id="formal-scene-a",
            project_id=project.id,
            scene_index=1,
            start_ms=0,
            end_ms=15_000,
            narration="第一幕",
            subtitle_ids_json='["cue-a"]',
        ),
        VisualScene(
            id="formal-scene-b",
            project_id=project.id,
            scene_index=2,
            start_ms=15_000,
            end_ms=30_000,
            narration="第二幕",
            subtitle_ids_json='["cue-b"]',
        ),
        VisualScene(
            id="formal-scene-locked",
            project_id=project.id,
            scene_index=3,
            start_ms=30_000,
            end_ms=38_000,
            narration="Locked scene",
            locked_visual=True,
        ),
    ]
    with Session(engine) as session:
        session.add_all([project, *scenes])
        session.commit()
        formal = project_workflow._formal_anime_scenes(session, project)

    engine.dispose()
    assert [scene.parent_scene_id for scene in formal] == ["formal-scene-a", "formal-scene-b"]
    assert all(":beat:" in scene.scene_id for scene in formal)
    assert [(scene.start_ms, scene.end_ms) for scene in formal] == [
        (0, 15_000),
        (15_000, 30_000),
    ]
    assert [scene.segment_ids for scene in formal] == [["cue-a"], ["cue-b"]]


def test_long_formal_scene_is_derived_into_contiguous_anime_beats(tmp_path: Path) -> None:
    from sqlmodel import Session, SQLModel, create_engine

    from app.models.storyboard import SubtitleCue, VisualScene

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    project = _project(tmp_path, "auto")
    cues = [
        SubtitleCue(
            id=f"cue-{index}", project_id=project.id, source_segment_id=f"segment-{index}",
            cue_index=index, start_ms=index * 6_000, end_ms=(index + 1) * 6_000,
            text=f"Beat {index}",
        )
        for index in range(5)
    ]
    scene = VisualScene(
        id="long-scene", project_id=project.id, scene_index=1,
        start_ms=0, end_ms=30_000, narration=" ".join(cue.text for cue in cues),
        subtitle_ids_json=json.dumps([cue.id for cue in cues]),
    )
    with Session(engine) as session:
        session.add_all([project, scene, *cues])
        session.commit()
        beats = project_workflow._formal_anime_scenes(session, project)

    engine.dispose()
    assert len(beats) >= 2
    assert beats[0].start_ms == scene.start_ms
    assert beats[-1].end_ms == scene.end_ms
    assert all(left.end_ms == right.start_ms for left, right in zip(beats, beats[1:]))
    assert all(beat.parent_scene_id == scene.id for beat in beats)
    assert all(beat.end_ms - beat.start_ms <= 15_000 for beat in beats)


def test_advanced_import_reuses_the_scene_zero_variant_slot(tmp_path: Path) -> None:
    from PIL import Image
    from sqlmodel import Session, SQLModel, create_engine, select

    from app.infrastructure.project_layout import get_project_work_dir
    from app.models.media import GeneratedImageVariant
    from app.models.storyboard import VisualScene
    from app.services.visual_enrichment.models import VisualCandidate, VisualType
    from app.services.visual_enrichment.planning import build_anime_visual_plan

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    project = _project(tmp_path, "auto")
    config = json.loads(project.config_json)
    config["visual_generation_mode"] = "anime_full_coverage"
    project.config_json = json.dumps(config)
    scene = VisualScene(
        id="scene-slot",
        project_id=project.id,
        scene_index=1,
        start_ms=0,
        end_ms=8_000,
        narration="A new scene",
    )
    old_variant = GeneratedImageVariant(
        id="legacy-advanced-id",
        project_id=project.id,
        scene_id=scene.id,
        variant_index=0,
        path=str(tmp_path / "old.png"),
        prompt="old prompt",
        model_path="old-provider",
        input_signature="old",
        seed=1,
        width=16,
        height=16,
        steps=0,
        guidance_scale=0,
        status="stale",
        workflow_version="advanced_visual_pipeline_v1",
    )
    candidate = VisualCandidate(
        candidate_id="candidate",
        scene_id=scene.id,
        start_ms=0,
        end_ms=8_000,
        trigger_ms=0,
        voiceover=scene.narration,
        boundary_strength=0.8,
        visualizability=0.8,
        importance=0.8,
        novelty=0.8,
        factual_density=0.5,
        rhetorical_salience=0.7,
        emotion_shift=0.5,
        duplicate_penalty=0,
        score=0.8,
        visual_type_hint=VisualType.CONCEPTUAL_ILLUSTRATION,
    )
    plan = build_anime_visual_plan(project.id, 8_000, [candidate])
    settings = SimpleNamespace(workspace_dir=tmp_path)
    root = get_project_work_dir(project, settings.workspace_dir)
    image_path = root / "generated.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 18), "navy").save(image_path)
    plan_path = root / "work" / "04_plan" / "visual_plan.json"
    generation_path = root / "work" / "05_assets" / "generated" / "generations.json"
    qc_path = root / "work" / "06_qc" / "image_qc.json"
    for path in (plan_path, generation_path, qc_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(plan.model_dump_json(), encoding="utf-8")
    visual_id = plan.visuals[0].visual_id
    generation_path.write_text(
        json.dumps([{"visual_id": visual_id, "path": str(image_path)}]), encoding="utf-8"
    )
    qc_path.write_text(
        json.dumps([{"visual_id": visual_id, "approved": True}]), encoding="utf-8"
    )

    with Session(engine) as session, patch.object(
        project_workflow, "get_settings", return_value=settings
    ):
        session.add_all([project, scene, old_variant])
        session.commit()
        result = project_workflow._import_outputs(
            session, project, provider="flux", model_name="flux-model"
        )
        variants = session.exec(
            select(GeneratedImageVariant).where(GeneratedImageVariant.scene_id == scene.id)
        ).all()

    engine.dispose()
    assert result["imported_image_count"] == 1
    assert len(variants) == 1
    assert variants[0].id == "legacy-advanced-id"
    assert variants[0].status == "completed"
    assert variants[0].prompt == plan.visuals[0].prompt
