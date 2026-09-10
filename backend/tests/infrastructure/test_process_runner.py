import threading
import unittest
from unittest.mock import Mock, patch

from app.infrastructure import process_runner


class ProcessRunnerDeferredTests(unittest.TestCase):
    def test_implicit_process_state_is_removed_after_unregister(self) -> None:
        process = Mock()
        process_runner.register_process("project-implicit", process)

        process_runner.unregister_process("project-implicit", process)

        self.assertFalse(process_runner.status("project-implicit")["running"])

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

    def test_windows_cancel_terminates_the_registered_process_tree(self) -> None:
        process = Mock(pid=4321)
        process.poll.return_value = None

        with self.assertRaises(process_runner.TaskCancelledError):
            with process_runner.controlled("project-cancel", "tts"):
                process_runner.register_process("project-cancel", process)
                with patch.object(process_runner.sys, "platform", "win32"), patch.object(
                    process_runner.subprocess, "run", return_value=Mock(returncode=0)
                ) as taskkill:
                    result = process_runner.cancel("project-cancel")

                self.assertTrue(result["cancelled"])
                taskkill.assert_called_once_with(
                    ["taskkill", "/PID", "4321", "/T", "/F"],
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                process.kill.assert_not_called()

    def test_unregister_process_preserves_stage_but_removes_stale_child(self) -> None:
        process = Mock()
        with self.assertRaises(process_runner.TaskCancelledError):
            with process_runner.controlled("project-unregister", "tts"):
                process_runner.register_process("project-unregister", process)
                process_runner.unregister_process("project-unregister", process)
                self.assertTrue(process_runner.status("project-unregister")["running"])
                process_runner.cancel("project-unregister")
                process.kill.assert_not_called()

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
