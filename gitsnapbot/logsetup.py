from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from typing import TextIO

from gitsnapbot import __version__

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
LEVEL_COLOR = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[1;31m",
}
CHANNEL_COLOR = "\033[34m"
TOKEN_IN_URL = re.compile(r"/bot[^/]+/")


def short_url(url: str) -> str:
    cleaned = TOKEN_IN_URL.sub("/bot***/", url)
    for prefix in ("https://api.github.com", "http://api.github.com"):
        if cleaned.startswith(prefix):
            return cleaned[len(prefix) :] or "/"
    for prefix in ("https://api.telegram.org", "http://api.telegram.org"):
        if cleaned.startswith(prefix):
            return cleaned[len(prefix) :] or "/"
    return cleaned


def use_color(enabled: bool, stream: TextIO) -> bool:
    if not enabled:
        return False
    if os.getenv("NO_COLOR"):
        return False
    return hasattr(stream, "isatty") and stream.isatty()


class ConsoleFormatter(logging.Formatter):
    def __init__(self, color: bool) -> None:
        super().__init__()
        self.color = color

    def format(self, record: logging.LogRecord) -> str:
        channel = record.name.removeprefix("gitsnapbot").lstrip(".") or "app"
        if channel.startswith("github"):
            channel = "github"
        elif channel.startswith("telegram"):
            channel = "telegram"
        elif channel.startswith("tracker"):
            channel = "poll"
        level = record.levelname
        stamp = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        message = record.getMessage()
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            message = f"{message}\n{record.exc_text}"
        if self.color:
            line = (
                f"{DIM}{stamp}{RESET}  "
                f"{LEVEL_COLOR.get(level, '')}{level:<8}{RESET} "
                f"{CHANNEL_COLOR}{channel:<9}{RESET} {message}"
            )
        else:
            line = f"{stamp}  {level:<8} {channel:<9} {message}"
        return line


def setup_logging(*, level: str, color: bool = True, log_file: str | None = None) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(ConsoleFormatter(use_color(color, sys.stderr)))
    root.addHandler(stream)

    if log_file:
        Path(log_file).expanduser().parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(ConsoleFormatter(color=False))
        root.addHandler(file_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("hpack").setLevel(logging.WARNING)


def startup_banner(
    *,
    github_login: str,
    telegram_username: str | None,
    poll_seconds: int,
    digest_label: str,
    remaining: int | None,
    limit: int | None,
    queued: int,
    paused: bool,
) -> str:
    hours = poll_seconds / 3600
    if poll_seconds % 3600 == 0 and poll_seconds >= 3600:
        poll = f"every {int(hours)}h"
    elif poll_seconds % 60 == 0:
        poll = f"every {poll_seconds // 60}m"
    else:
        poll = f"every {poll_seconds}s"
    quota = "unknown"
    if remaining is not None and limit is not None:
        quota = f"{remaining:,} / {limit:,} remaining"
    bot = f"@{telegram_username}" if telegram_username else "connected"
    state = "paused" if paused else "running"
    width = 58
    inner = width - 2
    lines = [
        f" GitSnapBot  v{__version__}",
        f" Status      {state}",
        f" GitHub      @{github_login}",
        f" Telegram    {bot}",
        f" Digest      {digest_label}",
        f" Poll        {poll}",
        f" Queue       {queued} item{'s' if queued != 1 else ''}",
        f" API quota   {quota}",
    ]
    top = "┌" + "─" * inner + "┐"
    bottom = "└" + "─" * inner + "┘"
    body = "\n".join("│" + line.ljust(inner)[:inner] + "│" for line in lines)
    return f"{top}\n{body}\n{bottom}"


def print_banner(text: str) -> None:
    """Write the identity box with no log prefix, so it is always first."""
    sys.stderr.write(f"\n{text}\n\n")
    sys.stderr.flush()
