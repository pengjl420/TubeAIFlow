import tempfile
import unittest
from pathlib import Path

from app.config import Settings
from app.providers.llm import CachedLLMClient, HybridLLMClient


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


class HybridLLMTests(unittest.TestCase):
    def test_keeps_confident_low_risk_storyboard_local(self) -> None:
        local = _Provider({"scenes": [{"confidence": 0.9, "identity_risk": 2}]}, name="local")
        cloud = _Provider({"scenes": [{"confidence": 0.95}]}, name="cloud")
        client = HybridLLMClient(local, cloud, Settings())

        result = client.chat_json("system", "user", task="storyboard")

        self.assertEqual(result, local.payload)
        self.assertEqual(cloud.calls, 0)
        self.assertEqual(client.routes, ["local"])

    def test_escalates_low_confidence_storyboard_to_cloud(self) -> None:
        local = _Provider({"scenes": [{"confidence": 0.4, "identity_risk": 2}]}, name="local")
        cloud = _Provider({"scenes": [{"confidence": 0.92}]}, name="cloud")
        client = HybridLLMClient(local, cloud, Settings())

        result = client.chat_json("system", "user", task="storyboard")

        self.assertEqual(result, cloud.payload)
        self.assertEqual(client.routes, ["cloud:quality-escalation"])

    def test_falls_back_to_cloud_when_local_service_fails(self) -> None:
        local = _Provider(error=OSError("offline"), name="local")
        cloud = _Provider({"scenes": [{"confidence": 0.92}]}, name="cloud")
        client = HybridLLMClient(local, cloud, Settings())

        result = client.chat_json("system", "user", task="storyboard")

        self.assertEqual(result, cloud.payload)
        self.assertEqual(client.routes, ["cloud:local-fallback"])

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
