"""
/**
 * @author: Meidlinger
 * @date: 2025-07-02
 */
"""

import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
from pathlib import Path


class DailyFileHandler(TimedRotatingFileHandler):
    def __init__(
        self,
        log_dir: Path,
        base_name: str,
        when: str = "midnight",
        interval: int = 1,
        backupCount: int = 7,
        encoding: str = "utf-8",
        utc: bool = False,
    ):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.base_name = base_name
        self._refresh_filename()

        super().__init__(
            filename=self.baseFilename,
            when=when,
            interval=interval,
            backupCount=backupCount,
            encoding=encoding,
            utc=utc,
        )

    def _refresh_filename(self):
        date_str = datetime.now().strftime("%Y%m%d")
        self.baseFilename = str(self.log_dir / f"{self.base_name}_{date_str}.log")

    def doRollover(self):
        super().doRollover()
        self._refresh_filename()
        if self.stream:
            self.stream.close()
        self.stream = self._open()


def get_logger(
    name: str,
    log_dir: Path,
    base_name: str,
    level: int = logging.INFO,
    to_console: bool = True,
) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    fmt = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    formatter = logging.Formatter(fmt)

    file_handler = DailyFileHandler(log_dir, base_name)
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if to_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    logger.setLevel(level)
    logger.propagate = False 
    return logger
