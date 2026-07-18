"""Run a CosyVoice zero-shot voice-clone batch in its own Python environment."""

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


def cosyvoice_prompt_text(model_dir: Path, reference_text: str, instruction: str) -> str:
    if not (model_dir / "cosyvoice3.yaml").is_file():
        return reference_text
    prefix = instruction.strip()
    if not prefix:
        return reference_text
    if "<|endofprompt|>" in prefix:
        return f"{prefix}{reference_text}"
    return f"{prefix}<|endofprompt|>{reference_text}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cosyvoice-root", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--batch-file", required=True)
    parser.add_argument("--voice", required=True)
    parser.add_argument("--reference-text", required=True)
    parser.add_argument("--result-file", required=True)
    parser.add_argument("--progress-file", required=True)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--instruction", default="You are a helpful assistant.")
    parser.add_argument("--fp16", action="store_true")
    args = parser.parse_args()

    cosyvoice_root = Path(args.cosyvoice_root).resolve()
    sys.path.insert(0, str(cosyvoice_root / "third_party" / "Matcha-TTS"))
    sys.path.insert(0, str(cosyvoice_root))

    import torch
    import torchaudio
    from cosyvoice.cli.cosyvoice import AutoModel

    model_dir = Path(args.model_dir).resolve()
    model = AutoModel(model_dir=str(model_dir), fp16=args.fp16)
    prompt_text = cosyvoice_prompt_text(model_dir, args.reference_text.strip(), args.instruction)
    prompt_audio = str(Path(args.voice).resolve())
    zero_shot_spk_id = "tubeaiflow_reference"
    model.add_zero_shot_spk(prompt_text, prompt_audio, zero_shot_spk_id)

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
            chunks = [
                item["tts_speech"].cpu()
                for item in model.inference_zero_shot(
                    task["text"],
                    prompt_text,
                    prompt_audio,
                    zero_shot_spk_id=zero_shot_spk_id,
                    stream=False,
                    speed=args.speed,
                )
            ]
            if not chunks:
                raise RuntimeError("CosyVoice returned no audio")
            wav = torch.cat(chunks, dim=1)
            torchaudio.save(str(output_path), wav, model.sample_rate)
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
