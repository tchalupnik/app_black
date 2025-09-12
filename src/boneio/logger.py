import logging
import os
import tempfile
from logging import Formatter
from logging.handlers import RotatingFileHandler
from pathlib import Path

from colorlog import ColoredFormatter

from boneio.config import LoggerConfig
from boneio.const import PAHO, PYMODBUS
from boneio.version import __version__

_LOGGER = logging.getLogger(__name__)
_nameToLevel = {
    "CRITICAL": logging.CRITICAL,
    "FATAL": logging.FATAL,
    "ERROR": logging.ERROR,
    "WARN": logging.WARNING,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}


def configure_logger(debug: int, log_config: LoggerConfig | None = None) -> None:
    """Configure logger based on config yaml."""

    def debug_logger():
        if debug == 0:
            logging.getLogger().setLevel(logging.INFO)
        if debug > 0:
            logging.getLogger().setLevel(logging.DEBUG)
            logging.getLogger(PAHO).setLevel(logging.WARN)
            logging.getLogger(PYMODBUS).setLevel(logging.WARN)
            logging.getLogger("pymodbus.client").setLevel(logging.WARN)
            _LOGGER.info("Debug mode active")
            _LOGGER.debug("Lib version is %s", __version__)
        if debug > 1:
            logging.getLogger(PAHO).setLevel(logging.DEBUG)
            logging.getLogger(PYMODBUS).setLevel(logging.DEBUG)
            logging.getLogger("pymodbus.client").setLevel(logging.DEBUG)
            logging.getLogger("hypercorn.error").setLevel(logging.DEBUG)

    if log_config is None:
        debug_logger()
        return
    default = log_config.default.upper() if log_config.default is not None else None
    if log_config.default is not None:
        level = _nameToLevel.get(log_config.default.upper())
        if level is not None:
            logging.getLogger().setLevel(_nameToLevel[default])
            if debug == 0:
                debug = -1

    for log_key, log_level in log_config.logs.items():
        logger = logging.getLogger(log_key)
        val = _nameToLevel.get(log_level.upper())
        if val is not None:
            _LOGGER.info("Setting %s log level to %s", log_key, log_level)
            logger.setLevel(val)
    debug_logger()


"""Shared logging configuration for BoneIO."""


def get_log_level(level_name: str) -> int:
    """Convert string log level to logging constant."""
    return _nameToLevel.get(level_name.upper(), logging.INFO)


def is_running_under_systemd():
    """Check if the process is running under systemd."""
    return os.getenv("JOURNAL_STREAM") is not None


def get_log_formatter(color: bool = True) -> Formatter:
    """Get log formatter with optional color support."""
    # When running under systemd, omit timestamp since journald adds it
    if is_running_under_systemd():
        log_format = "%(levelname)s (%(threadName)s) [%(name)s] %(message)s"
    else:
        log_format = "%(asctime)s %(levelname)s (%(threadName)s) [%(name)s] %(message)s"

    date_format = "%Y-%m-%d %H:%M:%S"

    if color:
        colored_format = "%(log_color)s" + log_format + "%(reset)s"
        return ColoredFormatter(
            fmt=colored_format,
            datefmt=date_format,
            reset=True,
            log_colors={
                "DEBUG": "cyan",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "red",
            },
        )
    return Formatter(log_format, datefmt=date_format)


def setup_logging(debug_level: int = 0) -> None:
    """Setup logging configuration."""
    log_format = "%(asctime)s %(levelname)s (%(threadName)s) [%(name)s] %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Set up basic configuration for console output
    logging.basicConfig(
        level=logging.INFO if debug_level == 0 else logging.DEBUG,
        format=log_format,
        datefmt=date_format,
    )

    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO if debug_level == 0 else logging.DEBUG)

    # Create formatter for console handler
    console_formatter = get_log_formatter(color=True)
    console_handler.setFormatter(console_formatter)

    # Add console handler to root logger
    logging.getLogger().handlers[0].setFormatter(console_formatter)

    # If debug level > 1, also log to file with rotation
    if debug_level > 1:
        # Use a secure temporary directory instead of /tmp
        # Try to get config directory first, fall back to secure temp dir
        config_dir = os.environ.get("BONEIO_CONFIG")
        if config_dir:
            log_dir = Path(config_dir).parent
        else:
            # Use user-specific temporary directory which is more secure than /tmp
            log_dir = Path(tempfile.gettempdir()) / "boneio"
            log_dir.mkdir(exist_ok=True, mode=0o700)  # Secure permissions

        log_file = log_dir / "boneio.log"

        # Create rotating file handler (10MB max size, keep 3 backup files)
        file_handler = RotatingFileHandler(
            str(log_file),
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=3,
            encoding="utf-8",
        )

        # Set formatter for file handler
        formatter = logging.Formatter(log_format, date_format)
        file_handler.setFormatter(formatter)

        # Set level for file handler
        file_handler.setLevel(logging.DEBUG)

        # Add handler to root logger
        logging.getLogger().addHandler(file_handler)

        logging.info("File logging enabled at: %s", log_file)
