from pathlib import Path

from send2trash import send2trash


def move_existing_to_recycle_bin(paths: list[Path]) -> list[str]:
    """Move existing project artifacts to the OS recycle bin.

    Missing paths are intentionally ignored so a project can still be removed
    after a user has manually deleted some or all of its generated files.
    """
    existing = _deduplicate_existing_paths(paths)
    recycled: list[str] = []
    for path in existing:
        send2trash(str(path))
        recycled.append(str(path))
    return recycled


def _deduplicate_existing_paths(paths: list[Path]) -> list[Path]:
    resolved: list[Path] = []
    for path in paths:
        candidate = path.expanduser().resolve()
        if not candidate.exists() or candidate in resolved:
            continue
        resolved.append(candidate)

    # If a parent directory is recycled, do not attempt to recycle its children
    # again. Shortest paths are considered first for deterministic behaviour.
    selected: list[Path] = []
    for candidate in sorted(resolved, key=lambda item: (len(item.parts), str(item).lower())):
        if any(parent == candidate or parent in candidate.parents for parent in selected):
            continue
        selected.append(candidate)
    return selected
