from __future__ import annotations

import hashlib
import json
import logging
import uuid
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.config import get_settings
from app.infrastructure.atomic_files import write_json_atomic
from app.infrastructure.project_layout import load_project_config
from app.integrations.llm.deepseek import DeepSeekClient
from app.models.project import Project
from app.models.visual_style import StyleTestRun, VisualStyleProfile, VisualStyleRevision
from app.providers import provider_registry
from app.services.visual_enrichment.planning import (
    DEFAULT_ANIME_NEGATIVE_PROMPT,
    DEFAULT_ANIME_STYLE_PROMPT,
)
from app.shared.time import utc_now_iso


logger = logging.getLogger(__name__)


DOCUMENTARY_STYLE_PROMPT = (
    "Cinematic documentary realism with natural human proportions, restrained color grading, "
    "credible materials, motivated practical lighting, authentic locations, subtle film texture, "
    "clear visual hierarchy, and a polished editorial still-photography finish."
)
DOCUMENTARY_NEGATIVE_PROMPT = (
    "watermark, logo, random text, captions, malformed anatomy, duplicate people, plastic skin, "
    "oversaturated colors, game render, generic stock-photo pose"
)
DEFAULT_CONTINUITY = [
    "Keep recurring people consistent in age, facial structure, hair, wardrobe, and recognizable details.",
    "Keep the series palette, rendering medium, texture, and lighting language consistent.",
]
DEFAULT_COMPOSITION = [
    "Use a 16:9 landscape composition with one clear focal hierarchy.",
    "Keep the lower area visually quiet and suitable for subtitles; do not render visible text.",
]
DEFAULT_MOTION = {
    "type": "slow_push",
    "zoom_start": 1.0,
    "zoom_end": 1.06,
    "pan_direction": "center",
    "transition": "cut",
    "subtitle_safe_zone": 0.18,
}


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item).strip() for item in parsed if str(item).strip()] if isinstance(parsed, list) else []


def _load_dict(value: str) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _content_hash(
    style_prompt: str,
    negative_prompt: str,
    continuity_rules: list[str],
    composition_rules: list[str],
    motion_preset: dict,
) -> str:
    return hashlib.sha256(
        _json(
            {
                "style_prompt": style_prompt.strip(),
                "negative_prompt": negative_prompt.strip(),
                "continuity_rules": continuity_rules,
                "composition_rules": composition_rules,
                "motion_preset": motion_preset,
            }
        ).encode("utf-8")
    ).hexdigest()


def ensure_builtin_styles(session: Session) -> None:
    definitions = (
        (
            "documentary",
            "纪录片写实",
            "适用于历史、商业、财经、人物与知识类长视频的自然电影化写实风格。",
            DOCUMENTARY_STYLE_PROMPT,
            DOCUMENTARY_NEGATIVE_PROMPT,
            ["纪录片", "写实", "电影感"],
        ),
        (
            "anime_documentary",
            "二维动漫纪录片",
            "全片统一的二维手绘纪录片风格，适合语义节拍全覆盖。",
            DEFAULT_ANIME_STYLE_PROMPT,
            DEFAULT_ANIME_NEGATIVE_PROMPT,
            ["二维动漫", "手绘", "全片覆盖"],
        ),
    )
    changed = False
    for key, name, description, prompt, negative, tags in definitions:
        existing = session.exec(
            select(VisualStyleProfile).where(VisualStyleProfile.builtin_key == key)
        ).first()
        if existing:
            continue
        profile_id = f"style_builtin_{key}"
        revision_id = f"style_revision_builtin_{key}_v1"
        revision = VisualStyleRevision(
            id=revision_id,
            style_profile_id=profile_id,
            version=1,
            status="published",
            style_prompt=prompt,
            negative_prompt=negative,
            continuity_rules_json=_json(DEFAULT_CONTINUITY),
            composition_rules_json=_json(DEFAULT_COMPOSITION),
            motion_preset_json=_json(DEFAULT_MOTION),
            source="builtin",
            content_hash=_content_hash(
                prompt, negative, DEFAULT_CONTINUITY, DEFAULT_COMPOSITION, DEFAULT_MOTION
            ),
            published_at=utc_now_iso(),
        )
        profile = VisualStyleProfile(
            id=profile_id,
            name=name,
            description=description,
            tags_json=_json(tags),
            status="published",
            current_revision_id=revision_id,
            builtin_key=key,
        )
        session.add(revision)
        session.add(profile)
        changed = True
    if changed:
        session.commit()


