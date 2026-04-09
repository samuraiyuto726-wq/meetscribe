import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator, Optional

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    trade_id:     str
    proxy_wallet: str
    condition_id: str
    token_id:     str
    side:         str    # "BUY" or "SELL"
    price:        float  # 0.0-1.0
    size:         float  # shares
    usd_size:     float  # USDC value
    outcome:      str    # "Yes" or "No"
    title:        str
    timestamp:    float = field(default_factory=time.time)


class TradeFeed:
    def __init__(self, config) -> None:
        self.config = config
        self._running = False
        self._last_seen_id: Optional[str] = None
        self._check_count = 0

    async def stream(self, wallet: str) -> AsyncIterator[Trade]:
        self._running = True
        print(f"\n[BOT] ========================================", flush=True)
        print(f"[BOT] Polymarket Copy-Bot STARTED", flush=True)
        print(f"[BOT] Tracking wallet : {wallet}", flush=True)
        print(f"[BOT] Check interval  : every {self.config.poll_interval_seconds:.0f}s", flush=True)
        print(f"[BOT] ========================================\n", flush=True)

        while self._running:
            self._check_count += 1
            now = datetime.now().strftime("%H:%M:%S")
            print(f"[BOT] [{now}] Check #{self._check_count} — Checking Polymarket...", flush=True)

            try:
                new_trades = await self._fetch_new_trades(wallet)
                if new_trades:
                    print(f"[BOT] Found {len(new_trades)} new trade(s) from top trader!", flush=True)
                    for trade in new_trades:
                        print(f"[BOT] -------------------------------------------", flush=True)
                        print(f"[BOT] *** NEW TRADE DETECTED ***", flush=True)
                        print(f"[BOT]   Action  : {trade.side}", flush=True)
                        print(f"[BOT]   Outcome : {trade.outcome}", flush=True)
                        print(f"[BOT]   Price   : {trade.price:.3f} ({trade.price*100:.1f}% probability)", flush=True)
                        print(f"[BOT]   Size    : ${trade.usd_size:.2f} USDC", flush=True)
                        print(f"[BOT]   Market  : {trade.title[:70]}", flush=True)
                        print(f"[BOT] -------------------------------------------", flush=True)
                        yield trade
                else:
                    print(f"[BOT] No new trades. Waiting {self.config.poll_interval_seconds:.0f}s...\n", flush=True)

            except Exception as exc:
                print(f"[BOT] ERROR: {exc} — retrying next cycle\n", flush=True)
                logger.warning("Poll error: %s", exc)

            await asyncio.sleep(self.config.poll_interval_seconds)

    def stop(self) -> None:
        self._running = False

    async def _fetch_new_trades(self, wallet: str) -> list:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                self.config.activity_url,
                params={"user": wallet, "limit": self.config.activity_limit},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()
                raw = await resp.json()

        entries = raw if isinstance(raw, list) else raw.get("data", [])
        if not entries:
            return []

        newest_id = str(entries[0].get("id", ""))
        if self._last_seen_id is None:
            self._last_seen_id = newest_id
            print(f"[BOT] Started tracking from trade_id={newest_id}", flush=True)
            return []

        new_entries = []
        for e in entries:
            if str(e.get("id", "")) == self._last_seen_id:
                break
            new_entries.append(e)

        if new_entries:
            self._last_seen_id = str(new_entries[0].get("id", ""))

        return [t for t in (self._parse(e) for e in new_entries) if t]

    def _parse(self, e: dict) -> Optional[Trade]:
        try:
            return Trade(
                trade_id=str(e["id"]),
                proxy_wallet=e.get("proxyWallet", ""),
                condition_id=e.get("conditionId", ""),
                token_id=e.get("tokenId", ""),
                side=e.get("side", "BUY").upper(),
                price=float(e.get("price", 0)),
                size=float(e.get("size", 0)),
                usd_size=float(e.get("usdcSize", 0)),
                outcome=e.get("outcome", ""),
                title=e.get("title", e.get("market", "Unknown")),
            )
        except Exception:
            return None
