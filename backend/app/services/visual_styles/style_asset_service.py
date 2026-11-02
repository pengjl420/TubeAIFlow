from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import uuid
from pathlib import Path

from PIL import Image
from sqlmodel import Session, select

from app.config import get_settings
from app.models.media import GeneratedImageVariant
from app.models.project import Project
from app.models.visual_style import StyleAsset, StyleAssetMatch, StyleTestRun, VisualStyleRevision
from app.schemas.storyboard import StoryboardContent
from app.shared.time import utc_now_iso


FINGERPRINT_DIMENSIONS = 256
AUTO_REUSE_THRESHOLD = 0.9
ELIGIBLE_FACT_RISKS = {"none", "low"}


def storyboard_query(storyboard: StoryboardContent) -> str:
    values = [
        storyboard.primary_query,
        storyboard.visual_summary,
        storyboard.time_period,
        storyboard.mood,
        *storyboard.entities,
        *storyboard.locations,
        *storyboard.must_include,
    ]
    return " ".join(value.strip() for value in values if value and value.strip())


def archive_style_test_candidate(
    session: Session,
    run: StyleTestRun,
    candidate_path: Path,
    *,
    candidate_index: int,
) -> StyleAsset:
    revision = session.get(VisualStyleRevision, run.style_revision_id)
    if not revision:
        raise LookupError("Style revision not found")
    return _archive(
        session,
        revision=revision,
        source=candidate_path,
        source_type="style_test",
        source_test_run_id=run.id,
        source_variant_id=f"{run.id}:{candidate_index}",
        prompt=run.compiled_prompt,
        negative_prompt=run.compiled_negative_prompt,
        query_text=run.scene_description,
        provider_id=run.provider_id,
        model_id=run.model_id,
        status="unreviewed",
    )


def archive_generated_variant(
    session: Session,
    project: Project,
    variant: GeneratedImageVariant,
    storyboard: StoryboardContent,
    *,
    provider_id: str,
    workspace_dir: Path | None = None,
) -> StyleAsset | None:
    if not variant.style_revision_id or not variant.style_profile_id:
        return None
    if variant.workflow_version.startswith("style_asset_reuse"):
        return None
    revision = session.get(VisualStyleRevision, variant.style_revision_id)
    if not revision:
        return None
    return _archive(
        session,
        revision=revision,
        source=Path(variant.path),
        source_type="project_generation",
        source_project_id=project.id,
        source_scene_id=variant.scene_id,
        source_variant_id=variant.id,
        prompt=variant.prompt,
        negative_prompt=variant.negative_prompt,
        query_text=storyboard_query(storyboard),
        entities=storyboard.entities,
        locations=storyboard.locations,
        mood=storyboard.mood,
        fact_risk=storyboard.fact_risk,
        provider_id=provider_id,
        model_id=variant.model_name,
        status="approved",
        workspace_dir=workspace_dir,
    )


def find_reusable_asset(
    session: Session,
    *,
    style_revision_id: str,
    storyboard: StoryboardContent,
    width: int,
    height: int,
    excluded_asset_ids: set[str] | None = None,
) -> tuple[StyleAsset, float] | None:
    if storyboard.fact_risk not in ELIGIBLE_FACT_RISKS or storyboard.identity_risk > 5:
        return None
    query = storyboard_query(storyboard)
    fingerprint = text_fingerprint(query)
    if not any(fingerprint):
        return None
    candidates = list(
        session.exec(
            select(StyleAsset).where(
                StyleAsset.style_revision_id == style_revision_id,
                StyleAsset.status == "approved",
            )
        ).all()
    )
    ranked: list[tuple[float, StyleAsset]] = []
    target_aspect = width / max(1, height)
    expected_entities = {_normalize(value) for value in storyboard.entities if value.strip()}
    for asset in candidates:
        if asset.id in (excluded_asset_ids or set()):
            continue
        path = Path(asset.path)
        if not path.is_file() or not asset.width or not asset.height:
            continue
        if abs(asset.width / asset.height - target_aspect) > 0.08:
            continue
        asset_entities = {_normalize(value) for value in _json_list(asset.entities_json)}
        if expected_entities and asset_entities and expected_entities.isdisjoint(asset_entities):
            continue
        score = cosine_similarity(fingerprint, _fingerprint(asset))
        if score >= AUTO_REUSE_THRESHOLD:
            ranked.append((score, asset))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], item[1].usage_count, item[1].created_at))
    score, asset = ranked[0]
    return asset, round(score, 6)


def materialize_reuse(
    session: Session,
    *,
    asset: StyleAsset,
    project: Project,
    scene_id: str,
    query_text: str,
    score: float,
    destination: Path,
) -> StyleAssetMatch:
    _copy_atomic(Path(asset.path), destination)
    now = utc_now_iso()
    asset.usage_count += 1
    asset.last_used_at = now
    asset.updated_at = now
    match = StyleAssetMatch(
        id=f"style_match_{uuid.uuid4().hex}",
        project_id=project.id,
        scene_id=scene_id,
        style_asset_id=asset.id,
        query_text=query_text,
        semantic_score=score,
        decision="auto_reused",
        materialized_path=str(destination.resolve()),
    )
    session.add_all([asset, match])
    return match


def list_assets(session: Session, style_profile_id: str) -> list[dict]:
    assets = list(
        session.exec(
            select(StyleAsset)
            .where(StyleAsset.style_profile_id == style_profile_id)
            .order_by(StyleAsset.created_at.desc())
        ).all()
    )
    return [_serialize_asset(asset) for asset in assets]


