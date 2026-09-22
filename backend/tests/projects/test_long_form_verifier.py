import json
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from runpy import run_path


class LongFormVerifierTests(unittest.TestCase):
    def test_rejects_delivery_files_changed_after_quality_check(self) -> None:
        verify = run_path(
            str(Path(__file__).resolve().parents[3] / "scripts" / "verify_long_form_delivery.py"),
            run_name="delivery_verifier",
        )["verify"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = [root / name for name in ("Story.prproj", "Story.wav", "Story.srt")]
            for path in files:
                path.write_bytes(b"delivery")
            qa = {
                "schema_version": 1,
                "passed": True,
                "delivery_verified": True,
                "premiere_conversion_verified": True,
                "verification_status": "manual_acceptance_required",
                "summary": {
                    "audio_duration_seconds": 25 * 60, "scene_count": 10,
                    "prproj_path": str(files[0]), "audio_path": str(files[1]),
                    "srt_path": str(files[2]),
                },
                "file_signatures": {
                    str(path): {
                        "size": path.stat().st_size,
                        "mtime_ns": path.stat().st_mtime_ns,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                    for path in files
                },
            }
            exported = {
                "schema_version": 1, "format": "prproj", "premiere_executable": "Premiere.exe",
                "export_id": "export-1", "created_at": "2026-09-22T00:00:00Z",
                "premiere_result": {"success": True}, "path": str(files[0]),
            }
            qa_path = root / "qa.json"
            export_path = root / "export.json"
            qa_path.write_text(json.dumps(qa), encoding="utf-8")
            export_path.write_text(json.dumps(exported), encoding="utf-8")
            self.assertEqual(verify(qa_path, export_path, 20, 30), [])

            original_mtime = files[1].stat().st_mtime_ns
            files[1].write_bytes(b"tampered")
            os.utime(files[1], ns=(original_mtime, original_mtime))
            self.assertTrue(any("QC 后发生变化" in failure
                                for failure in verify(qa_path, export_path, 20, 30)))


if __name__ == "__main__":
    unittest.main()
