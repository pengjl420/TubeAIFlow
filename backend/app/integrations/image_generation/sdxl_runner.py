from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--config-dir", required=True)
    parser.add_argument("--batch-file", required=True)
    parser.add_argument("--result-file", required=True)
    parser.add_argument("--progress-file", required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--dtype", default="float16")
    parser.add_argument("--cpu-offload", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    import torch
    from diffusers import StableDiffusionXLPipeline

    dtype = {
        "float16": torch.float16,
        "bfloat16": torch.bfloat16,
        "float32": torch.float32,
    }[args.dtype]
    jobs = json.loads(Path(args.batch_file).read_text(encoding="utf-8"))
    result_path = Path(args.result_file)
    progress_path = Path(args.progress_file)
    results = []

    pipeline = StableDiffusionXLPipeline.from_single_file(
        str(Path(args.model_path).resolve()),
        config=str(Path(args.config_dir).resolve()),
        torch_dtype=dtype,
        use_safetensors=True,
        local_files_only=True,
    )
    pipeline.set_progress_bar_config(disable=True)
    pipeline.enable_attention_slicing()
    pipeline.enable_vae_slicing()
    pipeline.enable_vae_tiling()
    if args.cpu_offload and args.device.startswith("cuda"):
        gpu_id = int(args.device.split(":", 1)[1]) if ":" in args.device else 0
        pipeline.enable_model_cpu_offload(gpu_id=gpu_id)
    else:
        pipeline.to(args.device)

    for index, job in enumerate(jobs, start=1):
        started = time.monotonic()
        output_path = Path(job["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"variant_id": job["variant_id"], "output_path": str(output_path)}
        try:
            generator = torch.Generator(device=args.device).manual_seed(int(job["seed"]))
            image = pipeline(
                prompt=job["prompt"],
                negative_prompt=job["negative_prompt"],
                width=int(job["width"]),
                height=int(job["height"]),
                num_inference_steps=int(job["steps"]),
                guidance_scale=float(job["guidance_scale"]),
                generator=generator,
            ).images[0]
            image.save(output_path, format="PNG", optimize=True)
            entry.update(
                status="completed",
                generation_seconds=round(time.monotonic() - started, 3),
            )
        except Exception as exc:
            entry.update(
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
                generation_seconds=round(time.monotonic() - started, 3),
            )
        results.append(entry)
        _write_json(result_path, results)
        _write_json(
            progress_path,
            {
                "status": "running" if index < len(jobs) else "completed",
                "completed": sum(item["status"] == "completed" for item in results),
                "failed": sum(item["status"] == "failed" for item in results),
                "total": len(jobs),
                "current_variant_id": job["variant_id"],
            },
        )

    del pipeline
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return 0 if all(item["status"] == "completed" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
