import json
import logging
import math
import uuid

from pydantic import ValidationError
from sqlalchemy import delete
from sqlmodel import Session, select

from app.config import get_settings
from app.infrastructure.atomic_files import write_json_atomic
from app.infrastructure.project_layout import (
    ensure_project_dirs,
    get_output_stem,
    get_project_work_dir,
)
from app.providers.llm import JSONLLMProvider, build_storyboard_llm, invoke_json
from app.models.narration import Segment
from app.models.media import GeneratedImageVariant, SceneAssignment
from app.models.project import Project
from app.models.storyboard import SceneRevision, SubtitleCue, VisualScene
from app.schemas.storyboard import StoryboardBatchResult, StoryboardContent
from app.services.storyboard.query_builder import normalize_storyboard
from app.services.storyboard.scene_grouper import GROUPING_PROMPT_VERSION, group_cues
from app.services.projects import project_service
from app.shared.time import utc_now_iso


STORYBOARD_PROMPT_VERSION = "documentary-storyboard-v2"
SCENES_PER_REQUEST = 8
STORYBOARD_LIST_FIELDS = (
    "entities",
    "locations",
    "alternative_queries",
    "must_include",
    "avoid",
)
STORYBOARD_TEN_POINT_FIELDS = (
    "importance_score",
    "motion_score",
    "identity_risk",
    "text_density",
)

logger = logging.getLogger(__name__)


def generate_storyboard(
    session: Session,
    project: Project,
    client: JSONLLMProvider | None = None,
) -> dict:
    cues = _load_narration_units(session, project.id)
    if not cues:
        raise ValueError("请先完成分段配音")
    llm_client = client or build_storyboard_llm(project.id)
    storyboard_mode = project_service.get_storyboard_mode(project)
    full_script = "\n".join(cue["text"] for cue in cues)
    if storyboard_mode == project_service.STORYBOARD_MODE_SEGMENTS:
        cue_groups = _group_cues_by_segment(cues)
        warnings = []
    else:
        cue_groups, warnings = group_cues(cues, llm_client, full_script)
    scene_values = _build_scene_values(project.id, cue_groups)
    if storyboard_mode == project_service.STORYBOARD_MODE_SEGMENTS:
        for scene, visual_hint in zip(
            scene_values,
            _load_segment_visual_hints(project),
            strict=False,
        ):
            if visual_hint:
                scene["visual_hint"] = visual_hint
    storyboard_by_scene = _generate_storyboard_content(
        scene_values,
        llm_client,
        full_script=full_script if storyboard_mode == project_service.STORYBOARD_MODE_AI else "",
        scenes_per_request=1
        if storyboard_mode == project_service.STORYBOARD_MODE_SEGMENTS
        else SCENES_PER_REQUEST,
    )

    existing_scenes = {
        scene.id: scene
        for scene in session.exec(
            select(VisualScene).where(VisualScene.project_id == project.id)
        ).all()
    }
    generated_ids = {value["id"] for value in scene_values}
    stale_locked = [
        scene.scene_index
        for scene_id, scene in existing_scenes.items()
        if scene_id not in generated_ids
        and (scene.locked_text or scene.locked_audio or scene.locked_visual)
    ]
    if stale_locked:
        indexes = ", ".join(str(index) for index in stale_locked)
        raise ValueError(f"Scene {indexes} is locked; unlock it before regrouping Storyboard")
    changed_locked = [
        existing.scene_index
        for value in scene_values
        if (existing := existing_scenes.get(value["id"]))
        and _locked_scene_membership_changed(existing, value)
    ]
    if changed_locked:
        indexes = ", ".join(str(index) for index in changed_locked)
        raise ValueError(
            f"Scene {indexes} is locked and its subtitle grouping changed; "
            "unlock it before regrouping Storyboard"
        )
    now = utc_now_iso()
    for value in scene_values:
        content = storyboard_by_scene[value["id"]]
        content_json = content.model_dump_json()
        existing = existing_scenes.get(value["id"])
        if existing:
            _save_revision(session, existing, "workflow_regenerate")
            existing.start_ms = value["start_ms"]
            existing.end_ms = value["end_ms"]
            existing.subtitle_ids_json = value["subtitle_ids_json"]
            if not existing.locked_text:
                existing.narration = value["narration"]
            if not existing.locked_visual:
                if existing.storyboard_json != content_json:
                    _invalidate_scene_visual_records(session, existing.id)
                existing.storyboard_json = content_json
                existing.confidence = content.confidence
                existing.status = "generated"
            existing.version += 1
            existing.updated_at = now
            session.add(existing)
        else:
            session.add(
                VisualScene(
                    **value,
                    storyboard_json=content_json,
                    confidence=content.confidence,
                    status="generated",
                    created_at=now,
                    updated_at=now,
                )
            )
    for scene_id, existing in existing_scenes.items():
        if scene_id not in generated_ids:
            session.exec(delete(SceneAssignment).where(SceneAssignment.scene_id == scene_id))
            session.exec(
                delete(GeneratedImageVariant).where(GeneratedImageVariant.scene_id == scene_id)
            )
            session.exec(delete(SceneRevision).where(SceneRevision.scene_id == scene_id))
            session.delete(existing)
    session.commit()

    scenes = list_scenes(session, project.id)
    artifact_path = _write_artifact(project, scenes, warnings, llm_client)
    return {
        "scenes": scenes,
        "warnings": warnings,
        "provider": getattr(llm_client, "name", "llm.extension"),
        "model": getattr(llm_client, "model", get_settings().deepseek_model),
        "routing": list(getattr(llm_client, "routes", [])),
        "path": str(artifact_path),
    }


