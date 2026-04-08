"""
Entry point for the copy-trading bot.

Run in simulation mode (default):
    python -m trading_bot

Override settings via env vars or a .env file:
    USE_MOCK=false TRADE_FEED_URL=wss://... python -m trading_bot
"""
import asyncio
import logging
import signal as _signal
import sys
from typing import Optional

from .config import Config
from .executor import TradeExecutor
from .feed import TradeFeed
from .leaderboard import LeaderboardFetcher
from .signal_generator import SignalGenerator

logger = logging.getLogger("trading_bot.main")


def setup_logging(config: Config) -> None:
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.log_file, mode="a"),
    ]
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format=fmt,
        handlers=handlers,
    )


async def run(config: Config) -> None:
    # ------------------------------------------------------------------ #
    # 1. Identify target trader                                           #
    # ------------------------------------------------------------------ #
    fetcher = LeaderboardFetcher(config)
    target = await fetcher.fetch_top_trader()
    if not target:
        logger.error("Could not identify a target trader. Exiting.")
        return

    logger.info("Target trader: %s", target)

    # ------------------------------------------------------------------ #
    # 2. Initialise components                                            #
    # ------------------------------------------------------------------ #
    feed = TradeFeed(config)
    generator = SignalGenerator(config, target_username=target)
    executor = TradeExecutor(config)

    mode = "SIMULATION" if (config.dry_run or config.use_mock) else "LIVE"
    logger.warning(
        "Bot starting in %s mode | copy_amount=$%.2f | target=%s",
        mode,
        config.copy_amount_usd,
        target,
    )

    # ------------------------------------------------------------------ #
    # 3. Main loop                                                        #
    # ------------------------------------------------------------------ #
    try:
        async for trade in feed.stream():
            signal = generator.process(trade)
            if signal is None:
                continue

            result = await executor.execute(signal)
            if result.success:
                logger.info(
                    "Order accepted | order_id=%s simulated=%s",
                    result.order_id,
                    result.is_simulated,
                )
            else:
                logger.error("Order failed: %s", result.error)

    except asyncio.CancelledError:
        logger.info("Shutdown signal received. Stopping feed…")
    finally:
        feed.stop()
        logger.info("Bot stopped cleanly.")


def main() -> None:
    """Synchronous entry point; handles OS signals for graceful shutdown."""
    config = Config()
    setup_logging(config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    main_task: Optional[asyncio.Task] = None

    def _shutdown() -> None:
        logger.info("Shutdown requested.")
        if main_task and not main_task.done():
            main_task.cancel()

    for sig in (getattr(_signal, "SIGINT", None), getattr(_signal, "SIGTERM", None)):
        if sig is not None:
            try:
                loop.add_signal_handler(sig, _shutdown)
            except NotImplementedError:
                # Windows does not support add_signal_handler for all signals
                pass

    try:
        main_task = loop.create_task(run(config))
        loop.run_until_complete(main_task)
    except KeyboardInterrupt:
        _shutdown()
        if main_task:
            loop.run_until_complete(main_task)
    finally:
        loop.close()


if __name__ == "__main__":
    main()
