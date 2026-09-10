from __future__ import annotations

import hashlib
import json
import logging
import random
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image
from sqlmodel import Session, select

from app.config import get_settings
from app.infrastructure import gpu_resource, process_runner as task_control
from app.infrastructure.project_layout import ensure_project_dirs, get_project_work_dir
from app.infrastructure.serialization import stable_json_hash
from app.integrations.tts.runner_io import write_json
from app.models.media import (
    LIBRARY_ROLE_PROJECT_GENERATED,
    GeneratedImageVariant,
    MediaFile,
    MediaShot,
    SceneAssignment,
)
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.providers import ImageBatchRequest, ImageProviderRuntime, provider_registry
from app.schemas.storyboard import StoryboardContent
from app.shared.time import utc_now_iso


logger = logging.getLogger(__name__)
WORKFLOW_VERSION = "sdxl_single_file_v1"
PROVIDER = "local_image_generation"


def _generate_project_images_local(session: Session, project: Project) -> dict:
    scenes = list(
        session.exec(
            select(VisualScene)
            .where(VisualScene.project_id == project.id)
            .order_by(VisualScene.scene_index)
        ).all()
    )
    if not scenes:
        raise ValueError("项目尚未生成视觉分镜")
    assigned_scene_ids = {
        item.scene_id
        for item in session.exec(
            select(SceneAssignment).where(
                SceneAssignment.project_id == project.id,
                SceneAssignment.selection_stage == "local_landscape_mix",
            )
        ).all()
    }
    return _generate(
        session,
        project,
        [scene for scene in scenes if scene.id not in assigned_scene_ids],
    )


def _regenerate_scene_images_local(
    session: Session,
    project: Project,
    scene_id: str,
    *,
    regeneration_id: str,
) -> dict:
    scene = session.get(VisualScene, scene_id)
    if not scene or scene.project_id != project.id:
        raise ValueError("Visual scene does not exist")
    if scene.locked_visual:
        raise ValueError("Scene visual is locked")
    if not regeneration_id.strip():
        raise ValueError("Image regeneration id is required")
    return _generate(
        session,
        project,
        [scene],
        force=True,
        regeneration_id=regeneration_id,
    )


def _runtime(project: Project) -> ImageProviderRuntime:
    provider_id = "image.local_sdxl"
    try:
        config = json.loads(project.config_json or "{}")
        provider_id = str(config.get("image_provider_id") or provider_id)
    except (TypeError, json.JSONDecodeError):
        pass
    return provider_registry.runtime(provider_id, ImageProviderRuntime)


def generate_project_images(session: Session, project: Project) -> dict:
    bind_builtin_provider_runtimes()
    return _generate_project_images_local(session, project)


def regenerate_scene_images(
    session: Session,
    project: Project,
    scene_id: str,
    *,
    regeneration_id: str,
) -> dict:
    bind_builtin_provider_runtimes()
    return _regenerate_scene_images_local(
        session,
        project,
        scene_id,
        regeneration_id=regeneration_id,
    )


