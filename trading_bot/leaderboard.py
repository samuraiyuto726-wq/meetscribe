import json
import logging
import re
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# Updated manually – the current Polymarket #1 trader by monthly profit
FALLBACK_WALLET = "0x492442eab586f242b53bda933fd5de859c8a3782"


class LeaderboardFetcher:
    def __init__(self, config) -> None:
        self.config = config

    async def fetch_top_trader(self) -> Optional[str]:
        if self.config.target_wallet:
            logger.info("Using pinned target wallet: %s", self.config.target_wallet)
            return self.config.target_wallet
        return await self._scrape()

    async def _scrape(self) -> str:
        """
        Polymarket leaderboard is Next.js SSR – we pull the __NEXT_DATA__
        JSON blob embedded in the page HTML and extract proxyWallet values.
        Falls back to FALLBACK_WALLET if the page structure changes.
        """
        url = "https://polymarket.com/leaderboard"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    resp.raise_for_status()
                    html = await resp.text()

            # proxyWallet addresses appear in rank order in the page JSON
            wallets = re.findall(r'"proxyWallet"\s*:\s*"(0x[a-fA-F0-9]{40,})"', html)
            if wallets:
                logger.info("Scraped #1 wallet from leaderboard page: %s", wallets[0])
                return wallets[0]

            logger.warning("No proxyWallet found in page HTML – using fallback")

        except Exception as exc:
            logger.warning("Leaderboard scrape failed: %s – using fallback wallet", exc)

        logger.info("Fallback wallet: %s", FALLBACK_WALLET)
        return FALLBACK_WALLET