def list_profiles(session: Session, *, include_archived: bool = False) -> list[dict]:
    ensure_builtin_styles(session)
    query = select(VisualStyleProfile).order_by(VisualStyleProfile.updated_at.desc())
    profiles = list(session.exec(query).all())
    if not include_archived:
        profiles = [item for item in profiles if item.status != "archived"]
    return [serialize_profile(session, item) for item in profiles]


def get_profile(session: Session, profile_id: str) -> VisualStyleProfile:
    ensure_builtin_styles(session)
    profile = session.get(VisualStyleProfile, profile_id)
    if not profile:
        raise LookupError("视觉风格不存在")
    return profile


def get_revision(session: Session, revision_id: str) -> VisualStyleRevision:
    revision = session.get(VisualStyleRevision, revision_id)
    if not revision:
        raise LookupError("视觉风格版本不存在")
    return revision


def serialize_revision(revision: VisualStyleRevision | None) -> dict | None:
    if not revision:
        return None
    return {
        "id": revision.id,
        "style_profile_id": revision.style_profile_id,
        "version": revision.version,
        "status": revision.status,
        "style_prompt": revision.style_prompt,
        "negative_prompt": revision.negative_prompt,
        "continuity_rules": _load_list(revision.continuity_rules_json),
        "composition_rules": _load_list(revision.composition_rules_json),
        "motion_preset": _load_dict(revision.motion_preset_json),
        "source": revision.source,
        "parent_revision_id": revision.parent_revision_id,
        "content_hash": revision.content_hash,
        "created_at": revision.created_at,
        "published_at": revision.published_at,
    }


