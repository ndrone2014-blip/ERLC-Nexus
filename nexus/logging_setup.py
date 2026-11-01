"""Structured logging with secret redaction."""

from __future__ import annotations

import json
import logging
import logging.handlers
import re
from datetime import datetime, timezone
from pathlib import Path

_REDACT_PATTERNS = [
    re.compile(r"(server-key['\"]?\s*[:=]\s*['\"]?)([^'\"\s,}]+)", re.I),
    re.compile(r"(authorization['\"]?\s*[:=]\s*['\"]?)([^'\"\s,}]+)", re.I),
    re.compile(r"(token['\"]?\s*[:=]\s*['\"]?)([^'\"\s,}]+)", re.I),
    re.compile(r"(secret['\"]?\s*[:=]\s*['\"]?)([^'\"\s,}]+)", re.I),
    # Discord bot tokens
    re.compile(r"()([MNO][A-Za-z\d_-]{23,25}\.[A-Za-z\d_-]{6}\.[A-Za-z\d_-]{27,})"),
]

_known_secrets: set[str] = set()


def register_secret(value: str) -> None:
    """Values registered here are masked anywhere they appear in a log line."""
    if value and len(value) >= 6:
        _known_secrets.add(value)


def redact(text: str) -> str:
    for secret in _known_secrets:
        if secret in text:
            text = text.replace(secret, "***")
    for pat in _REDACT_PATTERNS:
        text = pat.sub(lambda m: m.group(1) + "***", text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        record.msg = redact(msg)
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        for key in ("component", "event", "status"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, default=str)


def setup_logging(component: str, log_dir: Path, level: str = "INFO") -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(f"%(asctime)s [{component}] %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))
    console.addFilter(RedactingFilter())
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / f"{component}.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(JsonFormatter())
    file_handler.addFilter(RedactingFilter())
    root.addHandler(file_handler)

    for noisy in ("discord.gateway", "httpx", "httpcore", "aiosqlite", "sqlalchemy.engine", "alembic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return logging.getLogger("nexus")
