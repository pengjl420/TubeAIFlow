import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.infrastructure import gpu_resource


class GpuResourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        settings = type(
            "Settings",
            (),
            {"workspace_dir": Path(self.temp_dir.name)},
        )()
        self.settings_patch = patch.object(gpu_resource, "get_settings", return_value=settings)
        self.settings_patch.start()

    def tearDown(self) -> None:
        self.settings_patch.stop()
        self.temp_dir.cleanup()

    def test_concurrent_businesses_never_overlap(self) -> None:
        active = 0
        maximum = 0
        state_lock = threading.Lock()
        barrier = threading.Barrier(3)

        def run(owner: str) -> None:
            nonlocal active, maximum
            barrier.wait()
            with gpu_resource.exclusive_gpu(owner):
                with state_lock:
                    active += 1
                    maximum = max(maximum, active)
                time.sleep(0.05)
                with state_lock:
                    active -= 1

        threads = [
            threading.Thread(target=run, args=("tts",)),
            threading.Thread(target=run, args=("asset-vectorization",)),
        ]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=2)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(maximum, 1)

    def test_nested_business_reuses_lease_and_cleans_before_next_waiter(self) -> None:
        events = []
        first_entered = threading.Event()
        allow_first_to_finish = threading.Event()

        def first() -> None:
            with gpu_resource.exclusive_gpu("project-media-search"):
                with gpu_resource.exclusive_gpu("vision-embedding"):
                    gpu_resource.defer_cleanup(
                        "embedding-model", lambda: events.append("model-released")
                    )
                    events.append("embedding-finished")
                first_entered.set()
                allow_first_to_finish.wait(timeout=2)

        def second() -> None:
            first_entered.wait(timeout=2)
            with gpu_resource.exclusive_gpu("tts"):
                events.append("tts-started")

        first_thread = threading.Thread(target=first)
        second_thread = threading.Thread(target=second)
        first_thread.start()
        second_thread.start()
        first_entered.wait(timeout=2)
        time.sleep(0.05)
        self.assertNotIn("tts-started", events)
        allow_first_to_finish.set()
        first_thread.join(timeout=2)
        second_thread.join(timeout=2)

        self.assertEqual(
            events,
            ["embedding-finished", "model-released", "tts-started"],
        )

    def test_cleanup_is_deduplicated_for_a_batch(self) -> None:
        calls = []
        with gpu_resource.exclusive_gpu("asset-vectorization"):
            gpu_resource.defer_cleanup("embedding-model", lambda: calls.append("old"))
            gpu_resource.defer_cleanup("embedding-model", lambda: calls.append("latest"))
            self.assertEqual(calls, [])
        self.assertEqual(calls, ["latest"])


if __name__ == "__main__":
    unittest.main()