def _generate(
    session: Session,
    project: Project,
    scenes: list[VisualScene],
    force: bool = False,
    regeneration_id: str | None = None,
) -> dict:
    settings = get_settings()
    model_path = settings.image_generation_model_path
    if model_path is None or not model_path.is_file():
        raise ValueError("本地图片生成模型未配置或文件不存在")
    config_dir = settings.image_generation_config_dir
    if config_dir is None or not (config_dir / "model_index.json").is_file():
        raise ValueError("SDXL 本地管线配置未配置或缺少 model_index.json")
    python_path = settings.image_generation_python or Path(sys.executable)
    if not python_path.is_file():
        raise ValueError(f"图片生成 Python 不存在：{python_path}")

    base_dir = get_project_work_dir(project, settings.workspace_dir)
    ensure_project_dirs(base_dir)
    generated_dir = base_dir / "media" / "generated_images"
    logs_dir = base_dir / "logs"
    result_path = logs_dir / "image_generation_results.json"
    recovered_results = _load_results_by_variant(result_path)
    jobs = []
    variants = []
    for scene in scenes:
        if not scene.storyboard_json:
            raise ValueError(f"场景 {scene.scene_index} 尚未生成 Storyboard")
        storyboard = StoryboardContent.model_validate_json(scene.storyboard_json)
        prompt, negative_prompt = _prompts(storyboard, settings.image_generation_negative_prompt)
        scene_dir = generated_dir / f"scene_{scene.scene_index:04d}"
        attempt_key = (
            hashlib.sha1(regeneration_id.encode()).hexdigest()[:16]
            if force and regeneration_id
            else None
        )
        for variant_index in range(1, settings.image_generation_candidates_per_scene + 1):
            variant_id = (
                f"{scene.id}:image:regen:{attempt_key}:{variant_index}"
                if attempt_key
                else f"{scene.id}:image:{variant_index}"
            )
            output_path = (
                scene_dir / "regenerations" / attempt_key / f"candidate_{variant_index:02d}.png"
                if attempt_key
                else scene_dir / f"candidate_{variant_index:02d}.png"
            )
            seed = (
                _regeneration_seed(project.id, scene.id, variant_index, regeneration_id)
                if force
                else _stable_seed(project.id, scene.id, variant_index)
            )
            signature = _signature(
                prompt,
                negative_prompt,
                model_path,
                seed,
                settings.image_generation_width,
                settings.image_generation_height,
                settings.image_generation_steps,
                settings.image_generation_guidance_scale,
            )
            variant = session.get(GeneratedImageVariant, variant_id)
            recovered = recovered_results.get(variant_id)
            reusable = bool(
                variant
                and variant.input_signature == signature
                and (variant.status == "completed" or recovered is not None)
                and _valid_generated_image(Path(variant.path), variant.width, variant.height)
            )
            if variant is None:
                variant = GeneratedImageVariant(
                    id=variant_id,
                    project_id=project.id,
                    scene_id=scene.id,
                    variant_index=variant_index,
                    path=str(output_path),
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    model_path=str(model_path),
                    model_name=model_path.stem,
                    input_signature=signature,
                    seed=seed,
                    width=settings.image_generation_width,
                    height=settings.image_generation_height,
                    steps=settings.image_generation_steps,
                    guidance_scale=settings.image_generation_guidance_scale,
                )
            elif not reusable:
                variant.path = str(output_path)
                variant.prompt = prompt
                variant.negative_prompt = negative_prompt
                variant.model_path = str(model_path)
                variant.model_name = model_path.stem
                variant.input_signature = signature
                variant.seed = seed
                variant.width = settings.image_generation_width
                variant.height = settings.image_generation_height
                variant.steps = settings.image_generation_steps
                variant.guidance_scale = settings.image_generation_guidance_scale
                variant.status = "pending"
                variant.error_message = None
                variant.generation_seconds = None
                variant.updated_at = utc_now_iso()
                output_path.unlink(missing_ok=True)
            elif recovered is not None and variant.status != "completed":
                # The child process writes its result file continuously, while
                # the parent commits DB statuses after the full batch exits.
                # Preserve completed files when the backend is restarted in
                # the middle of a long image-generation batch.
                variant.status = "completed"
                variant.generation_seconds = recovered.get("generation_seconds")
                variant.error_message = None
                variant.updated_at = utc_now_iso()
            session.add(variant)
            variants.append(variant)
            if not reusable:
                jobs.append(
                    {
                        "variant_id": variant.id,
                        "output_path": str(output_path),
                        "prompt": prompt,
                        "negative_prompt": negative_prompt,
                        "seed": seed,
                        "width": variant.width,
                        "height": variant.height,
                        "steps": variant.steps,
                        "guidance_scale": variant.guidance_scale,
                    }
                )
    session.commit()

    if jobs:
        batch_path = logs_dir / "image_generation_batch.json"
        progress_path = logs_dir / "image_generation_progress.json"
        _runtime(project).generate_batch(
            ImageBatchRequest(
                project_id=project.id,
                jobs=tuple(jobs),
                batch_path=batch_path,
                result_path=result_path,
                progress_path=progress_path,
                python_path=python_path,
                model_path=model_path,
                config_dir=config_dir,
                device=settings.image_generation_device,
                dtype=settings.image_generation_dtype,
                cpu_offload=settings.image_generation_cpu_offload,
            )
        )
        _apply_results(session, result_path)

    for variant in variants:
        session.refresh(variant)
    failures = [item for item in variants if item.status == "failed"]
    if failures:
        # Keep the previous successful generation and its assignment intact.
        raise RuntimeError(f"{len(failures)} 个图片候选生成失败，请检查 image_generation_results.json")

    registered = 0
    for variant in variants:
        if variant.status == "completed" and Path(variant.path).is_file():
            _register_generated_image(session, project, variant)
            registered += 1
    stale_paths: list[Path] = []
    if force:
        keep_ids = {variant.id for variant in variants}
        for scene in scenes:
            stale_paths.extend(
                _clear_scene_generated_assets(session, scene.id, preserve_variant_ids=keep_ids)
            )
    session.commit()
    for stale_path in stale_paths:
        try:
            stale_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove superseded generated image: %s", stale_path)
    return {
        "project_id": project.id,
        "scene_count": len(scenes),
        "candidate_count": registered,
        "generated_count": len(jobs),
        "variants": [item.model_dump() for item in variants],
    }


