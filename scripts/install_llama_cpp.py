from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
INSTALL_DIR = ROOT / "backend" / "workspace" / "tools" / "llama.cpp"
GITHUB_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            target = (destination / entry.filename).resolve()
            if destination.resolve() not in target.parents and target != destination.resolve():
                raise ValueError(f"Unsafe archive entry: {entry.filename}")
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(entry) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def main() -> int:
    release = httpx.get(GITHUB_API, follow_redirects=True, timeout=30).json()
    release_tag = release["tag_name"]
    expected_name = f"llama-{release_tag}-bin-win-vulkan-x64.zip"
    asset = next(
        (item for item in release["assets"] if item["name"] == expected_name),
        None,
    )
    if asset is None:
        raise SystemExit(f"Latest llama.cpp release has no {expected_name}")
    with tempfile.TemporaryDirectory(dir=ROOT / "backend" / "workspace") as temporary:
        archive = Path(temporary) / expected_name
        with httpx.stream(
            "GET", asset["browser_download_url"], follow_redirects=True, timeout=600
        ) as response:
            response.raise_for_status()
            with archive.open("wb") as output:
                for chunk in response.iter_bytes(1024 * 1024):
                    output.write(chunk)
        actual_hash = sha256_file(archive)
        expected_digest = str(asset.get("digest") or "")
        if expected_digest.startswith("sha256:") and actual_hash != expected_digest[7:]:
            raise RuntimeError("llama.cpp release checksum mismatch")
        safe_extract(archive, INSTALL_DIR)
    server = next(INSTALL_DIR.rglob("llama-server.exe"), None)
    if server is None:
        raise RuntimeError("llama-server.exe was not found after extraction")
    manifest = {
        "repository": "ggml-org/llama.cpp",
        "release": release_tag,
        "asset": expected_name,
        "sha256": actual_hash,
        "server": str(server),
        "backend": "vulkan",
    }
    (INSTALL_DIR / "source.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
