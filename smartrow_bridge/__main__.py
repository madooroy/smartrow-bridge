from __future__ import annotations

import asyncio
import logging
import signal

from . import config, session_log
from .bridge import Bridge


async def _main(cfg: config.Config) -> None:
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, task.cancel)
    await Bridge(cfg).run()


def main() -> None:
    cfg = config.parse()
    # SRB_LOG_LEVEL applies to the bridge's own loggers only. Libraries stay at INFO:
    # their debug output (every HCI/ATT packet, some of it on the root logger) runs
    # to thousands of lines a minute.
    level = cfg.log_level.upper()
    logging.basicConfig(
        level=max(logging.INFO, logging.getLevelName(level)),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    logging.getLogger("smartrow_bridge").setLevel(level)
    if cfg.gatt_log:
        logging.getLogger("bumble.gatt_server").setLevel(logging.DEBUG)
    if cfg.session_log.lower() != "off":
        session_log.install(cfg.session_log)
    try:
        asyncio.run(_main(cfg))
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass


if __name__ == "__main__":
    main()
