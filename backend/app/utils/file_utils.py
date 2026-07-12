from pathlib import Path


def ensure_inside_workspace(path: Path, workspace_dir: Path) -> Path:
    resolved_path = path.resolve()
    resolved_workspace = workspace_dir.resolve()
    if resolved_path != resolved_workspace and resolved_workspace not in resolved_path.parents:
        raise ValueError(f"Path is outside workspace: {path}")
    return resolved_path


def project_dir(workspace_dir: Path, project_id: str) -> Path:
    safe_id = "".join(ch for ch in project_id if ch.isalnum() or ch in {"_", "-"})
    if safe_id != project_id or not safe_id:
        raise ValueError("Invalid project id")
    return workspace_dir / "projects" / safe_id