def list_scenes(session: Session, project_id: str) -> list[dict]:
    scenes = session.exec(
        select(VisualScene)
        .where(VisualScene.project_id == project_id)
        .order_by(VisualScene.scene_index)
    ).all()
    return [_serialize_scene(scene) for scene in scenes]


def update_scene(
    session: Session,
    project: Project,
    scene_id: str,
    *,
    narration: str | None = None,
    storyboard: StoryboardContent | None = None,
    status: str | None = None,
    locked_text: bool | None = None,
    locked_audio: bool | None = None,
    locked_visual: bool | None = None,
) -> dict:
    scene = session.get(VisualScene, scene_id)
    if not scene or scene.project_id != project.id:
        raise LookupError("Scene not found")
    original_snapshot = json.dumps(_serialize_scene(scene), ensure_ascii=False)
    changed = False
    derived_outputs_changed = False
    if narration is not None:
        normalized_narration = narration.strip()
        if not normalized_narration:
            raise ValueError("Scene narration cannot be empty")
        if normalized_narration != scene.narration:
            if scene.locked_text:
                raise ValueError("Scene text is locked")
            scene.narration = normalized_narration
            changed = True
            derived_outputs_changed = True
    if storyboard is not None:
        serialized_storyboard = storyboard.model_dump_json()
        if serialized_storyboard != scene.storyboard_json:
            if scene.locked_visual:
                raise ValueError("Scene visual is locked")
            scene.storyboard_json = serialized_storyboard
            scene.confidence = storyboard.confidence
            changed = True
            derived_outputs_changed = True
    if status is not None:
        normalized_status = status.strip().lower()
        if normalized_status not in {"draft", "generated", "reviewed"}:
            raise ValueError("Unsupported Scene status")
        if scene.status != normalized_status:
            scene.status = normalized_status
            changed = True
    for field_name, value in (
        ("locked_text", locked_text),
        ("locked_audio", locked_audio),
        ("locked_visual", locked_visual),
    ):
        if value is not None and getattr(scene, field_name) != value:
            setattr(scene, field_name, value)
            changed = True
    if not changed:
        return _serialize_scene(scene)
    _save_revision(session, scene, "manual_edit", snapshot_json=original_snapshot)
    scene.version += 1
    scene.updated_at = utc_now_iso()
    project.updated_at = scene.updated_at
    session.add(scene)
    session.add(project)
    session.commit()
    session.refresh(scene)
    if derived_outputs_changed:
        from app.services.storyboard.scene_workspace_service import invalidate_scene_outputs

        invalidate_scene_outputs(project, scene)
    scenes = list_scenes(session, project.id)
    _refresh_artifact_after_manual_edit(project, scenes)
    return _serialize_scene(scene)


