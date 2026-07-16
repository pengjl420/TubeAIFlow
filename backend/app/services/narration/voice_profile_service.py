import json
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
SUPPORTED_TTS_ENGINES = {"qwen3_tts", "chatterbox", "cosyvoice"}


def list_profiles(session: Session) -> list[dict]:
    profiles = session.exec(select(VoiceProfile).order_by(VoiceProfile.created_at.desc())).all()
    return [serialize_profile(profile) for profile in profiles]


def get_profile(session: Session, profile_id: str) -> VoiceProfile | None:
    return session.get(VoiceProfile, profile_id)


def create_profile(
    session: Session,
    *,
    name: str,
    tts_engine: str,
    reference_audio_text: str,
    source: BinaryIO,
    original_filename: str,
) -> VoiceProfile:
    profile_id = uuid.uuid4().hex[:12]
    validated_name = _validate_name(name)
    config = _validated_config(tts_engine, reference_audio_text, original_filename)
    audio_path = _save_audio(profile_id, source, original_filename)
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
    source: BinaryIO | None = None,
    original_filename: str | None = None,
) -> VoiceProfile:
    current_config = load_profile_config(profile)
    filename = original_filename or str(current_config.get("original_filename") or Path(profile.reference_audio_path).name)
    config = _validated_config(tts_engine, reference_audio_text, filename)
    old_path = Path(profile.reference_audio_path)
    if source is not None:
        audio_path = _save_audio(profile.id, source, filename)
        if old_path != audio_path:
            old_path.unlink(missing_ok=True)
        profile.reference_audio_path = str(audio_path)
    elif not old_path.is_file():
        raise ValueError("参考音频文件不存在，请重新上传")

    profile.name = _validate_name(name)
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


def serialize_profile(profile: VoiceProfile) -> dict:
    config = load_profile_config(profile)
    return {
        "id": profile.id,
        "name": profile.name,
        "tts_engine": str(config.get("tts_engine") or "qwen3_tts"),
        "reference_audio_text": str(config.get("reference_audio_text") or ""),
        "original_filename": str(config.get("original_filename") or Path(profile.reference_audio_path).name),
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
    config["reference_audio_text"] = str(profile_config.get("reference_audio_text") or "")
    config["reference_audio_filename"] = str(profile_config.get("original_filename") or audio_path.name)
    config["reference_audio_path"] = str(audio_path)
    project.reference_audio_path = str(audio_path)
    return config


def _synchronize_projects(session: Session, profile: VoiceProfile, force_reset: bool = False) -> None:
    for project in session.exec(select(Project)).all():
        config = load_project_config(project)
        if str(config.get("voice_profile_id") or "") != profile.id:
            continue
        previous = (
            str(config.get("tts_engine") or ""),
            str(config.get("reference_audio_text") or ""),
            project.reference_audio_path or "",
        )
        config = apply_profile_to_project(session, project, profile.id)
        current = (
            str(config.get("tts_engine") or ""),
            str(config.get("reference_audio_text") or ""),
            project.reference_audio_path or "",
        )
        project.config_json = json.dumps(config, ensure_ascii=False)
        project.updated_at = utc_now_iso()
        if force_reset or previous != current:
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
    source: BinaryIO,
    original_filename: str,
    max_bytes: int = 100 * 1024 * 1024,
) -> Path:
    extension = Path(original_filename).suffix.lower()
    if extension not in SUPPORTED_AUDIO_EXTENSIONS:
        raise ValueError("参考音频必须是 WAV、MP3、FLAC 或 M4A")
    profile_dir = get_settings().workspace_dir / "voices" / profile_id
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


def _validate_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise ValueError("请输入音色名称")
    if len(value) > 120:
        raise ValueError("音色名称不能超过 120 个字符")
    return value


def _validated_config(tts_engine: str, reference_audio_text: str, original_filename: str) -> dict:
    engine = tts_engine.strip().lower()
    if engine not in SUPPORTED_TTS_ENGINES:
        raise ValueError("不支持的 TTS 引擎")
    transcript = reference_audio_text.strip()
    if engine == "cosyvoice" and not transcript:
        raise ValueError("CosyVoice 需要填写参考音频逐字稿")
    return {
        "tts_engine": engine,
        "reference_audio_text": transcript,
        "original_filename": Path(original_filename).name,
    }
