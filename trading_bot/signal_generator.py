"""
Signal generator – filters the Polymarket activity feed for the target
wallet and emits copy-trade signals with safeguards:

  1. Duplicate prevention  – trade IDs are remembered to avoid re-firing
  2. Price filter          – skip trades outside your configured price band
  3. Per-hour rate limit   – caps how many signals fire in a rolling hour
  4. Per-day  rate limit   – caps total daily exposure
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from .feed import Trade
from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    """Decision to mirror a Polymarket trade with a fixed USDC amount."""

    trade: Trade
    copy_amount_usd: float      # USDC to spend
    generated_at: float = field(default_factory=time.time)

    def __str__(self) -> str:
        t = self.trade
        return (
            f"SIGNAL | {t.side} {t.outcome} @ {t.price:.3f} "
            f"| ${self.copy_amount_usd:.2f} USDC "
            f"| market: \"{t.title[:60]}\" "
            f"| trade_id={t.trade_id}"
        )


class SignalGenerator:
    def __init__(self, config, target_wallet: str) -> None:
        self.config = config
        self.target_wallet = target_wallet.lower()

        self._per_hour = RateLimiter(
            max_calls=config.max_signals_per_hour,
            period_seconds=3600,
        )
        self._per_day = RateLimiter(
            max_calls=config.max_signals_per_day,
            period_seconds=86400,
        )

        # trade_id → monotonic time when first seen
        self._seen: dict[str, float] = {}

    def process(self, trade: Trade) -> Optional[Signal]:
        """
        Evaluate a Polymarket trade event.
        Returns a Signal to mirror, or None with a logged reason.
        """
        # Filter: only care about the target wallet
        # (skip check when proxyWallet is absent from the API response,
        #  since the API was already queried with ?user=TARGET_WALLET)
        if trade.proxy_wallet and trade.proxy_wallet.lower() != self.target_wallet:
            return None

        logger.info(
            "Target trade detected | %s %s @ %.3f | $%.2f | \"%s\" | id=%s",
            trade.side,
            trade.outcome,
            trade.price,
            trade.usd_size,
            trade.title[:60],
            trade.trade_id,
        )

        # Safeguard 1: duplicate
        if self._is_duplicate(trade):
            logger.warning("Duplicate trade skipped: %s", trade.trade_id)
            return None

        # Safeguard 2: price band – avoid near-certain or near-impossible outcomes
        if not (self.config.min_price <= trade.price <= self.config.max_price):
            logger.warning(
                "Trade price %.3f outside band [%.2f, %.2f]. Skipped.",
                trade.price,
                self.config.min_price,
                self.config.max_price,
            )
            return None

        # Safeguard 3: per-hour cap
        if not self._per_hour.is_allowed():
            logger.warning(
                "Per-hour rate limit hit (%d/hr). Signal dropped for %s.",
                self.config.max_signals_per_hour,
                trade.trade_id,
            )
            return None

        # Safeguard 4: per-day cap
        if not self._per_day.is_allowed():
            logger.warning(
                "Per-day rate limit hit (%d/day). Signal dropped for %s.",
                self.config.max_signals_per_day,
                trade.trade_id,
            )
            return None

        self._record(trade)
        signal = Signal(trade=trade, copy_amount_usd=self.config.copy_amount_usd)
        logger.info("%s", signal)
        return signal

    def _is_duplicate(self, trade: Trade) -> bool:
        self._evict_expired()
        return trade.trade_id in self._seen

    def _record(self, trade: Trade) -> None:
        self._seen[trade.trade_id] = time.monotonic()

    def _evict_expired(self) -> None:
        cutoff = time.monotonic() - self.config.duplicate_window_seconds
        expired = [k for k, v in self._seen.items() if v < cutoff]
        for k in expired:
            del self._seen[k]
