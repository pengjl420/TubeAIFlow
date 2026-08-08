"""Run an IndexTTS segment batch inside the bundled IndexTTS runtime."""

import argparse
import json
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
    parser.add_argument("--index-root", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--batch-file", required=True)
    parser.add_argument("--voice", required=True)
    parser.add_argument("--result-file", required=True)
    parser.add_argument("--progress-file", required=True)
    parser.add_argument("--max-text-tokens", type=int, default=120)
    args = parser.parse_args()

    index_root = Path(args.index_root).resolve()
    sys.path.insert(0, str(index_root))
    sys.path.insert(0, str(index_root / "indextts"))

    from indextts.infer import IndexTTS

    model_dir = Path(args.model_dir).resolve()
    model = IndexTTS(model_dir=str(model_dir), cfg_path=str(model_dir / "config.yaml"))
    tasks = json.loads(Path(args.batch_file).resolve().read_text(encoding="utf-8"))
    result_file = Path(args.result_file).resolve()
    progress_file = Path(args.progress_file).resolve()
    voice = str(Path(args.voice).resolve())
    results: list[dict] = []
    write_json(result_file, results)
    write_json(progress_file, _progress(tasks, results, None, "running"))

    for task in tasks:
        segment_id = task["segment_id"]
        output_path = Path(task["output_path"]).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(progress_file, _progress(tasks, results, segment_id, "running"))
        try:
            model.infer(
                audio_prompt=voice,
                text=task["text"],
                output_path=str(output_path),
                verbose=False,
                max_text_tokens_per_sentence=args.max_text_tokens,
            )
            if not output_path.is_file():
                raise RuntimeError("IndexTTS did not create an audio file")
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
