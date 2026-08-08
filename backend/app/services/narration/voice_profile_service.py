import json
import math
import re
import uuid
from pathlib import Path
from typing import BinaryIO

from sqlmodel import Session, select

from app.config import get_settings
from app.models.narration import Segment, VoiceProfile
from app.models.project import Project
from app.infrastructure.project_layout import load_project_config
from app.shared.time import utc_now_iso


SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a"}
SUPPORTED_TTS_ENGINES = {"qwen3_tts", "index_tts", "moss_tts", "cosyvoice"}
SUPPORTED_VOICE_LANGUAGES = {"zh-CN", "en-US", "yue-HK"}
RECOMMENDED_ENGINE_BY_LANGUAGE = {
    "zh-CN": "index_tts",
    "en-US": "moss_tts",
    "yue-HK": "cosyvoice",
}
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def list_profiles(session: Session) -> list[dict]:
    profiles = session.exec(select(VoiceProfile).order_by(VoiceProfile.created_at.desc())).all()
    projects = list(session.exec(select(Project)).all())
    usage: dict[str, dict[str, int]] = {}
    for project in projects:
        profile_id = str(load_project_config(project).get("voice_profile_id") or "")
        if not profile_id:
            continue
        counts = usage.setdefault(profile_id, {"usage_count": 0, "running_project_count": 0})
        counts["usage_count"] += 1
        if project.status in {"narration_in_progress", "video_in_progress"}:
            counts["running_project_count"] += 1
    return [
        {**serialize_profile(profile), **usage.get(profile.id, {"usage_count": 0, "running_project_count": 0})}
        for profile in profiles
    ]


def get_profile(session: Session, profile_id: str) -> VoiceProfile | None:
    return session.get(VoiceProfile, profile_id)


def create_profile(
    session: Session,
    *,
    name: str,
    tts_engine: str,
    reference_audio_text: str,
    cosyvoice_speed: float = 1.0,
    tags: list[str] | None = None,
    source: BinaryIO,
    original_filename: str,
    language: str = "zh-CN",
) -> VoiceProfile:
    profile_id = uuid.uuid4().hex[:12]
    validated_name = _validate_name(name)
    config = _validated_config(tts_engine, reference_audio_text, original_filename, cosyvoice_speed, tags, language)
    audio_path = _save_audio(profile_id, validated_name, source, original_filename)
    now = utc_now_iso()
    profile = VoiceProfile(
        id=profile_id,
        name=validated_name,
        reference_audio_path=str(audio_path),
        config_json=json.dumps(
            config,
            ensure_ascii=False,
        ),
        created_at=now,
        updated_at=now,
    )
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


def update_profile(
    session: Session,
    profile: VoiceProfile,
    *,
    name: str,
    tts_engine: str,
    reference_audio_text: str,
    cosyvoice_speed: float | None = None,
    tags: list[str] | None = None,
    source: BinaryIO | None = None,
    original_filename: str | None = None,
    language: str | None = None,
) -> VoiceProfile:
    validated_name = _validate_name(name)
    current_config = load_profile_config(profile)
    filename = original_filename or str(current_config.get("original_filename") or Path(profile.reference_audio_path).name)
    if cosyvoice_speed is None:
        cosyvoice_speed = profile_cosyvoice_speed(current_config)
    if tags is None:
        tags = list(current_config.get("tags") or [])
    if language is None:
        language = profile_language(current_config)
    config = _validated_config(tts_engine, reference_audio_text, filename, cosyvoice_speed, tags, language)
    old_path = Path(profile.reference_audio_path)
    if source is not None:
        audio_path = _save_audio(
            profile.id,
            validated_name,
            source,
            filename,
            current_dir=old_path.parent,
        )
        if old_path != audio_path:
            old_path.unlink(missing_ok=True)
            try:
                old_path.parent.rmdir()
            except OSError:
                pass
        profile.reference_audio_path = str(audio_path)
    elif not old_path.is_file():
        raise ValueError("参考音频文件不存在，请重新上传")
    else:
        profile.reference_audio_path = str(
            _relocate_audio(profile.id, validated_name, old_path)
        )

    profile.name = validated_name
    profile.config_json = json.dumps(config, ensure_ascii=False)
    profile.updated_at = utc_now_iso()
    session.add(profile)
    _synchronize_projects(session, profile, force_reset=source is not None)
    session.commit()
    session.refresh(profile)
    return profile


def delete_profile(session: Session, profile: VoiceProfile) -> None:
    assigned_projects = [
        project
        for project in session.exec(select(Project)).all()
        if str(load_project_config(project).get("voice_profile_id") or "") == profile.id
    ]
    if assigned_projects:
        raise ValueError(f"该音色正被 {len(assigned_projects)} 个项目使用，请先为这些项目选择其他音色")
    audio_path = Path(profile.reference_audio_path)
    session.delete(profile)
    session.commit()
    audio_path.unlink(missing_ok=True)
    try:
        audio_path.parent.rmdir()
    except OSError:
        pass


