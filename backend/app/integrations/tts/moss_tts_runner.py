"""Run a MOSS-TTS Local v1.5 segment batch inside its own runtime."""

import argparse
import json
import shutil
import sys
from pathlib import Path

try:
    from .runner_io import write_json
except ImportError:
    from runner_io import write_json


def _progress(tasks: list[dict], results: list[dict], current: str | None, status: str) -> dict:
    return {
        "total": len(tasks),
        "completed": sum(bool(item.get("success")) for item in results),
        "failed": sum(not bool(item.get("success")) for item in results),
        "current_segment_id": current,
        "status": status,
        "segment_ids": [item["segment_id"] for item in tasks],
        "segment_results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--moss-root", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--codec-dir", required=True)
    parser.add_argument("--batch-file", required=True)
    parser.add_argument("--voice", required=True)
    parser.add_argument("--result-file", required=True)
    parser.add_argument("--progress-file", required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--max-new-tokens", type=int, default=7500)
    args = parser.parse_args()

    moss_root = Path(args.moss_root).resolve()
    sys.path.insert(0, str(moss_root / "moss_tts_local_v1.5"))
    from streaming import StreamingRequest, load_runtime, synthesize_stream

    runtime = load_runtime(
        model_dir=str(Path(args.model_dir).resolve()),
        codec_dir=str(Path(args.codec_dir).resolve()),
        device=args.device,
        tts_device=args.device,
        codec_device=args.device,
        dtype=args.dtype,
        attn_implementation="sdpa",
        codec_weight_dtype="bf16",
        codec_compute_dtype="bf16",
    )
    tasks = json.loads(Path(args.batch_file).resolve().read_text(encoding="utf-8"))
    result_file = Path(args.result_file).resolve()
    progress_file = Path(args.progress_file).resolve()
    run_dir = progress_file.parent / "moss_runs"
    results: list[dict] = []
    write_json(result_file, results)
    write_json(progress_file, _progress(tasks, results, None, "running"))

    for index, task in enumerate(tasks, start=1):
        segment_id = task["segment_id"]
        output_path = Path(task["output_path"]).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(progress_file, _progress(tasks, results, segment_id, "running"))
        try:
            request = StreamingRequest(
                text=task["text"],
                mode="voice_clone",
                prompt_text="",
                prompt_audio_path=str(Path(args.voice).resolve()),
                language="English",
                max_new_frames=args.max_new_tokens,
                do_sample=True,
                temperature=1.7,
                top_p=0.8,
                top_k=25,
                repetition_penalty=1.0,
                seed=1234 + index,
                codec_chunk_frames=8,
            )
            generated_path = None
            for event in synthesize_stream(runtime, request, output_dir=run_dir):
                if event.type == "result":
                    generated_path = Path(event.data["audio_path"]).resolve()
            if generated_path is None or not generated_path.is_file():
                raise RuntimeError("MOSS-TTS did not create an audio file")
            shutil.copyfile(generated_path, output_path)
            results.append({"segment_id": segment_id, "success": True})
        except Exception as exc:
            output_path.unlink(missing_ok=True)
            results.append({"segment_id": segment_id, "success": False, "error": str(exc)})
        write_json(result_file, results)

    status = "completed" if all(item["success"] for item in results) else "failed"
    write_json(progress_file, _progress(tasks, results, None, status))
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
