import logging
import sys
import json
from datetime import datetime, timezone
from pathlib import Path


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            log["exc"] = self.formatException(record.exc_info)
        return json.dumps(log)


def get_logger(name: str, level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(JSONFormatter())
    logger.addHandler(ch)

    # file handler
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    fh = logging.FileHandler(log_dir / "trading.log")
    fh.setFormatter(JSONFormatter())
    logger.addHandler(fh)

    logger.propagate = False
    return logger
