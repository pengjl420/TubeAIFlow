import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.project import Project
from app.services.visual_enrichment import project_workflow


def _project(root: Path, mode: str) -> Project:
    return Project(
        id="project-visual",
        name="Visual Project",
        output_dir=str(root),
        config_json=json.dumps(
            {
                "project_directory_name": "Visual Project",
                "visual_enrichment_mode": mode,
            }
        ),
    )


def test_auto_mode_records_fallback_when_advanced_stack_is_unavailable(tmp_path: Path) -> None:
    project = _project(tmp_path, "auto")
    with patch.object(
        project_workflow, "get_settings", return_value=SimpleNamespace(workspace_dir=tmp_path)
    ):
        report = project_workflow.enrich_project_visuals(None, project)  # type: ignore[arg-type]

    assert report["status"] == "fallback"
    assert "cleaned transcript" in report["error"]
    assert Path(report["report_path"]).is_file()


def test_advanced_mode_surfaces_setup_failure(tmp_path: Path) -> None:
    project = _project(tmp_path, "advanced")
    with (
        patch.object(
            project_workflow,
            "get_settings",
            return_value=SimpleNamespace(workspace_dir=tmp_path),
        ),
        pytest.raises(ValueError, match="cleaned transcript"),
    ):
        project_workflow.enrich_project_visuals(None, project)  # type: ignore[arg-type]
