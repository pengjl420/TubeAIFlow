import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError
from sqlmodel import Session, SQLModel, create_engine

from app.models.project import Project
from app.models.storyboard import SubtitleCue
from app.services.storyboard import storyboard_service
from app.services.storyboard.scene_grouper import group_cues


class _FakeDeepSeek:
    def chat_json(self, _system_prompt: str, user_prompt: str) -> dict:
        payload = json.loads(user_prompt)
        if "subtitle_cues" in payload:
            ids = [cue["id"] for cue in payload["subtitle_cues"]]
            return {"groups": [{"subtitle_ids": ids[:2]}, {"subtitle_ids": ids[2:]}]}
        return {
            "scenes": [
                {
                    "scene_id": scene["scene_id"],
                    "visual_summary": "A historical business documentary scene",
                    "visual_type": "historical_reconstruction",
                    "entities": [],
                    "locations": [],
                    "time_period": "1990s",
                    "scene_category": "business",
                    "mood": "focused",
                    "shot_preference": "wide_or_medium",
                    "primary_query": "1990s business office documentary",
                    "alternative_queries": ["historical office workers"],
                    "fallback_category": "business",
                    "fallback_mood": "neutral",
                    "must_include": ["office"],
                    "avoid": ["modern smartphone"],
                    "confidence": 0.82,
                }
                for scene in payload["scenes"]
            ]
        }


class _InvalidGroupingDeepSeek:
    def chat_json(self, _system_prompt: str, _user_prompt: str) -> dict:
        return {"groups": [{"subtitle_ids": ["unknown"]}]}


class _SingleGroupingDeepSeek:
    def chat_json(self, _system_prompt: str, user_prompt: str) -> dict:
        payload = json.loads(user_prompt)
        return {"groups": [{"subtitle_ids": [cue["id"] for cue in payload["subtitle_cues"]]}]}


class _ScalarStoryboardListsDeepSeek(_FakeDeepSeek):
    def chat_json(self, system_prompt: str, user_prompt: str) -> dict:
        result = super().chat_json(system_prompt, user_prompt)
        if "scenes" in result:
            for scene in result["scenes"]:
                scene["entities"] = None
                scene["locations"] = ""
                scene["alternative_queries"] = "historical office workers"
                scene["must_include"] = "office"
                scene["avoid"] = "modern smartphone"
        return result


class _InvalidStoryboardListDeepSeek(_FakeDeepSeek):
    def __init__(self) -> None:
        self.storyboard_calls = 0

    def chat_json(self, system_prompt: str, user_prompt: str) -> dict:
        payload = json.loads(user_prompt)
        if "subtitle_cues" in payload:
            return super().chat_json(system_prompt, user_prompt)
        self.storyboard_calls += 1
        scenes = payload.get("scenes") or payload.get("required_scenes")
        result = {
            "scenes": [
                {
                    "scene_id": scene["scene_id"],
                    "visual_summary": "A historical business documentary scene",
                    "visual_type": "historical_reconstruction",
                    "entities": [],
                    "locations": [],
                    "time_period": "1990s",
                    "scene_category": "business",
                    "mood": "focused",
                    "shot_preference": "wide_or_medium",
                    "primary_query": "1990s business office documentary",
                    "alternative_queries": ["historical office workers"],
                    "fallback_category": "business",
                    "fallback_mood": "neutral",
                    "must_include": {"subject": "office"},
                    "avoid": [],
                    "confidence": 0.82,
                }
                for scene in scenes
            ]
        }
        return result


