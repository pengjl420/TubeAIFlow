import logging
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from app.infrastructure.logging_config import (
    SensitiveDataFilter,
    configure_logging,
    redact_sensitive,
    current_task_id,
    task_log_context,
)


class LoggingConfigTests(unittest.TestCase):
    def test_redacts_common_secret_formats(self) -> None:
        text = redact_sensitive(
            "Authorization: Bearer abc.def api_key=secret-value password=hunter2 sk-exampletoken"
        )
        self.assertNotIn("abc.def", text)
        self.assertNotIn("secret-value", text)
        self.assertNotIn("hunter2", text)
        self.assertNotIn("sk-exampletoken", text)
        self.assertGreaterEqual(text.count("[REDACTED]"), 4)

    def test_rotating_handler_writes_engine_log(self) -> None:
        root = logging.getLogger()
        original_handlers = list(root.handlers)
        original_level = root.level
        temporary = tempfile.TemporaryDirectory()
        try:
            root.handlers = []
            path = configure_logging(Path(temporary.name))
            logging.getLogger("test").error("api_key=do-not-store")
            for handler in root.handlers:
                handler.flush()
            content = path.read_text(encoding="utf-8")
            self.assertIn("api_key=[REDACTED]", content)
            self.assertNotIn("do-not-store", content)

            # Two overlapping tasks must never exchange IDs; child loggers,
            # multiline messages and every traceback line retain the same ID.
            barrier = Barrier(2)

            def emit(task_id: str) -> None:
                with task_log_context(task_id):
                    barrier.wait(timeout=5)
                    logging.getLogger("provider.nested").info(
                        "%s first\n%s second", task_id, task_id
                    )
                    try:
                        raise RuntimeError(f"{task_id} password=private-secret")
                    except RuntimeError:
                        logging.getLogger("ffmpeg.nested").exception("%s failed", task_id)

            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(emit, ["alpha", "beta"]))
            logging.getLogger("test").info("outside-task")
            for handler in root.handlers:
                handler.flush()
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("private-secret", content)
            for line in content.splitlines()[1:-1]:
                self.assertRegex(line, r"^\[task_id=(alpha|beta)\] ")
                if "beta first" in line or "beta second" in line:
                    self.assertTrue(line.startswith("[task_id=beta]"))
                if "alpha first" in line or "alpha second" in line:
                    self.assertTrue(line.startswith("[task_id=alpha]"))
            self.assertNotIn("task_id=", content.splitlines()[-1])
        finally:
            for handler in root.handlers:
                if handler not in original_handlers:
                    handler.close()
            root.handlers = original_handlers
            root.setLevel(original_level)
            temporary.cleanup()

    def test_context_restores_outer_task_even_after_failure(self) -> None:
        self.assertIsNone(current_task_id())
        with task_log_context("outer"):
            with self.assertRaises(ValueError):
                with task_log_context("inner"):
                    self.assertEqual(current_task_id(), "inner")
                    raise ValueError("failed")
            self.assertEqual(current_task_id(), "outer")
        self.assertIsNone(current_task_id())

    def test_filter_handles_mapping_arguments(self) -> None:
        record = logging.LogRecord(
            "test",
            logging.INFO,
            __file__,
            1,
            "%(value)s",
            ({"value": "Bearer token"},),
            None,
        )
        self.assertTrue(SensitiveDataFilter().filter(record))
        self.assertEqual(record.getMessage(), "Bearer [REDACTED]")


if __name__ == "__main__":
    unittest.main()