def set_asset_status(
    session: Session, style_profile_id: str, asset_id: str, status: str
) -> dict:
    if status not in {"approved", "rejected", "archived"}:
        raise ValueError("Unsupported style asset status")
    asset = session.get(StyleAsset, asset_id)
    if not asset or asset.style_profile_id != style_profile_id:
        raise LookupError("Style asset not found")
    asset.status = status
    asset.updated_at = utc_now_iso()
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return _serialize_asset(asset)


def asset_image_path(session: Session, style_profile_id: str, asset_id: str) -> Path:
    asset = session.get(StyleAsset, asset_id)
    if not asset or asset.style_profile_id != style_profile_id:
        raise LookupError("Style asset not found")
    path = Path(asset.path).resolve()
    allowed = (get_settings().workspace_dir / "styles").resolve()
    if path != allowed and allowed not in path.parents:
        raise ValueError("Style asset path is invalid")
    return path


def _serialize_asset(asset: StyleAsset) -> dict:
    return {
        "id": asset.id,
        "style_profile_id": asset.style_profile_id,
        "style_revision_id": asset.style_revision_id,
        "source_type": asset.source_type,
        "status": asset.status,
        "width": asset.width,
        "height": asset.height,
        "query_text": asset.query_text,
        "provider_id": asset.provider_id,
        "model_id": asset.model_id,
        "usage_count": asset.usage_count,
        "created_at": asset.created_at,
        "image_url": f"/api/visual-styles/{asset.style_profile_id}/assets/{asset.id}/image",
    }


def text_fingerprint(value: str) -> list[float]:
    vector = [0.0] * FINGERPRINT_DIMENSIONS
    tokens = _tokens(value)
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % FINGERPRINT_DIMENSIONS
        sign = 1.0 if digest[2] & 1 else -1.0
        vector[index] += sign
    magnitude = math.sqrt(sum(item * item for item in vector))
    return [item / magnitude for item in vector] if magnitude else vector


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    return max(0.0, min(1.0, sum(a * b for a, b in zip(left, right, strict=True))))


def perceptual_hash(path: Path) -> str:
    with Image.open(path) as image:
        pixels = list(image.convert("L").resize((8, 8)).getdata())
    average = sum(pixels) / max(1, len(pixels))
    bits = "".join("1" if value >= average else "0" for value in pixels)
    return f"{int(bits, 2):016x}"


def _archive(
    session: Session,
    *,
    revision: VisualStyleRevision,
    source: Path,
    source_type: str,
    prompt: str,
    negative_prompt: str,
    query_text: str,
    provider_id: str,
    model_id: str,
    status: str,
    source_project_id: str | None = None,
    source_scene_id: str | None = None,
    source_test_run_id: str | None = None,
    source_variant_id: str | None = None,
    entities: list[str] | None = None,
    locations: list[str] | None = None,
    mood: str = "",
    fact_risk: str = "low",
    workspace_dir: Path | None = None,
) -> StyleAsset:
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    digest = _sha256(source)
    existing = session.exec(
        select(StyleAsset).where(
            StyleAsset.style_revision_id == revision.id,
            StyleAsset.file_hash == digest,
        )
    ).first()
    if existing:
        if status == "approved" and existing.status == "unreviewed":
            existing.status = "approved"
            existing.updated_at = utc_now_iso()
            session.add(existing)
            session.flush()
        return existing

    asset_id = f"style_asset_{hashlib.sha1(f'{revision.id}:{digest}'.encode()).hexdigest()[:24]}"
    destination = (
        (workspace_dir or get_settings().workspace_dir)
        / "styles"
        / revision.style_profile_id
        / "revisions"
        / revision.id
        / "assets"
        / asset_id
        / f"original{source.suffix.lower() or '.png'}"
    )
    _copy_atomic(source, destination)
    with Image.open(destination) as image:
        width, height = image.size
    asset = StyleAsset(
        id=asset_id,
        style_profile_id=revision.style_profile_id,
        style_revision_id=revision.id,
        source_type=source_type,
        source_project_id=source_project_id,
        source_scene_id=source_scene_id,
        source_test_run_id=source_test_run_id,
        source_variant_id=source_variant_id,
        path=str(destination.resolve()),
        file_hash=digest,
        perceptual_hash=perceptual_hash(destination),
        prompt=prompt,
        negative_prompt=negative_prompt,
        query_text=query_text,
        entities_json=json.dumps(entities or [], ensure_ascii=False),
        locations_json=json.dumps(locations or [], ensure_ascii=False),
        mood=mood,
        fact_risk=fact_risk,
        width=width,
        height=height,
        provider_id=provider_id,
        model_id=model_id,
        status=status,
        text_fingerprint_json=json.dumps(text_fingerprint(query_text)),
    )
    session.add(asset)
    session.flush()
    return asset


def _fingerprint(asset: StyleAsset) -> list[float]:
    try:
        values = json.loads(asset.text_fingerprint_json or "[]")
        if isinstance(values, list) and len(values) == FINGERPRINT_DIMENSIONS:
            return [float(value) for value in values]
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return text_fingerprint(asset.query_text)


def _tokens(value: str) -> list[str]:
    normalized = _normalize(value)
    latin = re.findall(r"[a-z0-9]{2,}", normalized)
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    return latin + [cjk[index : index + 2] for index in range(max(0, len(cjk) - 1))]


def _normalize(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def _json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copyfile(source, temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
