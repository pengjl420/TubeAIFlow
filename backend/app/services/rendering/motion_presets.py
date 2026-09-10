import hashlib

from app.models.media import SceneAssignment
from app.models.storyboard import VisualScene


PRESETS = {
    "static",
    "slow_zoom_in",
    "slow_zoom_out",
    "pan_left_to_right",
    "pan_right_to_left",
    "pan_top_to_bottom",
    "pan_bottom_to_top",
    "diagonal_top_left",
    "diagonal_top_right",
    "portrait_push_in",
    "environment_pull_out",
    "subtle_breathing",
}

LEGACY_PRESETS = {
    "zoom_in": "slow_zoom_in",
    "zoom_out": "slow_zoom_out",
    "pan_left": "pan_right_to_left",
    "pan_right": "pan_left_to_right",
    "still": "static",
}


def select_motion_preset(
    project_id: str,
    scene: VisualScene,
    assignment: SceneAssignment,
    previous_presets: list[str] | None = None,
) -> str:
    requested = LEGACY_PRESETS.get(assignment.motion_type, assignment.motion_type)
    if requested in PRESETS:
        return requested
    previous = previous_presets or []
    choices = _scene_choices(scene)
    digest = hashlib.sha256(f"{project_id}:{scene.id}:{assignment.id}".encode("utf-8")).digest()
    start = int.from_bytes(digest[:4], "big") % len(choices)
    for offset in range(len(choices)):
        candidate = choices[(start + offset) % len(choices)]
        if not previous or candidate != previous[-1]:
            return candidate
    return choices[start]


def _scene_choices(scene: VisualScene) -> tuple[str, ...]:
    storyboard = (scene.storyboard_json or "").casefold()
    if any(
        word in storyboard
        for word in ('"visual_type":"document', "map", "chart", "logo", "screenshot")
    ):
        return ("static", "slow_zoom_in", "subtle_breathing")
    if any(word in storyboard for word in ("portrait", "person", "人物", "close_up")):
        return ("portrait_push_in", "slow_zoom_in", "subtle_breathing")
    if any(word in storyboard for word in ("city", "architecture", "landscape", "城市", "建筑")):
        return (
            "environment_pull_out",
            "pan_left_to_right",
            "pan_right_to_left",
            "slow_zoom_out",
        )
    return (
        "slow_zoom_in",
        "slow_zoom_out",
        "pan_left_to_right",
        "pan_right_to_left",
        "subtle_breathing",
    )
