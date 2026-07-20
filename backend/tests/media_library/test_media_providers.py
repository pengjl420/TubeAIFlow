import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from sqlmodel import Session, SQLModel, create_engine

from app.integrations.media_providers.common import (
    ProviderRateLimitError,
    ProviderSearchResponse,
)
from app.integrations.media_providers.pexels import PexelsClient
from app.integrations.media_providers.pixabay import PixabayClient
from app.models.media import MediaProviderState
from app.models.project import Project
from app.models.storyboard import VisualScene
from app.schemas.media import RemoteMediaCandidate
from app.schemas.storyboard import StoryboardContent
from app.services.media_library import media_provider_service, retrieval_service


class MediaProviderClientTests(unittest.TestCase):
    def test_pexels_normalizes_video_and_quota_headers(self) -> None:
        reset = round((datetime.now(UTC) + timedelta(hours=1)).timestamp())

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.headers["Authorization"], "secret")
            return httpx.Response(
                200,
                headers={
                    "X-Ratelimit-Limit": "20000",
                    "X-Ratelimit-Remaining": "19999",
                    "X-Ratelimit-Reset": str(reset),
                },
                json={
                    "videos": [
                        {
                            "id": 42,
                            "url": "https://www.pexels.com/video/example-42/",
                            "duration": 8.5,
                            "user": {"name": "Creator"},
                            "video_pictures": [{"picture": "https://images.pexels.com/preview.jpg"}],
                            "video_files": [
                                {"width": 640, "height": 360, "link": "https://videos.pexels.com/sd.mp4"},
                                {"width": 1920, "height": 1080, "link": "https://videos.pexels.com/hd.mp4"},
                            ],
                        }
                    ]
                },
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            result = PexelsClient("secret", client).search_videos("airport traveler", 5)

        self.assertEqual(result.rate_limit, 20000)
        self.assertEqual(result.remaining, 19999)
        self.assertEqual(result.candidates[0].asset_id, "42")
        self.assertEqual(result.candidates[0].width, 1920)
        self.assertEqual(result.candidates[0].duration_ms, 8500)

    def test_pixabay_429_reports_cooldown_without_exposing_key(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, headers={"X-RateLimit-Reset": "60"})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(ProviderRateLimitError) as raised:
                PixabayClient("private-key", client).search_videos("city", 3)

        self.assertNotIn("private-key", str(raised.exception))
        self.assertGreater(datetime.fromisoformat(raised.exception.reset_at), datetime.now(UTC))


class MediaProviderServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{Path(self.temp_dir.name) / 'providers.db'}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(self.engine)
        self.settings = SimpleNamespace(
            pexels_api_key="pexels-key",
            pixabay_api_key="pixabay-key",
            media_search_cache_hours=24,
        )

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_search_uses_24_hour_cache_for_repeated_query(self) -> None:
        calls = []
        candidate = RemoteMediaCandidate(
            provider="pexels",
            asset_id="1",
            page_url="https://www.pexels.com/video/1/",
            download_url="https://videos.pexels.com/1.mp4",
            query="city",
        )

        class FakeClient:
            def search_videos(_self, query, _limit):
                calls.append(query)
                return ProviderSearchResponse([candidate], 20000, 19999, None)

        with Session(self.engine) as session:
            with (
                patch.object(media_provider_service, "get_settings", return_value=self.settings),
                patch.object(media_provider_service, "_client", return_value=FakeClient()),
            ):
                first = media_provider_service.search_provider(session, "pexels", ["City"], 5)
                second = media_provider_service.search_provider(session, "pexels", [" city "], 5)

        self.assertEqual(calls, ["city"])
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(second["candidates"][0]["asset_id"], "1")

    def test_rate_limit_persists_cooldown_and_skips_repeated_request(self) -> None:
        reset_at = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
        fake_client = Mock()
        fake_client.search_videos.side_effect = ProviderRateLimitError("quota reached", reset_at)

        with Session(self.engine) as session:
            with (
                patch.object(media_provider_service, "get_settings", return_value=self.settings),
                patch.object(media_provider_service, "_client", return_value=fake_client),
            ):
                first = media_provider_service.search_provider(session, "pexels", ["city"])
                second = media_provider_service.search_provider(session, "pexels", ["city"])
                state = session.get(MediaProviderState, "pexels")

        self.assertEqual(first["status"], "cooldown")
        self.assertEqual(second["status"], "cooldown")
        self.assertEqual(fake_client.search_videos.call_count, 1)
        self.assertEqual(state.reset_at, reset_at)

    def test_retrieval_falls_back_from_pexels_to_pixabay(self) -> None:
        storyboard = StoryboardContent(
            visual_summary="City skyline",
            visual_type="documentary",
            scene_category="city",
            mood="neutral",
            shot_preference="wide",
            primary_query="city skyline",
            fallback_category="city",
            fallback_mood="neutral",
            confidence=0.8,
        )
        project = Project(id="p1", name="Project")
        scene = VisualScene(
            id="p1:scene_0001",
            project_id=project.id,
            scene_index=1,
            start_ms=0,
            end_ms=5000,
            narration="City skyline",
            storyboard_json=storyboard.model_dump_json(),
        )
        attempts = [
            {"provider": "pexels", "status": "cooldown", "reset_at": "later", "downloaded": [], "errors": []},
            {"provider": "pixabay", "status": "available", "reset_at": None, "downloaded": [], "errors": []},
        ]
        with Session(self.engine) as session:
            session.add_all([project, scene])
            session.commit()
            with patch(
                "app.services.media_library.remote_retrieval_service.fetch_provider_candidates",
                side_effect=attempts,
            ) as fetch:
                result = retrieval_service.search_scene_candidates(session, project, scene.id)

        self.assertEqual([call.args[1] for call in fetch.call_args_list], ["pexels", "pixabay"])
        self.assertEqual(result["status"], "NO_RESULT")
        self.assertEqual(len(result["online_search"]), 2)


if __name__ == "__main__":
    unittest.main()
