from collections.abc import Generator

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
            connection.exec_driver_sql(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, utc_now_iso()),
            )


def create_db_and_tables() -> None:
    # Import all models before create_all so new databases receive the full schema.
    import app.models  # noqa: F401

    _apply_migrations()
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
