import threading
import unittest
from unittest.mock import Mock, patch

from app.config import Settings
from app.infrastructure import process_runner
from app.integrations.llm.deepseek import DeepSeekClient


class DeepSeekCancellationTests(unittest.TestCase):
    def test_cancel_closes_active_http_request_and_stops_retries(self) -> None:
        request_started = threading.Event()
        request_closed = threading.Event()

        http_client = Mock()

        def close() -> None:
            request_closed.set()

        def post(*_args, **_kwargs):
            request_started.set()
            request_closed.wait(timeout=2)
            raise OSError("request closed")

        http_client.close.side_effect = close
        http_client.post.side_effect = post
        client = DeepSeekClient(
            Settings(
                deepseek_api_key="test-key",
                deepseek_retry_count=3,
                deepseek_timeout_seconds=60,
            ),
            project_id="project-deepseek-cancel",
        )
        errors: list[BaseException] = []

        def run_request() -> None:
            try:
                with process_runner.controlled("project-deepseek-cancel", "storyboard"):
                    client.chat_json("system", "user")
            except BaseException as exc:
                errors.append(exc)

        with patch("app.integrations.llm.deepseek.httpx.Client", return_value=http_client):
            thread = threading.Thread(target=run_request)
            thread.start()
            self.assertTrue(request_started.wait(timeout=2))
            result = process_runner.cancel("project-deepseek-cancel")
            thread.join(timeout=2)

        self.assertTrue(result["cancelled"])
        self.assertTrue(request_closed.is_set())
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], process_runner.TaskCancelledError)
        self.assertEqual(http_client.post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