class StoryboardServiceTests(unittest.TestCase):
    def test_scalar_storyboard_list_fields_are_normalized_at_llm_boundary(self) -> None:
        with self.project_session() as (session, project, settings):
            with patch.object(storyboard_service, "get_settings", return_value=settings):
                result = storyboard_service.generate_storyboard(
                    session, project, client=_ScalarStoryboardListsDeepSeek()
                )

        storyboard = result["scenes"][0]["storyboard"]
        self.assertEqual(storyboard["entities"], [])
        self.assertEqual(storyboard["locations"], [])
        self.assertEqual(storyboard["alternative_queries"], ["historical office workers"])
        self.assertEqual(storyboard["must_include"], ["office"])
        self.assertEqual(storyboard["avoid"], ["modern smartphone"])

    def test_unsafe_storyboard_list_type_still_fails_after_one_repair(self) -> None:
        client = _InvalidStoryboardListDeepSeek()
        with self.project_session(cue_count=1) as (session, project, settings):
            with (
                patch.object(storyboard_service, "get_settings", return_value=settings),
                self.assertRaises(ValidationError),
            ):
                storyboard_service.generate_storyboard(session, project, client=client)

        self.assertEqual(client.storyboard_calls, 2)

    def test_invalid_ai_grouping_falls_back_to_complete_rule_based_coverage(self) -> None:
        cues = [
            {"id": f"s{index}", "start_ms": (index - 1) * 3000, "end_ms": index * 3000, "text": str(index)}
            for index in range(1, 5)
        ]

        groups, warnings = group_cues(cues, _InvalidGroupingDeepSeek())

        self.assertEqual([cue["id"] for group in groups for cue in group], ["s1", "s2", "s3", "s4"])
        self.assertTrue(warnings)

    def test_ai_grouping_is_split_at_fifteen_seconds(self) -> None:
        cues = [
            {"id": f"s{index}", "start_ms": (index - 1) * 3000, "end_ms": index * 3000, "text": str(index)}
            for index in range(1, 8)
        ]

        groups, warnings = group_cues(cues, _SingleGroupingDeepSeek())

        self.assertEqual([[cue["id"] for cue in group] for group in groups], [
            ["s1", "s2", "s3", "s4", "s5"],
            ["s6", "s7"],
        ])
        self.assertEqual(warnings, [])

    def test_generate_storyboard_persists_validated_scenes_and_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(
                f"sqlite:///{Path(directory) / 'storyboard.db'}",
                connect_args={"check_same_thread": False},
            )
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                project = Project(id="p1", name="Project")
                session.add(project)
                for index in range(1, 4):
                    session.add(
                        SubtitleCue(
                            id=f"p1:sub_{index:04d}",
                            project_id="p1",
                            source_segment_id="imported_srt",
                            cue_index=index,
                            start_ms=(index - 1) * 3000,
                            end_ms=index * 3000,
                            text=f"字幕 {index}",
                        )
                    )
                session.commit()

                settings = SimpleNamespace(
                    workspace_dir=Path(directory),
                    deepseek_model="deepseek-test",
                )
                with patch.object(storyboard_service, "get_settings", return_value=settings):
                    result = storyboard_service.generate_storyboard(
                        session, project, client=_FakeDeepSeek()
                    )

                self.assertEqual(len(result["scenes"]), 2)
                self.assertEqual(result["scenes"][0]["subtitle_ids"], ["p1:sub_0001", "p1:sub_0002"])
                self.assertEqual(result["scenes"][1]["end_ms"], 9000)
                self.assertEqual(result["scenes"][0]["storyboard"]["fallback_category"], "business")
                self.assertTrue(Path(result["path"]).is_file())
            engine.dispose()

    @contextmanager
    def project_session(self, cue_count: int = 3):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(
                f"sqlite:///{Path(directory) / 'storyboard.db'}",
                connect_args={"check_same_thread": False},
            )
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                project = Project(id="p1", name="Project")
                session.add(project)
                for index in range(1, cue_count + 1):
                    session.add(
                        SubtitleCue(
                            id=f"p1:sub_{index:04d}",
                            project_id="p1",
                            source_segment_id="imported_srt",
                            cue_index=index,
                            start_ms=(index - 1) * 3000,
                            end_ms=index * 3000,
                            text=f"字幕 {index}",
                        )
                    )
                session.commit()
                settings = SimpleNamespace(
                    workspace_dir=Path(directory),
                    deepseek_model="deepseek-test",
                )
                yield session, project, settings
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
