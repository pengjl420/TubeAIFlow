import threading
import unittest

from app.infrastructure import process_runner


class ProcessRunnerDeferredTests(unittest.TestCase):
    def test_deferred_call_runs_before_stage_lock_is_released(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def active_stage() -> None:
            with process_runner.controlled("project-deferred", "tts"):
                entered.set()
                release.wait(timeout=2)
            finished.set()

        thread = threading.Thread(target=active_stage)
        thread.start()
        self.assertTrue(entered.wait(timeout=2))

        deferred = process_runner.defer_if_running(
            "project-deferred",
            "tts",
            lambda: process_runner.status("project-deferred")["stage"],
        )
        self.assertIsNotNone(deferred)
        release.set()

        self.assertEqual(deferred.wait(), "tts")
        self.assertTrue(finished.wait(timeout=2))
        self.assertFalse(process_runner.status("project-deferred")["running"])
        thread.join(timeout=2)

    def test_deferred_call_receives_active_stage_failure(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def failing_stage() -> None:
            try:
                with process_runner.controlled("project-failure", "tts"):
                    entered.set()
                    release.wait(timeout=2)
                    raise RuntimeError("batch failed")
            except RuntimeError:
                pass

        thread = threading.Thread(target=failing_stage)
        thread.start()
        self.assertTrue(entered.wait(timeout=2))
        deferred = process_runner.defer_if_running(
            "project-failure", "tts", lambda: "should not run"
        )
        self.assertIsNotNone(deferred)
        release.set()

        with self.assertRaisesRegex(RuntimeError, "batch failed"):
            deferred.wait()
        thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
