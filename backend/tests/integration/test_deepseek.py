import threading
import unittest
from unittest.mock import Mock, patch

import httpx

from app.config import Settings
from app.infrastructure import process_runner
from app.integrations.llm.deepseek import DeepSeekClient, ProviderOutputTruncatedError


class DeepSeekCancellationTests(unittest.TestCase):
    def test_output_truncation_is_typed_and_not_retried(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [{"finish_reason": "length", "message": {"content": "{}"}}]
        }
        http_client = Mock()
        http_client.post.return_value = response
        client = DeepSeekClient(Settings(deepseek_api_key="test-key", deepseek_retry_count=3))

        with patch("app.integrations.llm.deepseek.httpx.Client", return_value=http_client):
            with self.assertRaises(ProviderOutputTruncatedError) as raised:
                client.chat_json("system", "user")

        self.assertEqual(raised.exception.code, "PROVIDER_OUTPUT_TRUNCATED")
        self.assertEqual(http_client.post.call_count, 1)

    def test_non_transient_http_error_is_not_retried(self) -> None:
        request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
        response = httpx.Response(401, request=request)
        http_client = Mock()
        http_client.post.return_value = response
        client = DeepSeekClient(Settings(deepseek_api_key="test-key", deepseek_retry_count=3))

        with patch("app.integrations.llm.deepseek.httpx.Client", return_value=http_client):
            with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
                client.chat_json("system", "user")

        self.assertEqual(http_client.post.call_count, 1)

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
