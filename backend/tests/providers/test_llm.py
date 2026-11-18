import tempfile
import unittest
from pathlib import Path

from app.providers.llm import CachedLLMClient


class _Provider:
    def __init__(self, payload=None, error: Exception | None = None, name="test") -> None:
        self.payload = payload or {}
        self.error = error
        self.name = name
        self.model = f"{name}-model"
        self.calls = 0

    def chat_json(self, _system: str, _user: str, **_kwargs) -> dict:
        self.calls += 1
        if self.error:
            raise self.error
        return self.payload


class CloudLLMTests(unittest.TestCase):
    def test_cache_reuses_identical_structured_request(self) -> None:
        provider = _Provider({"value": 1})
        with tempfile.TemporaryDirectory() as directory:
            client = CachedLLMClient(provider, Path(directory))
            first = client.chat_json("system", "user", schema={"type": "object"})
            second = client.chat_json("system", "user", schema={"type": "object"})

        self.assertEqual(first, second)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(client.routes, ["cache:generic"])


if __name__ == "__main__":
    unittest.main()
