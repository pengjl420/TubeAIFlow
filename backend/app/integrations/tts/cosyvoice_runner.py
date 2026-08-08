"""Run a CosyVoice zero-shot voice-clone batch in its own Python environment."""

import argparse
import hashlib
import json
import statistics
import sys
import unicodedata
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


def segment_attempt_seed(
    segment_id: str,
    text: str,
    attempt: int,
    seed_round: int = 0,
) -> int:
    """Return a reproducible seed that changes for each explicit retry round."""
    material = (
        f"tubeaiflow-cosyvoice-v2\0{segment_id}\0{text}\0{seed_round}\0{attempt}"
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:4], "big")


def spoken_character_count(text: str) -> int:
    """Estimate spoken length while ignoring punctuation and whitespace.

    ASCII digits expand into words when spoken (for example, ``1950s`` becomes
    roughly "nineteen fifties"). Counting every digit as one character makes
    otherwise normal audio look abnormally long, so use a conservative spoken
    weight for digits while retaining the existing behavior for other scripts.
    """
    return sum(
        4 if char.isascii() and char.isdigit() else 1
        for char in text
        if unicodedata.category(char)[0] in {"L", "N"}
    )


def duration_quality(
    text: str,
    duration: float,
    accepted_seconds_per_character: list[float],
    min_chars_per_second: float,
    duration_slack_seconds: float,
    duration_outlier_ratio: float,
) -> tuple[bool, str | None, float]:
    character_count = spoken_character_count(text)
    if character_count < 8 or duration <= 0:
        return False, None, 0.0

    seconds_per_character = duration / character_count
    absolute_limit = character_count / min_chars_per_second + duration_slack_seconds
    if duration > absolute_limit:
        return (
            True,
            f"duration {duration:.2f}s exceeds absolute limit {absolute_limit:.2f}s "
            f"for {character_count} spoken characters",
            seconds_per_character,
        )

    if len(accepted_seconds_per_character) >= 5:
        typical_ratio = statistics.median(accepted_seconds_per_character[-50:])
        expected_duration = typical_ratio * character_count
        if (
            seconds_per_character > typical_ratio * duration_outlier_ratio
            and duration > expected_duration + duration_slack_seconds
        ):
            return (
                True,
                f"duration {duration:.2f}s is an outlier; recent expectation is "
                f"{expected_duration:.2f}s for {character_count} spoken characters",
                seconds_per_character,
            )
    return False, None, seconds_per_character


def validate_runtime(torch, onnxruntime) -> None:
    """Fail early with an actionable error when GPU packages cannot run."""
    if not torch.cuda.is_available():
        return

    device_name = torch.cuda.get_device_name(0)
    capability = torch.cuda.get_device_capability(0)
    architecture = f"sm_{capability[0]}{capability[1]}"
    supported_architectures = list(torch.cuda.get_arch_list())
    if supported_architectures and architecture not in supported_architectures:
        raise RuntimeError(
            f"PyTorch {torch.__version__} does not support {device_name} ({architecture}); "
            f"this build supports {', '.join(supported_architectures)}. Install a PyTorch "
            "CUDA build that includes the GPU architecture."
        )

    try:
        probe = torch.ones(1, device="cuda")
        probe.add_(1)
        torch.cuda.synchronize()
    except Exception as exc:
        raise RuntimeError(
            f"CUDA preflight failed for {device_name} ({architecture}) with "
            f"PyTorch {torch.__version__}: {exc}"
        ) from exc

    providers = onnxruntime.get_available_providers()
    if "CUDAExecutionProvider" not in providers:
        raise RuntimeError(
            "ONNX Runtime CUDAExecutionProvider is unavailable while CUDA is enabled; "
            f"available providers: {', '.join(providers)}. Install a CUDA-compatible "
            "onnxruntime-gpu package."
        )


def initialization_failure_results(tasks: list[dict], error: Exception) -> list[dict]:
    message = f"CosyVoice initialization failed: {error}"
    return [
        {
            "segment_id": task["segment_id"],
            "success": False,
            "error": message,
            "attempts": [],
        }
        for task in tasks
    ]


