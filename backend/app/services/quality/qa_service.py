import json
from pathlib import Path

from sqlmodel import Session, select

from app.config import get_settings
from app.infrastructure.ffmpeg import (
    analyze_audio_quality,
    detect_video_anomalies,
    probe_duration,
    probe_media,
)
from app.infrastructure.atomic_files import write_json_atomic
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
from app.services.rendering.render_config import get_project_render_config
from app.services.rendering.scene_quality_checker import expected_codec_name
from app.services.rendering import timeline_composer
from app.services.narration.subtitle_service import display_units, spoken_weight


MAX_DURATION_ERROR_SECONDS = 0.1


def run_quality_check(session: Session, project: Project) -> dict:
    issues: list[dict] = []
    render_config = get_project_render_config(project)
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
    all_assignments = list(
        session.exec(
            select(SceneAssignment).where(SceneAssignment.project_id == project.id)
        ).all()
    )
    assignments: dict[str, list[SceneAssignment]] = {}
    for item in all_assignments:
        assignments.setdefault(item.scene_id, []).append(item)
    _check_timeline(scenes, issues)
    audio_path = get_final_audio_path(project, get_settings().workspace_dir)
    video_path = get_final_video_path(project, get_settings().workspace_dir)
    visual_track_path = (
        get_project_work_dir(project, get_settings().workspace_dir)
        / "renders"
        / "visual_track.mp4"
    )
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
        _check_audio_analysis(audio_path, project.id, issues)
    _check_subtitles(cues, issues, get_settings())
    if not get_final_srt_path(project, get_settings().workspace_dir).is_file():
        _issue(issues, "subtitle_missing", "error", "项目 SRT 字幕文件不存在")
    if not visual_track_path.is_file():
        _issue(issues, "visual_track_missing", "error", "纯视频轨道不存在")
    else:
        try:
            visual_metadata = probe_media(visual_track_path)
            if visual_metadata.get("audio_stream_count") != 0:
                _issue(issues, "visual_track_has_audio", "error", "纯视频轨道包含意外音频流")
            visual_sar = visual_metadata.get("sample_aspect_ratio")
            if visual_sar and visual_sar not in {"1:1", "1/1"}:
                _issue(
                    issues,
                    "visual_track_sar_mismatch",
                    "error",
                    f"纯视频轨道像素宽高比不是 1:1（实际为 {visual_sar}）",
                )
        except RuntimeError as exc:
            _issue(issues, "visual_track_invalid", "error", str(exc))

    for scene in scenes:
        scene_assignments = assignments.get(scene.id, [])
        coverage = timeline_composer.scene_coverage(session, scene)
        if not coverage["complete"]:
            _issue(
                issues,
                "assignment_missing",
                "error",
                f"场景镜头轨道尚缺 {coverage['remaining_ms'] / 1000:.2f} 秒",
                scene_id=scene.id,
            )
            continue
        for assignment in scene_assignments:
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

    _check_repetition(session, scenes, all_assignments, issues)

    video_metadata = None
    if video_path.is_file():
        try:
            video_metadata = probe_media(video_path)
            expected_video = render_config.video
            if (
                video_metadata.get("width") != expected_video.width
                or video_metadata.get("height") != expected_video.height
            ):
                _issue(
                    issues,
                    "resolution_mismatch",
                    "error",
                    f"最终视频不是 {expected_video.width}×{expected_video.height}",
                )
            video_sar = video_metadata.get("sample_aspect_ratio")
            if video_sar and video_sar not in {"1:1", "1/1"}:
                _issue(
                    issues,
                    "video_sar_mismatch",
                    "error",
                    f"最终视频像素宽高比不是 1:1（实际为 {video_sar}）",
                )
            expected_codec = expected_codec_name(expected_video.video_codec)
            if video_metadata.get("codec_name") != expected_codec:
                _issue(
                    issues,
                    "codec_mismatch",
                    "warning",
                    f"最终视频编码不是 {expected_codec}",
                )
        except RuntimeError as exc:
            _issue(issues, "video_probe_failed", "error", str(exc))
        _check_video_analysis(video_path, project.id, issues)

    report = {
        "passed": not any(item["severity"] == "error" for item in issues),
        "summary": {
            "scene_count": len(scenes),
            "assignment_count": sum(
                timeline_composer.scene_coverage(session, scene)["complete"] for scene in scenes
            ),
            "shot_assignment_count": len(all_assignments),
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
    write_json_atomic(path, report)
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


def _check_subtitles(cues: list[SubtitleCue], issues: list[dict], settings) -> None:
    max_units = getattr(settings, "subtitle_max_display_units", 22)
    min_duration_ms = getattr(settings, "subtitle_min_cue_duration_ms", 1000)
    max_duration_ms = getattr(settings, "subtitle_max_cue_duration_ms", 6000)
    target_cps = getattr(settings, "subtitle_target_characters_per_second", 7.0)
    previous_end: int | None = None
    for cue in cues:
        duration_ms = cue.end_ms - cue.start_ms
        if duration_ms <= 0:
            _issue(
                issues,
                "subtitle_duration_invalid",
                "error",
                "字幕结束时间必须晚于开始时间",
                subtitle_id=cue.id,
                suggestion="重新生成字幕时间轴",
            )
            continue
        if previous_end is not None and cue.start_ms < previous_end:
            _issue(
                issues,
                "subtitle_overlap",
                "error",
                "字幕时间段存在重叠",
                subtitle_id=cue.id,
                suggestion="调整当前字幕的开始时间",
            )
        if display_units(cue.text) > max_units + 0.001:
            _issue(
                issues,
                "subtitle_too_wide",
                "warning",
                f"字幕显示宽度超过 {max_units} 个单位",
                subtitle_id=cue.id,
                suggestion="按自然标点进一步拆分字幕",
            )
        if duration_ms < min_duration_ms:
            _issue(
                issues,
                "subtitle_too_short",
                "warning",
                f"字幕显示时间短于 {min_duration_ms / 1000:.1f} 秒",
                subtitle_id=cue.id,
                suggestion="与相邻字幕合并或调整时间边界",
            )
        if duration_ms > max_duration_ms:
            _issue(
                issues,
                "subtitle_too_long",
                "warning",
                f"字幕显示时间长于 {max_duration_ms / 1000:.1f} 秒",
                subtitle_id=cue.id,
                suggestion="在不改变原文的前提下进一步拆分字幕",
            )
        characters_per_second = spoken_weight(cue.text) / (duration_ms / 1000)
        if characters_per_second > target_cps:
            _issue(
                issues,
                "subtitle_too_fast",
                "warning",
                f"字幕阅读速度为 {characters_per_second:.1f} 字/秒，超过目标 {target_cps:.1f}",
                subtitle_id=cue.id,
                suggestion="缩短字幕文字或延长显示时间",
            )
        previous_end = cue.end_ms


def _check_audio_analysis(audio_path: Path, project_id: str, issues: list[dict]) -> None:
    try:
        analysis = analyze_audio_quality(audio_path, project_id)
    except RuntimeError as exc:
        _issue(issues, "audio_analysis_failed", "warning", str(exc))
        return
    mean_volume = analysis.get("mean_volume_db")
    max_volume = analysis.get("max_volume_db")
    if mean_volume is not None and mean_volume < -30:
        _issue(issues, "audio_too_quiet", "warning", f"平均音量过低（{mean_volume:.1f} dB）")
    if max_volume is not None and max_volume >= -0.1:
        _issue(issues, "audio_clipping_risk", "warning", f"峰值接近 0 dB（{max_volume:.1f} dB）")
    for interval in analysis.get("silence_intervals", []):
        if float(interval.get("duration", 0)) >= 5:
            _issue(
                issues,
                "audio_long_silence",
                "warning",
                f"检测到 {float(interval['duration']):.1f} 秒长静音",
            )


def _check_video_analysis(video_path: Path, project_id: str, issues: list[dict]) -> None:
    try:
        analysis = detect_video_anomalies(video_path, project_id)
    except RuntimeError as exc:
        _issue(issues, "video_analysis_failed", "warning", str(exc))
        return
    for interval in analysis.get("black_intervals", []):
        _issue(
            issues,
            "sustained_black_frame",
            "warning",
            f"检测到 {float(interval['duration']):.1f} 秒持续黑帧",
        )
    for interval in analysis.get("freeze_intervals", []):
        _issue(
            issues,
            "sustained_freeze_frame",
            "warning",
            f"检测到 {float(interval['duration']):.1f} 秒冻结画面",
        )


def _check_repetition(
    session: Session,
    scenes: list[VisualScene],
    assignments: list[SceneAssignment],
    issues: list[dict],
) -> None:
    scene_index = {scene.id: scene.scene_index for scene in scenes}
    media_by_scene: list[tuple[int, str]] = []
    for assignment in assignments:
        shot = session.get(MediaShot, assignment.media_shot_id)
        if shot and assignment.scene_id in scene_index:
            media_by_scene.append((scene_index[assignment.scene_id], shot.media_file_id))
    media_by_scene.sort()
    counts: dict[str, int] = {}
    for _index, media_id in media_by_scene:
        counts[media_id] = counts.get(media_id, 0) + 1
    for media_id, count in counts.items():
        if count >= 3:
            _issue(
                issues,
                "repeated_asset",
                "warning",
                f"同一素材在 {count} 个镜头中重复使用",
                suggestion=f"替换素材 {media_id} 的部分使用位置",
            )

    consecutive = 1
    for previous, current in zip(media_by_scene, media_by_scene[1:], strict=False):
        consecutive = consecutive + 1 if previous[1] == current[1] else 1
        if consecutive == 3:
            _issue(
                issues,
                "consecutive_repeated_asset",
                "warning",
                "同一素材连续用于至少 3 个 Scene",
            )


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
