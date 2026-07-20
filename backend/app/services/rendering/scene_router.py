from dataclasses import dataclass

from sqlmodel import Session

from app.config import Settings
from app.models.media import MediaFile, MediaShot, SceneAssignment
from app.models.storyboard import VisualScene
from app.schemas.storyboard import StoryboardContent


@dataclass(frozen=True)
class SceneRoute:
    provider: str
    reason: str


def route_project_scenes(
    session: Session,
    scenes: list[VisualScene],
    assignments: dict[str, list[SceneAssignment]],
    settings: Settings,
) -> dict[str, SceneRoute]:
    routes = {scene.id: SceneRoute("ffmpeg", "FFmpeg 是默认渲染方式") for scene in scenes}
    if not getattr(settings, "framepack_enabled", False) or getattr(settings, "framepack_max_ratio", 0) <= 0:
        return routes

    forced: list[tuple[VisualScene, StoryboardContent]] = []
    automatic: list[tuple[VisualScene, StoryboardContent]] = []
    for scene in scenes:
        items = assignments.get(scene.id, [])
        if len(items) != 1:
            continue
        assignment = items[0]
        media = _assignment_media(session, assignment)
        if media is None or media.media_type != "image":
            continue
        storyboard = _storyboard(scene)
        if assignment.render_mode == "ffmpeg":
            routes[scene.id] = SceneRoute("ffmpeg", "用户指定 FFmpeg")
        elif assignment.render_mode == "framepack":
            if _eligible(scene, storyboard):
                forced.append((scene, storyboard))
            else:
                routes[scene.id] = SceneRoute("ffmpeg", "用户指定 FramePack，但镜头风险规则要求 FFmpeg")
        elif _eligible(scene, storyboard):
            automatic.append((scene, storyboard))

    for scene, _storyboard_value in forced:
        routes[scene.id] = SceneRoute("framepack", "用户指定 FramePack")

    limit = max(1, int(len(scenes) * settings.framepack_max_ratio))
    remaining = max(0, limit - len(forced))
    automatic.sort(
        key=lambda item: (
            -item[1].importance_score,
            -item[1].motion_score,
            item[1].identity_risk,
            item[0].scene_index,
        )
    )
    for scene, _storyboard_value in automatic[:remaining]:
        routes[scene.id] = SceneRoute("framepack", "重点动态镜头自动路由")
    return routes


def route_single_scene(
    session: Session,
    scene: VisualScene,
    assignments: list[SceneAssignment],
    settings: Settings,
) -> SceneRoute:
    return route_project_scenes(session, [scene], {scene.id: assignments}, settings)[scene.id]


def _eligible(scene: VisualScene, storyboard: StoryboardContent) -> bool:
    duration = (scene.end_ms - scene.start_ms) / 1000
    denied_types = {
        "map", "document", "contract", "book", "newspaper", "logo", "chart",
        "product_packaging", "webpage", "software_ui", "historical_photo",
    }
    return (
        3.0 <= duration <= 6.5
        and storyboard.scene_type.casefold() not in denied_types
        and storyboard.importance_score >= 7
        and storyboard.motion_score >= 6
        and storyboard.identity_risk <= 6
        and storyboard.text_density == 0
        and storyboard.subject_count <= 2
    )


def _storyboard(scene: VisualScene) -> StoryboardContent:
    if scene.storyboard_json:
        return StoryboardContent.model_validate_json(scene.storyboard_json)
    return StoryboardContent(
        visual_summary=scene.narration or "Documentary scene",
        visual_type="general",
        scene_category="general",
        mood="neutral",
        shot_preference="medium",
        primary_query="documentary scene",
        fallback_category="transition",
        fallback_mood="neutral",
        confidence=0.5,
    )


def _assignment_media(session: Session, assignment: SceneAssignment) -> MediaFile | None:
    shot = session.get(MediaShot, assignment.media_shot_id)
    return session.get(MediaFile, shot.media_file_id) if shot else None
