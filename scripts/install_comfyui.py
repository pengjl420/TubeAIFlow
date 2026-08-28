from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALL_DIR = ROOT / "backend" / "workspace" / "tools" / "ComfyUI"
REPOSITORY = "https://github.com/Comfy-Org/ComfyUI.git"
REVISION = "5ab2f7a2d676c1fb7b410c22e82e2ed8f217b56c"


def run(*arguments: str) -> None:
    subprocess.run(arguments, cwd=ROOT, check=True)


def main() -> int:
    if not (INSTALL_DIR / ".git").is_dir():
        INSTALL_DIR.parent.mkdir(parents=True, exist_ok=True)
        run("git", "clone", "--filter=blob:none", REPOSITORY, str(INSTALL_DIR))
    run("git", "-C", str(INSTALL_DIR), "fetch", "--depth", "1", "origin", REVISION)
    run("git", "-C", str(INSTALL_DIR), "checkout", "--detach", REVISION)
    run(sys.executable, "-m", "pip", "install", "-r", str(INSTALL_DIR / "requirements.txt"))
    print(f"ComfyUI {REVISION} installed at {INSTALL_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