def list_scene_revisions(session: Session, project_id: str, scene_id: str) -> list[dict]:
    scene = session.get(VisualScene, scene_id)
    if not scene or scene.project_id != project_id:
        raise LookupError("Scene not found")
    revisions = session.exec(
        select(SceneRevision)
        .where(SceneRevision.scene_id == scene_id)
        .order_by(SceneRevision.version.desc())
    ).all()
    return [
        {
            "id": revision.id,
            "scene_id": revision.scene_id,
            "version": revision.version,
            "change_type": revision.change_type,
            "created_at": revision.created_at,
        }
        for revision in revisions
    ]


def restore_scene_revision(
    session: Session, project: Project, scene_id: str, revision_id: str
) -> dict:
    scene = session.get(VisualScene, scene_id)
    revision = session.get(SceneRevision, revision_id)
    if (
        not scene
        or scene.project_id != project.id
        or not revision
        or revision.project_id != project.id
        or revision.scene_id != scene.id
    ):
        raise LookupError("Scene revision not found")
    snapshot = json.loads(revision.snapshot_json)
    _save_revision(session, scene, "before_restore")
    scene.narration = str(snapshot["narration"])
    storyboard = snapshot.get("storyboard")
    scene.storyboard_json = (
        StoryboardContent.model_validate(storyboard).model_dump_json() if storyboard else None
    )
    scene.confidence = snapshot.get("confidence")
    scene.status = str(snapshot.get("status") or "draft")
    scene.locked_text = bool(snapshot.get("locked_text", False))
    scene.locked_audio = bool(snapshot.get("locked_audio", False))
    scene.locked_visual = bool(snapshot.get("locked_visual", False))
    scene.version += 1
    scene.updated_at = utc_now_iso()
    project.updated_at = scene.updated_at
    session.add(scene)
    session.add(project)
    session.commit()
    session.refresh(scene)
    from app.services.storyboard.scene_workspace_service import invalidate_scene_outputs

    invalidate_scene_outputs(project, scene)
    scenes = list_scenes(session, project.id)
    _refresh_artifact_after_manual_edit(project, scenes)
    return _serialize_scene(scene)


def regenerate_scene(
    session: Session,
    project: Project,
    scene_id: str,
    client: JSONLLMProvider | None = None,
) -> dict:
    scene = session.get(VisualScene, scene_id)
    if not scene or scene.project_id != project.id:
        raise LookupError("Scene not found")
    if scene.locked_visual:
        raise ValueError("Scene visual is locked")
    llm_client = client or build_storyboard_llm(project.id)
    all_scenes = session.exec(
        select(VisualScene)
        .where(VisualScene.project_id == project.id)
        .order_by(VisualScene.scene_index)
    ).all()
    content = _generate_storyboard_content(
        [
            {
                "id": scene.id,
                "start_ms": scene.start_ms,
                "end_ms": scene.end_ms,
                "narration": scene.narration,
            }
        ],
        llm_client,
        full_script="\n".join(item.narration for item in all_scenes),
        scenes_per_request=1,
    )[scene.id]
    _save_revision(session, scene, "before_regenerate")
    scene.storyboard_json = content.model_dump_json()
    scene.confidence = content.confidence
    scene.status = "generated"
    scene.version += 1
    scene.updated_at = utc_now_iso()
    project.updated_at = scene.updated_at
    _invalidate_scene_visual_records(session, scene.id)
    session.add(scene)
    session.add(project)
    session.commit()
    session.refresh(scene)
    from app.services.storyboard.scene_workspace_service import invalidate_scene_outputs

    invalidate_scene_outputs(project, scene)
    scenes = list_scenes(session, project.id)
    _refresh_artifact_after_manual_edit(project, scenes)
    return _serialize_scene(scene)


def _invalidate_scene_visual_records(session: Session, scene_id: str) -> None:
    """Detach rendered choices and make candidates from an older brief unselectable."""
    session.exec(delete(SceneAssignment).where(SceneAssignment.scene_id == scene_id))
    variants = session.exec(
        select(GeneratedImageVariant).where(GeneratedImageVariant.scene_id == scene_id)
    ).all()
    for variant in variants:
        variant.status = "stale"
        variant.updated_at = utc_now_iso()
        session.add(variant)


def _save_revision(
    session: Session,
    scene: VisualScene,
    change_type: str,
    *,
    snapshot_json: str | None = None,
) -> None:
    session.add(
        SceneRevision(
            id=uuid.uuid4().hex,
            project_id=scene.project_id,
            scene_id=scene.id,
            version=scene.version,
            change_type=change_type,
            snapshot_json=snapshot_json or json.dumps(_serialize_scene(scene), ensure_ascii=False),
        )
    )


