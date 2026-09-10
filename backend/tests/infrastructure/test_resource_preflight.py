from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.infrastructure import resource_preflight
from app.models.project import Project


def test_sixty_minute_render_requires_capacity_for_intermediate_files(tmp_path: Path) -> None:
    script = tmp_path / "script.txt"
    script.write_text("长视频测试。" * 2600, encoding="utf-8")
    project = Project(
        id="project",
        name="Project",
        output_dir=str(tmp_path),
        script_clean_path=str(script),
    )
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with (
        Session(engine) as session,
        patch.object(
            resource_preflight, "get_settings", return_value=SimpleNamespace(workspace_dir=tmp_path)
        ),
        patch.object(
            resource_preflight.shutil,
            "disk_usage",
            return_value=SimpleNamespace(free=100 * resource_preflight.GIB),
        ),
    ):
        result = resource_preflight.check_project_disk_space(session, project, "final_render")

    assert result.estimated_duration_seconds >= 3600
    assert result.required_bytes >= 10 * resource_preflight.GIB
    assert result.sufficient
    engine.dispose()


def test_preflight_fails_with_stable_error_code(tmp_path: Path) -> None:
    project = Project(id="project", name="Project", output_dir=str(tmp_path))
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with (
        Session(engine) as session,
        patch.object(
            resource_preflight, "get_settings", return_value=SimpleNamespace(workspace_dir=tmp_path)
        ),
        patch.object(
            resource_preflight.shutil,
            "disk_usage",
            return_value=SimpleNamespace(free=resource_preflight.GIB),
        ),
    ):
        with pytest.raises(resource_preflight.InsufficientDiskSpaceError) as captured:
            resource_preflight.check_project_disk_space(session, project, "tts")

    assert captured.value.code == "INSUFFICIENT_DISK_SPACE"
    engine.dispose()
