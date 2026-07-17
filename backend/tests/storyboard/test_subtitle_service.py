import unittest

from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from app.models.storyboard import SubtitleCue, VisualScene
from app.services.narration.subtitle_service import parse_srt, replace_project_cues


class SubtitleImportTests(unittest.TestCase):
    def test_parse_srt_preserves_multiline_source_text(self) -> None:
        cues = parse_srt(
            """1
00:00:00,000 --> 00:00:02,500
第一行
第二行

2
00:00:02,500 --> 00:00:05,000
下一条字幕
"""
        )

        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0]["text"], "第一行\n第二行")
        self.assertEqual(cues[1]["start_ms"], 2500)

    def test_parse_srt_rejects_overlapping_cues(self) -> None:
        with self.assertRaisesRegex(ValueError, "重叠"):
            parse_srt(
                """1
00:00:00,000 --> 00:00:03,000
第一条

2
00:00:02,900 --> 00:00:04,000
第二条
"""
            )

    def test_unchanged_cues_keep_existing_scenes_but_changes_invalidate_them(self) -> None:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(engine)
        values = [
            {
                "id": "p:sub_0001",
                "source_segment_id": "imported_srt",
                "cue_index": 1,
                "start_ms": 0,
                "end_ms": 2000,
                "text": "字幕",
            }
        ]
        with Session(engine) as session:
            self.assertTrue(replace_project_cues(session, "p", values))
            session.add(
                VisualScene(
                    id="p:scene_0001",
                    project_id="p",
                    scene_index=1,
                    start_ms=0,
                    end_ms=2000,
                    narration="字幕",
                )
            )
            session.commit()
            self.assertFalse(replace_project_cues(session, "p", values))
            self.assertIsNotNone(session.get(VisualScene, "p:scene_0001"))

            changed = [dict(values[0], text="修改后的字幕")]
            self.assertTrue(replace_project_cues(session, "p", changed))
            self.assertIsNone(session.get(VisualScene, "p:scene_0001"))
            self.assertEqual(session.get(SubtitleCue, "p:sub_0001").text, "修改后的字幕")
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