def _load_narration_units(session: Session, project_id: str) -> list[dict]:
    """Build private scene timing directly from real narration durations.

    These units are workflow inputs only; no subtitle cues or public timeline
    artifact is created.
    """
    segments = session.exec(
        select(Segment).where(Segment.project_id == project_id).order_by(Segment.segment_index)
    ).all()
    if not segments:
        # Read-only compatibility for projects created before subtitle/timeline
        # generation was removed. New projects never create these rows.
        legacy_cues = session.exec(
            select(SubtitleCue)
            .where(SubtitleCue.project_id == project_id)
            .order_by(SubtitleCue.start_ms, SubtitleCue.cue_index)
        ).all()
        return [
            {
                "id": cue.id,
                "start_ms": cue.start_ms,
                "end_ms": cue.end_ms,
                "text": cue.text,
                "source_segment_id": cue.source_segment_id,
            }
            for cue in legacy_cues
        ]
    units: list[dict] = []
    cursor_ms = 0
    for segment in segments:
        duration_ms = round(float(segment.duration or 0) * 1000)
        if duration_ms <= 0:
            raise ValueError(f"配音分段 {segment.segment_id} 缺少有效音频时长")
        units.append(
            {
                "id": segment.id,
                "start_ms": cursor_ms,
                "end_ms": cursor_ms + duration_ms,
                "text": segment.text,
                "source_segment_id": segment.id,
            }
        )
        cursor_ms += duration_ms
    return units


def _group_cues_by_segment(cues: list[dict]) -> list[list[dict]]:
    """Keep all subtitle cues derived from one narration segment in one visual scene."""
    groups: list[list[dict]] = []
    for cue in cues:
        if groups and groups[-1][-1]["source_segment_id"] == cue["source_segment_id"]:
            groups[-1].append(cue)
        else:
            groups.append([cue])
    return groups


def _build_scene_values(project_id: str, cue_groups: list[list[dict]]) -> list[dict]:
    values = []
    for index, cues in enumerate(cue_groups, start=1):
        values.append(
            {
                "id": f"{project_id}:scene_{index:04d}",
                "project_id": project_id,
                "scene_index": index,
                "start_ms": cues[0]["start_ms"],
                "end_ms": cues[-1]["end_ms"],
                "narration": " ".join(cue["text"].replace("\n", " ").strip() for cue in cues),
                "subtitle_ids_json": json.dumps([cue["id"] for cue in cues], ensure_ascii=False),
            }
        )
    return values


def _locked_scene_membership_changed(scene: VisualScene, value: dict) -> bool:
    subtitle_changed = scene.subtitle_ids_json != value["subtitle_ids_json"]
    narration_changed = scene.narration != value["narration"]
    timing_changed = scene.start_ms != value["start_ms"] or scene.end_ms != value["end_ms"]
    if scene.locked_audio and (subtitle_changed or timing_changed):
        return True
    if scene.locked_text and (subtitle_changed or narration_changed):
        return True
    if scene.locked_visual and (subtitle_changed or narration_changed):
        return True
    return False


def _load_segment_visual_hints(project: Project) -> list[str]:
    """Reuse full-context visual ideas emitted during AI transcript segmentation."""
    path = (
        get_project_work_dir(project, get_settings().workspace_dir)
        / "segments"
        / f"{get_output_stem(project)}_segments.json"
    )
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [
        str(item.get("visual_description") or "").strip() if isinstance(item, dict) else ""
        for item in payload
    ]


def _generate_storyboard_content(
    scene_values: list[dict],
    client: JSONLLMProvider,
    *,
    full_script: str = "",
    scenes_per_request: int = SCENES_PER_REQUEST,
) -> dict[str, StoryboardContent]:
    result: dict[str, StoryboardContent] = {}
    for offset in range(0, len(scene_values), scenes_per_request):
        batch = scene_values[offset : offset + scenes_per_request]
        parsed = _request_storyboard_batch(batch, client, full_script)
        expected_ids = {scene["id"] for scene in batch}
        actual_ids = {scene.scene_id for scene in parsed.scenes}
        if actual_ids != expected_ids or len(parsed.scenes) != len(batch):
            raise ValueError("LLM 返回的 Storyboard 场景 ID 不完整")
        for scene in parsed.scenes:
            content = StoryboardContent.model_validate(scene.model_dump(exclude={"scene_id"}))
            result[scene.scene_id] = normalize_storyboard(content)
    return result


