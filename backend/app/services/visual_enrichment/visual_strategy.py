from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Protocol

import yaml

from app.infrastructure.project_layout import load_project_config
from app.models.project import Project
from app.schemas.storyboard import StoryboardContent
from app.services.visual_enrichment.models import VisualCandidate, VisualPlan
from app.services.visual_enrichment.planning import (
    DEFAULT_ANIME_NEGATIVE_PROMPT,
    DEFAULT_ANIME_STYLE_PROMPT,
    build_anime_visual_plan,
    build_visual_plan,
)
from app.services.visual_enrichment.providers import LLMProvider
from app.services.visual_enrichment.selection import select_candidates


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "production_5060ti.yaml"


@dataclass(frozen=True, slots=True)
class VisualStrategyMetadata:
    id: str
    version: str
    display_name: str
    description: str
    compatible_video_modes: tuple[str, ...]
    full_timeline_coverage: bool = False
    supports_multiple_beats_per_scene: bool = False

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "version": self.version,
            "display_name": self.display_name,
            "description": self.description,
            "compatible_video_modes": list(self.compatible_video_modes),
            "full_timeline_coverage": self.full_timeline_coverage,
            "supports_multiple_beats_per_scene": self.supports_multiple_beats_per_scene,
        }


@dataclass(frozen=True, slots=True)
class AnimeGenerationProfile:
    target_beat_seconds: tuple[int, int] = (8, 15)
    candidates_per_beat: int = 1
    style_prompt: str = DEFAULT_ANIME_STYLE_PROMPT
    negative_prompt: str = DEFAULT_ANIME_NEGATIVE_PROMPT
    motion_prompt: str = (
        "Use slow 2D documentary camera movement. Derive framing changes every 3-6 seconds "
        "with gentle push, pan, or detail crop while preserving the master illustration."
    )


class VisualGenerationStrategy(Protocol):
    metadata: VisualStrategyMetadata

    def build_plan(
        self,
        *,
        project_id: str,
        duration_ms: int,
        candidates: list[VisualCandidate],
        config: dict,
        provider: LLMProvider | None,
    ) -> VisualPlan: ...

    def compose_prompt(
        self,
        project: Project,
        storyboard: StoryboardContent,
        configured_negative: str,
    ) -> tuple[str, str]: ...


class VisualStrategyRegistry:
    def __init__(self) -> None:
        self._items: dict[str, VisualGenerationStrategy] = {}

    def register(self, strategy: VisualGenerationStrategy) -> None:
        strategy_id = strategy.metadata.id.strip().lower()
        if not strategy_id:
            raise ValueError("Visual strategy id is required")
        self._items[strategy_id] = strategy

    def get(self, strategy_id: str) -> VisualGenerationStrategy:
        normalized = str(strategy_id or "curated").strip().lower()
        try:
            return self._items[normalized]
        except KeyError as exc:
            raise ValueError(f"Unsupported visual generation mode: {normalized}") from exc

    def list(self) -> list[VisualStrategyMetadata]:
        return [item.metadata for item in self._items.values()]

    def resolve_for_video_mode(self, strategy_id: str | None, video_mode: str) -> str:
        strategy = self.get(strategy_id or "curated")
        if video_mode not in strategy.metadata.compatible_video_modes:
            raise ValueError(
                f"Visual strategy {strategy.metadata.id} is incompatible with video mode "
                f"{video_mode}"
            )
        return strategy.metadata.id


def _base_prompt(
    storyboard: StoryboardContent, configured_negative: str, *, photorealistic: bool
) -> tuple[str, list[str]]:
    prompt = storyboard.image_prompt.strip()
    if not prompt:
        parts = [
            storyboard.visual_summary,
            f"documentary cinematic {storyboard.visual_type}",
            f"{storyboard.shot_preference} shot",
            f"{storyboard.mood} mood",
        ]
        if storyboard.time_period:
            parts.append(f"historically accurate {storyboard.time_period}")
        if storyboard.locations:
            parts.append("location: " + ", ".join(storyboard.locations))
        if storyboard.must_include:
            parts.append("must visibly include " + ", ".join(storyboard.must_include))
        parts.append(
            "photorealistic, natural lighting, coherent anatomy, 16:9 composition, no visible text"
            if photorealistic
            else "coherent anatomy, 16:9 composition, no visible text"
        )
        prompt = ", ".join(part for part in parts if part)
    return prompt, [configured_negative, storyboard.negative_prompt, *storyboard.avoid]


class CuratedVisualStrategy:
    metadata = VisualStrategyMetadata(
        id="curated",
        version="1",
        display_name="重点视觉增强",
        description="按重要性、间隔和每分钟上限选择重点视觉。",
        compatible_video_modes=("ai_generated_images", "ai_landscape_mix", "landscape", "none"),
    )

    def build_plan(self, *, project_id, duration_ms, candidates, config, provider):
        selection = config.get("selection", {})
        image = config.get("image", {})
        video = config.get("video", {})
        selected = select_candidates(
            candidates,
            duration_ms=duration_ms,
            threshold=float(selection.get("candidate_threshold", 0.62)),
            min_gap_sec=float(selection.get("min_generated_visual_gap_sec", 10)),
            hard_max_per_minute=float(selection.get("hard_max_visuals_per_minute", 4)),
        )
        return build_visual_plan(
            project_id,
            duration_ms,
            selected,
            width=int(image.get("width", 1344)),
            height=int(image.get("height", 768)),
            subtitle_safe_zone=float(video.get("subtitle_safe_zone", 0.18)),
            candidates_normal=int(image.get("candidates_normal", 2)),
            candidates_high=int(image.get("candidates_high", 3)),
            provider=provider,
        )

    def compose_prompt(self, project, storyboard, configured_negative):
        prompt, negatives = _base_prompt(
            storyboard, configured_negative, photorealistic=True
        )
        return prompt, ", ".join(item for item in negatives if item)


