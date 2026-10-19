"""One-line JSON logs. Document text, quotes and filenames are never logged.

Only the fields in ALLOWED_FIELDS are copied from a record's `extra`, so a careless
`logger.info(..., extra={"quote": ...})` cannot leak letter text into the log.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import UTC, datetime
from pathlib import Path

ALLOWED_FIELDS = (
    "document_id",
    "run_id",
    "job_id",
    "step",
    "status",
    "reason",
    "duration_ms",
    "input_tokens",
    "output_tokens",
    "attempt",
    "path",
    "count",
)

LOGGER_NAME = "papertrail"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for name in ALLOWED_FIELDS:
            value = record.__dict__.get(name)
            if value is not None:
                payload[name] = value
        if record.exc_info and record.exc_info[0] is not None:
            # The exception type only: messages from parsers or SDKs can contain document text.
            payload["error_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(logs_dir: Path | None, *, level: int = logging.INFO) -> None:
    """Console + rotating file (5 files x 5 MB) in the data folder."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = JsonFormatter()
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    if logs_dir is not None:
        logs_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            logs_dir / "papertrail.log", maxBytes=5 * 1024 * 1024, backupCount=4, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