def _request_storyboard_batch(
    batch: list[dict], client: JSONLLMProvider, full_script: str = ""
) -> StoryboardBatchResult:
    system_prompt = _storyboard_system_prompt()
    user_prompt = _storyboard_user_prompt(batch, full_script)
    raw_payload = invoke_json(
        client,
        system_prompt,
        user_prompt,
        schema=StoryboardBatchResult.model_json_schema(),
        task="storyboard",
    )
    try:
        return StoryboardBatchResult.model_validate(_normalize_llm_storyboard_payload(raw_payload))
    except ValidationError as exc:
        logger.warning("Storyboard response validation failed; requesting one repair: %s", exc)
        repaired_payload = invoke_json(
            client,
            system_prompt,
            _storyboard_repair_prompt(batch, raw_payload, exc, full_script),
            schema=StoryboardBatchResult.model_json_schema(),
            task="storyboard-repair",
        )
        return StoryboardBatchResult.model_validate(
            _normalize_llm_storyboard_payload(repaired_payload)
        )


def _normalize_llm_storyboard_payload(payload: dict) -> dict:
    """Repair safe, unambiguous LLM variations before strict validation."""
    if not isinstance(payload, dict) or not isinstance(payload.get("scenes"), list):
        return payload

    normalized = dict(payload)
    normalized_scenes = []
    for scene in payload["scenes"]:
        if not isinstance(scene, dict):
            normalized_scenes.append(scene)
            continue
        normalized_scene = dict(scene)
        for field_name in STORYBOARD_LIST_FIELDS:
            value = normalized_scene.get(field_name)
            if value is None:
                normalized_scene[field_name] = []
            elif isinstance(value, str):
                value = value.strip()
                normalized_scene[field_name] = [value] if value else []
        for field_name in STORYBOARD_TEN_POINT_FIELDS:
            value = normalized_scene.get(field_name)
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and 10 < value <= 100
            ):
                # Models sometimes use a percentage scale despite the requested
                # ten-point scale. Half-up rounding preserves values such as 85 as 9.
                normalized_scene[field_name] = math.floor(value / 10 + 0.5)
        normalized_scenes.append(normalized_scene)
    normalized["scenes"] = normalized_scenes
    return normalized


def _storyboard_system_prompt() -> str:
    return """
You are a documentary storyboard editor and stock-footage search expert.
Return JSON only, with root format {"scenes":[...]}.
For every input scene return exactly one object using the same scene_id and these fields:
scene_id, visual_summary, visual_type, entities, locations, time_period, scene_category,
mood, shot_preference, primary_query, alternative_queries, fallback_category,
fallback_mood, allow_landscape_fallback, must_include, avoid, confidence.
Also return recommended_source, fact_risk and visual_brief. recommended_source should be one of
stock_video, archive, generated_image, generated_video, chart, map, timeline, document or text_card.
fact_risk must be none, low, medium or high. visual_brief must contain subject, action,
environment, semantic_message, composition, camera, era, mood, must_include and must_avoid.
Describe visible, verifiable content rather than merely restating the narration. Keep visual_brief
provider-neutral; do not add model names, quality buzzwords or rendering parameters.
Also return motion_prompt, scene_type, importance_score, motion_score, identity_risk,
text_density and subject_count. motion_prompt describes only subtle subject/environment/camera
motion plus identity consistency constraints; do not repeat image style keywords.
importance_score, motion_score, identity_risk and text_density MUST be integers from 0 to 10,
never percentages from 0 to 100. importance_score measures narrative importance; motion_score
measures how much natural subject or environmental motion benefits the scene; identity_risk
measures the risk that generated motion changes a recognizable person, brand or object;
text_density measures the amount of text that must remain legible. subject_count MUST be an
integer from 0 to 20. Example: {"importance_score":8,"motion_score":4,"identity_risk":6,
"text_density":0,"subject_count":1}.
entities, locations, alternative_queries, must_include and avoid MUST always be JSON arrays
of strings. Use [] when there are no values. Never return a single string for these fields.
All visual descriptions and search queries must be concise English suitable for stock-footage search.
Use concrete visible subjects, actions, settings and eras. Do not translate or rewrite narration.
Do not claim a person's identity when it cannot be visually verified.
alternative_queries must contain 1-3 progressively broader English queries.
confidence must be a number from 0 to 1.
allow_landscape_fallback must be false for concrete people, brands, products, landmarks,
locations or historical events whose visible subject is essential; otherwise it may be true
for transitions, time passing, reflection, summaries and abstract emotional narration.
Example field shapes:
{"entities":[],"locations":[],"alternative_queries":["shipping terminal workers"],
"must_include":["container terminal"],"avoid":["close-ups of individuals"],
"allow_landscape_fallback":false,"confidence":0.82}
""".strip()