class AnimeFullCoverageStrategy:
    metadata = VisualStrategyMetadata(
        id="anime_full_coverage",
        version="2",
        display_name="全片统一二维动漫",
        description="按 8–15 秒语义节拍覆盖全片，并保持统一二维动漫风格。",
        compatible_video_modes=("ai_generated_images",),
        full_timeline_coverage=True,
        supports_multiple_beats_per_scene=True,
    )

    def build_plan(self, *, project_id, duration_ms, candidates, config, provider):
        image = config.get("image", {})
        video = config.get("video", {})
        anime = config.get("anime", {})
        return build_anime_visual_plan(
            project_id,
            duration_ms,
            candidates,
            width=int(image.get("width", 1344)),
            height=int(image.get("height", 768)),
            subtitle_safe_zone=float(video.get("subtitle_safe_zone", 0.18)),
            candidates_per_scene=int(anime.get("candidates_per_scene", 1)),
            style_prompt=str(anime.get("style_prompt") or DEFAULT_ANIME_STYLE_PROMPT),
            negative_style_prompt=str(
                anime.get("negative_prompt") or DEFAULT_ANIME_NEGATIVE_PROMPT
            ),
            provider=provider,
        )

    def compose_prompt(self, project, storyboard, configured_negative):
        base_prompt, negative_parts = _base_prompt(
            storyboard, configured_negative, photorealistic=False
        )
        profile = load_anime_generation_profile(project)
        prompt = (
            f"SERIES ART DIRECTION — apply exactly to this scene:\n{profile.style_prompt}\n\n"
            f"SCENE CONTENT:\n{base_prompt}\n\n"
            "Create one concrete story moment matching the narration. Preserve recurring character "
            "appearance and wardrobe when the same entity returns. 16:9 landscape, clear focal "
            "hierarchy, quiet subtitle-safe lower area, no visible text.\n\n"
            f"MOTION GUIDANCE:\n{profile.motion_prompt}"
        )
        negative_parts.append(profile.negative_prompt)
        return prompt, ", ".join(item for item in negative_parts if item)


visual_strategy_registry = VisualStrategyRegistry()
visual_strategy_registry.register(CuratedVisualStrategy())
visual_strategy_registry.register(AnimeFullCoverageStrategy())


def get_visual_generation_mode(project: Project) -> str:
    config = load_project_config(project)
    mode = str(config.get("visual_generation_mode") or "curated").strip().lower()
    try:
        return visual_strategy_registry.get(mode).metadata.id
    except ValueError:
        return "curated"


def load_anime_generation_profile(project: Project) -> AnimeGenerationProfile:
    config = load_project_config(project)
    configured_path = str(config.get("visual_enrichment_config_path") or "").strip()
    path = Path(configured_path).expanduser() if configured_path else DEFAULT_CONFIG_PATH
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        payload = {}
    anime = payload.get("anime", {}) if isinstance(payload, dict) else {}
    if not isinstance(anime, dict):
        anime = {}
    target = anime.get("target_master_scene_sec", [8, 15])
    if not isinstance(target, (list, tuple)) or len(target) != 2:
        target = [8, 15]
    motion_range = anime.get("derived_shot_change_sec", [3, 6])
    if not isinstance(motion_range, (list, tuple)) or len(motion_range) != 2:
        motion_range = [3, 6]
    return AnimeGenerationProfile(
        target_beat_seconds=(int(target[0]), int(target[1])),
        candidates_per_beat=max(1, int(anime.get("candidates_per_scene", 1))),
        style_prompt=str(anime.get("style_prompt") or DEFAULT_ANIME_STYLE_PROMPT),
        negative_prompt=str(anime.get("negative_prompt") or DEFAULT_ANIME_NEGATIVE_PROMPT),
        motion_prompt=(
            "Use slow 2D documentary camera movement. Derive framing changes every "
            f"{int(motion_range[0])}-{int(motion_range[1])} seconds with gentle push, pan, "
            "or detail crop while preserving the master illustration."
        ),
    )


def compose_image_prompts(
    project: Project,
    storyboard: StoryboardContent,
    configured_negative: str,
) -> tuple[str, str]:
    strategy = visual_strategy_registry.get(get_visual_generation_mode(project))
    return strategy.compose_prompt(project, storyboard, configured_negative)


def stable_visual_beat_id(scene_id: str, start_ms: int, end_ms: int, version: str = "2") -> str:
    digest = hashlib.sha256(
        f"{scene_id}:{start_ms}:{end_ms}:{version}".encode("utf-8")
    ).hexdigest()[:16]
    return f"{scene_id}:beat:{digest}"
