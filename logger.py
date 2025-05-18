# filename: logger.py
import logging
from rich.logging import RichHandler
from config import LOG_LEVEL, LOG_FILE, LOG_FORMAT, LOG_DATE_FORMAT

# Ensure logging level is valid
numeric_level = getattr(logging, LOG_LEVEL.upper(), None)
if not isinstance(numeric_level, int):
    raise ValueError(f"Invalid log level: {LOG_LEVEL}")

# Configure Rich Handler for console output
rich_handler = RichHandler(
    rich_tracebacks=True,
    show_path=False, # Show filename and line number in the main log message instead
    keywords=["INFO", "DEBUG", "WARNING", "ERROR", "CRITICAL", "[INFO]", "[DEBUG]", "[WARNING]", "[ERROR]", "[CRITICAL]"] # Keywords to highlight
)
rich_handler.setFormatter(logging.Formatter(fmt="%(message)s", datefmt="[%X]")) # Simpler format for console

# Configure File Handler for output to a file
file_handler = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8') # Append mode
file_handler.setFormatter(logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

def get_logger(name: str) -> logging.Logger:
    """Configures and returns a logger instance."""
    logger = logging.getLogger(name)
    logger.setLevel(numeric_level)

    # Prevent adding handlers multiple times if get_logger is called more than once for the same logger name
    if not logger.handlers:
        logger.addHandler(rich_handler)
        logger.addHandler(file_handler)
        logger.propagate = False # Prevent duplication if root logger also has handlers
    
    return logger

# Example of a global logger if needed, though per-module is often better
# global_logger = get_logger("BookingScraperApp")