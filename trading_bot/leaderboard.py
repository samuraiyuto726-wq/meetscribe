"""
Leaderboard module – fetches the public trader leaderboard and picks
the best-performing account to mirror.

HOW TO ADD A REAL EXCHANGE
--------------------------
1. Set USE_MOCK=false in your .env
2. Set LEADERBOARD_URL to the exchange's leaderboard endpoint
3. Set API_KEY / API_SECRET if the endpoint requires auth
4. Update _parse_response() to match the exchange's JSON shape
"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Type alias for the leaderboard entry structure expected internally
_TraderInfo = dict  # {"username": str, "pnl_30d": float, "win_rate": float}


class LeaderboardFetcher:
    def __init__(self, config) -> None:
        self.config = config

    async def fetch_top_trader(self) -> Optional[str]:
        """
        Return the username/ID of the top trader.

        If TARGET_USERNAME is set in config, it is returned immediately
        without touching any API – useful for backtesting a known trader.
        """
        if self.config.target_username:
            logger.info(
                "Using manually configured target: %s",
                self.config.target_username,
            )
            return self.config.target_username

        if self.config.use_mock:
            return await self._mock_fetch()
        return await self._real_fetch()

    # ------------------------------------------------------------------ #
    # Mock implementation                                                 #
    # ------------------------------------------------------------------ #

    async def _mock_fetch(self) -> str:
        await asyncio.sleep(0.05)  # simulate network round-trip
        leaderboard: list[_TraderInfo] = [
            {"username": "alpha_trader", "pnl_30d": 42.5, "win_rate": 0.68},
            {"username": "beta_scalper", "pnl_30d": 38.1, "win_rate": 0.72},
            {"username": "gamma_swing", "pnl_30d": 31.0, "win_rate": 0.61},
        ]
        top = max(leaderboard, key=lambda t: t["pnl_30d"])
        logger.info(
            "[MOCK] Top trader → %s  (30d PnL: %.1f%%  win-rate: %.0f%%)",
            top["username"],
            top["pnl_30d"],
            top["win_rate"] * 100,
        )
        return top["username"]

    # ------------------------------------------------------------------ #
    # Real implementation stub                                            #
    # ------------------------------------------------------------------ #

    async def _real_fetch(self) -> Optional[str]:
        """
        Fetch leaderboard from the configured exchange URL.

        Replace the _parse_response() method below to match your exchange.
        Common examples:
          • Bybit copy-trading master list:
              GET https://api.bybit.com/v5/copytrading/public/master-order
          • Binance leaderboard (unofficial):
              GET https://www.binance.com/bapi/futures/v3/public/future/leaderboard/getOtherLeaderboardBaseInfo
        """
        # aiohttp is listed in requirements_bot.txt
        try:
            import aiohttp
        except ImportError:
            logger.error("aiohttp not installed – run: pip install aiohttp")
            return None

        headers: dict[str, str] = {}
        if self.config.api_key:
            # ADAPT: your exchange's auth header name
            headers["X-API-Key"] = self.config.api_key

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.config.leaderboard_url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    return self._parse_response(data)

        except Exception as exc:  # network errors, auth failures, timeouts
            logger.error("Leaderboard fetch failed: %s", exc)
            return None

    def _parse_response(self, data: dict) -> Optional[str]:
        """
        ADAPT THIS to your exchange's response format.

        Bybit example:
            data["result"]["list"] → list of dicts with keys:
            "leaderId", "nickName", "roi", "pnl"

        Return the trader identifier (username or user-ID) of the top entry.
        """
        traders: list[dict] = data.get("result", {}).get("list", [])
        if not traders:
            logger.warning("Leaderboard returned 0 traders")
            return None
        top = max(traders, key=lambda t: float(t.get("pnl", 0)))
        return top.get("nickName") or top.get("leaderId")
