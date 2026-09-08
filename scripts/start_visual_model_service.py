from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LLM_FILENAMES = {
    "qwen3-4b-q4_k_m": "Qwen3-4B-Q4_K_M.gguf",
    "qwen3-8b-q4_k_m": "Qwen3-8B-Q4_K_M.gguf",
    "qwen3-14b-q4_k_m": "Qwen3-14B-Q4_K_M.gguf",
}


def _semantic_settings() -> tuple[str, Path]:
    model_id = "qwen3-8b-q4_k_m"
    models_dir = ROOT / "models" / "llm"
    database = ROOT / "backend" / "workspace" / "app.db"
    if database.is_file():
        try:
            with sqlite3.connect(database) as connection:
                row = connection.execute(
                    "SELECT config_json FROM system_settings WHERE id = 1"
                ).fetchone()
            payload = json.loads(row[0]) if row else {}
            if isinstance(payload, dict):
                model_id = str(payload.get("local_llm_model") or model_id)
                models_dir = Path(payload.get("local_llm_models_dir") or models_dir)
        except (sqlite3.Error, json.JSONDecodeError, OSError):
            pass
    if model_id not in LLM_FILENAMES:
        raise RuntimeError(f"Unsupported local semantic model: {model_id}")
    return model_id, models_dir.expanduser().resolve()


def semantic_command() -> tuple[list[str], Path]:
    tools_dir = ROOT / "backend" / "workspace" / "tools" / "llama.cpp"
    executable = next(tools_dir.rglob("llama-server.exe"), tools_dir / "llama-server.exe")
    model_id, models_dir = _semantic_settings()
    model = models_dir / model_id / LLM_FILENAMES[model_id]
    return (
        [
            str(executable),
            "--model",
            str(model),
            "--host",
            "127.0.0.1",
            "--port",
            "18090",
            "--ctx-size",
            "16384",
            "--n-gpu-layers",
            "99",
            "--jinja",
        ],
        ROOT,
    )


def image_command() -> tuple[list[str], Path]:
    comfyui = ROOT / "backend" / "workspace" / "tools" / "ComfyUI"
    return (
        [
            sys.executable,
            str(comfyui / "main.py"),
            "--listen",
            "127.0.0.1",
            "--port",
            "8188",
            "--disable-auto-launch",
            "--extra-model-paths-config",
            str(ROOT / "config" / "comfyui_extra_model_paths.yaml"),
            "--output-directory",
            str(ROOT / "backend" / "workspace" / "comfyui_output"),
            "--temp-directory",
            str(ROOT / "backend" / "workspace" / "comfyui_temp"),
            "--lowvram",
        ],
        comfyui,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start one visual AI service. Run semantic and image services serially."
    )
    parser.add_argument("service", choices=("semantic", "image"))
    args = parser.parse_args()
    command, working_directory = (
        semantic_command() if args.service == "semantic" else image_command()
    )
    missing = Path(command[0]) if args.service == "semantic" else working_directory / "main.py"
    if not missing.is_file():
        raise SystemExit(f"Missing runtime: {missing}")
    return subprocess.run(command, cwd=working_directory, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
