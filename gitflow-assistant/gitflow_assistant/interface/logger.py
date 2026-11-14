"""Logging configuration with automatic redaction of credentials."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Optional

from gitflow_assistant.core.git_engine import redact
from gitflow_assistant.utils.path_manager import data_dir, ensure_dir


class RedactingFilter(logging.Filter):
    """Strip credentials from every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            record.args = tuple(redact(str(a)) for a in (record.args if isinstance(record.args, tuple) else (record.args,)))
        return True


def setup_logging(verbose: bool = False, log_dir: Optional[Path] = None) -> Path:
    """Configure a rotating log file (and stderr output with ``-v``). Returns the log path."""
    directory = ensure_dir(log_dir or (data_dir() / "logs"))
    log_file = directory / "gitflow.log"
    logger = logging.getLogger("gitflow")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    redactor = RedactingFilter()
    try:
        file_handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=512 * 1024, backupCount=3,
                                                            encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
        file_handler.addFilter(redactor)
        logger.addHandler(file_handler)
    except OSError:
        logger.addHandler(logging.NullHandler())
    if verbose:
        console = logging.StreamHandler()
        console.setLevel(logging.DEBUG)
        console.setFormatter(logging.Formatter("[debug] %(name)s: %(message)s"))
        console.addFilter(redactor)
        logger.addHandler(console)
    return log_file
