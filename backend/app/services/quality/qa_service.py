import json
from pathlib import Path

from sqlmodel import Session, select

from app.config import get_settings
from app.infrastructure.ffmpeg import probe_duration, probe_media
from app.infrastructure.project_layout import (
    get_final_audio_path,
    get_final_srt_path,
    get_final_video_path,
    get_project_work_dir,
)
from app.models.media import MediaFile, MediaShot, SceneAssignment
from app.models.project import Project
from app.models.storyboard import SubtitleCue, VisualScene
from app.services.rendering.scene_renderer import scene_output_path


MAX_DURATION_ERROR_SECONDS = 0.1


def run_quality_check(session: Session, project: Project) -> dict:
    issues: list[dict] = []
    scenes = list(
        session.exec(
            select(VisualScene)
            .where(VisualScene.project_id == project.id)
            .order_by(VisualScene.scene_index)
        ).all()
    )
    cues = list(
        session.exec(
            select(SubtitleCue)
            .where(SubtitleCue.project_id == project.id)
            .order_by(SubtitleCue.start_ms, SubtitleCue.cue_index)
        ).all()
    )
    assignments = {
        item.scene_id: item
        for item in session.exec(
            select(SceneAssignment).where(SceneAssignment.project_id == project.id)
        ).all()
    }
    _check_timeline(scenes, issues)
    audio_path = get_final_audio_path(project, get_settings().workspace_dir)
    video_path = get_final_video_path(project, get_settings().workspace_dir)
    audio_duration = _duration_or_issue(audio_path, "audio_missing", "完整配音文件不存在", issues)
    video_duration = _duration_or_issue(video_path, "video_missing", "最终视频不存在", issues)
    if audio_duration is not None and video_duration is not None:
        difference = abs(audio_duration - video_duration)
        if difference > MAX_DURATION_ERROR_SECONDS:
            _issue(
                issues,
                "duration_mismatch",
                "error",
                f"视频与配音时长相差 {difference:.3f} 秒",
                suggestion="重新执行最终合成并检查场景首尾时间轴",
            )
    if audio_duration is not None:
        for cue in cues:
            if cue.end_ms / 1000 > audio_duration + 0.001:
                _issue(
                    issues,
                    "subtitle_overflow",
                    "error",
                    "字幕结束时间超过配音时长",
                    subtitle_id=cue.id,
                    suggestion="重新生成字幕时间轴",
                )
    if not get_final_srt_path(project, get_settings().workspace_dir).is_file():
        _issue(issues, "subtitle_missing", "error", "项目 SRT 字幕文件不存在")

    for scene in scenes:
        assignment = assignments.get(scene.id)
        if not assignment or not assignment.manual_confirmed:
            _issue(
                issues,
                "assignment_missing",
                "error",
                "场景尚未完成人工素材确认",
                scene_id=scene.id,
            )
            continue
        shot = session.get(MediaShot, assignment.media_shot_id)
        media_file = session.get(MediaFile, shot.media_file_id) if shot else None
        if not shot or not media_file:
            _issue(issues, "source_missing", "error", "场景素材记录不完整", scene_id=scene.id)
        elif not media_file.provider or not media_file.id or not media_file.path:
            _issue(issues, "source_metadata_missing", "error", "素材来源信息不完整", scene_id=scene.id)
        rendered_path = scene_output_path(project, scene)
        if not rendered_path.is_file():
            _issue(issues, "scene_render_missing", "error", "场景中间视频不存在", scene_id=scene.id)
            continue
        try:
            rendered_duration = probe_duration(rendered_path)
        except RuntimeError as exc:
            _issue(issues, "scene_render_invalid", "error", str(exc), scene_id=scene.id)
            continue
        expected = (scene.end_ms - scene.start_ms) / 1000
        if abs(rendered_duration - expected) > 0.12:
            _issue(
                issues,
                "scene_duration_mismatch",
                "error",
                f"场景视频时长与时间轴相差 {abs(rendered_duration - expected):.3f} 秒",
                scene_id=scene.id,
            )

    video_metadata = None
    if video_path.is_file():
        try:
            video_metadata = probe_media(video_path)
            if video_metadata.get("width") != 1920 or video_metadata.get("height") != 1080:
                _issue(issues, "resolution_mismatch", "error", "最终视频不是 1920×1080")
            if video_metadata.get("codec_name") != "h264":
                _issue(issues, "codec_mismatch", "warning", "最终视频编码不是 H.264")
        except RuntimeError as exc:
            _issue(issues, "video_probe_failed", "error", str(exc))

    report = {
        "passed": not any(item["severity"] == "error" for item in issues),
        "summary": {
            "scene_count": len(scenes),
            "assignment_count": len(assignments),
            "subtitle_count": len(cues),
            "error_count": sum(item["severity"] == "error" for item in issues),
            "warning_count": sum(item["severity"] == "warning" for item in issues),
            "audio_duration_seconds": audio_duration,
            "video_duration_seconds": video_duration,
            "video_metadata": video_metadata,
        },
        "issues": issues,
    }
    path = _report_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def read_report(project: Project) -> dict | None:
    path = _report_path(project)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _check_timeline(scenes: list[VisualScene], issues: list[dict]) -> None:
    if not scenes:
        _issue(issues, "timeline_empty", "error", "项目没有视觉场景")
        return
    previous_end = scenes[0].start_ms
    if previous_end != 0:
        _issue(issues, "timeline_start_gap", "error", "视觉时间轴没有从 0 开始")
    for scene in scenes:
        if scene.end_ms <= scene.start_ms:
            _issue(issues, "negative_scene_duration", "error", "场景时长无效", scene_id=scene.id)
        if scene.start_ms != previous_end:
            _issue(issues, "timeline_gap", "error", "视觉场景之间存在空洞或重叠", scene_id=scene.id)
        previous_end = scene.end_ms


def _duration_or_issue(path: Path, issue_type: str, message: str, issues: list[dict]) -> float | None:
    if not path.is_file():
        _issue(issues, issue_type, "error", message)
        return None
    try:
        return probe_duration(path)
    except RuntimeError as exc:
        _issue(issues, issue_type, "error", str(exc))
        return None


def _issue(
    issues: list[dict],
    issue_type: str,
    severity: str,
    message: str,
    *,
    scene_id: str | None = None,
    subtitle_id: str | None = None,
    suggestion: str | None = None,
) -> None:
    issues.append(
        {
            "type": issue_type,
            "severity": severity,
            "scene_id": scene_id,
            "subtitle_id": subtitle_id,
            "message": message,
            "suggestion": suggestion,
        }
    )


def _report_path(project: Project) -> Path:
    return get_project_work_dir(project, get_settings().workspace_dir) / "reports" / "qa.json"
