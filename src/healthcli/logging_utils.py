import logging
from datetime import datetime
from pathlib import Path


def setup_logger(name: str = "healthcli", log_dir: str = "logs") -> logging.Logger:
    """ 
    Set up a logger that logs to both console and a file with timestamps.
    """
    Path(log_dir).mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = Path(log_dir) / f"quality_{timestamp}.log"

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s") # format for log messages

    # Headers are only added once to avoid duplicate logs
    if not logger.handlers:
        # File handler
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger
