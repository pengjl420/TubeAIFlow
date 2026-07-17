import hashlib
import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import httpx
from sqlmodel import Session

from app.config import get_settings
from app.services.settings.system_settings_service import save_settings


logger = logging.getLogger(__name__)

DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
CHECKSUM_URL = f"{DOWNLOAD_URL}.sha256"
VERSION_URL = f"{DOWNLOAD_URL}.ver"
MAX_DOWNLOAD_BYTES = 250 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024


def get_ffmpeg_status() -> dict:
    settings = get_settings()
    ffmpeg_path = _find_executable(settings.ffmpeg_path)
    ffprobe_path = _find_executable(settings.ffprobe_path)
    version = _read_version(ffmpeg_path)
    probe_version = _read_version(ffprobe_path)
    return {
        "installed": bool(version and probe_version),
        "ffmpeg_path": str(ffmpeg_path) if ffmpeg_path else None,
        "ffprobe_path": str(ffprobe_path) if ffprobe_path else None,
        "version": version,
        "platform_supported": sys.platform == "win32",
    }


def install_ffmpeg(session: Session) -> dict:
    if sys.platform != "win32":
        raise ValueError("自动安装 FFmpeg 当前仅支持 Windows 10/11 64 位系统")

    settings = get_settings()
    install_root = settings.workspace_dir / "tools" / "ffmpeg" / "windows-x64"
    install_root.mkdir(parents=True, exist_ok=True)

    try:
        client_context = httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(600.0, connect=30.0),
        )
        with client_context as client:
            return _install_from_client(session, client, install_root)
    except httpx.HTTPError as exc:
        logger.exception("FFmpeg download failed")
        raise RuntimeError(f"FFmpeg 下载失败：{exc}") from exc


def _install_from_client(session: Session, client: httpx.Client, install_root: Path) -> dict:
    version = _download_text(client, VERSION_URL)
    if not re.fullmatch(r"[0-9A-Za-z._-]+", version):
        raise RuntimeError("FFmpeg 下载源返回了无效版本号")
    expected_hash = _download_text(client, CHECKSUM_URL).split()[0].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise RuntimeError("FFmpeg 下载源返回了无效 SHA-256 校验值")

    version_dir = install_root / version
    existing = _installed_paths(version_dir)
    if existing and _executables_work(*existing):
        return _save_installed_paths(session, existing)

    archive_path: Path | None = None
    staging_dir: Path | None = None
    try:
        archive_path = _download_archive(client, install_root)
        actual_hash = _sha256(archive_path)
        if actual_hash != expected_hash:
            raise RuntimeError("FFmpeg 压缩包 SHA-256 校验失败，文件可能不完整")

        staging_dir = Path(tempfile.mkdtemp(prefix=f"{version}-", dir=install_root))
        ffmpeg_path, ffprobe_path = _extract_executables(archive_path, staging_dir)
        if not _executables_work(ffmpeg_path, ffprobe_path):
            raise RuntimeError("下载的 FFmpeg 或 FFprobe 无法正常运行")

        metadata = {
            "version": version,
            "source": DOWNLOAD_URL,
            "sha256": actual_hash,
            "license": "GPLv3 (Gyan essentials build)",
        }
        (staging_dir / "INSTALLATION.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if version_dir.exists():
            shutil.rmtree(version_dir)
        staging_dir.replace(version_dir)
        staging_dir = None
        installed = _installed_paths(version_dir)
        if not installed:
            raise RuntimeError("FFmpeg 安装完成，但未找到可执行文件")
        return _save_installed_paths(session, installed)
    finally:
        if archive_path:
            archive_path.unlink(missing_ok=True)
        if staging_dir and staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


def _save_installed_paths(session: Session, paths: tuple[Path, Path]) -> dict:
    ffmpeg_path, ffprobe_path = paths
    values = get_settings().model_dump(mode="json")
    values["ffmpeg_path"] = str(ffmpeg_path.resolve())
    values["ffprobe_path"] = str(ffprobe_path.resolve())
    public_settings = save_settings(session, values)
    return {"settings": public_settings, "status": get_ffmpeg_status()}


def _download_text(client: httpx.Client, url: str) -> str:
    response = client.get(url)
    response.raise_for_status()
    value = response.text.strip()
    if not value:
        raise RuntimeError("FFmpeg 下载源返回了空响应")
    return value


def _download_archive(client: httpx.Client, install_root: Path) -> Path:
    handle = tempfile.NamedTemporaryFile(
        prefix="ffmpeg-", suffix=".zip", dir=install_root, delete=False
    )
    archive_path = Path(handle.name)
    downloaded = 0
    try:
        with handle, client.stream("GET", DOWNLOAD_URL) as response:
            response.raise_for_status()
            content_length = int(response.headers.get("content-length", "0") or 0)
            if content_length > MAX_DOWNLOAD_BYTES:
                raise RuntimeError("FFmpeg 下载文件超过允许的 250 MiB")
            for chunk in response.iter_bytes(CHUNK_SIZE):
                downloaded += len(chunk)
                if downloaded > MAX_DOWNLOAD_BYTES:
                    raise RuntimeError("FFmpeg 下载文件超过允许的 250 MiB")
                handle.write(chunk)
        if downloaded == 0:
            raise RuntimeError("FFmpeg 下载文件为空")
        return archive_path
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise


def _extract_executables(archive_path: Path, destination: Path) -> tuple[Path, Path]:
    bin_dir = destination / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    wanted = {"ffmpeg.exe": None, "ffprobe.exe": None}
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            normalized = info.filename.replace("\\", "/")
            name = Path(normalized).name.lower()
            if name in wanted and "/bin/" in f"/{normalized.lower()}":
                if info.file_size > MAX_DOWNLOAD_BYTES:
                    raise RuntimeError(f"压缩包中的 {name} 文件异常过大")
                wanted[name] = info
        missing = [name for name, info in wanted.items() if info is None]
        if missing:
            raise RuntimeError(f"FFmpeg 压缩包缺少文件：{', '.join(missing)}")
        for name, info in wanted.items():
            target = bin_dir / name
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, CHUNK_SIZE)
    return bin_dir / "ffmpeg.exe", bin_dir / "ffprobe.exe"


def _installed_paths(version_dir: Path) -> tuple[Path, Path] | None:
    ffmpeg_path = version_dir / "bin" / "ffmpeg.exe"
    ffprobe_path = version_dir / "bin" / "ffprobe.exe"
    return (ffmpeg_path, ffprobe_path) if ffmpeg_path.is_file() and ffprobe_path.is_file() else None


def _executables_work(ffmpeg_path: Path, ffprobe_path: Path) -> bool:
    return bool(_read_version(ffmpeg_path) and _read_version(ffprobe_path))


def _read_version(executable: Path | None) -> str | None:
    if not executable:
        return None
    try:
        result = subprocess.run(
            [str(executable), "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    first_line = result.stdout.splitlines()[0] if result.stdout else ""
    match = re.search(r"(?:ffmpeg|ffprobe) version\s+([^\s]+)", first_line, re.IGNORECASE)
    return match.group(1) if match else first_line or None


def _find_executable(configured: str) -> Path | None:
    candidate = Path(configured).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    found = shutil.which(configured)
    return Path(found).resolve() if found else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()
