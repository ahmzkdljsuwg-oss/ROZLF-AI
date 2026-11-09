from __future__ import annotations

import logging
import re

_SECRET_KEYS = re.compile(r"(token|key|secret|password|authorization|apikey)", re.I)
_SECRET_PAIR = re.compile(
    r"(?i)\b(token|key|secret|password|apikey|api_key|authorization)\b(\s*[:=]\s*)([^\s,;'\"]+)"
)


def redact(text: str) -> str:
    """Remove anything that looks like a credential before it reaches a log line."""
    if not text:
        return ""
    return _SECRET_PAIR.sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        k: ("***" if _SECRET_KEYS.search(str(k)) else v) for k, v in record.args.items()
                    }
                else:
                    record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        except Exception:  # never break logging on a malformed record
            pass
        return True


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
