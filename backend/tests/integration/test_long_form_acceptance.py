from pathlib import Path

import pytest

from app.models.storyboard import VisualScene
from app.services.narration.segmenter import split_script
from app.services.rendering.timeline_composer import scene_frame_window
from app.services.rendering.visual_track_composer import _transition_inputs_fit
from app.services.storyboard.scene_grouper import _chunk_cues


@pytest.mark.parametrize("minutes", [20, 30, 60])
def test_long_form_planning_stays_bounded_and_frame_exact(minutes: int) -> None:
    sentence = "这是用于验证长视频稳定性的完整测试句子，包含自然停顿。"
    target_characters = minutes * 260
    script = (sentence * (target_characters // len(sentence) + 1))[:target_characters]

    segments = split_script(script)
    assert all(1 <= len(item["text"]) <= 180 for item in segments)
    assert "".join(item["text"] for item in segments) == script

    cue_count = minutes * 12
    cues = [
        {
            "id": f"cue-{index}",
            "start_ms": index * 5_000,
            "end_ms": (index + 1) * 5_000,
            "text": sentence,
        }
        for index in range(cue_count)
    ]
    batches = _chunk_cues(cues)
    assert sum(map(len, batches)) == cue_count
    assert all(len(batch) <= 80 for batch in batches)

    scenes = [
        VisualScene(
            id=f"scene-{index}",
            project_id="long-form",
            scene_index=index + 1,
            start_ms=index * 5_000,
            end_ms=(index + 1) * 5_000,
            narration=sentence,
        )
        for index in range(cue_count)
    ]
    windows = [scene_frame_window(scene, 30) for scene in scenes]
    assert sum(item[2] for item in windows) == minutes * 60 * 30
    assert all(left[1] == right[0] for left, right in zip(windows, windows[1:]))


def test_long_form_transition_command_guard_prefers_stable_concat() -> None:
    short = [Path(f"C:/project/scenes/scene_{index:04d}.mp4") for index in range(20)]
    long = [
        Path("C:/project-with-a-long-name/scene-renders")
        / (f"scene_{index:04d}_" + "x" * 100 + ".mp4")
        for index in range(720)
    ]

    assert _transition_inputs_fit(short)
    assert not _transition_inputs_fit(long)
