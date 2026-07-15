"""Run a Qwen3-TTS voice-clone batch inside its own Python environment."""

import argparse
import json
import sys
from pathlib import Path


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def progress_payload(
    total: int,
    segment_ids: list[str],
    results: list[dict],
    current_segment_id: str | None,
    current_index: int | None,
    status: str,
) -> dict:
    payload = {
        "total": total,
        "completed": sum(1 for item in results if item["success"]),
        "failed": sum(1 for item in results if not item["success"]),
        "current_segment_id": current_segment_id,
        "status": status,
        "segment_ids": segment_ids,
        "segment_results": results,
    }
    if current_index is not None:
        payload["current_index"] = current_index
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qwen-root", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--batch-file", required=True)
    parser.add_argument("--voice", required=True)
    parser.add_argument("--reference-text", default="")
    parser.add_argument("--result-file", required=True)
    parser.add_argument("--progress-file", required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--dtype", choices=("bfloat16", "float16", "float32"), default="bfloat16")
    parser.add_argument("--language", default="Chinese")
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    args = parser.parse_args()

    qwen_root = Path(args.qwen_root).resolve()
    sys.path.insert(0, str(qwen_root))

    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    dtype = {
        "bfloat16": torch.bfloat16,
        "float16": torch.float16,
        "float32": torch.float32,
    }[args.dtype]
    model = Qwen3TTSModel.from_pretrained(
        str(Path(args.model_dir).resolve()),
        device_map=args.device,
        dtype=dtype,
        # flash-attn is optional and is not installed in the standard local setup.
        attn_implementation="sdpa",
    )

    reference_text = args.reference_text.strip() or None
    prompt = model.create_voice_clone_prompt(
        ref_audio=str(Path(args.voice).resolve()),
        ref_text=reference_text,
        x_vector_only_mode=reference_text is None,
    )

    tasks = json.loads(Path(args.batch_file).resolve().read_text(encoding="utf-8"))
    result_file = Path(args.result_file).resolve()
    progress_file = Path(args.progress_file).resolve()
    results = []
    total = len(tasks)
    segment_ids = [task["segment_id"] for task in tasks]
    write_json(progress_file, progress_payload(total, segment_ids, results, None, None, "running"))

    for index, task in enumerate(tasks, start=1):
        output_path = Path(task["output_path"]).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(
            progress_file,
            progress_payload(total, segment_ids, results, task["segment_id"], index, "running"),
        )
        try:
            wavs, sample_rate = model.generate_voice_clone(
                text=task["text"],
                language=args.language,
                voice_clone_prompt=prompt,
                max_new_tokens=args.max_new_tokens,
            )
            sf.write(str(output_path), wavs[0], sample_rate)
            results.append({"segment_id": task["segment_id"], "success": True})
        except Exception as exc:
            output_path.unlink(missing_ok=True)
            results.append(
                {"segment_id": task["segment_id"], "success": False, "error": str(exc)}
            )
        write_json(
            progress_file,
            progress_payload(total, segment_ids, results, task["segment_id"], index, "running"),
        )

    write_json(result_file, results)
    write_json(
        progress_file,
        progress_payload(
            total,
            segment_ids,
            results,
            None,
            None,
            "completed" if all(item["success"] for item in results) else "failed",
        ),
    )
    return 0 if all(item["success"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
