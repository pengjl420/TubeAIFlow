"""Run an IndexTTS1 batch inside its own Python environment."""

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
    parser.add_argument("--index-root", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--batch-file", required=True)
    parser.add_argument("--voice", required=True)
    parser.add_argument("--result-file", required=True)
    parser.add_argument("--progress-file", required=True)
    parser.add_argument("--fp16", action="store_true")
    args = parser.parse_args()

    index_root = Path(args.index_root).resolve()
    sys.path.insert(0, str(index_root))

    from indextts.infer import IndexTTS

    model_dir = Path(args.model_dir).resolve()
    tts = IndexTTS(
        cfg_path=str(model_dir / "config.yaml"),
        model_dir=str(model_dir),
        is_fp16=args.fp16,
    )
    batch_file = Path(args.batch_file).resolve()
    voice_path = Path(args.voice).resolve()
    result_file = Path(args.result_file).resolve()
    progress_file = Path(args.progress_file).resolve()

    tasks = json.loads(batch_file.read_text(encoding="utf-8"))
    results = []
    total = len(tasks)
    segment_ids = [task["segment_id"] for task in tasks]
    write_json(progress_file, progress_payload(total, segment_ids, results, None, None, "running"))

    for index, task in enumerate(tasks, start=1):
        output_path = Path(task["output_path"]).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(progress_file, progress_payload(total, segment_ids, results, task["segment_id"], index, "running"))
        try:
            tts.infer(
                audio_prompt=str(voice_path),
                text=task["text"],
                output_path=str(output_path),
            )
            results.append({"segment_id": task["segment_id"], "success": True})
        except Exception as exc:
            results.append(
                {"segment_id": task["segment_id"], "success": False, "error": str(exc)}
            )
        write_json(progress_file, progress_payload(total, segment_ids, results, task["segment_id"], index, "running"))

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
