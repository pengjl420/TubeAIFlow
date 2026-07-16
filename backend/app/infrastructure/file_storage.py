from pathlib import Path


def ensure_inside_workspace(path: Path, workspace_dir: Path) -> Path:
    resolved_path = path.resolve()
    resolved_workspace = workspace_dir.resolve()
    if resolved_path != resolved_workspace and resolved_workspace not in resolved_path.parents:
        raise ValueError(f"Path is outside workspace: {path}")
    return resolved_path


def ensure_inside_any(path: Path, allowed_roots: list[Path]) -> Path:
    """Resolve a path and require it to be inside one of the allowed roots."""
    last_error: ValueError | None = None
    for root in allowed_roots:
        try:
            return ensure_inside_workspace(path, root)
        except ValueError as exc:
            last_error = exc
    raise ValueError(f"Path is outside allowed project directories: {path}") from last_error


def project_dir(workspace_dir: Path, project_id: str) -> Path:
    safe_id = "".join(ch for ch in project_id if ch.isalnum() or ch in {"_", "-"})
    if safe_id != project_id or not safe_id:
        raise ValueError("Invalid project id")
    return workspace_dir / "projects" / safe_id
