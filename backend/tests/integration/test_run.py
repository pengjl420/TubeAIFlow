import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import run
from app.find_available_port import find_available_port


class BackendRunTests(unittest.TestCase):
    def test_instance_lock_blocks_a_second_backend(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "backend.lock"
            first = run.acquire_instance_lock(lock_path)
            self.assertIsNotNone(first)
            try:
                self.assertIsNone(run.acquire_instance_lock(lock_path))
            finally:
                if first is not None:
                    run.release_instance_lock(first)

            second = run.acquire_instance_lock(lock_path)
            self.assertIsNotNone(second)
            if second is not None:
                run.release_instance_lock(second)

    def test_launcher_disables_uvicorn_reload(self) -> None:
        lock_file = MagicMock()
        with (
            patch.object(run, "acquire_instance_lock", return_value=lock_file),
            patch.object(run, "release_instance_lock") as release,
            patch.object(
                run,
                "get_settings",
                return_value=SimpleNamespace(app_host="127.0.0.1", app_port=18080),
            ),
            patch.object(run.uvicorn, "run") as uvicorn_run,
        ):
            run.main()

        uvicorn_run.assert_called_once_with(
            "app.main:app",
            host="127.0.0.1",
            port=18080,
            reload=False,
        )
        release.assert_called_once_with(lock_file)

    def test_find_available_port_skips_an_occupied_port(self) -> None:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            occupied_port = listener.getsockname()[1]
            selected = find_available_port(occupied_port, attempts=20)

        self.assertGreater(selected, occupied_port)


if __name__ == "__main__":
    unittest.main()
