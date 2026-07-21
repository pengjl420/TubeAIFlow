import json
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET

from sqlmodel import Session, select

from app.config import get_settings
from app.infrastructure.ffmpeg import probe_duration
from app.infrastructure.project_layout import (
    ensure_project_dirs,
    get_final_audio_path,
    get_final_fcpxml_path,
    get_final_srt_path,
    get_project_work_dir,
)
from app.models.media import MediaFile, MediaShot, SceneAssignment
from app.models.project import Project
from app.models.storyboard import SubtitleCue, VisualScene
from app.services.projects import project_service
from app.services.rendering import rough_cut_service, timeline_composer


FCPXML_VERSION = "1.10"
FPS = 30


def export_project_fcpxml(session: Session, project: Project) -> dict:
    video_mode = project_service.get_project_video_mode(project)
    if video_mode == project_service.VIDEO_MODE_NONE:
        return _export_audio_only_fcpxml(session, project)
    if video_mode == project_service.VIDEO_MODE_LANDSCAPE:
        return _export_landscape_fcpxml(session, project)
    return _export_scene_fcpxml(session, project)


def _export_scene_fcpxml(session: Session, project: Project) -> dict:
    scenes = list(
        session.exec(
            select(VisualScene)
            .where(VisualScene.project_id == project.id)
            .order_by(VisualScene.scene_index)
        ).all()
    )
    if not scenes:
        raise ValueError("Project has no visual scenes to export")

    placements: list[tuple[VisualScene, SceneAssignment, MediaShot, MediaFile]] = []
    media_files: dict[str, MediaFile] = {}
    for scene in scenes:
        coverage = timeline_composer.scene_coverage(session, scene)
        if not coverage["complete"]:
            raise ValueError(f"Scene {scene.scene_index} does not cover its full duration")
        for assignment in coverage["assignments"]:
            shot = session.get(MediaShot, assignment.media_shot_id)
            media = session.get(MediaFile, shot.media_file_id) if shot else None
            if not shot or not media:
                raise ValueError(f"Scene {scene.scene_index} references missing media")
            source_path = Path(media.path).expanduser().resolve()
            if not source_path.is_file():
                raise ValueError(f"Media file does not exist: {source_path}")
            media_files[media.id] = media
            placements.append((scene, assignment, shot, media))

    audio_path = get_final_audio_path(project, get_settings().workspace_dir)
    if not audio_path.is_file():
        raise ValueError("Merged narration audio does not exist")

    cues = list(
        session.exec(
            select(SubtitleCue)
            .where(SubtitleCue.project_id == project.id)
            .order_by(SubtitleCue.start_ms, SubtitleCue.cue_index)
        ).all()
    )
    total_ms = max(scene.end_ms for scene in scenes)
    root = _build_xml(project, total_ms, media_files, placements, audio_path, cues)
    output_path = _write_fcpxml(project, root)

    work_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(work_dir)
    report = {
        "path": str(output_path),
        "format": "fcpxml",
        "fcpxml_version": FCPXML_VERSION,
        "fps": FPS,
        "duration_ms": total_ms,
        "scene_count": len(scenes),
        "clip_count": len(placements),
        "subtitle_count": len(cues),
        "audio_path": str(audio_path),
        "subtitle_path": str(get_final_srt_path(project, get_settings().workspace_dir)),
        "media_paths": [str(Path(item.path).resolve()) for item in media_files.values()],
        "compatibility_notes": [
            "Media is linked by absolute file URI; relink in the editor after moving files.",
            "Motion presets and application-specific effects are intentionally left editable.",
            "The SRT file remains the subtitle fallback if title import is incomplete.",
        ],
    }
    report_path = work_dir / "reports" / "fcpxml_export_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _export_landscape_fcpxml(session: Session, project: Project) -> dict:
    selected, transitions, target_duration = rough_cut_service.prepare_rough_cut_selection(project)
    audio_path = get_final_audio_path(project, get_settings().workspace_dir)
    cues = list(
        session.exec(
            select(SubtitleCue)
            .where(SubtitleCue.project_id == project.id)
            .order_by(SubtitleCue.start_ms, SubtitleCue.cue_index)
        ).all()
    )
    total_ms = max(1, round(target_duration * 1000))
    root = _build_landscape_xml(project, total_ms, selected, audio_path, cues)
    output_path = _write_fcpxml(project, root)

    work_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(work_dir)
    report = {
        "path": str(output_path),
        "format": "fcpxml",
        "fcpxml_version": FCPXML_VERSION,
        "fps": FPS,
        "duration_ms": total_ms,
        "scene_count": 0,
        "clip_count": len(selected),
        "subtitle_count": len(cues),
        "audio_path": str(audio_path),
        "subtitle_path": str(get_final_srt_path(project, get_settings().workspace_dir)),
        "media_paths": [str(item.source_path.resolve()) for item in selected],
        "compatibility_notes": [
            "Landscape rough-cut transitions are exported as editable hard cuts.",
            "Media is linked by absolute file URI; relink in the editor after moving files.",
            "The SRT file remains the subtitle fallback if title import is incomplete.",
        ],
        "planned_transition_count": len(transitions),
    }
    report_path = work_dir / "reports" / "fcpxml_export_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _export_audio_only_fcpxml(session: Session, project: Project) -> dict:
    audio_path = get_final_audio_path(project, get_settings().workspace_dir)
    if not audio_path.is_file():
        raise ValueError("Merged narration audio does not exist")
    cues = list(
        session.exec(
            select(SubtitleCue)
            .where(SubtitleCue.project_id == project.id)
            .order_by(SubtitleCue.start_ms, SubtitleCue.cue_index)
        ).all()
    )
    audio_duration_ms = max(1, round(probe_duration(audio_path) * 1000))
    total_ms = max(audio_duration_ms, max((cue.end_ms for cue in cues), default=0))
    root = _build_audio_only_xml(project, total_ms, audio_path, cues)
    output_path = _write_fcpxml(project, root)

    work_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(work_dir)
    report = {
        "path": str(output_path),
        "format": "fcpxml",
        "fcpxml_version": FCPXML_VERSION,
        "fps": FPS,
        "duration_ms": total_ms,
        "scene_count": 0,
        "clip_count": 0,
        "subtitle_count": len(cues),
        "audio_path": str(audio_path),
        "subtitle_path": str(get_final_srt_path(project, get_settings().workspace_dir)),
        "media_paths": [],
        "compatibility_notes": [
            "This audio-only timeline contains narration and subtitle titles without video clips.",
            "The SRT file remains the subtitle fallback if title import is incomplete.",
        ],
    }
    report_path = work_dir / "reports" / "fcpxml_export_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _write_fcpxml(project: Project, root: ET.Element) -> Path:
    xml_body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    xml_text = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE fcpxml>\n'
        f"{xml_body}\n"
    )
    ET.fromstring(xml_body)
    output_path = get_final_fcpxml_path(project, get_settings().workspace_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(".fcpxml.tmp")
    temp_path.write_text(xml_text, encoding="utf-8")
    temp_path.replace(output_path)
    return output_path


def _build_landscape_xml(
    project: Project,
    total_ms: int,
    selected: list[rough_cut_service.SelectedVideo],
    audio_path: Path,
    cues: list[SubtitleCue],
) -> ET.Element:
    root = ET.Element("fcpxml", {"version": FCPXML_VERSION})
    resources = ET.SubElement(root, "resources")
    ET.SubElement(
        resources,
        "format",
        {
            "id": "r1", "name": "FFVideoFormat1080p30", "frameDuration": "1/30s",
            "width": "1920", "height": "1080", "colorSpace": "1-1-1 (Rec. 709)",
        },
    )
    clip_resource_ids: list[str] = []
    for index, item in enumerate(selected, start=2):
        resource_id = f"r{index}"
        clip_resource_ids.append(resource_id)
        asset = ET.SubElement(
            resources,
            "asset",
            {
                "id": resource_id,
                "name": item.source_path.name,
                "start": "0s",
                "duration": _time(max(1, round(item.source_duration * 1000))),
                "hasVideo": "1",
                "format": "r1",
            },
        )
        ET.SubElement(
            asset,
            "media-rep",
            {"kind": "original-media", "src": item.source_path.resolve().as_uri()},
        )

    audio_resource_id = f"r{len(selected) + 2}"
    audio_asset = ET.SubElement(
        resources,
        "asset",
        {
            "id": audio_resource_id, "name": audio_path.name, "start": "0s",
            "duration": _time(total_ms), "hasAudio": "1", "audioSources": "1",
            "audioChannels": "2", "audioRate": "48000",
        },
    )
    ET.SubElement(
        audio_asset,
        "media-rep",
        {"kind": "original-media", "src": audio_path.resolve().as_uri()},
    )
    title_resource_id = f"r{len(selected) + 3}"
    ET.SubElement(
        resources,
        "effect",
        {
            "id": title_resource_id,
            "name": "Basic Title",
            "uid": ".../Titles.localized/Bumper:Opener.localized/Basic Title.localized/Basic Title.moti",
        },
    )

    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", {"name": project.name})
    project_node = ET.SubElement(event, "project", {"name": project.name})
    sequence = ET.SubElement(
        project_node,
        "sequence",
        {"format": "r1", "duration": _time(total_ms), "tcStart": "0s", "tcFormat": "NDF"},
    )
    spine = ET.SubElement(sequence, "spine")
    cursor_ms = 0
    primary_nodes: list[ET.Element] = []
    for item, resource_id in zip(selected, clip_resource_ids):
        remaining_ms = total_ms - cursor_ms
        if remaining_ms <= 0:
            break
        duration_ms = min(max(1, round(item.clip_duration * 1000)), remaining_ms)
        primary_nodes.append(
            ET.SubElement(
                spine,
                "asset-clip",
                {
                    "name": item.source_path.name,
                    "ref": resource_id,
                    "offset": _time(cursor_ms),
                    "start": _time(round(rough_cut_service.CLIP_START_OFFSET * 1000)),
                    "duration": _time(duration_ms),
                    "format": "r1",
                },
            )
        )
        cursor_ms += duration_ms
    if not primary_nodes or cursor_ms < total_ms:
        raise ValueError("Selected landscape clips do not cover the narration duration")
    _add_audio_and_titles(primary_nodes[0], audio_resource_id, title_resource_id, audio_path, total_ms, cues)
    return root


def _build_audio_only_xml(
    project: Project,
    total_ms: int,
    audio_path: Path,
    cues: list[SubtitleCue],
) -> ET.Element:
    root = ET.Element("fcpxml", {"version": FCPXML_VERSION})
    resources = ET.SubElement(root, "resources")
    ET.SubElement(
        resources,
        "format",
        {
            "id": "r1", "name": "FFVideoFormat1080p30", "frameDuration": "1/30s",
            "width": "1920", "height": "1080", "colorSpace": "1-1-1 (Rec. 709)",
        },
    )
    audio_asset = ET.SubElement(
        resources,
        "asset",
        {
            "id": "r2", "name": audio_path.name, "start": "0s",
            "duration": _time(total_ms), "hasAudio": "1", "audioSources": "1",
            "audioChannels": "2", "audioRate": "48000",
        },
    )
    ET.SubElement(
        audio_asset,
        "media-rep",
        {"kind": "original-media", "src": audio_path.resolve().as_uri()},
    )
    ET.SubElement(
        resources,
        "effect",
        {
            "id": "r3", "name": "Basic Title",
            "uid": ".../Titles.localized/Bumper:Opener.localized/Basic Title.localized/Basic Title.moti",
        },
    )
    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", {"name": project.name})
    project_node = ET.SubElement(event, "project", {"name": project.name})
    sequence = ET.SubElement(
        project_node,
        "sequence",
        {"format": "r1", "duration": _time(total_ms), "tcStart": "0s", "tcFormat": "NDF"},
    )
    spine = ET.SubElement(sequence, "spine")
    gap = ET.SubElement(
        spine,
        "gap",
        {"name": "Narration timeline", "offset": "0s", "start": "0s", "duration": _time(total_ms)},
    )
    _add_audio_and_titles(gap, "r2", "r3", audio_path, total_ms, cues)
    return root


def _add_audio_and_titles(
    anchor: ET.Element,
    audio_resource_id: str,
    title_resource_id: str,
    audio_path: Path,
    total_ms: int,
    cues: list[SubtitleCue],
) -> None:
    ET.SubElement(
        anchor,
        "asset-clip",
        {
            "name": audio_path.name, "ref": audio_resource_id, "lane": "-1",
            "offset": "0s", "start": "0s", "duration": _time(total_ms), "role": "dialogue",
        },
    )
    for index, cue in enumerate(cues, start=1):
        title = ET.SubElement(
            anchor,
            "title",
            {
                "name": f"Subtitle {index}", "ref": title_resource_id, "lane": "2",
                "offset": _time(cue.start_ms), "start": "0s",
                "duration": _time(cue.end_ms - cue.start_ms),
            },
        )
        text = ET.SubElement(title, "text")
        style_id = f"ts{index}"
        ET.SubElement(text, "text-style", {"ref": style_id}).text = cue.text
        style_def = ET.SubElement(title, "text-style-def", {"id": style_id})
        ET.SubElement(
            style_def,
            "text-style",
            {"font": "Arial", "fontSize": "48", "fontColor": "1 1 1 1", "alignment": "center"},
        )


def _build_xml(
    project: Project,
    total_ms: int,
    media_files: dict[str, MediaFile],
    placements: list[tuple[VisualScene, SceneAssignment, MediaShot, MediaFile]],
    audio_path: Path,
    cues: list[SubtitleCue],
) -> ET.Element:
    root = ET.Element("fcpxml", {"version": FCPXML_VERSION})
    resources = ET.SubElement(root, "resources")
    ET.SubElement(
        resources,
        "format",
        {
            "id": "r1",
            "name": "FFVideoFormat1080p30",
            "frameDuration": "1/30s",
            "width": "1920",
            "height": "1080",
            "colorSpace": "1-1-1 (Rec. 709)",
        },
    )

    media_resource_ids: dict[str, str] = {}
    for index, media in enumerate(media_files.values(), start=2):
        resource_id = f"r{index}"
        media_resource_ids[media.id] = resource_id
        attributes = {
            "id": resource_id,
            "name": media.filename,
            "start": "0s",
            "duration": _time(max(1, media.duration_ms or total_ms)),
            "hasVideo": "1",
            "format": "r1",
        }
        asset = ET.SubElement(resources, "asset", attributes)
        ET.SubElement(
            asset,
            "media-rep",
            {"kind": "original-media", "src": Path(media.path).resolve().as_uri()},
        )

    audio_resource_id = f"r{len(media_files) + 2}"
    audio_asset = ET.SubElement(
        resources,
        "asset",
        {
            "id": audio_resource_id,
            "name": audio_path.name,
            "start": "0s",
            "duration": _time(total_ms),
            "hasAudio": "1",
            "audioSources": "1",
            "audioChannels": "2",
            "audioRate": "48000",
        },
    )
    ET.SubElement(
        audio_asset,
        "media-rep",
        {"kind": "original-media", "src": audio_path.resolve().as_uri()},
    )
    title_resource_id = f"r{len(media_files) + 3}"
    ET.SubElement(
        resources,
        "effect",
        {
            "id": title_resource_id,
            "name": "Basic Title",
            "uid": ".../Titles.localized/Bumper:Opener.localized/Basic Title.localized/Basic Title.moti",
        },
    )

    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", {"name": project.name})
    project_node = ET.SubElement(event, "project", {"name": project.name})
    sequence = ET.SubElement(
        project_node,
        "sequence",
        {"format": "r1", "duration": _time(total_ms), "tcStart": "0s", "tcFormat": "NDF"},
    )
    spine = ET.SubElement(sequence, "spine")

    primary_nodes: list[ET.Element] = []
    for scene, assignment, shot, media in placements:
        start_ms = scene.start_ms + assignment.scene_offset_start_ms
        end_offset = assignment.scene_offset_end_ms
        if end_offset is None:
            raise ValueError(f"Assignment {assignment.id} has no timeline end")
        duration_ms = end_offset - assignment.scene_offset_start_ms
        source_start_ms = 0 if media.media_type == "image" else shot.start_ms + assignment.trim_start_ms
        clip = ET.SubElement(
            spine,
            "asset-clip",
            {
                "name": media.filename,
                "ref": media_resource_ids[media.id],
                "offset": _time(start_ms),
                "start": _time(source_start_ms),
                "duration": _time(duration_ms),
                "format": "r1",
            },
        )
        if assignment.playback_speed != 1.0 and media.media_type != "image":
            time_map = ET.SubElement(clip, "timeMap")
            ET.SubElement(time_map, "timept", {"time": "0s", "value": _time(source_start_ms)})
            ET.SubElement(
                time_map,
                "timept",
                {
                    "time": _time(duration_ms),
                    "value": _time(source_start_ms + round(duration_ms * assignment.playback_speed)),
                },
            )
        primary_nodes.append(clip)

    if not primary_nodes:
        raise ValueError("Project has no assigned clips")
    anchor = primary_nodes[0]
    _add_audio_and_titles(anchor, audio_resource_id, title_resource_id, audio_path, total_ms, cues)
    return root


def _time(milliseconds: int) -> str:
    if milliseconds == 0:
        return "0s"
    value = Fraction(int(milliseconds), 1000)
    return f"{value.numerator}/{value.denominator}s"
