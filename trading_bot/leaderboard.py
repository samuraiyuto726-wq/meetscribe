"""
Leaderboard module – fetches Polymarket's top traders and returns the
#1 wallet address to mirror.

Polymarket data API (no auth required):
  GET https://data-api.polymarket.com/leaderboard
      ?window=1m          # 1d | 1w | 1m | all
      &limit=10
      &offset=0

Response shape (approximate):
  [
    {
      "proxyWallet": "0xabc...",
      "name": "trader_display_name",   # may be empty
      "pnl": 12345.67,
      "volume": 50000.0,
      "rank": 1
    },
    ...
  ]
"""
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


class LeaderboardFetcher:
    def __init__(self, config) -> None:
        self.config = config

    async def fetch_top_trader(self) -> Optional[str]:
        """
        Return the proxy wallet address of the #1 ranked trader.

        If TARGET_WALLET is set in config it is returned immediately,
        skipping the API call.
        """
        if self.config.target_wallet:
            logger.info("Using manually configured target wallet: %s", self.config.target_wallet)
            return self.config.target_wallet

        return await self._fetch_from_api()

    async def _fetch_from_api(self) -> Optional[str]:
        params = {
            "window": self.config.leaderboard_window,
            "limit": 10,
            "offset": 0,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.config.leaderboard_url,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()

            return self._parse(data)

        except aiohttp.ClientError as exc:
            logger.error("Leaderboard fetch failed: %s", exc)
            return None

    def _parse(self, data: list | dict) -> Optional[str]:
        """
        Extract the #1 trader's proxy wallet from the API response.

        Polymarket returns a list sorted by rank ascending.  We take
        rank=1 (index 0) directly rather than re-sorting, so if the
        API ever changes sort order update this method.
        """
        # Response can be a list or wrapped in {"data": [...]}
        entries: list = data if isinstance(data, list) else data.get("data", [])

        if not entries:
            logger.warning("Leaderboard returned 0 entries")
            return None

        top = entries[0]
        wallet = top.get("proxyWallet") or top.get("address")
        name = top.get("name") or "(unnamed)"
        pnl = top.get("pnl", "?")
        volume = top.get("volume", "?")

        logger.info(
            "Leaderboard #1 → %s  name=%s  pnl=$%.2f  volume=$%.2f",
            wallet,
            name,
            float(pnl) if pnl != "?" else 0,
            float(volume) if volume != "?" else 0,
        )
        return wallet
