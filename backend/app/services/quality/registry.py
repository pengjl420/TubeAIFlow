from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlmodel import Session

from app.models.media import SceneAssignment
from app.models.project import Project
from app.models.storyboard import SubtitleCue, VisualScene
from app.services.quality.models import DeliveryQualityIssue


@dataclass(frozen=True, slots=True)
class QualityCheckContext:
    session: Session
    project: Project
    scenes: tuple[VisualScene, ...]
    subtitles: tuple[SubtitleCue, ...]
    assignments: tuple[SceneAssignment, ...]


class QualityChecker(Protocol):
    id: str
    version: str

    def check(self, context: QualityCheckContext) -> list[DeliveryQualityIssue]: ...


class QualityCheckerRegistry:
    def __init__(self) -> None:
        self._items: dict[str, QualityChecker] = {}

    def register(self, checker: QualityChecker) -> None:
        if not checker.id.strip():
            raise ValueError("Quality checker id is required")
        self._items[checker.id] = checker

    def list(self) -> tuple[QualityChecker, ...]:
        return tuple(self._items.values())

    def run(self, context: QualityCheckContext) -> list[DeliveryQualityIssue]:
        issues: list[DeliveryQualityIssue] = []
        for checker in self._items.values():
            issues.extend(checker.check(context))
        return issues


quality_checker_registry = QualityCheckerRegistry()
