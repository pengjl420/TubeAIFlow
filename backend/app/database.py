from collections.abc import Generator
from datetime import datetime, timezone
import json
import logging
import shutil
import sqlite3
from pathlib import Path

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from app.config import DATABASE_PATH


LATEST_SCHEMA_VERSION = 22
logger = logging.getLogger(__name__)


DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(
    f"sqlite:///{DATABASE_PATH}",
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


TASK_RUN_MIGRATION = """
CREATE TABLE IF NOT EXISTS task_runs (
    id VARCHAR NOT NULL PRIMARY KEY,
    project_id VARCHAR NOT NULL,
    batch_id VARCHAR,
    batch_item_id VARCHAR,
    workflow VARCHAR NOT NULL DEFAULT 'narration_generation',
    status VARCHAR NOT NULL DEFAULT 'queued',
    current_stage VARCHAR NOT NULL DEFAULT 'segmenting',
    include_video BOOLEAN NOT NULL DEFAULT 0,
    queue_sequence INTEGER NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    compensation_count INTEGER NOT NULL DEFAULT 0,
    cancel_requested BOOLEAN NOT NULL DEFAULT 0,
    checkpoint_json VARCHAR NOT NULL DEFAULT '{}',
    config_snapshot_json VARCHAR NOT NULL DEFAULT '{}',
    error_message VARCHAR,
    lease_owner VARCHAR,
    heartbeat_at VARCHAR,
    created_at VARCHAR NOT NULL,
    updated_at VARCHAR NOT NULL,
    started_at VARCHAR,
    finished_at VARCHAR,
    last_recovered_at VARCHAR
)
"""


def _apply_migrations() -> None:
    migrations = {
        1: [
            TASK_RUN_MIGRATION,
            "CREATE INDEX IF NOT EXISTS ix_task_runs_project_id ON task_runs (project_id)",
            "CREATE INDEX IF NOT EXISTS ix_task_runs_batch_id ON task_runs (batch_id)",
            "CREATE INDEX IF NOT EXISTS ix_task_runs_batch_item_id ON task_runs (batch_item_id)",
            "CREATE INDEX IF NOT EXISTS ix_task_runs_status ON task_runs (status)",
            "CREATE INDEX IF NOT EXISTS ix_task_runs_queue_sequence ON task_runs (queue_sequence)",
        ],
        2: [
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_task_runs_active_project "
            "ON task_runs (project_id) WHERE status IN ('queued', 'running', 'paused')",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_task_runs_single_running "
            "ON task_runs (status) WHERE status = 'running'",
        ],
        3: [],
        4: [
            """
            CREATE TABLE IF NOT EXISTS subtitle_cues (
                id VARCHAR NOT NULL PRIMARY KEY,
                project_id VARCHAR NOT NULL,
                source_segment_id VARCHAR NOT NULL,
                cue_index INTEGER NOT NULL,
                start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL,
                text VARCHAR NOT NULL,
                created_at VARCHAR NOT NULL,
                updated_at VARCHAR NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_subtitle_cues_project_id ON subtitle_cues (project_id)",
            "CREATE INDEX IF NOT EXISTS ix_subtitle_cues_source_segment_id ON subtitle_cues (source_segment_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_subtitle_cues_source "
            "ON subtitle_cues (project_id, source_segment_id, cue_index)",
            """
            CREATE TABLE IF NOT EXISTS visual_scenes (
                id VARCHAR NOT NULL PRIMARY KEY,
                project_id VARCHAR NOT NULL,
                scene_index INTEGER NOT NULL,
                start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL,
                narration VARCHAR NOT NULL,
                subtitle_ids_json VARCHAR NOT NULL DEFAULT '[]',
                storyboard_json VARCHAR,
                confidence FLOAT,
                status VARCHAR NOT NULL DEFAULT 'draft',
                created_at VARCHAR NOT NULL,
                updated_at VARCHAR NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_visual_scenes_project_id ON visual_scenes (project_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_visual_scenes_project_index "
            "ON visual_scenes (project_id, scene_index)",
        ],
        5: [
            """
            CREATE TABLE IF NOT EXISTS media_files (
                id VARCHAR NOT NULL PRIMARY KEY,
                provider VARCHAR NOT NULL DEFAULT 'local',
                provider_asset_id VARCHAR,
                path VARCHAR NOT NULL,
                filename VARCHAR NOT NULL,
                media_type VARCHAR NOT NULL,
                file_hash VARCHAR NOT NULL,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER,
                width INTEGER,
                height INTEGER,
                status VARCHAR NOT NULL DEFAULT 'ready',
                metadata_json VARCHAR NOT NULL DEFAULT '{}',
                created_at VARCHAR NOT NULL,
                updated_at VARCHAR NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_media_files_provider ON media_files (provider)",
            "CREATE INDEX IF NOT EXISTS ix_media_files_media_type ON media_files (media_type)",
            "CREATE INDEX IF NOT EXISTS ix_media_files_status ON media_files (status)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_media_files_hash ON media_files (file_hash)",
            """
            CREATE TABLE IF NOT EXISTS media_shots (
                id VARCHAR NOT NULL PRIMARY KEY,
                media_file_id VARCHAR NOT NULL,
                shot_index INTEGER NOT NULL,
                start_ms INTEGER NOT NULL DEFAULT 0,
                end_ms INTEGER,
                description VARCHAR NOT NULL DEFAULT '',
                tags_json VARCHAR NOT NULL DEFAULT '[]',
                thumbnail_path VARCHAR,
                vector_id INTEGER,
                status VARCHAR NOT NULL DEFAULT 'ready',
                technical_json VARCHAR NOT NULL DEFAULT '{}',
                created_at VARCHAR NOT NULL,
                updated_at VARCHAR NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_media_shots_media_file_id ON media_shots (media_file_id)",
            "CREATE INDEX IF NOT EXISTS ix_media_shots_status ON media_shots (status)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_media_shots_file_index "
            "ON media_shots (media_file_id, shot_index)",
            """
            CREATE TABLE IF NOT EXISTS scene_candidates (
                id VARCHAR NOT NULL PRIMARY KEY,
                project_id VARCHAR NOT NULL,
                scene_id VARCHAR NOT NULL,
                media_shot_id VARCHAR NOT NULL,
                source VARCHAR NOT NULL DEFAULT 'local',
                query VARCHAR NOT NULL DEFAULT '',
                semantic_score FLOAT NOT NULL DEFAULT 0,
                text_score FLOAT NOT NULL DEFAULT 0,
                tag_score FLOAT NOT NULL DEFAULT 0,
                technical_score FLOAT NOT NULL DEFAULT 0,
                total_score FLOAT NOT NULL DEFAULT 0,
                status VARCHAR NOT NULL DEFAULT 'LOW_RELEVANCE',
                conflicts_json VARCHAR NOT NULL DEFAULT '[]',
                created_at VARCHAR NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_scene_candidates_project_id ON scene_candidates (project_id)",
            "CREATE INDEX IF NOT EXISTS ix_scene_candidates_scene_id ON scene_candidates (scene_id)",
            "CREATE INDEX IF NOT EXISTS ix_scene_candidates_media_shot_id ON scene_candidates (media_shot_id)",
            "CREATE INDEX IF NOT EXISTS ix_scene_candidates_status ON scene_candidates (status)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_scene_candidates_scene_shot "
            "ON scene_candidates (scene_id, media_shot_id)",
            """
            CREATE TABLE IF NOT EXISTS scene_assignments (
                id VARCHAR NOT NULL PRIMARY KEY,
                project_id VARCHAR NOT NULL,
                scene_id VARCHAR NOT NULL,
                media_shot_id VARCHAR NOT NULL,
                candidate_id VARCHAR,
                trim_start_ms INTEGER NOT NULL DEFAULT 0,
                trim_end_ms INTEGER,
                playback_speed FLOAT NOT NULL DEFAULT 1.0,
                transition VARCHAR NOT NULL DEFAULT 'cut',
                manual_confirmed BOOLEAN NOT NULL DEFAULT 1,
                created_at VARCHAR NOT NULL,
                updated_at VARCHAR NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_scene_assignments_project_id ON scene_assignments (project_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_scene_assignments_scene_id "
            "ON scene_assignments (scene_id)",
        ],
        6: [
            """
            CREATE TABLE IF NOT EXISTS media_keyframes (
                id VARCHAR NOT NULL PRIMARY KEY,
                media_shot_id VARCHAR NOT NULL,
                frame_index INTEGER NOT NULL,
                timestamp_ms INTEGER NOT NULL,
                path VARCHAR NOT NULL,
                created_at VARCHAR NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_media_keyframes_media_shot_id "
            "ON media_keyframes (media_shot_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_media_keyframes_shot_index "
            "ON media_keyframes (media_shot_id, frame_index)",
        ],
        7: [
            """
            CREATE TABLE IF NOT EXISTS media_provider_states (
                provider VARCHAR NOT NULL PRIMARY KEY,
                status VARCHAR NOT NULL DEFAULT 'available',
                rate_limit INTEGER,
                remaining INTEGER,
                reset_at VARCHAR,
                last_error VARCHAR,
                updated_at VARCHAR NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_media_provider_states_status "
            "ON media_provider_states (status)",
            """
            CREATE TABLE IF NOT EXISTS media_query_cache (
                id VARCHAR NOT NULL PRIMARY KEY,
                provider VARCHAR NOT NULL,
                query VARCHAR NOT NULL,
                media_type VARCHAR NOT NULL DEFAULT 'video',
                response_json VARCHAR NOT NULL DEFAULT '[]',
                expires_at VARCHAR NOT NULL,
                created_at VARCHAR NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_media_query_cache_provider "
            "ON media_query_cache (provider)",
            "CREATE INDEX IF NOT EXISTS ix_media_query_cache_expires_at "
            "ON media_query_cache (expires_at)",
        ],
        8: [
            "ALTER TABLE media_files ADD COLUMN library_role VARCHAR NOT NULL DEFAULT 'semantic'",
            "ALTER TABLE media_files ADD COLUMN fallback_category VARCHAR NOT NULL DEFAULT ''",
            "ALTER TABLE media_files ADD COLUMN mood VARCHAR NOT NULL DEFAULT ''",
            "ALTER TABLE media_files ADD COLUMN review_status VARCHAR NOT NULL DEFAULT 'approved'",
            "ALTER TABLE media_files ADD COLUMN enabled BOOLEAN NOT NULL DEFAULT 1",
            "CREATE INDEX IF NOT EXISTS ix_media_files_library_role ON media_files (library_role)",
            "CREATE INDEX IF NOT EXISTS ix_media_files_review_status ON media_files (review_status)",
            "CREATE INDEX IF NOT EXISTS ix_media_files_enabled ON media_files (enabled)",
            "ALTER TABLE media_shots ADD COLUMN library_role VARCHAR NOT NULL DEFAULT 'semantic'",
            "ALTER TABLE media_shots ADD COLUMN fallback_category VARCHAR NOT NULL DEFAULT ''",
            "ALTER TABLE media_shots ADD COLUMN mood VARCHAR NOT NULL DEFAULT ''",
            "CREATE INDEX IF NOT EXISTS ix_media_shots_library_role ON media_shots (library_role)",
            "ALTER TABLE scene_candidates ADD COLUMN selection_stage VARCHAR NOT NULL DEFAULT 'local_semantic'",
            "ALTER TABLE scene_candidates ADD COLUMN is_fallback BOOLEAN NOT NULL DEFAULT 0",
            "CREATE INDEX IF NOT EXISTS ix_scene_candidates_selection_stage ON scene_candidates (selection_stage)",
            "ALTER TABLE scene_assignments ADD COLUMN selection_stage VARCHAR NOT NULL DEFAULT 'manual'",
            "ALTER TABLE scene_assignments ADD COLUMN selection_reason VARCHAR NOT NULL DEFAULT ''",
            "ALTER TABLE scene_assignments ADD COLUMN is_fallback BOOLEAN NOT NULL DEFAULT 0",
            "CREATE INDEX IF NOT EXISTS ix_scene_assignments_selection_stage ON scene_assignments (selection_stage)",
        ],
        9: [
            "DROP INDEX IF EXISTS uq_scene_assignments_scene_id",
            "ALTER TABLE scene_assignments ADD COLUMN sequence_index INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE scene_assignments ADD COLUMN scene_offset_start_ms INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE scene_assignments ADD COLUMN scene_offset_end_ms INTEGER",
            "CREATE INDEX IF NOT EXISTS ix_scene_assignments_sequence_index ON scene_assignments (sequence_index)",
            "CREATE INDEX IF NOT EXISTS ix_scene_assignments_scene_sequence "
            "ON scene_assignments (scene_id, sequence_index)",
        ],
        10: [
            "ALTER TABLE scene_assignments ADD COLUMN display_duration_ms INTEGER",
            "ALTER TABLE scene_assignments ADD COLUMN motion_type VARCHAR NOT NULL DEFAULT 'auto'",
            "ALTER TABLE scene_assignments ADD COLUMN zoom_start FLOAT NOT NULL DEFAULT 1.0",
            "ALTER TABLE scene_assignments ADD COLUMN zoom_end FLOAT NOT NULL DEFAULT 1.06",
            "ALTER TABLE scene_assignments ADD COLUMN pan_direction VARCHAR NOT NULL DEFAULT 'center'",
            "ALTER TABLE scene_assignments ADD COLUMN crop_anchor VARCHAR NOT NULL DEFAULT 'center'",
            """
            CREATE TABLE IF NOT EXISTS generated_image_variants (
                id VARCHAR NOT NULL PRIMARY KEY,
                project_id VARCHAR NOT NULL,
                scene_id VARCHAR NOT NULL,
                variant_index INTEGER NOT NULL,
                path VARCHAR NOT NULL,
                prompt VARCHAR NOT NULL,
                negative_prompt VARCHAR NOT NULL DEFAULT '',
                model_path VARCHAR NOT NULL,
                model_name VARCHAR NOT NULL DEFAULT '',
                workflow_version VARCHAR NOT NULL DEFAULT 'sdxl_single_file_v1',
                input_signature VARCHAR NOT NULL,
                seed INTEGER NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                steps INTEGER NOT NULL,
                guidance_scale FLOAT NOT NULL,
                status VARCHAR NOT NULL DEFAULT 'pending',
                generation_seconds FLOAT,
                error_message VARCHAR,
                media_file_id VARCHAR,
                candidate_id VARCHAR,
                created_at VARCHAR NOT NULL,
                updated_at VARCHAR NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_generated_image_variants_project_id ON generated_image_variants (project_id)",
            "CREATE INDEX IF NOT EXISTS ix_generated_image_variants_scene_id ON generated_image_variants (scene_id)",
            "CREATE INDEX IF NOT EXISTS ix_generated_image_variants_input_signature ON generated_image_variants (input_signature)",
            "CREATE INDEX IF NOT EXISTS ix_generated_image_variants_status ON generated_image_variants (status)",
            "CREATE INDEX IF NOT EXISTS ix_generated_image_variants_media_file_id ON generated_image_variants (media_file_id)",
            "CREATE INDEX IF NOT EXISTS ix_generated_image_variants_candidate_id ON generated_image_variants (candidate_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_generated_image_variant_scene_index ON generated_image_variants (scene_id, variant_index)",
        ],
        11: [
            "ALTER TABLE scene_assignments ADD COLUMN render_mode VARCHAR NOT NULL DEFAULT 'auto'",
        ],
        12: [
            """
            CREATE TABLE IF NOT EXISTS local_video_merge_tasks (
                id VARCHAR NOT NULL PRIMARY KEY,
                media_dir VARCHAR NOT NULL,
                output_dir VARCHAR NOT NULL,
                output_filename VARCHAR NOT NULL,
                target_duration FLOAT NOT NULL,
                status VARCHAR NOT NULL DEFAULT 'queued',
                queue_sequence INTEGER NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                result_json VARCHAR NOT NULL DEFAULT '{}',
                error_message VARCHAR,
                created_at VARCHAR NOT NULL,
                updated_at VARCHAR NOT NULL,
                started_at VARCHAR,
                finished_at VARCHAR
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_local_video_merge_tasks_status "
            "ON local_video_merge_tasks (status)",
            "CREATE INDEX IF NOT EXISTS ix_local_video_merge_tasks_queue_sequence "
            "ON local_video_merge_tasks (queue_sequence)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_local_video_merge_tasks_single_running "
            "ON local_video_merge_tasks (status) WHERE status = 'running'",
        ],
        13: [
            """
            CREATE TABLE IF NOT EXISTS avatar_profiles (
                id VARCHAR NOT NULL PRIMARY KEY,
                name VARCHAR NOT NULL,
                template_video_path VARCHAR NOT NULL,
                duration_ms INTEGER,
                width INTEGER,
                height INTEGER,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                created_at VARCHAR NOT NULL,
                updated_at VARCHAR NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_avatar_profiles_enabled ON avatar_profiles (enabled)",
            """
            CREATE TABLE IF NOT EXISTS avatar_generation_tasks (
                id VARCHAR NOT NULL PRIMARY KEY,
                avatar_profile_id VARCHAR NOT NULL,
                audio_path VARCHAR NOT NULL,
                output_filename VARCHAR NOT NULL,
                chunk_seconds INTEGER NOT NULL DEFAULT 420,
                audio_duration_ms INTEGER NOT NULL DEFAULT 0,
                status VARCHAR NOT NULL DEFAULT 'queued',
                queue_sequence INTEGER NOT NULL,
                total_chunks INTEGER NOT NULL DEFAULT 0,
                completed_chunks INTEGER NOT NULL DEFAULT 0,
                current_chunk INTEGER,
                progress FLOAT NOT NULL DEFAULT 0,
                result_path VARCHAR,
                error_message VARCHAR,
                created_at VARCHAR NOT NULL,
                updated_at VARCHAR NOT NULL,
                started_at VARCHAR,
                finished_at VARCHAR
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_avatar_generation_tasks_profile ON avatar_generation_tasks (avatar_profile_id)",
            "CREATE INDEX IF NOT EXISTS ix_avatar_generation_tasks_status ON avatar_generation_tasks (status)",
            "CREATE INDEX IF NOT EXISTS ix_avatar_generation_tasks_queue ON avatar_generation_tasks (queue_sequence)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_avatar_generation_tasks_running ON avatar_generation_tasks (status) WHERE status = 'running'",
            """
            CREATE TABLE IF NOT EXISTS avatar_clips (
                id VARCHAR NOT NULL PRIMARY KEY,
                task_id VARCHAR NOT NULL,
                clip_index INTEGER NOT NULL,
                start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL,
                audio_path VARCHAR NOT NULL,
                duix_task_code VARCHAR NOT NULL,
                status VARCHAR NOT NULL DEFAULT 'pending',
                progress FLOAT NOT NULL DEFAULT 0,
                output_path VARCHAR,
                actual_duration_ms INTEGER,
                error_message VARCHAR,
                created_at VARCHAR NOT NULL,
                updated_at VARCHAR NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_avatar_clips_task ON avatar_clips (task_id)",
            "CREATE INDEX IF NOT EXISTS ix_avatar_clips_status ON avatar_clips (status)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_avatar_clips_task_index ON avatar_clips (task_id, clip_index)",
        ],
        14: [
            "ALTER TABLE avatar_generation_tasks ADD COLUMN context_ms INTEGER NOT NULL DEFAULT 800",
            "ALTER TABLE avatar_generation_tasks ADD COLUMN continuity_report_path VARCHAR",
            "ALTER TABLE avatar_clips ADD COLUMN generation_start_ms INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE avatar_clips ADD COLUMN generation_end_ms INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE avatar_clips ADD COLUMN trim_start_ms INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE avatar_clips ADD COLUMN trim_end_ms INTEGER NOT NULL DEFAULT 0",
        ],
        15: [
            """
            CREATE TABLE IF NOT EXISTS voice_generation_tasks (
                id VARCHAR NOT NULL PRIMARY KEY,
                voice_profile_id VARCHAR NOT NULL,
                voice_profile_name VARCHAR NOT NULL,
                text VARCHAR NOT NULL,
                output_filename VARCHAR NOT NULL,
                output_path VARCHAR,
                duration FLOAT,
                status VARCHAR NOT NULL DEFAULT 'queued',
                queue_sequence INTEGER NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                error_message VARCHAR,
                created_at VARCHAR NOT NULL,
                updated_at VARCHAR NOT NULL,
                started_at VARCHAR,
                finished_at VARCHAR
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_voice_generation_tasks_profile "
            "ON voice_generation_tasks (voice_profile_id)",
            "CREATE INDEX IF NOT EXISTS ix_voice_generation_tasks_status "
            "ON voice_generation_tasks (status)",
            "CREATE INDEX IF NOT EXISTS ix_voice_generation_tasks_queue "
            "ON voice_generation_tasks (queue_sequence)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_voice_generation_tasks_running "
            "ON voice_generation_tasks (status) WHERE status = 'running'",
        ],
        16: [],
        17: [
            "ALTER TABLE visual_scenes ADD COLUMN locked_text BOOLEAN NOT NULL DEFAULT 0",
            "ALTER TABLE visual_scenes ADD COLUMN locked_audio BOOLEAN NOT NULL DEFAULT 0",
            "ALTER TABLE visual_scenes ADD COLUMN locked_visual BOOLEAN NOT NULL DEFAULT 0",
            "ALTER TABLE visual_scenes ADD COLUMN version INTEGER NOT NULL DEFAULT 1",
            """
            CREATE TABLE IF NOT EXISTS scene_revisions (
                id VARCHAR NOT NULL PRIMARY KEY,
                project_id VARCHAR NOT NULL,
                scene_id VARCHAR NOT NULL,
                version INTEGER NOT NULL,
                change_type VARCHAR NOT NULL DEFAULT 'manual_edit',
                snapshot_json VARCHAR NOT NULL,
                created_at VARCHAR NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_scene_revisions_project_id ON scene_revisions (project_id)",
            "CREATE INDEX IF NOT EXISTS ix_scene_revisions_scene_id ON scene_revisions (scene_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_scene_revisions_scene_version ON scene_revisions (scene_id, version)",
        ],
        18: [
            "ALTER TABLE task_runs ADD COLUMN job_type VARCHAR NOT NULL DEFAULT 'project_workflow'",
            "ALTER TABLE task_runs ADD COLUMN scene_id VARCHAR",
            "ALTER TABLE task_runs ADD COLUMN resource_class VARCHAR NOT NULL DEFAULT 'cpu'",
            "ALTER TABLE task_runs ADD COLUMN pause_requested BOOLEAN NOT NULL DEFAULT 0",
            "ALTER TABLE task_runs ADD COLUMN progress FLOAT NOT NULL DEFAULT 0",
            "ALTER TABLE task_runs ADD COLUMN max_retries INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE task_runs ADD COLUMN error_code VARCHAR",
            "ALTER TABLE task_runs ADD COLUMN result_json VARCHAR NOT NULL DEFAULT '{}'",
            "CREATE INDEX IF NOT EXISTS ix_task_runs_job_type ON task_runs (job_type)",
            "CREATE INDEX IF NOT EXISTS ix_task_runs_scene_id ON task_runs (scene_id)",
            "CREATE INDEX IF NOT EXISTS ix_task_runs_resource_class ON task_runs (resource_class)",
        ],
        19: [
            "DROP INDEX IF EXISTS uq_task_runs_single_running",
        ],
        20: [
            "ALTER TABLE task_runs ADD COLUMN request_json VARCHAR NOT NULL DEFAULT '{}'",
        ],
        # Version 16 installed triggers before scene_revisions existed. Re-run
        # trigger installation after all revision tables are present.
        21: [],
        22: [
            "DROP INDEX IF EXISTS uq_media_files_hash",
            "CREATE INDEX IF NOT EXISTS ix_media_files_hash ON media_files (file_hash)",
        ],
    }
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at VARCHAR NOT NULL)"
        )
        applied = {
            row[0]
            for row in connection.exec_driver_sql("SELECT version FROM schema_migrations").fetchall()
        }
        from app.shared.time import utc_now_iso

        for version, statements in migrations.items():
            if version in applied:
                continue
            for statement in statements:
                connection.exec_driver_sql(statement)
            if version == 3:
                _migrate_source_subtitles(connection)
            if version in {16, 21}:
                _install_referential_integrity_triggers(connection)
            connection.exec_driver_sql(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, utc_now_iso()),
            )


def _migrate_source_subtitles(connection) -> None:
    """Collapse legacy bilingual subtitle storage into one source-text field."""
    segment_table = connection.exec_driver_sql(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'segments'"
    ).first()
    if segment_table:
        columns = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(segments)").fetchall()
        }
        if "text_zh" in columns or "text_en" in columns:
            source_column = "text" if "text" in columns else "text_zh"
            connection.exec_driver_sql("DROP TABLE IF EXISTS segments_source_migration")
            connection.exec_driver_sql(
                """
                CREATE TABLE segments_source_migration (
                    id VARCHAR NOT NULL PRIMARY KEY,
                    segment_id VARCHAR NOT NULL,
                    project_id VARCHAR NOT NULL,
                    segment_index INTEGER NOT NULL,
                    text VARCHAR NOT NULL,
                    audio_path VARCHAR,
                    duration FLOAT,
                    start_time FLOAT,
                    end_time FLOAT,
                    status VARCHAR NOT NULL,
                    error_message VARCHAR,
                    created_at VARCHAR NOT NULL,
                    updated_at VARCHAR NOT NULL
                )
                """
            )
            connection.exec_driver_sql(
                f"""
                INSERT INTO segments_source_migration (
                    id, segment_id, project_id, segment_index, text, audio_path,
                    duration, start_time, end_time, status, error_message, created_at, updated_at
                )
                SELECT
                    id, segment_id, project_id, segment_index, {source_column}, audio_path,
                    duration, start_time, end_time, status, error_message, created_at, updated_at
                FROM segments
                """
            )
            connection.exec_driver_sql("DROP TABLE segments")
            connection.exec_driver_sql("ALTER TABLE segments_source_migration RENAME TO segments")
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_segments_segment_id ON segments (segment_id)"
            )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_segments_project_id ON segments (project_id)"
            )

    connection.exec_driver_sql("DROP TABLE IF EXISTS subtitle_templates")

    project_table = connection.exec_driver_sql(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'projects'"
    ).first()
    if not project_table:
        return
    project_columns = {
        row[1] for row in connection.exec_driver_sql("PRAGMA table_info(projects)").fetchall()
    }
    if "status" in project_columns:
        connection.exec_driver_sql(
            "UPDATE projects SET status = 'narration_ready' "
            "WHERE status IN ('zh_subtitle_created', 'en_subtitle_created')"
        )
    if "config_json" not in project_columns:
        return
    rows = connection.exec_driver_sql(
        "SELECT id, config_json FROM projects WHERE config_json IS NOT NULL"
    ).fetchall()
    for project_id, raw_config in rows:
        try:
            config = json.loads(raw_config)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(config, dict) or "include_translation" not in config:
            continue
        config.pop("include_translation", None)
        connection.exec_driver_sql(
            "UPDATE projects SET config_json = ? WHERE id = ?",
            (json.dumps(config, ensure_ascii=False), project_id),
        )


def _install_referential_integrity_triggers(connection) -> None:
    """Protect new writes while legacy tables transition to native foreign keys."""
    relationships = (
        ("segments", "project_id", "projects", "id"),
        ("task_runs", "project_id", "projects", "id"),
        ("subtitle_cues", "project_id", "projects", "id"),
        ("visual_scenes", "project_id", "projects", "id"),
        ("scene_revisions", "project_id", "projects", "id"),
        ("scene_revisions", "scene_id", "visual_scenes", "id"),
        ("media_shots", "media_file_id", "media_files", "id"),
        ("media_keyframes", "media_shot_id", "media_shots", "id"),
        ("scene_assignments", "project_id", "projects", "id"),
        ("scene_assignments", "scene_id", "visual_scenes", "id"),
        ("scene_assignments", "media_shot_id", "media_shots", "id"),
        ("generated_image_variants", "project_id", "projects", "id"),
        ("generated_image_variants", "scene_id", "visual_scenes", "id"),
        ("batch_items", "batch_id", "batch_jobs", "id"),
        ("batch_items", "project_id", "projects", "id"),
        ("avatar_generation_tasks", "avatar_profile_id", "avatar_profiles", "id"),
        ("avatar_clips", "task_id", "avatar_generation_tasks", "id"),
        ("voice_generation_tasks", "voice_profile_id", "voice_profiles", "id"),
    )
    tables = {
        row[0]
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    for child, child_column, parent, parent_column in relationships:
        if child not in tables or parent not in tables:
            continue
        key = f"{child}_{child_column}_{parent}"
        for operation in ("INSERT", "UPDATE OF " + child_column):
            suffix = "insert" if operation == "INSERT" else "update"
            connection.exec_driver_sql(
                f"""
                CREATE TRIGGER IF NOT EXISTS fk_{key}_{suffix}
                BEFORE {operation} ON {child}
                FOR EACH ROW
                WHEN NEW.{child_column} IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM {parent} WHERE {parent_column} = NEW.{child_column}
                  )
                BEGIN
                    SELECT RAISE(ABORT, 'referential integrity: {child}.{child_column}');
                END
                """
            )


def _referential_integrity_violations(connection) -> list[str]:
    checks = (
        ("segments", "project_id", "projects"),
        ("task_runs", "project_id", "projects"),
        ("subtitle_cues", "project_id", "projects"),
        ("visual_scenes", "project_id", "projects"),
        ("scene_revisions", "project_id", "projects"),
        ("scene_revisions", "scene_id", "visual_scenes"),
        ("media_shots", "media_file_id", "media_files"),
        ("scene_assignments", "scene_id", "visual_scenes"),
        ("scene_assignments", "media_shot_id", "media_shots"),
    )
    tables = {
        row[0]
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    violations = []
    for child, column, parent in checks:
        if child not in tables or parent not in tables:
            continue
        count = connection.exec_driver_sql(
            f"SELECT COUNT(*) FROM {child} c LEFT JOIN {parent} p ON p.id = c.{column} "
            f"WHERE c.{column} IS NOT NULL AND p.id IS NULL"
        ).scalar_one()
        if count:
            violations.append(f"{child}.{column}: {count}")
    return violations


def create_db_and_tables() -> None:
    # Import all models before create_all so new databases receive the full schema.
    import app.models  # noqa: F401

    backup_path = _backup_database_before_migration()
    try:
        _apply_migrations()
        SQLModel.metadata.create_all(engine)
        with engine.begin() as connection:
            _install_referential_integrity_triggers(connection)
        _validate_database()
    except Exception:
        engine.dispose()
        if backup_path is not None:
            shutil.copy2(backup_path, _engine_database_path())
        raise


def _engine_database_path() -> Path:
    database = engine.url.database
    return Path(database).resolve() if database else DATABASE_PATH.resolve()


def _backup_database_before_migration() -> Path | None:
    database_path = _engine_database_path()
    if not database_path.is_file() or database_path.stat().st_size == 0:
        return None
    with sqlite3.connect(database_path) as connection:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        current_version = (
            int(connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0])
            if table
            else 0
        )
        if current_version >= LATEST_SCHEMA_VERSION:
            return None
        backup_dir = database_path.parent / ".backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = backup_dir / f"{database_path.stem}-schema-{current_version}-{timestamp}.db"
        with sqlite3.connect(backup_path) as backup:
            connection.backup(backup)
    return backup_path


def _validate_database() -> None:
    with engine.connect() as connection:
        integrity = connection.exec_driver_sql("PRAGMA integrity_check").scalar_one()
        if integrity != "ok":
            raise RuntimeError(f"Database integrity check failed: {integrity}")
        version = connection.exec_driver_sql(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).scalar_one()
        if int(version) != LATEST_SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version is {version}, expected {LATEST_SCHEMA_VERSION}"
            )
        violations = _referential_integrity_violations(connection)
        if violations:
            logger.warning(
                "Legacy orphaned database references require repair: %s",
                ", ".join(violations),
            )


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
