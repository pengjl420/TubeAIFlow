from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def semantic_command() -> tuple[list[str], Path]:
    executable = ROOT / "backend" / "workspace" / "tools" / "llama.cpp" / "llama-server.exe"
    model = ROOT / "models" / "llm" / "qwen3-8b-q4_k_m" / "Qwen3-8B-Q4_K_M.gguf"
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
