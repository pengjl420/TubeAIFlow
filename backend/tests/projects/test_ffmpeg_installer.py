import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.infrastructure import ffmpeg
from app.services.settings import ffmpeg_installer_service as installer


class FfmpegInstallerTests(unittest.TestCase):
    def test_runtime_discovers_installed_version_when_configured_path_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            discovered = (
                workspace
                / "tools"
                / "ffmpeg"
                / "windows-x64"
                / "9.0"
                / "bin"
                / "ffmpeg.exe"
            )
            discovered.parent.mkdir(parents=True)
            discovered.write_bytes(b"binary")
            settings = SimpleNamespace(workspace_dir=workspace)

            with (
                patch.object(ffmpeg, "get_settings", return_value=settings),
                patch.object(ffmpeg.shutil, "which", return_value=None),
            ):
                resolved = ffmpeg._resolve_tool(
                    str(workspace / "tools" / "ffmpeg" / "windows-x64" / "8.1" / "bin" / "ffmpeg.exe")
                )

            self.assertEqual(Path(resolved), discovered.resolve())

    def test_extracts_only_required_executables(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "ffmpeg.zip"
            destination = root / "install"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("ffmpeg-test/bin/ffmpeg.exe", b"ffmpeg")
                archive.writestr("ffmpeg-test/bin/ffprobe.exe", b"ffprobe")
                archive.writestr("ffmpeg-test/doc/readme.txt", b"ignored")

            ffmpeg_path, ffprobe_path = installer._extract_executables(
                archive_path, destination
            )

            self.assertEqual(ffmpeg_path.read_bytes(), b"ffmpeg")
            self.assertEqual(ffprobe_path.read_bytes(), b"ffprobe")
            self.assertFalse((destination / "doc" / "readme.txt").exists())

    def test_extract_rejects_archive_missing_ffprobe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "ffmpeg.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("ffmpeg-test/bin/ffmpeg.exe", b"ffmpeg")

            with self.assertRaisesRegex(RuntimeError, "ffprobe.exe"):
                installer._extract_executables(archive_path, root / "install")

    def test_sha256_reads_downloaded_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "archive.zip"
            path.write_bytes(b"known content")
            self.assertEqual(
                installer._sha256(path),
                hashlib.sha256(b"known content").hexdigest(),
            )

    @patch.object(installer.sys, "platform", "linux")
    def test_automatic_install_is_windows_only(self) -> None:
        with self.assertRaisesRegex(ValueError, "Windows"):
            installer.install_ffmpeg(MagicMock())


if __name__ == "__main__":
    unittest.main()
