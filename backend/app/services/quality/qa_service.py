import json
import hashlib
import uuid
from pathlib import Path

from sqlmodel import Session, select

from app.config import get_settings
from app.infrastructure.ffmpeg import (
    analyze_audio_quality,
    probe_duration,
)
from app.infrastructure.atomic_files import write_json_atomic
from app.infrastructure.project_layout import (
    get_final_audio_path,
    get_final_prproj_path,
    get_final_srt_path,
    get_project_work_dir,
)
from app.models.media import MediaFile, MediaShot, SceneAssignment
from app.models.project import Project
from app.models.storyboard import SubtitleCue, VisualScene
from app.services.narration.subtitle_service import display_units, parse_srt, spoken_weight
from app.services.quality.models import DeliveryQualityReport, migrate_quality_report
from app.services.quality.registry import QualityCheckContext, quality_checker_registry
from app.services.quality.evidence import file_signature, signature_matches
from app.shared.time import utc_now_iso


MAX_DURATION_ERROR_SECONDS = 1.0


def run_quality_check(session: Session, project: Project) -> dict:
    issues: list[dict] = []
    settings = get_settings()
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
        session.exec(select(SceneAssignment).where(SceneAssignment.project_id == project.id)).all()
    )
    assignments: dict[str, list[SceneAssignment]] = {}
    for item in all_assignments:
        assignments.setdefault(item.scene_id, []).append(item)
    _check_timeline(scenes, issues)
    audio_path = get_final_audio_path(project, settings.workspace_dir)
    srt_path = get_final_srt_path(project, settings.workspace_dir)
    prproj_path = get_final_prproj_path(project, settings.workspace_dir)
    conversion_path = (
        get_project_work_dir(project, settings.workspace_dir)
        / "reports"
        / "prproj_export_report.json"
    )
    audio_duration = _duration_or_issue(audio_path, "audio_missing", "完整配音文件不存在", issues)
    if scenes and audio_duration is not None:
        difference = abs(scenes[-1].end_ms / 1000 - audio_duration)
        if difference > MAX_DURATION_ERROR_SECONDS:
            _issue(issues, "scene_audio_duration_mismatch", "error",
                   f"Scene 时间轴与配音时长相差 {difference:.3f} 秒",
                   suggestion="检查配音合并和 Scene 时间边界")
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
    _check_subtitles(cues, issues, settings)
    if not cues:
        _issue(issues, "subtitle_cues_missing", "error", "项目没有可交付的字幕时间线",
               suggestion="重新生成字幕对齐与 SRT")
    for path, issue_type, label in (
        (srt_path, "subtitle_missing", "项目 SRT 字幕"),
        (prproj_path, "prproj_missing", "真实 PRPROJ 工程"),
    ):
        if not path.is_file() or path.stat().st_size == 0:
            _issue(issues, issue_type, "error", f"{label}文件不存在或为空",
                   file_path=str(path))
    _check_delivered_srt(srt_path, cues, issues)
    premiere_conversion_verified = False
    conversion_evidence_paths: list[Path] = []
    if prproj_path.is_file():
        premiere_conversion_verified = _check_conversion_record(
            conversion_path, prproj_path, issues
        )
        conversion_evidence_paths = _conversion_evidence_paths(conversion_path)

    covered_scene_count = 0
    for scene in scenes:
        scene_assignments = assignments.get(scene.id, [])
        if _check_scene_assignments(scene, scene_assignments, issues):
            covered_scene_count += 1
        for assignment in scene_assignments:
            shot = session.get(MediaShot, assignment.media_shot_id)
            media_file = session.get(MediaFile, shot.media_file_id) if shot else None
            if not shot or not media_file:
                _issue(issues, "source_missing", "error", "场景素材记录不完整", scene_id=scene.id)
            elif not media_file.provider or not media_file.id or not media_file.path:
                _issue(
                    issues,
                    "source_metadata_missing",
                    "error",
                    "素材来源信息不完整",
                    scene_id=scene.id,
                )
            elif not Path(media_file.path).is_file():
                _issue(issues, "source_file_missing", "error", "关联素材文件不存在",
                       scene_id=scene.id, file_path=media_file.path,
                       suggestion="恢复素材原路径，或在剪辑软件中重新链接")

    _check_repetition(session, scenes, all_assignments, issues)

    extension_context = QualityCheckContext(
        session=session,
        project=project,
        scenes=tuple(scenes),
        subtitles=tuple(cues),
        assignments=tuple(all_assignments),
    )
    issues.extend(
        item.model_dump(mode="json")
        for item in quality_checker_registry.run(extension_context)
    )

    linked_paths: list[Path] = []
    for assignment in all_assignments:
        shot = session.get(MediaShot, assignment.media_shot_id)
        media = session.get(MediaFile, shot.media_file_id) if shot else None
        if media and media.path:
            linked_paths.append(Path(media.path))
    if prproj_path.is_file() and any(path.is_absolute() for path in linked_paths):
        _issue(issues, "absolute_media_paths", "warning",
               "工程使用绝对素材路径；移动项目后可能需要重新链接",
               suggestion="移动项目后在目标剪辑软件中检查素材链接")

    cues_by_id = {cue.id: (index, cue) for index, cue in enumerate(cues, start=1)}
    for issue in issues:
        cue_location = cues_by_id.get(issue["subtitle_id"])
        if cue_location:
            index, cue = cue_location
            issue["subtitle_cue_index"] = index
            issue["subtitle_start_ms"] = cue.start_ms

    passed = not any(item["severity"] == "error" for item in issues)
    report = {
        "schema_version": 1,
        "report_id": uuid.uuid4().hex,
        "project_id": project.id,
        "created_at": utc_now_iso(),
        "passed": passed,
        "delivery_verified": passed and premiere_conversion_verified,
        "premiere_conversion_verified": premiere_conversion_verified,
        "verification_status": (
            "manual_acceptance_required"
            if passed and premiere_conversion_verified
            else "failed"
        ),
        "manual_acceptance_required": True,
        "stale": False,
        "summary": {
            "scene_count": len(scenes),
            "assignment_count": covered_scene_count,
            "shot_assignment_count": len(all_assignments),
            "subtitle_count": len(cues),
            "error_count": sum(item["severity"] == "error" for item in issues),
            "warning_count": sum(item["severity"] == "warning" for item in issues),
            "audio_duration_seconds": audio_duration,
            "prproj_path": str(prproj_path),
            "audio_path": str(audio_path),
            "srt_path": str(srt_path),
        },
        "issues": issues,
        "file_signatures": {
            str(path): _file_signature(
                path,
                strong=(
                    path in {audio_path, srt_path, prproj_path, conversion_path}
                    or path in conversion_evidence_paths
                ),
            )
            for path in {
                audio_path,
                srt_path,
                prproj_path,
                conversion_path,
                *conversion_evidence_paths,
                *linked_paths,
            }
        },
        "project_signature": _project_signature(session, project),
    }
    report = DeliveryQualityReport.model_validate(report).model_dump(mode="json")
    path = _report_path(project)
    write_json_atomic(path, report)
    return report