def _prompts(storyboard: StoryboardContent, configured_negative: str) -> tuple[str, str]:
    if storyboard.image_prompt:
        negative = ", ".join(
            item for item in (configured_negative, storyboard.negative_prompt) if item
        )
        return storyboard.image_prompt, negative
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
    parts.append("photorealistic, natural lighting, coherent anatomy, 16:9 composition, no visible text")
    negative = ", ".join([configured_negative, *storyboard.avoid])
    return ", ".join(part for part in parts if part), negative


def _run_batch(
    project_id: str,
    python_path: Path,
    model_path: Path,
    config_dir: Path,
    batch_path: Path,
    result_path: Path,
    progress_path: Path,
    device: str,
    dtype: str,
    cpu_offload: bool,
) -> None:
    runner = Path(__file__).parents[2] / "integrations" / "image_generation" / "sdxl_runner.py"
    command = [
        str(python_path), "-s", str(runner),
        "--model-path", str(model_path),
        "--config-dir", str(config_dir),
        "--batch-file", str(batch_path),
        "--result-file", str(result_path),
        "--progress-file", str(progress_path),
        "--device", device,
        "--dtype", dtype,
    ]
    if cpu_offload:
        command.append("--cpu-offload")
    started = time.monotonic()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    task_control.register_process(project_id, process)
    try:
        stdout, stderr = process.communicate()
    finally:
        task_control.unregister_process(project_id, process)
    task_control.check_cancelled(project_id)
    logger.info("Image generation runner completed in %.2fs", time.monotonic() - started)
    if process.returncode != 0:
        details = (stderr or stdout or "图片生成子进程失败").strip()
        if not result_path.is_file():
            raise RuntimeError(details[-4000:])


def _apply_results(session: Session, result_path: Path) -> None:
    if not result_path.is_file():
        raise RuntimeError("图片生成结果文件不存在")
    results = json.loads(result_path.read_text(encoding="utf-8"))
    for result in results:
        variant = session.get(GeneratedImageVariant, result["variant_id"])
        if not variant:
            continue
        variant.status = result.get("status", "failed")
        variant.generation_seconds = result.get("generation_seconds")
        variant.error_message = result.get("error")
        variant.updated_at = utc_now_iso()
        session.add(variant)
    session.commit()


def _load_results_by_variant(result_path: Path) -> dict[str, dict]:
    if not result_path.is_file():
        return {}
    try:
        results = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(results, list):
        return {}
    return {
        str(item["variant_id"]): item
        for item in results
        if isinstance(item, dict)
        and item.get("variant_id")
        and item.get("status") == "completed"
    }


def _valid_generated_image(path: Path, width: int, height: int) -> bool:
    if not path.is_file():
        return False
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            return image.size == (width, height)
    except (OSError, ValueError):
        return False


def _register_generated_image(session: Session, project: Project, variant: GeneratedImageVariant) -> None:
    path = Path(variant.path).resolve()
    file_hash = _sha256(path)
    media_file = session.exec(
        select(MediaFile).where(
            MediaFile.provider == PROVIDER,
            MediaFile.provider_asset_id == variant.id,
        )
    ).first()
    if media_file is None:
        for candidate in session.exec(
            select(MediaFile).where(
                MediaFile.provider == PROVIDER,
                MediaFile.file_hash == file_hash,
            )
        ).all():
            try:
                metadata = json.loads(candidate.metadata_json or "{}")
            except json.JSONDecodeError:
                continue
            if metadata.get("project_id") == project.id:
                media_file = candidate
                break
    if media_file is None:
        with Image.open(path) as image:
            width, height = image.size
        media_file = MediaFile(
            id=f"generated_media_{hashlib.sha1(variant.id.encode()).hexdigest()[:20]}",
            provider=PROVIDER,
            provider_asset_id=variant.id,
            path=str(path),
            filename=path.name,
            media_type="image",
            file_hash=file_hash,
            size_bytes=path.stat().st_size,
            width=width,
            height=height,
            library_role=LIBRARY_ROLE_PROJECT_GENERATED,
            metadata_json=json.dumps(
                {
                    "project_id": project.id,
                    "scene_id": variant.scene_id,
                    "variant_id": variant.id,
                    "prompt": variant.prompt,
                    "negative_prompt": variant.negative_prompt,
                    "model": variant.model_name,
                    "seed": variant.seed,
                    "ai_generated": True,
                },
                ensure_ascii=False,
            ),
        )
        shot = MediaShot(
            id=f"generated_shot_{hashlib.sha1(variant.id.encode()).hexdigest()[:20]}",
            media_file_id=media_file.id,
            shot_index=1,
            description=variant.prompt,
            tags_json=json.dumps(["ai generated", "documentary", "project scoped"]),
            thumbnail_path=str(path),
            library_role=LIBRARY_ROLE_PROJECT_GENERATED,
            technical_json=json.dumps({"ai_generated": True, "variant_id": variant.id}),
        )
        session.add_all([media_file, shot])
        session.flush()
    else:
        shot = session.exec(select(MediaShot).where(MediaShot.media_file_id == media_file.id)).first()
        if shot is None:
            raise RuntimeError("生成图片素材缺少 MediaShot")

    variant.media_file_id = media_file.id
    variant.updated_at = utc_now_iso()
    session.add(variant)


