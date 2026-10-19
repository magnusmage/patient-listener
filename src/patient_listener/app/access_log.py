"""Redact credentials from Uvicorn access-log request targets."""

from __future__ import annotations

import logging
import re

__all__ = ["AccessLogRedactionFilter", "redact_request_target", "install_access_log_redaction"]

_SENSITIVE_QUERY = re.compile(r"([?&](?:token|device)=)[^&\s]*", re.IGNORECASE)


def redact_request_target(target: str) -> str:
    """Return an access-log target with bearer-like query values removed."""
    return _SENSITIVE_QUERY.sub(r"\1REDACTED", target)


class AccessLogRedactionFilter(logging.Filter):
    """Remove session credentials before Uvicorn formats an access log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Uvicorn's access records use a five-item tuple whose third item is the request target.
        if isinstance(record.args, tuple) and len(record.args) >= 3 and isinstance(record.args[2], str):
            args = list(record.args)
            args[2] = redact_request_target(args[2])
            record.args = tuple(args)
        return True


def install_access_log_redaction() -> None:
    """Install one filter on Uvicorn's access logger for this process."""
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, AccessLogRedactionFilter) for item in logger.filters):
        logger.addFilter(AccessLogRedactionFilter())
