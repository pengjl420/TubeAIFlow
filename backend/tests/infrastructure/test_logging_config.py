import logging
import tempfile
import unittest
from pathlib import Path

from app.infrastructure.logging_config import (
    SensitiveDataFilter,
    configure_logging,
    redact_sensitive,
)


class LoggingConfigTests(unittest.TestCase):
    def test_redacts_common_secret_formats(self) -> None:
        text = redact_sensitive(
            "Authorization: Bearer abc.def api_key=secret-value "
            "password=hunter2 sk-exampletoken"
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
        finally:
            for handler in root.handlers:
                if handler not in original_handlers:
                    handler.close()
            root.handlers = original_handlers
            root.setLevel(original_level)
            temporary.cleanup()

    def test_filter_handles_mapping_arguments(self) -> None:
        record = logging.LogRecord(
            "test", logging.INFO, __file__, 1, "%(value)s",
            ({"value": "Bearer token"},), None,
        )
        self.assertTrue(SensitiveDataFilter().filter(record))
        self.assertEqual(record.getMessage(), "Bearer [REDACTED]")


if __name__ == "__main__":
    unittest.main()