def read_report(project: Project, session: Session | None = None) -> dict | None:
    path = _report_path(project)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        data = DeliveryQualityReport.model_validate(
            migrate_quality_report(data, project_id=project.id)
        ).model_dump(mode="json")
    except ValueError:
        return None
    signatures = data.get("file_signatures")
    files_changed = not isinstance(signatures, dict) or any(
        not signature_matches(Path(path), signature) for path, signature in signatures.items()
    )
    project_changed = session is not None and data.get("project_signature") != _project_signature(session, project)
    if files_changed or project_changed:
        data["passed"] = False
        data["delivery_verified"] = False
        data["verification_status"] = "failed"
        data["manual_acceptance_required"] = True
        data["stale"] = True
        data.setdefault("issues", []).append({
            "type": "quality_report_stale", "severity": "error", "scene_id": None,
            "subtitle_id": None, "message": "交付文件或素材已变化，请重新运行质量检查",
            "suggestion": "点击重新检查", "file_path": None,
        })
        data.setdefault("summary", {})["error_count"] = sum(
            issue.get("severity") == "error" for issue in data["issues"]
        )
    return data


def write_failed_report(project: Project, message: str) -> dict:
    """Persist a QC execution failure without invalidating an already exported PRPROJ."""
    report = {
        "schema_version": 1,
        "report_id": uuid.uuid4().hex,
        "project_id": project.id,
        "created_at": utc_now_iso(),
        "passed": False,
        "delivery_verified": False,
        "premiere_conversion_verified": False,
        "verification_status": "failed",
        "manual_acceptance_required": True,
        "stale": False,
        "summary": {
            "scene_count": 0,
            "assignment_count": 0,
            "shot_assignment_count": 0,
            "subtitle_count": 0,
            "error_count": 1,
            "warning_count": 0,
            "audio_duration_seconds": None,
        },
        "issues": [
            {
                "type": "quality_check_failed",
                "severity": "error",
                "scene_id": None,
                "subtitle_id": None,
                "message": f"交付质量检查执行失败：{message}",
                "suggestion": "检查本地日志与 FFmpeg 配置后重新运行质量检查",
                "file_path": None,
            }
        ],
        "file_signatures": {},
        "project_signature": None,
    }
    report = DeliveryQualityReport.model_validate(report).model_dump(mode="json")
    write_json_atomic(_report_path(project), report)
    return report


