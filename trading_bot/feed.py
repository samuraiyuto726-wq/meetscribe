"""
Trade feed for Polymarket – polls the activity endpoint periodically.

Polymarket does NOT expose a public WebSocket feed for individual trader
activity, so we use a REST polling loop instead.

Endpoint:
  GET https://data-api.polymarket.com/activity
      ?user=<proxy_wallet>
      &limit=20

Response shape (approximate):
  [
    {
      "id": "trade_abc123",
      "proxyWallet": "0x...",
      "conditionId": "0xmarketid...",
      "tokenId": "12345678...",      # outcome token address/ID
      "side": "BUY",                 # or "SELL"
      "price": "0.65",               # probability (0–1)
      "size": "100",                 # shares
      "usdcSize": "65.00",           # USD value
      "outcome": "Yes",              # "Yes" or "No"
      "title": "Will X happen?",     # market question
      "timestamp": "2024-01-01T12:00:00Z"
    },
    ...
  ]

NOTE: The API returns the most recent trades first.  We remember the
last-seen trade ID and only yield trades newer than that on each poll.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """Normalised Polymarket trade event."""

    trade_id: str
    proxy_wallet: str       # trader's proxy wallet address
    condition_id: str       # Polymarket market condition ID
    token_id: str           # outcome token ID (used for CLOB orders)
    side: str               # "BUY" or "SELL"
    price: float            # 0.0–1.0  (implied probability / share price)
    size: float             # number of shares
    usd_size: float         # USDC value of the trade
    outcome: str            # "Yes" or "No"
    title: str              # human-readable market question
    timestamp: float = field(default_factory=time.time)


class TradeFeed:
    """
    Polls Polymarket's activity endpoint for a given wallet address
    and yields new Trade events as an async generator.

    Usage:
        feed = TradeFeed(config)
        async for trade in feed.stream(wallet_address):
            ...
        feed.stop()
    """

    def __init__(self, config) -> None:
        self.config = config
        self._running = False
        self._last_seen_id: Optional[str] = None

    async def stream(self, wallet: str) -> AsyncIterator[Trade]:
        self._running = True
        logger.info(
            "Polling activity for %s every %.0fs",
            wallet,
            self.config.poll_interval_seconds,
        )

        while self._running:
            try:
                new_trades = await self._fetch_new_trades(wallet)
                for trade in new_trades:
                    yield trade
            except Exception as exc:
                logger.warning("Activity poll error: %s – retrying next cycle", exc)

            await asyncio.sleep(self.config.poll_interval_seconds)

    def stop(self) -> None:
        self._running = False

    async def _fetch_new_trades(self, wallet: str) -> list[Trade]:
        params = {
            "user": wallet,
            "limit": self.config.activity_limit,
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(
                self.config.activity_url,
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()
                raw: list = await resp.json()

        # Unwrap if the API wraps in {"data": [...]}
        entries: list = raw if isinstance(raw, list) else raw.get("data", [])

        if not entries:
            return []

        # On first poll, seed the cursor without yielding anything
        # so we don't replay old trades on startup.
        newest_id = str(entries[0].get("id", ""))
        if self._last_seen_id is None:
            self._last_seen_id = newest_id
            logger.info("Seeded activity cursor at trade_id=%s", newest_id)
            return []

        # Find all trades newer than the last cursor
        new_entries = []
        for entry in entries:
            entry_id = str(entry.get("id", ""))
            if entry_id == self._last_seen_id:
                break
            new_entries.append(entry)

        if new_entries:
            self._last_seen_id = str(new_entries[0].get("id", ""))
            logger.debug("Found %d new trade(s) for %s", len(new_entries), wallet)

        return [self._parse(e) for e in new_entries if self._parse(e) is not None]

    def _parse(self, entry: dict) -> Optional[Trade]:
        try:
            return Trade(
                trade_id=str(entry["id"]),
                proxy_wallet=entry.get("proxyWallet", ""),
                condition_id=entry.get("conditionId", ""),
                token_id=entry.get("tokenId", ""),
                side=entry.get("side", "BUY").upper(),
                price=float(entry.get("price", 0)),
                size=float(entry.get("size", 0)),
                usd_size=float(entry.get("usdcSize", 0)),
                outcome=entry.get("outcome", ""),
                title=entry.get("title", entry.get("market", "Unknown market")),
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.debug("Could not parse activity entry: %s | %s", exc, entry)
            return None
