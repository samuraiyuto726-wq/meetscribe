"""
Trade feed module – streams live trades from an exchange.

In mock mode it generates synthetic trades internally so you can run
the full bot loop without any network connection.

HOW TO SWITCH TO A REAL FEED
-----------------------------
1. Set USE_MOCK=false and TRADE_FEED_URL=wss://<exchange>/... in your .env
2. Implement _parse_ws_message() for your exchange's message format
3. Update the subscription payload in _real_stream() if needed
"""
import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """Normalised representation of a single trade event."""

    trade_id: str
    username: str       # trader who placed the order
    symbol: str         # e.g. "BTCUSDT"
    side: str           # "buy" or "sell"
    size: float         # base-asset quantity
    price: float        # execution price in quote asset (usually USD)
    timestamp: float = field(default_factory=time.time)
    leverage: int = 1
    order_type: str = "market"  # "market" | "limit"


class TradeFeed:
    """
    Async trade-event stream.

    Usage (within an async context):
        feed = TradeFeed(config)
        async for trade in feed.stream():
            process(trade)

    Call feed.stop() to break the loop cleanly.
    """

    def __init__(self, config) -> None:
        self.config = config
        self._running = False

    async def stream(self) -> AsyncIterator[Trade]:
        self._running = True
        if self.config.use_mock:
            async for trade in self._mock_stream():
                yield trade
        else:
            async for trade in self._real_stream():
                yield trade

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------ #
    # Mock stream                                                         #
    # ------------------------------------------------------------------ #

    async def _mock_stream(self) -> AsyncIterator[Trade]:
        """
        Yields realistic-looking synthetic trades.

        The target trader ("alpha_trader" by default) appears roughly
        20 % of the time so signal events are clearly distinguishable
        in logs without flooding them.
        """
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
        all_users = [
            "alpha_trader",   # ← default leaderboard winner
            "beta_scalper",
            "gamma_swing",
            "random_user_1",
            "random_user_2",
        ]
        # Rough mid-prices (mocked, not real-time)
        ref_prices: dict[str, float] = {
            "BTCUSDT": 65_000.0,
            "ETHUSDT": 3_200.0,
            "SOLUSDT": 140.0,
            "BNBUSDT": 580.0,
        }

        counter = 0
        while self._running:
            # Vary cadence: ~1–3 trades per second to simulate a busy feed
            await asyncio.sleep(random.uniform(0.4, 1.5))

            symbol = random.choice(symbols)
            # Weight the target trader higher so signals appear within seconds
            username = random.choices(
                all_users, weights=[30, 20, 20, 15, 15], k=1
            )[0]

            mid = ref_prices[symbol]
            price = round(mid * random.uniform(0.9985, 1.0015), 2)

            trade = Trade(
                trade_id=f"mock_{counter:07d}",
                username=username,
                symbol=symbol,
                side=random.choice(["buy", "sell"]),
                size=round(random.uniform(0.001, 0.05), 5),
                price=price,
                leverage=random.choice([1, 2, 5, 10]),
            )
            counter += 1
            logger.debug(
                "[FEED] %s | %s %s %s @ %.2f",
                trade.username,
                trade.side.upper(),
                trade.size,
                trade.symbol,
                trade.price,
            )
            yield trade

    # ------------------------------------------------------------------ #
    # Real WebSocket stream                                               #
    # ------------------------------------------------------------------ #

    async def _real_stream(self) -> AsyncIterator[Trade]:
        """
        Connects to a WebSocket trade feed with automatic reconnection.

        Default subscription payload is formatted for Bybit V5 linear
        perpetuals.  Adjust the 'args' list and _parse_ws_message() for
        other exchanges (Binance, OKX, etc.).

        Requires:  pip install websockets
        """
        try:
            import websockets
        except ImportError:
            logger.error("websockets not installed – run: pip install websockets")
            return

        reconnect_delay = 2.0

        while self._running:
            try:
                async with websockets.connect(
                    self.config.trade_feed_url,
                    ping_interval=20,
                    ping_timeout=10,
                ) as ws:
                    # ADAPT: your exchange's subscription message
                    sub_msg = json.dumps({
                        "op": "subscribe",
                        "args": [
                            "publicTrade.BTCUSDT",
                            "publicTrade.ETHUSDT",
                            "publicTrade.SOLUSDT",
                        ],
                    })
                    await ws.send(sub_msg)
                    logger.info("Connected to trade feed: %s", self.config.trade_feed_url)
                    reconnect_delay = 2.0  # reset backoff on successful connect

                    async for raw in ws:
                        if not self._running:
                            return
                        trade = self._parse_ws_message(raw)
                        if trade:
                            yield trade

            except Exception as exc:
                logger.warning(
                    "Trade feed disconnected: %s. Reconnecting in %.0fs…",
                    exc,
                    reconnect_delay,
                )
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60.0)  # exponential cap

    def _parse_ws_message(self, raw: str) -> Optional[Trade]:
        """
        ADAPT THIS to your exchange's wire format.

        Bybit V5 public trade message example:
        {
          "topic": "publicTrade.BTCUSDT",
          "type": "snapshot",
          "data": [{
            "T": 1672304486865,   ← timestamp ms
            "s": "BTCUSDT",       ← symbol
            "S": "Buy",           ← side
            "v": "0.001",         ← size
            "p": "16578.50",      ← price
            "i": "2290000000067"  ← trade id
          }]
        }

        NOTE: Public trade feeds do NOT include the trader's username.
        To identify a specific trader you typically need a copy-trading
        or social-trading endpoint, or a private account WebSocket.
        Update this method once you know your exchange's data shape.
        """
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("Non-JSON message ignored: %s", raw[:120])
            return None

        data_list = msg.get("data", [])
        if not data_list:
            return None

        entry = data_list[0]
        try:
            return Trade(
                trade_id=str(entry["i"]),
                username=entry.get("uid", "unknown"),  # add trader ID if available
                symbol=entry["s"],
                side=entry["S"].lower(),
                size=float(entry["v"]),
                price=float(entry["p"]),
                timestamp=entry["T"] / 1000,
            )
        except KeyError as exc:
            logger.debug("Unexpected message shape, missing key %s: %s", exc, entry)
            return None
