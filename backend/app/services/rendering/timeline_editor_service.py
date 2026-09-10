from __future__ import annotations

from sqlmodel import Session, select

from app.config import get_settings
from app.infrastructure.atomic_files import write_json_atomic
from app.infrastructure.project_layout import get_project_work_dir, load_project_config
from app.models.media import MediaFile, MediaShot, SceneAssignment
from app.models.narration import Segment
from app.models.project import Project
from app.models.storyboard import SubtitleCue, VisualScene
from app.services.rendering import timeline_composer
from app.services.storyboard.scene_workspace_service import invalidate_scene_outputs
from app.shared.time import utc_now_iso


def timeline(session: Session, project: Project) -> dict:
    scenes = list(
        session.exec(
            select(VisualScene)
            .where(VisualScene.project_id == project.id)
            .order_by(VisualScene.scene_index)
        ).all()
    )
    visual_clips = []
    for scene in scenes:
        for assignment in timeline_composer.scene_assignments(session, scene.id):
            shot = session.get(MediaShot, assignment.media_shot_id)
            media = session.get(MediaFile, shot.media_file_id) if shot else None
            if not shot or not media:
                continue
            visual_clips.append(
                {
                    "id": assignment.id,
                    "scene_id": scene.id,
                    "scene_index": scene.scene_index,
                    "asset_id": media.id,
                    "asset_path": media.path,
                    "media_type": media.media_type,
                    "start_ms": scene.start_ms + assignment.scene_offset_start_ms,
                    "end_ms": scene.start_ms + (assignment.scene_offset_end_ms or 0),
                    "source_start_ms": shot.start_ms + assignment.trim_start_ms,
                    "source_end_ms": (shot.start_ms + assignment.trim_end_ms)
                    if assignment.trim_end_ms is not None
                    else shot.end_ms,
                    "sequence_index": assignment.sequence_index,
                    "display_duration_ms": assignment.display_duration_ms,
                    "playback_speed": assignment.playback_speed,
                    "motion_type": assignment.motion_type,
                    "zoom_start": assignment.zoom_start,
                    "zoom_end": assignment.zoom_end,
                    "pan_direction": assignment.pan_direction,
                    "crop_anchor": assignment.crop_anchor,
                    "transition": assignment.transition,
                }
            )
    narration_clips = []
    cursor_ms = 0
    for segment in session.exec(
        select(Segment).where(Segment.project_id == project.id).order_by(Segment.segment_index)
    ).all():
        duration_ms = round(float(segment.duration or 0) * 1000)
        start_ms = (
            round(float(segment.start_time) * 1000) if segment.start_time is not None else cursor_ms
        )
        end_ms = (
            round(float(segment.end_time) * 1000)
            if segment.end_time is not None
            else start_ms + duration_ms
        )
        narration_clips.append(
            {
                "id": segment.id,
                "text": segment.text,
                "asset_path": segment.audio_path,
                "start_ms": start_ms,
                "end_ms": end_ms,
            }
        )
        cursor_ms = end_ms
    subtitle_clips = [
        cue.model_dump()
        for cue in session.exec(
            select(SubtitleCue)
            .where(SubtitleCue.project_id == project.id)
            .order_by(SubtitleCue.start_ms)
        ).all()
    ]
    duration_ms = max(
        max((scene.end_ms for scene in scenes), default=0),
        max((clip["end_ms"] for clip in narration_clips), default=0),
        max((clip["end_ms"] for clip in subtitle_clips), default=0),
    )
    config = load_project_config(project)
    return {
        "format_version": 1,
        "project_id": project.id,
        "duration_ms": duration_ms,
        "fps": int(config.get("fps", 30)),
        "tracks": [
            {"id": "visual", "type": "video", "clips": visual_clips},
            {"id": "narration", "type": "audio", "clips": narration_clips},
            {"id": "subtitles", "type": "subtitle", "clips": subtitle_clips},
        ],
    }


def update_visual_clip(
    session: Session, project: Project, assignment_id: str, values: dict
) -> dict:
    assignment = session.get(SceneAssignment, assignment_id)
    if not assignment or assignment.project_id != project.id:
        raise LookupError("Timeline clip not found")
    scene = session.get(VisualScene, assignment.scene_id)
    if not scene:
        raise LookupError("Scene not found")
    if scene.locked_visual:
        raise ValueError("Scene visual is locked")
    allowed = {
        "sequence_index",
        "display_duration_ms",
        "trim_start_ms",
        "trim_end_ms",
        "playback_speed",
        "motion_type",
        "zoom_start",
        "zoom_end",
        "pan_direction",
        "crop_anchor",
        "transition",
    }
    desired_sequence = values.get("sequence_index") or assignment.sequence_index
    for key, value in values.items():
        if key in allowed and value is not None:
            setattr(assignment, key, value)
    if assignment.sequence_index < 1:
        raise ValueError("Clip sequence must be at least 1")
    if assignment.playback_speed < 0.25 or assignment.playback_speed > 4:
        raise ValueError("Playback speed must be between 0.25 and 4")
    if assignment.display_duration_ms is not None and assignment.display_duration_ms <= 0:
        raise ValueError("Display duration must be greater than zero")
    if not 1 <= assignment.zoom_start <= 2 or not 1 <= assignment.zoom_end <= 2:
        raise ValueError("Zoom must be between 1 and 2")
    if assignment.trim_start_ms < 0 or (
        assignment.trim_end_ms is not None and assignment.trim_end_ms <= assignment.trim_start_ms
    ):
        raise ValueError("Invalid source trim range")
    assignment.updated_at = utc_now_iso()
    session.add(assignment)
    assignments = [
        item
        for item in timeline_composer.scene_assignments(session, scene.id)
        if item.id != assignment.id
    ]
    insertion_index = min(int(desired_sequence) - 1, len(assignments))
    assignments.insert(insertion_index, assignment)
    timeline_composer.reflow_scene_assignments(session, scene, assignments)
    session.commit()
    invalidate_scene_outputs(project, scene)
    return save_timeline(session, project)


def save_timeline(session: Session, project: Project) -> dict:
    data = timeline(session, project)
    path = (
        get_project_work_dir(project, get_settings().workspace_dir) / "timeline" / "timeline.json"
    )
    write_json_atomic(path, data)
    return data
