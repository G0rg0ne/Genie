import os
import sys

from loguru import logger

LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
    "<level>{message}</level>"
)


def setup_logging(level: str | None = None) -> None:
    level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    use_colors = sys.stderr.isatty() or os.getenv("FORCE_COLOR", "").lower() in {
        "1",
        "true",
        "yes",
    }

    logger.remove()
    logger.add(
        sys.stderr,
        format=LOG_FORMAT,
        level=level,
        colorize=use_colors,
        backtrace=True,
        diagnose=False,
    )
