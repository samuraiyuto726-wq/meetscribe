"""
Entry point for the Polymarket copy-trading bot.

Default (safe) run – simulation only, reads live Polymarket data:
    python -m trading_bot

Simulation with a pinned wallet (skip leaderboard):
    TARGET_WALLET=0x... python -m trading_bot

Live trading (after you've read executor.py's risk checklist):
    DRY_RUN=false PRIVATE_KEY=0x... python -m trading_bot
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
    # 1. Identify target trader from Polymarket leaderboard              #
    # ------------------------------------------------------------------ #
    fetcher = LeaderboardFetcher(config)
    target_wallet = await fetcher.fetch_top_trader()
    if not target_wallet:
        logger.error("Could not identify a target trader. Exiting.")
        return

    logger.info("Target wallet: %s", target_wallet)

    # ------------------------------------------------------------------ #
    # 2. Wire up components                                               #
    # ------------------------------------------------------------------ #
    feed = TradeFeed(config)
    generator = SignalGenerator(config, target_wallet=target_wallet)
    executor = TradeExecutor(config)

    mode = "DRY RUN (simulation)" if config.dry_run else "LIVE"
    logger.warning(
        "Bot starting | mode=%s | copy=$%.2f USDC | target=%s | poll=%.0fs",
        mode,
        config.copy_amount_usd,
        target_wallet,
        config.poll_interval_seconds,
    )

    # ------------------------------------------------------------------ #
    # 3. Poll loop                                                        #
    # ------------------------------------------------------------------ #
    try:
        async for trade in feed.stream(target_wallet):
            signal = generator.process(trade)
            if signal is None:
                continue

            result = await executor.execute(signal)

            if result.success:
                logger.info(
                    "Order accepted | order_id=%s | shares=%.4f | simulated=%s",
                    result.order_id,
                    result.shares_bought or 0,
                    result.is_simulated,
                )
            else:
                logger.error("Order failed: %s", result.error)

    except asyncio.CancelledError:
        logger.info("Shutdown signal received.")
    finally:
        feed.stop()
        logger.info("Bot stopped cleanly.")


def main() -> None:
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
                pass  # Windows

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
