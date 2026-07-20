import json
import logging

from pydantic import ValidationError
from sqlalchemy import delete
from sqlmodel import Session, select

from app.config import get_settings
from app.infrastructure.file_storage import project_dir
from app.infrastructure.project_layout import ensure_project_dirs
from app.integrations.llm.deepseek import DeepSeekClient
from app.models.project import Project
from app.models.storyboard import SubtitleCue, VisualScene
from app.schemas.storyboard import StoryboardBatchResult, StoryboardContent
from app.services.storyboard.query_builder import normalize_storyboard
from app.services.storyboard.scene_grouper import GROUPING_PROMPT_VERSION, group_cues
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

logger = logging.getLogger(__name__)


def generate_storyboard(
    session: Session,
    project: Project,
    client: DeepSeekClient | None = None,
) -> dict:
    cues = _load_cues(session, project.id)
    if not cues:
        raise ValueError("请先导入或生成 SRT 字幕")
    llm_client = client or DeepSeekClient()
    cue_groups, warnings = group_cues(cues, llm_client)
    scene_values = _build_scene_values(project.id, cue_groups)
    storyboard_by_scene = _generate_storyboard_content(scene_values, llm_client)

    session.exec(delete(VisualScene).where(VisualScene.project_id == project.id))
    now = utc_now_iso()
    for value in scene_values:
        content = storyboard_by_scene[value["id"]]
        session.add(
            VisualScene(
                **value,
                storyboard_json=content.model_dump_json(),
                confidence=content.confidence,
                status="generated",
                created_at=now,
                updated_at=now,
            )
        )
    session.commit()

    scenes = list_scenes(session, project.id)
    artifact_path = _write_artifact(project, scenes, warnings)
    return {
        "scenes": scenes,
        "warnings": warnings,
        "model": get_settings().deepseek_model,
        "path": str(artifact_path),
    }


def list_scenes(session: Session, project_id: str) -> list[dict]:
    scenes = session.exec(
        select(VisualScene)
        .where(VisualScene.project_id == project_id)
        .order_by(VisualScene.scene_index)
    ).all()
    return [_serialize_scene(scene) for scene in scenes]


def update_scene_storyboard(
    session: Session,
    project: Project,
    scene_id: str,
    content: StoryboardContent,
) -> dict:
    scene = session.get(VisualScene, scene_id)
    if not scene or scene.project_id != project.id:
        raise ValueError("视觉场景不存在")
    normalized = normalize_storyboard(content)
    scene.storyboard_json = normalized.model_dump_json()
    scene.confidence = normalized.confidence
    scene.status = "edited"
    scene.updated_at = utc_now_iso()
    session.add(scene)
    session.commit()
    session.refresh(scene)
    scenes = list_scenes(session, project.id)
    _write_artifact(project, scenes, [])
    return _serialize_scene(scene)


def _load_cues(session: Session, project_id: str) -> list[dict]:
    cues = session.exec(
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
        }
        for cue in cues
    ]


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
                "subtitle_ids_json": json.dumps(
                    [cue["id"] for cue in cues], ensure_ascii=False
                ),
            }
        )
    return values


def _generate_storyboard_content(
    scene_values: list[dict], client: DeepSeekClient
) -> dict[str, StoryboardContent]:
    result: dict[str, StoryboardContent] = {}
    for offset in range(0, len(scene_values), SCENES_PER_REQUEST):
        batch = scene_values[offset : offset + SCENES_PER_REQUEST]
        parsed = _request_storyboard_batch(batch, client)
        expected_ids = {scene["id"] for scene in batch}
        actual_ids = {scene.scene_id for scene in parsed.scenes}
        if actual_ids != expected_ids or len(parsed.scenes) != len(batch):
            raise ValueError("DeepSeek 返回的 Storyboard 场景 ID 不完整")
        for scene in parsed.scenes:
            content = StoryboardContent.model_validate(
                scene.model_dump(exclude={"scene_id"})
            )
            result[scene.scene_id] = normalize_storyboard(content)
    return result


def _request_storyboard_batch(
    batch: list[dict], client: DeepSeekClient
) -> StoryboardBatchResult:
    system_prompt = _storyboard_system_prompt()
    user_prompt = _storyboard_user_prompt(batch)
    raw_payload = client.chat_json(system_prompt, user_prompt)
    try:
        return StoryboardBatchResult.model_validate(
            _normalize_llm_storyboard_payload(raw_payload)
        )
    except ValidationError as exc:
        logger.warning("Storyboard response validation failed; requesting one repair: %s", exc)
        repaired_payload = client.chat_json(
            system_prompt,
            _storyboard_repair_prompt(batch, raw_payload, exc),
        )
        return StoryboardBatchResult.model_validate(
            _normalize_llm_storyboard_payload(repaired_payload)
        )


def _normalize_llm_storyboard_payload(payload: dict) -> dict:
    """Repair safe scalar/list variations before strict schema validation."""
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
Also return motion_prompt, scene_type, importance_score, motion_score, identity_risk,
text_density and subject_count. motion_prompt describes only subtle subject/environment/camera
motion plus identity consistency constraints; do not repeat image style keywords.
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


def _storyboard_user_prompt(scene_values: list[dict]) -> str:
    payload = [
        {
            "scene_id": scene["id"],
            "start_ms": scene["start_ms"],
            "end_ms": scene["end_ms"],
            "narration": scene["narration"],
        }
        for scene in scene_values
    ]
    return json.dumps({"scenes": payload}, ensure_ascii=False)


def _storyboard_repair_prompt(
    scene_values: list[dict], raw_payload: dict, validation_error: ValidationError
) -> str:
    return json.dumps(
        {
            "instruction": (
                "Repair the previous response so it exactly matches the required JSON schema. "
                "Return JSON only, keep every scene_id unchanged, and do not omit scenes."
            ),
            "required_scenes": json.loads(_storyboard_user_prompt(scene_values))["scenes"],
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
    }


def _write_artifact(project: Project, scenes: list[dict], warnings: list[str]):
    base_dir = project_dir(get_settings().workspace_dir, project.id)
    ensure_project_dirs(base_dir)
    path = base_dir / "storyboard" / "scenes.json"
    payload = {
        "project_id": project.id,
        "model": get_settings().deepseek_model,
        "grouping_prompt_version": GROUPING_PROMPT_VERSION,
        "storyboard_prompt_version": STORYBOARD_PROMPT_VERSION,
        "generated_at": utc_now_iso(),
        "warnings": warnings,
        "scenes": scenes,
    }
    temp_path = path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)
    return path
