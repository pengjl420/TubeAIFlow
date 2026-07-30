import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import StoryboardTransitionEffect
from app.services.rendering import local_video_merge_service
from app.services.rendering import rough_cut_service


class LocalVideoMergeServiceTests(unittest.TestCase):
    def test_groups_duplicate_names_case_insensitively(self) -> None:
        paths = [
            Path("first") / "Clip.MP4",
            Path("second") / "clip.mp4",
            Path("second") / "other.mov",
        ]

        groups = local_video_merge_service._group_by_filename(paths)

        self.assertEqual(len(groups), 2)
        self.assertEqual(len(groups["clip.mp4"]), 2)

    def test_output_filename_defaults_to_mp4_and_rejects_directories(self) -> None:
        self.assertEqual(
            local_video_merge_service._normalize_output_filename("result"),
            "result.mp4",
        )
        with self.assertRaisesRegex(ValueError, "不能包含目录"):
            local_video_merge_service._normalize_output_filename("../result.mp4")

    @patch(
        "app.services.rendering.rough_cut_service.random.choices",
        return_value=["fade"],
    )
    def test_full_transition_plan_covers_every_boundary(self, _choices_mock) -> None:
        selected = [
            rough_cut_service.SelectedVideo(Path(f"{index}.mp4"), str(index), 3.0, 2.9)
            for index in range(4)
        ]

        plan = rough_cut_service.build_full_transition_plan(
            selected,
            [StoryboardTransitionEffect(name="fade", percentage=100)],
        )

        self.assertEqual([item.after_clip_index for item in plan], [1, 2, 3])

    @patch("app.services.rendering.local_video_merge_service.ensure_ffmpeg_available")
    @patch("app.services.rendering.local_video_merge_service.probe_duration")
    @patch("app.services.rendering.local_video_merge_service.rough_cut_service.compose_normalized_clips")
    @patch("app.services.rendering.local_video_merge_service.rough_cut_service.normalize_selected_clips")
    @patch("app.services.rendering.local_video_merge_service.rough_cut_service.build_full_transition_plan")
    @patch("app.services.rendering.local_video_merge_service.rough_cut_service.select_videos_for_duration")
    @patch("app.services.rendering.local_video_merge_service.rough_cut_service.scan_video_files")
    def test_compose_reuses_rough_cut_pipeline_and_limits_duration(
        self,
        scan_mock,
        select_mock,
        transition_mock,
        normalize_mock,
        compose_mock,
        probe_mock,
        _ensure_mock,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            source.write_bytes(b"source")
            scan_mock.return_value = [source]
            select_mock.return_value = [
                rough_cut_service.SelectedVideo(source, "source.mp4", 12.0, 11.9)
            ]
            transition_mock.return_value = []
            normalize_mock.side_effect = lambda _selected, temp: [temp / "0001.mp4"]
            probe_mock.return_value = 10.0

            result = local_video_merge_service.compose_local_video(
                str(root),
                str(root),
                "merged.mp4",
                10.0,
            )

        self.assertEqual(result["requested_duration"], 10.0)
        self.assertEqual(compose_mock.call_args.kwargs["output_duration"], 10.0)


if __name__ == "__main__":
    unittest.main()
