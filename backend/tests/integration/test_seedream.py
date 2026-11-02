import base64
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from PIL import Image

from app.config import Settings
from app.integrations.image_generation.seedream import (
    SEEDREAM_FLASH_MODEL_ID,
    SeedreamClient,
    SeedreamResultUnknownError,
)


def _png_base64() -> str:
    stream = BytesIO()
    Image.new("RGB", (16, 9), (20, 30, 40)).save(stream, format="PNG")
    return base64.b64encode(stream.getvalue()).decode("ascii")


class SeedreamClientTests(unittest.TestCase):
    def test_generates_png_with_ark_contract_without_leaking_key_to_disk(self) -> None:
        settings = Settings(
            seedream_api_key="secret-key",
        )
        response = httpx.Response(
            200,
            request=httpx.Request("POST", "https://ark.cn-beijing.volces.com/api/v3/images/generations"),
            json={"data": [{"b64_json": _png_base64()}]},
        )
        http_client = Mock()
        http_client.post.return_value = response

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "image.png"
            with patch(
                "app.integrations.image_generation.seedream.httpx.Client",
                return_value=http_client,
            ):
                SeedreamClient(settings).generate(prompt="storyboard", output_path=output)

            self.assertTrue(output.is_file())
            with Image.open(output) as image:
                self.assertEqual(image.size, (16, 9))

        _, kwargs = http_client.post.call_args
        self.assertEqual(
            http_client.post.call_args.args[0],
            "https://ark.cn-beijing.volces.com/api/v3/images/generations",
        )
        self.assertEqual(kwargs["json"]["model"], "doubao-seedream-5-0-pro-260628")
        self.assertEqual(kwargs["json"]["response_format"], "b64_json")
        self.assertEqual(kwargs["json"]["output_format"], "png")
        self.assertEqual(kwargs["json"]["size"], "2848x1600")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-key")

    def test_flash_uses_its_official_model_id_with_the_shared_contract(self) -> None:
        response = httpx.Response(
            200,
            request=httpx.Request(
                "POST", "https://ark.cn-beijing.volces.com/api/v3/images/generations"
            ),
            json={"data": [{"b64_json": _png_base64()}]},
        )
        http_client = Mock()
        http_client.post.return_value = response

        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "app.integrations.image_generation.seedream.httpx.Client",
                return_value=http_client,
            ):
                SeedreamClient(
                    Settings(seedream_api_key="secret-key"),
                    model_id=SEEDREAM_FLASH_MODEL_ID,
                ).generate(prompt="storyboard", output_path=Path(directory) / "image.png")

        payload = http_client.post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "doubao-seedream-5-0-flash-260915")
        self.assertEqual(payload["size"], "2848x1600")
        self.assertEqual(payload["response_format"], "b64_json")
        self.assertEqual(payload["output_format"], "png")
        self.assertFalse(payload["watermark"])

    def test_rejects_missing_api_key_before_network_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "Seedream API Key"):
                SeedreamClient(Settings(seedream_api_key="")).generate(
                    prompt="storyboard", output_path=Path(directory) / "image.png"
                )

    def test_reports_model_access_error_with_provider_detail(self) -> None:
        response = httpx.Response(
            404,
            request=httpx.Request("POST", "https://ark.cn-beijing.volces.com/api/v3/images/generations"),
            headers={"x-request-id": "request-123"},
            json={
                "error": {
                    "code": "ModelNotOpen",
                    "message": "The model is not activated for this account",
                }
            },
        )
        http_client = Mock()
        http_client.post.return_value = response

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch(
                    "app.integrations.image_generation.seedream.httpx.Client",
                    return_value=http_client,
                ),
                self.assertRaisesRegex(
                    RuntimeError,
                    "模型 doubao-seedream-5-0-pro-260628 不存在、未开通.*ModelNotOpen.*request-123",
                ) as raised,
            ):
                SeedreamClient(Settings(seedream_api_key="secret-key")).generate(
                    prompt="storyboard", output_path=Path(directory) / "image.png"
                )

        self.assertEqual(raised.exception.code, "SEEDREAM_MODEL_UNAVAILABLE")

    def test_reports_invalid_api_key_without_echoing_key(self) -> None:
        response = httpx.Response(
            401,
            request=httpx.Request("POST", "https://ark.cn-beijing.volces.com/api/v3/images/generations"),
            json={"error": {"code": "ApiKey.Invalid", "message": "Invalid API key"}},
        )
        http_client = Mock()
        http_client.post.return_value = response

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch(
                    "app.integrations.image_generation.seedream.httpx.Client",
                    return_value=http_client,
                ),
                self.assertRaisesRegex(RuntimeError, "API Key 无效") as raised,
            ):
                SeedreamClient(Settings(seedream_api_key="top-secret-key")).generate(
                    prompt="storyboard", output_path=Path(directory) / "image.png"
                )

        self.assertEqual(raised.exception.code, "SEEDREAM_AUTH_FAILED")
        self.assertNotIn("top-secret-key", str(raised.exception))

    def test_read_timeout_is_not_retried_to_avoid_duplicate_generation(self) -> None:
        request = httpx.Request(
            "POST", "https://ark.cn-beijing.volces.com/api/v3/images/generations"
        )
        http_client = Mock()
        http_client.post.side_effect = httpx.ReadTimeout("late response", request=request)

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch(
                    "app.integrations.image_generation.seedream.httpx.Client",
                    return_value=http_client,
                ),
                self.assertRaises(SeedreamResultUnknownError),
            ):
                SeedreamClient(Settings(seedream_api_key="secret-key")).generate(
                    prompt="storyboard", output_path=Path(directory) / "image.png"
                )

        self.assertEqual(http_client.post.call_count, 1)

    def test_rate_limit_retries_the_same_candidate_with_backoff(self) -> None:
        request = httpx.Request(
            "POST", "https://ark.cn-beijing.volces.com/api/v3/images/generations"
        )
        limited = httpx.Response(
            429,
            request=request,
            headers={"retry-after": "3"},
            json={"error": {"code": "RateLimit", "message": "try later"}},
        )
        success = httpx.Response(
            200,
            request=request,
            json={"data": [{"b64_json": _png_base64()}]},
        )
        http_client = Mock()
        http_client.post.side_effect = [limited, success]

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch(
                    "app.integrations.image_generation.seedream.httpx.Client",
                    return_value=http_client,
                ),
                patch("app.integrations.image_generation.seedream.time.sleep") as sleep,
            ):
                SeedreamClient(Settings(seedream_api_key="secret-key")).generate(
                    prompt="storyboard", output_path=Path(directory) / "image.png"
                )

        self.assertEqual(http_client.post.call_count, 2)
        sleep.assert_called_once_with(3.0)


if __name__ == "__main__":
    unittest.main()