def use_cached_wetext(cosyvoice_root: Path) -> bool:
    """Route WeText to its complete local cache without a ModelScope API call."""
    model_dir = (
        cosyvoice_root
        / "model_cache"
        / "modelscope"
        / "hub"
        / "pengzhendong"
        / "wetext"
    )
    required_files = (
        model_dir / "en" / "tn" / "tagger.fst",
        model_dir / "en" / "tn" / "verbalizer.fst",
        model_dir / "zh" / "tn" / "tagger.fst",
        model_dir / "zh" / "tn" / "verbalizer.fst",
        model_dir / "zh" / "tn" / "verbalizer_remove_erhua.fst",
    )
    if not all(path.is_file() for path in required_files):
        return False

    import modelscope

    remote_snapshot_download = modelscope.snapshot_download

    def snapshot_download(model_id, *args, **kwargs):
        if model_id == "pengzhendong/wetext":
            return str(model_dir)
        return remote_snapshot_download(model_id, *args, **kwargs)

    modelscope.snapshot_download = snapshot_download
    return True


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
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--seed-round", type=int, default=0)
    parser.add_argument("--min-chars-per-second", type=float, default=2.8)
    parser.add_argument("--duration-slack-seconds", type=float, default=2.0)
    parser.add_argument("--duration-outlier-ratio", type=float, default=1.45)
    args = parser.parse_args()

    tasks = json.loads(Path(args.batch_file).resolve().read_text(encoding="utf-8"))
    result_file = Path(args.result_file).resolve()
    progress_file = Path(args.progress_file).resolve()
    results = []
    total = len(tasks)
    segment_ids = [task["segment_id"] for task in tasks]
    write_json(result_file, results)
    write_json(progress_file, progress_payload(total, segment_ids, results, None, None, "running"))

    cosyvoice_root = Path(args.cosyvoice_root).resolve()
    sys.path.insert(0, str(cosyvoice_root / "third_party" / "Matcha-TTS"))
    sys.path.insert(0, str(cosyvoice_root))

    try:
        import onnxruntime
        import torch
        import torchaudio

        use_cached_wetext(cosyvoice_root)
        from cosyvoice.cli.cosyvoice import AutoModel
        from cosyvoice.utils.common import set_all_random_seed

        validate_runtime(torch, onnxruntime)
        model_dir = Path(args.model_dir).resolve()
        model = AutoModel(model_dir=str(model_dir), fp16=args.fp16)
        prompt_text = cosyvoice_prompt_text(
            model_dir, args.reference_text.strip(), args.instruction
        )
        prompt_audio = str(Path(args.voice).resolve())
        zero_shot_spk_id = "tubeaiflow_reference"
        model.add_zero_shot_spk(prompt_text, prompt_audio, zero_shot_spk_id)
    except Exception as exc:
        results = initialization_failure_results(tasks, exc)
        write_json(result_file, results)
        write_json(
            progress_file,
            progress_payload(total, segment_ids, results, None, None, "failed"),
        )
        print(results[0]["error"] if results else str(exc), file=sys.stderr)
        return 1

    accepted_seconds_per_character = []

    for index, task in enumerate(tasks, start=1):
        output_path = Path(task["output_path"]).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(
            progress_file,
            progress_payload(total, segment_ids, results, task["segment_id"], index, "running"),
        )
        attempts = []
        try:
            for attempt in range(1, args.max_attempts + 1):
                seed = segment_attempt_seed(
                    task["segment_id"],
                    task["text"],
                    attempt,
                    args.seed_round,
                )
                set_all_random_seed(seed)
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
                duration = wav.shape[1] / model.sample_rate
                suspicious, reason, seconds_per_character = duration_quality(
                    task["text"],
                    duration,
                    accepted_seconds_per_character,
                    args.min_chars_per_second,
                    args.duration_slack_seconds,
                    args.duration_outlier_ratio,
                )
                attempts.append(
                    {
                        "attempt": attempt,
                        "seed_round": args.seed_round,
                        "seed": seed,
                        "duration": round(duration, 3),
                        "rejected": suspicious,
                        "reason": reason,
                    }
                )
                print(
                    f"CosyVoice attempt segment={task['segment_id']} attempt={attempt} "
                    f"seed={seed} duration={duration:.3f}s "
                    f"status={'rejected' if suspicious else 'accepted'}"
                )
                if suspicious:
                    print(
                        f"Rejected segment {task['segment_id']} attempt {attempt}: {reason}",
                        file=sys.stderr,
                    )
                    continue

                torchaudio.save(str(output_path), wav, model.sample_rate)
                if seconds_per_character > 0:
                    accepted_seconds_per_character.append(seconds_per_character)
                results.append(
                    {
                        "segment_id": task["segment_id"],
                        "success": True,
                        "duration": round(duration, 3),
                        "attempts": attempts,
                    }
                )
                break
            else:
                raise RuntimeError(
                    f"CosyVoice produced suspicious duration in all {args.max_attempts} attempts"
                )
        except Exception as exc:
            output_path.unlink(missing_ok=True)
            results.append(
                {
                    "segment_id": task["segment_id"],
                    "success": False,
                    "error": str(exc),
                    "attempts": attempts,
                }
            )
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
