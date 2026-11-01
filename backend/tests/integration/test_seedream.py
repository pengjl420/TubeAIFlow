import base64
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from PIL import Image

from app.config import Settings
from app.integrations.image_generation.seedream import SeedreamClient


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
        self.assertEqual(kwargs["json"]["model"], "doubao-seedream-5-0-260128")
        self.assertEqual(kwargs["json"]["response_format"], "b64_json")
        self.assertEqual(kwargs["json"]["output_format"], "png")
        self.assertEqual(kwargs["json"]["size"], "2848x1600")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-key")

    def test_rejects_missing_api_key_before_network_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "Seedream API Key"):
                SeedreamClient(Settings(seedream_api_key="")).generate(
                    prompt="storyboard", output_path=Path(directory) / "image.png"
                )


if __name__ == "__main__":
    unittest.main()
