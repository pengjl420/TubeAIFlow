from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path


_REDACTIONS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)((?:api[_-]?key|access[_-]?token|password|cookie)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
)


def redact_sensitive(value: object) -> str:
    text = str(value)
    for pattern in _REDACTIONS:
        text = pattern.sub(
            lambda match: f"{match.group(1) if match.lastindex else ''}[REDACTED]",
            text,
        )
    return text


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_sensitive(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: _redact_argument(value) for key, value in record.args.items()
                }
            else:
                record.args = tuple(_redact_argument(value) for value in record.args)
        return True


def _redact_argument(value: object) -> object:
    return redact_sensitive(value) if isinstance(value, str) else value


def configure_logging(workspace_dir: Path, *, level: int = logging.INFO) -> Path:
    """Configure one rotating local engine log and return its path."""
    log_dir = workspace_dir.expanduser().resolve() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "engine.log"

    root = logging.getLogger()
    if any(
        getattr(handler, "_tubeaifolw_engine_handler", False)
        for handler in root.handlers
    ):
        return log_path

    handler = RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler._tubeaifolw_engine_handler = True  # type: ignore[attr-defined]
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    handler.addFilter(SensitiveDataFilter())
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
    return log_path