def duplicate_profile(session: Session, profile: VoiceProfile) -> VoiceProfile:
    source_path = Path(profile.reference_audio_path)
    if not source_path.is_file():
        raise ValueError("参考音频文件不存在，无法复制音色")
    config = load_profile_config(profile)
    base_name = f"{profile.name} - 副本"
    existing_names = {item.name for item in session.exec(select(VoiceProfile)).all()}
    name = base_name
    suffix = 2
    while name in existing_names:
        name = f"{base_name} {suffix}"
        suffix += 1
    with source_path.open("rb") as source:
        return create_profile(
            session,
            name=name,
            tts_engine=str(config.get("tts_engine") or "qwen3_tts"),
            reference_audio_text=str(config.get("reference_audio_text") or ""),
            cosyvoice_speed=profile_cosyvoice_speed(config),
            tags=list(config.get("tags") or []),
            source=source,
            original_filename=str(config.get("original_filename") or source_path.name),
            language=profile_language(config),
        )


def serialize_profile(profile: VoiceProfile) -> dict:
    config = load_profile_config(profile)
    return {
        "id": profile.id,
        "name": profile.name,
        "tts_engine": str(config.get("tts_engine") or "qwen3_tts"),
        "language": profile_language(config),
        "reference_audio_text": str(config.get("reference_audio_text") or ""),
        "cosyvoice_speed": profile_cosyvoice_speed(config),
        "original_filename": str(config.get("original_filename") or Path(profile.reference_audio_path).name),
        "tags": list(config.get("tags") or []),
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


def load_profile_config(profile: VoiceProfile) -> dict:
    if not profile.config_json:
        return {}
    try:
        value = json.loads(profile.config_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def apply_profile_to_project(session: Session, project: Project, profile_id: str) -> dict:
    profile = get_profile(session, profile_id.strip())
    if not profile:
        raise ValueError("请选择有效的系统音色")
    audio_path = Path(profile.reference_audio_path).resolve()
    if not audio_path.is_file():
        raise ValueError("所选系统音色的参考音频文件不存在")
    profile_config = load_profile_config(profile)
    config = load_project_config(project)
    config["voice_profile_id"] = profile.id
    config["voice_profile_name"] = profile.name
    config["tts_engine"] = str(profile_config.get("tts_engine") or "qwen3_tts")
    config["voice_language"] = profile_language(profile_config)
    config["reference_audio_text"] = str(profile_config.get("reference_audio_text") or "")
    config["cosyvoice_speed"] = profile_cosyvoice_speed(profile_config)
    config["reference_audio_filename"] = str(profile_config.get("original_filename") or audio_path.name)
    config["reference_audio_path"] = str(audio_path)
    project.reference_audio_path = str(audio_path)
    return config


def migrate_profile_directories(session: Session) -> int:
    """Rename legacy ID-based voice folders to their configured profile names."""
    migrated = 0
    for profile in session.exec(select(VoiceProfile)).all():
        old_path = Path(profile.reference_audio_path)
        if not old_path.is_file():
            continue
        audio_path = _relocate_audio(profile.id, profile.name, old_path)
        if audio_path == old_path:
            continue
        profile.reference_audio_path = str(audio_path)
        profile.updated_at = utc_now_iso()
        session.add(profile)
        _synchronize_projects(session, profile)
        migrated += 1
    if migrated:
        session.commit()
    return migrated


def migrate_profile_language_engines(session: Session) -> int:
    """Upgrade pre-language profiles to the language-specific engine routing."""
    migrated = 0
    for profile in session.exec(select(VoiceProfile)).all():
        config = load_profile_config(profile)
        configured_language = str(config.get("language") or "")
        if configured_language in SUPPORTED_VOICE_LANGUAGES:
            language = configured_language
        elif "粤语" in profile.name or "粵語" in profile.name:
            language = "yue-HK"
        elif "英文" in profile.name or "english" in profile.name.lower():
            language = "en-US"
        else:
            language = "zh-CN"
        current_engine = str(config.get("tts_engine") or "qwen3_tts").strip().lower()
        target_engine = (
            "qwen3_tts"
            if current_engine == "qwen3_tts"
            else RECOMMENDED_ENGINE_BY_LANGUAGE[language]
        )
        if configured_language == language and current_engine == target_engine:
            continue
        config["language"] = language
        config["tts_engine"] = target_engine
        profile.config_json = json.dumps(config, ensure_ascii=False)
        profile.updated_at = utc_now_iso()
        session.add(profile)
        _synchronize_projects(session, profile, force_reset=current_engine != target_engine)
        migrated += 1
    if migrated:
        session.commit()
    return migrated


def _synchronize_projects(session: Session, profile: VoiceProfile, force_reset: bool = False) -> None:
    for project in session.exec(select(Project)).all():
        config = load_project_config(project)
        if str(config.get("voice_profile_id") or "") != profile.id:
            continue
        previous_tts_config = (
            str(config.get("tts_engine") or ""),
            str(config.get("voice_language") or "zh-CN"),
            str(config.get("reference_audio_text") or ""),
            profile_cosyvoice_speed(config),
        )
        config = apply_profile_to_project(session, project, profile.id)
        current_tts_config = (
            str(config.get("tts_engine") or ""),
            str(config.get("voice_language") or "zh-CN"),
            str(config.get("reference_audio_text") or ""),
            profile_cosyvoice_speed(config),
        )
        project.config_json = json.dumps(config, ensure_ascii=False)
        project.updated_at = utc_now_iso()
        if force_reset or previous_tts_config != current_tts_config:
            for segment in session.exec(select(Segment).where(Segment.project_id == project.id)).all():
                segment.audio_path = None
                segment.duration = None
                segment.start_time = None
                segment.end_time = None
                segment.status = "pending"
                segment.error_message = None
                segment.updated_at = utc_now_iso()
                session.add(segment)
            if project.status not in {"created", "script_imported"}:
                project.status = "segmented"
        session.add(project)


def _save_audio(
    profile_id: str,
    profile_name: str,
    source: BinaryIO,
    original_filename: str,
    current_dir: Path | None = None,
    max_bytes: int = 100 * 1024 * 1024,
) -> Path:
    extension = Path(original_filename).suffix.lower()
    if extension not in SUPPORTED_AUDIO_EXTENSIONS:
        raise ValueError("参考音频必须是 WAV、MP3、FLAC 或 M4A")
    profile_dir = _profile_directory(profile_id, profile_name, current_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    output_path = profile_dir / f"reference{extension}"
    written = 0
    try:
        with output_path.open("wb") as target:
            while chunk := source.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise ValueError("参考音频超过 100 MB 限制")
                target.write(chunk)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    return output_path.resolve()


def _relocate_audio(profile_id: str, profile_name: str, old_path: Path) -> Path:
    old_path = old_path.resolve()
    target_dir = _profile_directory(profile_id, profile_name, old_path.parent)
    if target_dir.resolve() == old_path.parent:
        return old_path
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    old_path.parent.rename(target_dir)
    return (target_dir / old_path.name).resolve()


def _profile_directory(
    profile_id: str,
    profile_name: str,
    current_dir: Path | None = None,
) -> Path:
    voices_dir = (get_settings().workspace_dir / "voices").resolve()
    folder_name = _safe_folder_name(profile_name, profile_id)
    candidate = voices_dir / folder_name
    if current_dir is not None and candidate.resolve() == current_dir.resolve():
        return candidate
    if not candidate.exists():
        return candidate
    return voices_dir / f"{folder_name}_{profile_id[:8]}"


def _safe_folder_name(profile_name: str, profile_id: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", profile_name.strip())
    value = re.sub(r"\s+", " ", value).rstrip(" .")
    if not value or value in {".", ".."} or value.upper() in WINDOWS_RESERVED_NAMES:
        return f"voice_{profile_id[:8]}"
    return value[:100].rstrip(" .") or f"voice_{profile_id[:8]}"


def _validate_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise ValueError("请输入音色名称")
    if len(value) > 120:
        raise ValueError("音色名称不能超过 120 个字符")
    return value


def _validated_config(
    tts_engine: str,
    reference_audio_text: str,
    original_filename: str,
    cosyvoice_speed: float,
    tags: list[str] | None = None,
    language: str = "zh-CN",
) -> dict:
    engine = tts_engine.strip().lower()
    if engine not in SUPPORTED_TTS_ENGINES:
        raise ValueError("不支持的 TTS 引擎")
    normalized_language = language.strip()
    if normalized_language not in SUPPORTED_VOICE_LANGUAGES:
        raise ValueError("不支持的音色语言")
    transcript = reference_audio_text.strip()
    if engine == "cosyvoice" and not transcript:
        raise ValueError("CosyVoice 需要填写参考音频逐字稿")
    speed = _validate_cosyvoice_speed(cosyvoice_speed)
    normalized_tags: list[str] = []
    for raw_tag in tags or []:
        tag = str(raw_tag).strip()
        if tag and tag not in normalized_tags:
            normalized_tags.append(tag[:20])
        if len(normalized_tags) >= 8:
            break
    return {
        "tts_engine": engine,
        "language": normalized_language,
        "reference_audio_text": transcript,
        "cosyvoice_speed": speed,
        "original_filename": Path(original_filename).name,
        "tags": normalized_tags,
    }


def _validate_cosyvoice_speed(value: object) -> float:
    try:
        speed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("CosyVoice 语速必须是数字") from exc
    if not math.isfinite(speed) or not 0.5 <= speed <= 2.0:
        raise ValueError("CosyVoice 语速必须在 0.5 到 2.0 之间")
    return speed


def profile_cosyvoice_speed(config: dict) -> float:
    try:
        return _validate_cosyvoice_speed(config.get("cosyvoice_speed", 1.0))
    except ValueError:
        return 1.0


def profile_language(config: dict) -> str:
    value = str(config.get("language") or "zh-CN")
    return value if value in SUPPORTED_VOICE_LANGUAGES else "zh-CN"