def _storyboard_user_prompt(scene_values: list[dict], full_script: str = "") -> str:
    payload = [
        {
            "scene_id": scene["id"],
            "start_ms": scene["start_ms"],
            "end_ms": scene["end_ms"],
            "narration": scene["narration"],
            **(
                {"suggested_visual_description": scene["visual_hint"]}
                if scene.get("visual_hint")
                else {}
            ),
        }
        for scene in scene_values
    ]
    request = {"scenes": payload}
    if full_script:
        request["full_script_context"] = _compact_script_context(full_script)
    return json.dumps(request, ensure_ascii=False)


def _compact_script_context(script: str, limit: int = 6000) -> str | dict:
    text = script.strip()
    if len(text) <= limit:
        return text
    side = limit // 2
    return {
        "total_characters": len(text),
        "opening": text[:side],
        "closing": text[-side:],
        "context_policy": "hierarchical_excerpt_v1",
    }


def _storyboard_repair_prompt(
    scene_values: list[dict],
    raw_payload: dict,
    validation_error: ValidationError,
    full_script: str = "",
) -> str:
    return json.dumps(
        {
            "instruction": (
                "Repair the previous response so it exactly matches the required JSON schema. "
                "Return JSON only, keep every scene_id unchanged, and do not omit scenes. "
                "importance_score, motion_score, identity_risk and text_density must each be "
                "an integer from 0 to 10, never a percentage from 0 to 100. subject_count must "
                "be an integer from 0 to 20, and confidence must be a number from 0 to 1."
            ),
            "required_scenes": json.loads(_storyboard_user_prompt(scene_values, full_script))[
                "scenes"
            ],
            "validation_errors": validation_error.errors(
                include_url=False, include_context=False, include_input=False
            ),
            "previous_response": raw_payload,
        },
        ensure_ascii=False,
    )


def _serialize_scene(scene: VisualScene) -> dict:
    storyboard = None
    if scene.storyboard_json:
        storyboard = StoryboardContent.model_validate_json(scene.storyboard_json).model_dump()
    return {
        "id": scene.id,
        "project_id": scene.project_id,
        "scene_index": scene.scene_index,
        "start_ms": scene.start_ms,
        "end_ms": scene.end_ms,
        "narration": scene.narration,
        "subtitle_ids": json.loads(scene.subtitle_ids_json),
        "storyboard": storyboard,
        "confidence": scene.confidence,
        "status": scene.status,
        "locked_text": scene.locked_text,
        "locked_audio": scene.locked_audio,
        "locked_visual": scene.locked_visual,
        "version": scene.version,
    }


def _write_artifact(
    project: Project,
    scenes: list[dict],
    warnings: list[str],
    client: JSONLLMProvider,
):
    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(base_dir)
    path = base_dir / "storyboard" / "scenes.json"
    payload = {
        "project_id": project.id,
        "provider": getattr(client, "name", "llm.extension"),
        "model": getattr(client, "model", get_settings().deepseek_model),
        "routing": list(getattr(client, "routes", [])),
        "grouping_prompt_version": GROUPING_PROMPT_VERSION,
        "storyboard_prompt_version": STORYBOARD_PROMPT_VERSION,
        "storyboard_mode": project_service.get_storyboard_mode(project),
        "generated_at": utc_now_iso(),
        "warnings": warnings,
        "scenes": scenes,
    }
    write_json_atomic(path, payload)
    return path


def _refresh_artifact_after_manual_edit(project: Project, scenes: list[dict]) -> None:
    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(base_dir)
    path = base_dir / "storyboard" / "scenes.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.update(
        {
            "project_id": project.id,
            "updated_at": utc_now_iso(),
            "scenes": scenes,
        }
    )
    write_json_atomic(path, payload)