def _clear_scene_generated_assets(
    session: Session,
    scene_id: str,
    *,
    preserve_variant_ids: set[str] | None = None,
) -> list[Path]:
    preserved = preserve_variant_ids or set()
    variants = list(
        session.exec(
            select(GeneratedImageVariant).where(GeneratedImageVariant.scene_id == scene_id)
        ).all()
    )
    variants = [item for item in variants if item.id not in preserved]
    media_ids = {item.media_file_id for item in variants if item.media_file_id}
    shot_ids_by_media = {
        media_id: {
            shot.id
            for shot in session.exec(
                select(MediaShot).where(MediaShot.media_file_id == media_id)
            ).all()
        }
        for media_id in media_ids
    }
    stale_shot_ids = {shot_id for ids in shot_ids_by_media.values() for shot_id in ids}
    for assignment in session.exec(
        select(SceneAssignment).where(SceneAssignment.scene_id == scene_id)
    ).all():
        if assignment.media_shot_id in stale_shot_ids:
            session.delete(assignment)
    for variant in variants:
        session.delete(variant)
    session.flush()
    deleted_media_ids: set[str] = set()
    for media_id in media_ids:
        still_referenced = session.exec(
            select(GeneratedImageVariant).where(GeneratedImageVariant.media_file_id == media_id)
        ).first()
        if still_referenced:
            continue
        shots = list(
            session.exec(select(MediaShot).where(MediaShot.media_file_id == media_id)).all()
        )
        referenced_assignment = session.exec(
            select(SceneAssignment).where(
                SceneAssignment.media_shot_id.in_([shot.id for shot in shots])
            )
        ).first() if shots else None
        if referenced_assignment:
            continue
        for shot in shots:
            session.delete(shot)
        media_file = session.get(MediaFile, media_id)
        if media_file and media_file.provider == PROVIDER:
            session.delete(media_file)
            deleted_media_ids.add(media_id)
    session.flush()
    # If a new variant deduplicated to an old MediaFile, that MediaFile still
    # points at the old path. Keep it until the final reference is removed.
    return [
        Path(item.path)
        for item in variants
        if item.media_file_id is None or item.media_file_id in deleted_media_ids
    ]


def _stable_seed(project_id: str, scene_id: str, variant_index: int) -> int:
    value = hashlib.sha256(f"{project_id}:{scene_id}:{variant_index}".encode()).digest()
    return int.from_bytes(value[:4], "big") & 0x7FFFFFFF or random.randint(1, 2**31 - 1)


def _regeneration_seed(
    project_id: str,
    scene_id: str,
    variant_index: int,
    regeneration_id: str | None,
) -> int:
    if not regeneration_id:
        raise ValueError("Image regeneration id is required")
    value = hashlib.sha256(
        f"{project_id}:{scene_id}:{variant_index}:regenerate:{regeneration_id}".encode()
    ).digest()
    return int.from_bytes(value[:4], "big") & 0x7FFFFFFF or 1


def _signature(prompt: str, negative: str, model: Path, seed: int, width: int, height: int, steps: int, guidance: float) -> str:
    payload = [WORKFLOW_VERSION, prompt, negative, str(model.resolve()), model.stat().st_mtime_ns, seed, width, height, steps, guidance]
    return stable_json_hash(payload)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _generate_batch_local(request: ImageBatchRequest) -> None:
    request.result_path.unlink(missing_ok=True)
    write_json(request.batch_path, list(request.jobs))
    write_json(
        request.progress_path,
        {"status": "queued", "completed": 0, "failed": 0, "total": len(request.jobs)},
    )
    with gpu_resource.exclusive_gpu(f"image-generation:project:{request.project_id}"):
        _run_batch(
            request.project_id,
            request.python_path,
            request.model_path,
            request.config_dir,
            request.batch_path,
            request.result_path,
            request.progress_path,
            request.device,
            request.dtype,
            request.cpu_offload,
        )


def bind_builtin_provider_runtimes() -> None:
    if not provider_registry.is_executable("image.local_sdxl"):
        provider_registry.bind_runtime(
            "image.local_sdxl",
            ImageProviderRuntime(generate_batch=_generate_batch_local),
        )
