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
from app.schemas.storyboard import StoryboardContent
from app.shared.time import utc_now_iso


logger = logging.getLogger(__name__)
WORKFLOW_VERSION = "sdxl_single_file_v1"
PROVIDER = "local_image_generation"


def generate_project_images(session: Session, project: Project) -> dict:
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


def _generate(
    session: Session,
    project: Project,
    scenes: list[VisualScene],
    force: bool = False,
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
        if force:
            _clear_scene_generated_assets(session, scene.id)
        if not scene.storyboard_json:
            raise ValueError(f"场景 {scene.scene_index} 尚未生成 Storyboard")
        storyboard = StoryboardContent.model_validate_json(scene.storyboard_json)
        prompt, negative_prompt = _prompts(storyboard, settings.image_generation_negative_prompt)
        scene_dir = generated_dir / f"scene_{scene.scene_index:04d}"
        for variant_index in range(1, settings.image_generation_candidates_per_scene + 1):
            variant_id = f"{scene.id}:image:{variant_index}"
            output_path = scene_dir / f"candidate_{variant_index:02d}.png"
            seed = _stable_seed(project.id, scene.id, variant_index)
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
            elif force or not reusable:
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
            if force or not reusable:
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
        result_path.unlink(missing_ok=True)
        write_json(batch_path, jobs)
        write_json(progress_path, {"status": "queued", "completed": 0, "failed": 0, "total": len(jobs)})
        with gpu_resource.exclusive_gpu(f"image-generation:project:{project.id}"):
            _run_batch(
                project,
                python_path,
                model_path,
                config_dir,
                batch_path,
                result_path,
                progress_path,
                settings.image_generation_device,
                settings.image_generation_dtype,
                settings.image_generation_cpu_offload,
            )
        _apply_results(session, result_path)

    registered = 0
    for variant in variants:
        session.refresh(variant)
        if variant.status == "completed" and Path(variant.path).is_file():
            _register_generated_image(session, project, variant)
            registered += 1
    session.commit()
    failures = [item for item in variants if item.status == "failed"]
    if failures:
        raise RuntimeError(f"{len(failures)} 个图片候选生成失败，请检查 image_generation_results.json")
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
    project: Project,
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
    task_control.register_process(project.id, process)
    try:
        stdout, stderr = process.communicate()
    finally:
        task_control.unregister_process(project.id, process)
    task_control.check_cancelled(project.id)
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
    media_file = session.exec(select(MediaFile).where(MediaFile.file_hash == file_hash)).first()
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


def _clear_scene_generated_assets(session: Session, scene_id: str) -> None:
    variants = list(
        session.exec(
            select(GeneratedImageVariant).where(GeneratedImageVariant.scene_id == scene_id)
        ).all()
    )
    media_ids = {item.media_file_id for item in variants if item.media_file_id}
    for assignment in session.exec(
        select(SceneAssignment).where(SceneAssignment.scene_id == scene_id)
    ).all():
        if assignment.media_shot_id in {
            shot.id
            for media_id in media_ids
            for shot in session.exec(select(MediaShot).where(MediaShot.media_file_id == media_id)).all()
        }:
            session.delete(assignment)
    for media_id in media_ids:
        still_referenced = session.exec(
            select(GeneratedImageVariant).where(
                GeneratedImageVariant.media_file_id == media_id,
                GeneratedImageVariant.scene_id != scene_id,
            )
        ).first()
        if still_referenced:
            continue
        for shot in session.exec(select(MediaShot).where(MediaShot.media_file_id == media_id)).all():
            session.delete(shot)
        media_file = session.get(MediaFile, media_id)
        if media_file and media_file.provider == PROVIDER:
            session.delete(media_file)
    for variant in variants:
        variant.media_file_id = None
        session.add(variant)
    session.flush()


def _stable_seed(project_id: str, scene_id: str, variant_index: int) -> int:
    value = hashlib.sha256(f"{project_id}:{scene_id}:{variant_index}".encode()).digest()
    return int.from_bytes(value[:4], "big") & 0x7FFFFFFF or random.randint(1, 2**31 - 1)


def _signature(prompt: str, negative: str, model: Path, seed: int, width: int, height: int, steps: int, guidance: float) -> str:
    payload = [WORKFLOW_VERSION, prompt, negative, str(model.resolve()), model.stat().st_mtime_ns, seed, width, height, steps, guidance]
    return stable_json_hash(payload)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