def record_manual_acceptance(
    session: Session,
    project: Project,
    *,
    editor: str,
    editor_version: str = "",
    checked_by: str | None = None,
    audio_ok: bool,
    subtitles_ok: bool,
    media_links_ok: bool,
    notes: str = "",
) -> dict:
    report = read_report(project, session)
    if report is None:
        raise ValueError("请先运行交付质量检查")
    if report.get("stale") or not report.get("delivery_verified"):
        raise ValueError("交付报告未通过或已经过期，不能记录人工验收")
    if not all((audio_ok, subtitles_ok, media_links_ok)):
        raise ValueError("旁白、字幕和素材链接必须全部确认通过")
    report["verification_status"] = "manually_accepted"
    report["manual_acceptance_required"] = False
    report["manual_acceptance"] = {
        "editor": editor.strip(),
        "editor_version": editor_version.strip(),
        "checked_at": utc_now_iso(),
        "checked_by": checked_by.strip() if checked_by else None,
        "audio_ok": audio_ok,
        "subtitles_ok": subtitles_ok,
        "media_links_ok": media_links_ok,
        "notes": notes.strip(),
    }
    report = DeliveryQualityReport.model_validate(report).model_dump(mode="json")
    write_json_atomic(_report_path(project), report)
    return report


_file_signature = file_signature
_signature_matches = signature_matches


