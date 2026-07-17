from collections.abc import Generator
import json

from sqlmodel import Session, SQLModel, create_engine

from app.config import DATABASE_PATH


DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(
    f"sqlite:///{DATABASE_PATH}",
    connect_args={"check_same_thread": False, "timeout": 30},
)


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


def create_db_and_tables() -> None:
    # Import all models before create_all so new databases receive the full schema.
    import app.models  # noqa: F401

    _apply_migrations()
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
