import json
from pathlib import Path

from app.config import get_settings
from app.models.project import Project
from app.services.subtitle_splitter import split_timed_subtitle_cues, wrap_subtitle_text
from app.utils.project_paths import ensure_project_dirs, get_output_stem, get_project_work_dir
from app.utils.time_utils import seconds_to_ass_time


DEFAULT_STYLE = {
    "font": "Microsoft YaHei",
    "font_size": 64,
    "primary_color": "&H00FFFFFF",
    "outline_color": "&H00000000",
    "outline": 3,
    "shadow": 1,
    "alignment": 2,
    "margin_v": 80,
}

EN_STYLE = {**DEFAULT_STYLE, "font": "Arial", "font_size": 48, "margin_v": 70}


def create_ass(project: Project, language: str) -> Path:
    base_dir = get_project_work_dir(project, get_settings().workspace_dir)
    timeline_path = base_dir / "timeline" / f"{get_output_stem(project)}_timeline.json"
    if not timeline_path.exists():
        legacy_path = base_dir / "timeline" / "timeline.json"
        timeline_path = legacy_path if legacy_path.exists() else timeline_path
    if not timeline_path.exists():
        raise ValueError("timeline.json does not exist")
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))

    style = EN_STYLE if language == "en" else DEFAULT_STYLE
    lines = [_ass_header(style)]
    for item in timeline["segments"]:
        text = item.get("text_en") if language == "en" else item.get("text_zh")
        if not text:
            continue
        for cue_start, cue_end, cue_text in split_timed_subtitle_cues(
            text,
            float(item["start"]),
            float(item["end"]),
            language,
        ):
            wrapped = wrap_subtitle_text(cue_text, language)
            start = seconds_to_ass_time(cue_start)
            end = seconds_to_ass_time(cue_end)
            lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{_escape_ass(wrapped)}")

    ensure_project_dirs(base_dir)
    subtitles_dir = base_dir / "subtitles"
    subtitles_dir.mkdir(parents=True, exist_ok=True)
    output_path = subtitles_dir / f"{get_output_stem(project)}_{language}.ass"
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def _ass_header(style: dict) -> str:
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style["font"]},{style["font_size"]},{style["primary_color"]},&H000000FF,{style["outline_color"]},&H64000000,0,0,0,0,100,100,0,0,1,{style["outline"]},{style["shadow"]},{style["alignment"]},80,80,{style["margin_v"]},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"""


def _escape_ass(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")