def _project_signature(session: Session, project: Project) -> str:
    models = (VisualScene, SubtitleCue, SceneAssignment)
    records = [
        [item.model_dump() for item in session.exec(
            select(model).where(model.project_id == project.id).order_by(model.id)
        ).all()]
        for model in models
    ]
    assignments = records[2]
    shot_ids = sorted({assignment["media_shot_id"] for assignment in assignments})
    shot_models = list(
        session.exec(
            select(MediaShot).where(MediaShot.id.in_(shot_ids)).order_by(MediaShot.id)
        ).all()
    ) if shot_ids else []
    media_ids = sorted({shot.media_file_id for shot in shot_models})
    media_models = list(
        session.exec(
            select(MediaFile).where(MediaFile.id.in_(media_ids)).order_by(MediaFile.id)
        ).all()
    ) if media_ids else []
    shots = [shot.model_dump() for shot in shot_models]
    media = [item.model_dump() for item in media_models]
    payload = [project.output_dir, project.config_json, *records,
               sorted(shots, key=lambda item: item["id"]),
               media]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _check_delivered_srt(srt_path: Path, cues: list[SubtitleCue], issues: list[dict]) -> None:
    if not srt_path.is_file() or srt_path.stat().st_size == 0:
        return
    try:
        delivered_cues = parse_srt(srt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        _issue(issues, "subtitle_file_invalid", "error", f"SRT 无法读取或解析：{exc}",
               file_path=str(srt_path))
        return
    if len(delivered_cues) != len(cues) or any(
        abs(file_cue["start_ms"] - cue.start_ms) > 50
        or abs(file_cue["end_ms"] - cue.end_ms) > 50
        or " ".join(file_cue["text"].split()) != " ".join(cue.text.replace("\\N", " ").split())
        for file_cue, cue in zip(delivered_cues, cues, strict=False)
    ):
        _issue(issues, "subtitle_file_outdated", "error",
               "SRT 与项目字幕时间线不一致", file_path=str(srt_path),
               suggestion="重新导出字幕文件")


def _check_conversion_record(
    report_path: Path, prproj_path: Path, issues: list[dict]
) -> bool:
    try:
        conversion = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        conversion = None
    signature = conversion.get("prproj_signature") if isinstance(conversion, dict) else None
    marker = conversion.get("premiere_result") if isinstance(conversion, dict) else None
    source_fcpxml_path = (
        Path(str(conversion.get("source_fcpxml_path"))) if isinstance(conversion, dict)
        and conversion.get("source_fcpxml_path") else None
    )
    source_premiere_xml_path = (
        Path(str(conversion.get("source_premiere_xml_path"))) if isinstance(conversion, dict)
        and conversion.get("source_premiere_xml_path") else None
    )
    sources_match = bool(
        source_fcpxml_path
        and source_premiere_xml_path
        and _signature_matches(source_fcpxml_path, conversion.get("source_fcpxml_signature"))
        and _signature_matches(
            source_premiere_xml_path, conversion.get("source_premiere_xml_signature")
        )
    )
    if not isinstance(conversion, dict) or conversion.get("format") != "prproj" or \
            conversion.get("path") != str(prproj_path) or not conversion.get("export_id") or \
            not conversion.get("created_at") or \
            not conversion.get("premiere_executable") or not isinstance(marker, dict) or \
            marker.get("success") is not True or not _signature_matches(prproj_path, signature) or \
            not sources_match:
        _issue(issues, "prproj_conversion_unverified", "error",
               "缺少匹配的 Premiere Pro 转换记录，无法核实工程来源",
               file_path=str(report_path))
        return False
    return True


def _conversion_evidence_paths(report_path: Path) -> list[Path]:
    try:
        conversion = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(conversion, dict):
        return []
    return [
        Path(str(value))
        for value in (
            conversion.get("source_fcpxml_path"),
            conversion.get("source_premiere_xml_path"),
        )
        if value
    ]


def _check_scene_assignments(
    scene: VisualScene, assignments: list[SceneAssignment], issues: list[dict]
) -> bool:
    duration_ms = scene.end_ms - scene.start_ms
    cursor_ms = 0
    complete = bool(assignments) and duration_ms > 0
    for assignment in sorted(assignments, key=lambda item: item.sequence_index):
        start_ms = assignment.scene_offset_start_ms
        end_ms = assignment.scene_offset_end_ms
        if end_ms is None or start_ms != cursor_ms or end_ms <= start_ms or end_ms > duration_ms:
            _issue(issues, "assignment_invalid", "error",
                   "Scene 镜头位置有空洞、重叠或无效时间范围",
                   scene_id=scene.id, suggestion="重新分配或调整此 Scene 的素材")
            complete = False
        if end_ms is not None:
            cursor_ms = end_ms
    if cursor_ms < duration_ms:
        _issue(issues, "assignment_missing", "error",
               f"场景镜头轨道尚缺 {(duration_ms - cursor_ms) / 1000:.2f} 秒",
               scene_id=scene.id)
        complete = False
    return complete and cursor_ms == duration_ms


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


def _duration_or_issue(
    path: Path, issue_type: str, message: str, issues: list[dict]
) -> float | None:
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
    file_path: str | None = None,
) -> None:
    issues.append(
        {
            "type": issue_type,
            "severity": severity,
            "scene_id": scene_id,
            "subtitle_id": subtitle_id,
            "message": message,
            "suggestion": suggestion,
            "file_path": file_path,
        }
    )


def _report_path(project: Project) -> Path:
    return get_project_work_dir(project, get_settings().workspace_dir) / "reports" / "qa.json"
