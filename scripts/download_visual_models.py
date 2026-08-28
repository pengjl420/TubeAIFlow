from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download, snapshot_download


ROOT = Path(__file__).resolve().parents[1]
MODELS_ROOT = ROOT / "models"


@dataclass(frozen=True)
class ModelSpec:
    model_type: str
    repo_id: str
    directory: str
    required_files: tuple[str, ...]
    allow_patterns: tuple[str, ...] | None = None

    @property
    def target(self) -> Path:
        return MODELS_ROOT / self.model_type / self.directory


MODELS = {
    "llm": ModelSpec(
        model_type="llm",
        repo_id="Qwen/Qwen3-8B-GGUF",
        directory="qwen3-8b-q4_k_m",
        required_files=("Qwen3-8B-Q4_K_M.gguf",),
        allow_patterns=("Qwen3-8B-Q4_K_M.gguf", "README.md", "LICENSE", "params"),
    ),
    "embedding": ModelSpec(
        model_type="embedding",
        repo_id="BAAI/bge-m3",
        directory="bge-m3-onnx",
        required_files=("onnx/model.onnx", "onnx/model.onnx_data", "onnx/tokenizer.json"),
        allow_patterns=(
            "onnx/*",
            "1_Pooling/config.json",
            "config.json",
            "modules.json",
            "config_sentence_transformers.json",
            "sentence_bert_config.json",
            "README.md",
        ),
    ),
    "image_generation": ModelSpec(
        model_type="image_generation",
        repo_id="black-forest-labs/FLUX.2-klein-4b-fp8",
        directory="flux2-klein-4b-fp8",
        required_files=("flux-2-klein-4b-fp8.safetensors",),
        allow_patterns=("*.safetensors", "README.md", "LICENSE.md"),
    ),
    "vision": ModelSpec(
        model_type="vision",
        repo_id="Qwen/Qwen3-VL-4B-Instruct",
        directory="qwen3-vl-4b-instruct-bf16",
        required_files=(
            "model-00001-of-00002.safetensors",
            "model-00002-of-00002.safetensors",
            "model.safetensors.index.json",
            "config.json",
        ),
    ),
}

IMAGE_COMPONENTS = (
    (
        "Comfy-Org/z_image_turbo",
        "split_files/text_encoders/qwen_3_4b_fp8_mixed.safetensors",
        "text_encoder/qwen_3_4b_fp8_mixed.safetensors",
    ),
    (
        "Comfy-Org/flux2-dev",
        "split_files/vae/flux2-vae.safetensors",
        "vae/flux2-vae.safetensors",
    ),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(spec: ModelSpec) -> dict:
    spec.target.mkdir(parents=True, exist_ok=True)
    print(f"[{spec.model_type}] {spec.repo_id} -> {spec.target}", flush=True)
    api = HfApi()
    info = api.model_info(spec.repo_id, files_metadata=True)
    snapshot_download(
        repo_id=spec.repo_id,
        revision=info.sha,
        local_dir=spec.target,
        allow_patterns=list(spec.allow_patterns) if spec.allow_patterns else None,
        max_workers=4,
    )
    missing = [relative for relative in spec.required_files if not (spec.target / relative).is_file()]
    if missing:
        raise RuntimeError(f"Incomplete {spec.repo_id} download; missing: {missing}")
    checksums = {
        relative: sha256_file(spec.target / relative)
        for relative in spec.required_files
    }
    components = []
    if spec.model_type == "image_generation":
        components = _download_image_components(spec.target)
    manifest = {
        "model_type": spec.model_type,
        "repo_id": spec.repo_id,
        "revision": info.sha,
        "license": info.card_data.get("license") if info.card_data else None,
        "directory": str(spec.target),
        "required_files": list(spec.required_files),
        "sha256": checksums,
        **({"components": components} if components else {}),
    }
    (spec.target / "source.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[{spec.model_type}] verified {len(checksums)} required file(s)", flush=True)
    return manifest


def _download_image_components(target: Path) -> list[dict]:
    api = HfApi()
    components = []
    for repo_id, source_file, target_relative in IMAGE_COMPONENTS:
        info = api.model_info(repo_id)
        downloaded = Path(
            hf_hub_download(
                repo_id=repo_id,
                filename=source_file,
                revision=info.sha,
                local_dir=target / ".components" / repo_id.replace("/", "--"),
            )
        )
        destination = target / target_relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.is_file() or destination.stat().st_size != downloaded.stat().st_size:
            shutil.copy2(downloaded, destination)
        components.append(
            {
                "repo_id": repo_id,
                "revision": info.sha,
                "source_file": source_file,
                "target_file": target_relative,
                "sha256": sha256_file(destination),
            }
        )
        if downloaded.resolve() != destination.resolve():
            downloaded.unlink()
        print(f"[image_generation] verified component {target_relative}", flush=True)
    return components


def main() -> int:
    parser = argparse.ArgumentParser(description="Download visual-pipeline models by model type")
    parser.add_argument(
        "--types",
        nargs="+",
        choices=tuple(MODELS),
        default=list(MODELS),
    )
    args = parser.parse_args()
    free_gb = shutil.disk_usage(MODELS_ROOT).free / 1024**3
    if free_gb < 25:
        raise SystemExit(f"At least 25 GiB free is required; only {free_gb:.1f} GiB remains")
    manifests = [download(MODELS[model_type]) for model_type in args.types]
    inventory_path = MODELS_ROOT / "visual_pipeline_models.json"
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        inventory = {}
    if not isinstance(inventory, dict):
        inventory = {}
    inventory.update({item["model_type"]: item for item in manifests})
    inventory_path.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