def serialize_profile(session: Session, profile: VisualStyleProfile) -> dict:
    revisions = list(
        session.exec(
            select(VisualStyleRevision)
            .where(VisualStyleRevision.style_profile_id == profile.id)
            .order_by(VisualStyleRevision.version.desc())
        ).all()
    )
    current = next((item for item in revisions if item.id == profile.current_revision_id), None)
    draft = next((item for item in revisions if item.id == profile.draft_revision_id), None)
    return {
        "id": profile.id,
        "name": profile.name,
        "description": profile.description,
        "tags": _load_list(profile.tags_json),
        "status": profile.status,
        "cover_image_path": profile.cover_image_path,
        "builtin_key": profile.builtin_key,
        "current_revision": serialize_revision(current),
        "draft_revision": serialize_revision(draft),
        "revisions": [serialize_revision(item) for item in revisions],
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


def create_profile(
    session: Session,
    *,
    name: str,
    description: str,
    tags: list[str],
    style_prompt: str,
    negative_prompt: str,
) -> dict:
    if not name.strip() or not style_prompt.strip():
        raise ValueError("风格名称和主提示词不能为空")
    profile_id = f"style_{uuid.uuid4().hex[:16]}"
    revision_id = f"style_revision_{uuid.uuid4().hex[:16]}"
    revision = VisualStyleRevision(
        id=revision_id,
        style_profile_id=profile_id,
        version=1,
        style_prompt=style_prompt.strip(),
        negative_prompt=negative_prompt.strip(),
        continuity_rules_json=_json(DEFAULT_CONTINUITY),
        composition_rules_json=_json(DEFAULT_COMPOSITION),
        motion_preset_json=_json(DEFAULT_MOTION),
        content_hash=_content_hash(
            style_prompt, negative_prompt, DEFAULT_CONTINUITY, DEFAULT_COMPOSITION, DEFAULT_MOTION
        ),
    )
    profile = VisualStyleProfile(
        id=profile_id,
        name=name.strip(),
        description=description.strip(),
        tags_json=_json(tags),
        draft_revision_id=revision_id,
    )
    session.add(revision)
    session.add(profile)
    session.commit()
    return serialize_profile(session, profile)


def update_draft(
    session: Session,
    profile: VisualStyleProfile,
    *,
    name: str,
    description: str,
    tags: list[str],
    style_prompt: str,
    negative_prompt: str,
    continuity_rules: list[str],
    composition_rules: list[str],
    motion_preset: dict,
    source: str = "manual",
) -> dict:
    if profile.builtin_key:
        raise ValueError("内置风格不可直接修改，请先复制为自定义风格")
    if not name.strip() or not style_prompt.strip():
        raise ValueError("风格名称和主提示词不能为空")
    revision = session.get(VisualStyleRevision, profile.draft_revision_id) if profile.draft_revision_id else None
    if not revision:
        latest_version = session.exec(
            select(VisualStyleRevision.version)
            .where(VisualStyleRevision.style_profile_id == profile.id)
            .order_by(VisualStyleRevision.version.desc())
        ).first() or 0
        revision = VisualStyleRevision(
            id=f"style_revision_{uuid.uuid4().hex[:16]}",
            style_profile_id=profile.id,
            version=int(latest_version) + 1,
            style_prompt=style_prompt.strip(),
            parent_revision_id=profile.current_revision_id,
            content_hash="",
        )
        profile.draft_revision_id = revision.id
    revision.style_prompt = style_prompt.strip()
    revision.negative_prompt = negative_prompt.strip()
    revision.continuity_rules_json = _json(continuity_rules)
    revision.composition_rules_json = _json(composition_rules)
    revision.motion_preset_json = _json(motion_preset)
    revision.source = source
    revision.content_hash = _content_hash(
        revision.style_prompt,
        revision.negative_prompt,
        continuity_rules,
        composition_rules,
        motion_preset,
    )
    profile.name = name.strip()
    profile.description = description.strip()
    profile.tags_json = _json(tags)
    profile.status = "draft" if not profile.current_revision_id else "published"
    profile.updated_at = utc_now_iso()
    session.add(revision)
    session.add(profile)
    session.commit()
    return serialize_profile(session, profile)


def publish_draft(session: Session, profile: VisualStyleProfile) -> dict:
    if profile.builtin_key:
        return serialize_profile(session, profile)
    revision = session.get(VisualStyleRevision, profile.draft_revision_id) if profile.draft_revision_id else None
    if not revision:
        raise ValueError("没有可发布的草稿版本")
    revision.status = "published"
    revision.published_at = utc_now_iso()
    profile.current_revision_id = revision.id
    profile.draft_revision_id = None
    profile.status = "published"
    profile.updated_at = utc_now_iso()
    session.add(revision)
    session.add(profile)
    session.commit()
    return serialize_profile(session, profile)


def duplicate_profile(session: Session, profile: VisualStyleProfile) -> dict:
    source_id = profile.current_revision_id or profile.draft_revision_id
    source = get_revision(session, source_id) if source_id else None
    if not source:
        raise ValueError("风格没有可复制的版本")
    created = create_profile(
        session,
        name=f"{profile.name} 副本",
        description=profile.description,
        tags=_load_list(profile.tags_json),
        style_prompt=source.style_prompt,
        negative_prompt=source.negative_prompt,
    )
    copied = get_profile(session, created["id"])
    return update_draft(
        session,
        copied,
        name=copied.name,
        description=copied.description,
        tags=_load_list(copied.tags_json),
        style_prompt=source.style_prompt,
        negative_prompt=source.negative_prompt,
        continuity_rules=_load_list(source.continuity_rules_json),
        composition_rules=_load_list(source.composition_rules_json),
        motion_preset=_load_dict(source.motion_preset_json),
    )


def archive_profile(session: Session, profile: VisualStyleProfile) -> dict:
    if profile.builtin_key:
        raise ValueError("内置风格不可归档")
    profile.status = "archived"
    profile.updated_at = utc_now_iso()
    session.add(profile)
    session.commit()
    return serialize_profile(session, profile)


def optimize_prompt(style_prompt: str, negative_prompt: str, goal: str) -> dict:
    if not style_prompt.strip():
        raise ValueError("请先输入需要优化的风格提示词")
    system_prompt = (
        "You are the visual art director for a long-form documentary image pipeline. "
        "Improve only the reusable art style contract. Never add a concrete person, event, place, "
        "story action, or test-scene content. Return one JSON object with keys "
        "optimized_style_prompt, optimized_negative_prompt, continuity_rules, "
        "composition_rules, warnings, summary. All list fields must be arrays of strings. "
        "Make the prompts concise, provider-neutral, and suitable for Seedream."
    )
    result = DeepSeekClient().chat_json(
        system_prompt,
        _json(
            {
                "goal": goal.strip() or "Improve consistency and remove ambiguity",
                "style_prompt": style_prompt,
                "negative_prompt": negative_prompt,
            }
        ),
    )
    required = {"optimized_style_prompt", "optimized_negative_prompt"}
    if not required.issubset(result) or not str(result["optimized_style_prompt"]).strip():
        raise RuntimeError("DeepSeek 返回的风格优化结果不完整")
    return result


def compile_revision(
    revision: VisualStyleRevision,
    scene_prompt: str,
    scene_negative: str = "",
    configured_negative: str = "",
) -> dict:
    continuity = _load_list(revision.continuity_rules_json)
    composition = _load_list(revision.composition_rules_json)
    positive_sections = [
        f"STYLE CONTRACT — apply consistently across the entire series:\n{revision.style_prompt.strip()}",
    ]
    if continuity:
        positive_sections.append("CONTINUITY RULES:\n- " + "\n- ".join(continuity))
    positive_sections.append(f"SCENE CONTENT:\n{scene_prompt.strip()}")
    if composition:
        positive_sections.append("COMPOSITION AND OUTPUT:\n- " + "\n- ".join(composition))
    negative_parts: list[str] = []
    for value in (configured_negative, revision.negative_prompt, scene_negative):
        for item in str(value or "").split(","):
            cleaned = item.strip()
            if cleaned and cleaned.casefold() not in {part.casefold() for part in negative_parts}:
                negative_parts.append(cleaned)
    return {
        "image_prompt": "\n\n".join(positive_sections),
        "negative_prompt": ", ".join(negative_parts),
        "motion_directive": _load_dict(revision.motion_preset_json),
        "style_profile_id": revision.style_profile_id,
        "style_revision_id": revision.id,
        "style_content_hash": revision.content_hash,
    }


def resolve_project_revision(session: Session, project: Project) -> VisualStyleRevision:
    ensure_builtin_styles(session)
    config = load_project_config(project)
    revision_id = str(config.get("visual_style_revision_id") or "").strip()
    if revision_id:
        revision = session.get(VisualStyleRevision, revision_id)
        if revision and revision.status == "published":
            return revision
    builtin_key = (
        "anime_documentary"
        if str(config.get("visual_generation_mode") or "curated") == "anime_full_coverage"
        else "documentary"
    )
    profile = session.exec(
        select(VisualStyleProfile).where(VisualStyleProfile.builtin_key == builtin_key)
    ).one()
    return get_revision(session, str(profile.current_revision_id))


def compile_project_style(
    session: Session,
    project: Project,
    *,
    scene_prompt: str,
    scene_negative: str,
    configured_negative: str,
) -> dict:
    return compile_revision(
        resolve_project_revision(session, project),
        scene_prompt,
        scene_negative,
        configured_negative,
    )


def project_motion_settings(session: Session, project: Project) -> dict:
    revision = resolve_project_revision(session, project)
    preset = _load_dict(revision.motion_preset_json)
    kind = str(preset.get("type") or "slow_push")
    pan = str(preset.get("pan_direction") or "center")
    motion_type = {
        "slow_push": "slow_zoom_in",
        "slow_pull": "slow_zoom_out",
        "static": "static",
        "pan": "pan_right_to_left" if pan == "left" else "pan_left_to_right",
    }.get(kind, "auto")
    return {
        "motion_type": motion_type,
        "zoom_start": float(preset.get("zoom_start", 1.0)),
        "zoom_end": float(preset.get("zoom_end", 1.06)),
        "pan_direction": pan,
        "transition": str(preset.get("transition") or "cut"),
    }


def enqueue_style_test(
    session: Session,
    revision: VisualStyleRevision,
    *,
    scene_description: str,
    candidates: int,
    client_request_id: str,
) -> dict:
    if not scene_description.strip():
        raise ValueError("测试画面描述不能为空")
    client_request_id = client_request_id.strip()
    if not client_request_id or len(client_request_id) > 64:
        raise ValueError("无效的测试请求标识")
    candidates = max(1, min(4, int(candidates)))
    existing = session.exec(
        select(StyleTestRun).where(StyleTestRun.client_request_id == client_request_id)
    ).first()
    if existing:
        if (
            existing.style_revision_id != revision.id
            or existing.scene_description != scene_description.strip()
            or existing.candidate_count != candidates
        ):
            raise ValueError("测试请求标识已被用于不同的生成参数")
        return serialize_test_run(existing)

    settings = get_settings()
    provider = provider_registry.get(settings.image_generation_provider_id)
    compiled = compile_revision(
        revision,
        scene_description,
        configured_negative=settings.image_generation_negative_prompt,
    )
    run_id = f"style_test_{uuid.uuid4().hex[:16]}"
    output_dir = settings.workspace_dir / "styles" / revision.style_profile_id / "tests" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_rows = [
        {
            "index": index,
            "status": "queued",
            "path": str(output_dir / f"candidate_{index:02d}.png"),
            "generation_seconds": None,
            "error_code": None,
            "error_message": None,
        }
        for index in range(1, candidates + 1)
    ]
    run = StyleTestRun(
        id=run_id,
        client_request_id=client_request_id,
        style_revision_id=revision.id,
        status="queued",
        candidate_count=candidates,
        scene_description=scene_description.strip(),
        compiled_prompt=compiled["image_prompt"],
        compiled_negative_prompt=compiled["negative_prompt"],
        provider_id=provider.id,
        model_id=provider.model_id,
        output_json=_json(candidate_rows),
    )
    session.add(run)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.exec(
            select(StyleTestRun).where(StyleTestRun.client_request_id == client_request_id)
        ).first()
        if not existing:
            raise
        if (
            existing.style_revision_id != revision.id
            or existing.scene_description != scene_description.strip()
            or existing.candidate_count != candidates
        ):
            raise ValueError("测试请求标识已被用于不同的生成参数")
        return serialize_test_run(existing)
    try:
        write_test_run_manifest(run)
    except OSError:
        logger.exception("Failed to write style test manifest for %s", run.id)
    return serialize_test_run(run)


def _candidate_rows(run: StyleTestRun) -> list[dict]:
    try:
        values = json.loads(run.output_json or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(values, list):
        return []
    rows: list[dict] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        item = dict(value)
        # Records created before the asynchronous queue contain only completed
        # output metadata.
        item.setdefault("status", "completed")
        rows.append(item)
    return rows


def write_test_run_manifest(run: StyleTestRun) -> None:
    rows = _candidate_rows(run)
    first_path = next((Path(str(item["path"])) for item in rows if item.get("path")), None)
    if not first_path:
        return
    write_json_atomic(
        first_path.parent / "test.json",
        {
            "id": run.id,
            "client_request_id": run.client_request_id,
            "style_revision_id": run.style_revision_id,
            "scene_description": run.scene_description,
            "compiled_prompt": run.compiled_prompt,
            "compiled_negative_prompt": run.compiled_negative_prompt,
            "candidates": rows,
            "status": run.status,
            "error_code": run.error_code,
            "error": run.error_message,
        },
    )


def serialize_test_run(run: StyleTestRun) -> dict:
    candidates = _candidate_rows(run)
    outputs = [item for item in candidates if item.get("status") == "completed"]
    candidate_count = max(int(run.candidate_count or 0), len(candidates))
    return {
        "id": run.id,
        "client_request_id": run.client_request_id,
        "style_revision_id": run.style_revision_id,
        "status": run.status,
        "candidate_count": candidate_count,
        "completed_candidates": len(outputs),
        "scene_description": run.scene_description,
        "compiled_prompt": run.compiled_prompt,
        "compiled_negative_prompt": run.compiled_negative_prompt,
        "provider_id": run.provider_id,
        "model_id": run.model_id,
        "outputs": [
            {
                "index": item.get("index"),
                "generation_seconds": item.get("generation_seconds"),
                "image_url": f"/api/visual-styles/tests/{run.id}/images/{item.get('index')}",
            }
            for item in outputs
        ],
        "candidates": [
            {
                "index": item.get("index"),
                "status": item.get("status"),
                "generation_seconds": item.get("generation_seconds"),
                "error_code": item.get("error_code"),
                "error_message": item.get("error_message"),
            }
            for item in candidates
        ],
        "generation_seconds": run.generation_seconds,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


def get_test_run(session: Session, run_id: str) -> dict:
    run = session.get(StyleTestRun, run_id)
    if not run:
        raise LookupError("测试记录不存在")
    return serialize_test_run(run)


def list_test_runs(session: Session, profile_id: str) -> list[dict]:
    revision_ids = list(
        session.exec(
            select(VisualStyleRevision.id).where(
                VisualStyleRevision.style_profile_id == profile_id
            )
        ).all()
    )
    if not revision_ids:
        return []
    runs = session.exec(
        select(StyleTestRun)
        .where(StyleTestRun.style_revision_id.in_(revision_ids))
        .order_by(StyleTestRun.created_at.desc())
        .limit(30)
    ).all()
    return [serialize_test_run(item) for item in runs]


def test_image_path(session: Session, run_id: str, index: int) -> Path:
    run = session.get(StyleTestRun, run_id)
    if not run:
        raise LookupError("测试记录不存在")
    outputs = json.loads(run.output_json or "[]")
    match = next((item for item in outputs if int(item.get("index", -1)) == index), None)
    if not match:
        raise LookupError("测试图片不存在")
    path = Path(str(match["path"])).resolve()
    allowed = (get_settings().workspace_dir / "styles").resolve()
    if path != allowed and allowed not in path.parents:
        raise ValueError("测试图片路径无效")
    return path
