"""Run a Chatterbox multilingual voice-clone batch in its own Python environment."""

import argparse
import json
import sys
from pathlib import Path

try:
    from .runner_io import write_json
except ImportError:
    from runner_io import write_json


def progress_payload(total, segment_ids, results, current_segment_id, current_index, status) -> dict:
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
    parser.add_argument("--chatterbox-root")
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--batch-file", required=True)
    parser.add_argument("--voice", required=True)
    parser.add_argument("--result-file", required=True)
    parser.add_argument("--progress-file", required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--language", default="zh")
    parser.add_argument("--t3-model", choices=("v2", "v3"), default="v3")
    parser.add_argument("--exaggeration", type=float, default=0.5)
    parser.add_argument("--cfg-weight", type=float, default=0.5)
    parser.add_argument("--temperature", type=float, default=0.8)
    args = parser.parse_args()

    if args.chatterbox_root:
        root = Path(args.chatterbox_root).resolve()
        sys.path.insert(0, str(root / "src"))
        sys.path.insert(0, str(root))

    import torchaudio
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    model = ChatterboxMultilingualTTS.from_local(
        Path(args.model_dir).resolve(),
        device=args.device,
        t3_model=args.t3_model,
    )
    model.prepare_conditionals(
        str(Path(args.voice).resolve()),
        exaggeration=args.exaggeration,
    )

    tasks = json.loads(Path(args.batch_file).resolve().read_text(encoding="utf-8"))
    result_file = Path(args.result_file).resolve()
    progress_file = Path(args.progress_file).resolve()
    results = []
    total = len(tasks)
    segment_ids = [task["segment_id"] for task in tasks]
    write_json(result_file, results)
    write_json(progress_file, progress_payload(total, segment_ids, results, None, None, "running"))

    for index, task in enumerate(tasks, start=1):
        output_path = Path(task["output_path"]).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(
            progress_file,
            progress_payload(total, segment_ids, results, task["segment_id"], index, "running"),
        )
        try:
            wav = model.generate(
                task["text"],
                language_id=args.language,
                exaggeration=args.exaggeration,
                cfg_weight=args.cfg_weight,
                temperature=args.temperature,
            )
            torchaudio.save(str(output_path), wav.cpu(), model.sr)
            results.append({"segment_id": task["segment_id"], "success": True})
        except Exception as exc:
            output_path.unlink(missing_ok=True)
            results.append({"segment_id": task["segment_id"], "success": False, "error": str(exc)})
        write_json(result_file, results)
        write_json(
            progress_file,
            progress_payload(total, segment_ids, results, task["segment_id"], index, "running"),
        )

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
