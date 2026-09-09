from __future__ import annotations

import asyncio
import logging
import sys

from dotenv import load_dotenv

from gitsnapbot.app import BotApp
from gitsnapbot.config import Config
from gitsnapbot.logsetup import setup_logging

log = logging.getLogger("gitsnapbot")


async def run() -> None:
    config = Config.from_env()
    setup_logging(level=config.log_level, color=config.log_color, log_file=config.log_file)
    app = BotApp(config)
    try:
        await app.start()
    except Exception:
        log.critical("GitSnapBot stopped because of an unrecoverable error", exc_info=True)
        raise
    finally:
        await app.close()


def main() -> None:
    load_dotenv()
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log = logging.getLogger("gitsnapbot")
        log.info("Received interrupt — GitSnapBot stopped")
        sys.exit(0)


if __name__ == "__main__":
    main()
