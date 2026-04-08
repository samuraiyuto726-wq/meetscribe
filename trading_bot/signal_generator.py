"""
Signal generator – watches the trade stream and emits copy-trade signals
for the target trader, with three layers of safeguards:

  1. Duplicate prevention – each trade_id is remembered for a configurable
     window so a re-delivered event never produces two signals.
  2. Per-minute rate limit – caps burst activity.
  3. Per-hour rate limit  – caps sustained activity.
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
    """A decision to mirror a specific trade with a fixed USD amount."""

    trade: Trade
    copy_amount_usd: float
    generated_at: float = field(default_factory=time.time)

    def __str__(self) -> str:
        t = self.trade
        return (
            f"SIGNAL | {t.side.upper()} {t.symbol} "
            f"| ${self.copy_amount_usd:.2f} "
            f"| source={t.username} price={t.price:.4f} "
            f"| trade_id={t.trade_id}"
        )


class SignalGenerator:
    """
    Filters the trade stream for the target trader and produces Signals.

    Parameters
    ----------
    config       : Config instance
    target_username : username / ID to mirror (from leaderboard or env)
    """

    def __init__(self, config, target_username: str) -> None:
        self.config = config
        self.target_username = target_username

        # Sliding-window rate limiters
        self._per_minute = RateLimiter(
            max_calls=config.max_signals_per_minute,
            period_seconds=60,
        )
        self._per_hour = RateLimiter(
            max_calls=config.max_signals_per_hour,
            period_seconds=3600,
        )

        # Duplicate store: trade_id → monotonic timestamp when first seen
        self._seen: dict[str, float] = {}

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def process(self, trade: Trade) -> Optional[Signal]:
        """
        Evaluate a trade event.

        Returns a Signal if the event should be mirrored, otherwise None.
        All rejection reasons are logged at WARNING level.
        """
        if trade.username != self.target_username:
            return None  # not our trader – silent skip

        logger.info(
            "Target trade detected: %s %s %s %s @ %.4f (id=%s)",
            trade.username,
            trade.side.upper(),
            trade.size,
            trade.symbol,
            trade.price,
            trade.trade_id,
        )

        # Safeguard 1: duplicate prevention
        if self._is_duplicate(trade):
            logger.warning("Duplicate trade skipped: %s", trade.trade_id)
            return None

        # Safeguard 2: per-minute cap
        if not self._per_minute.is_allowed():
            logger.warning(
                "Per-minute rate limit hit. Signal dropped for trade_id=%s "
                "(remaining this minute: 0 / %d)",
                trade.trade_id,
                self.config.max_signals_per_minute,
            )
            return None

        # Safeguard 3: per-hour cap
        if not self._per_hour.is_allowed():
            logger.warning(
                "Per-hour rate limit hit. Signal dropped for trade_id=%s "
                "(limit: %d/hr)",
                trade.trade_id,
                self.config.max_signals_per_hour,
            )
            return None

        self._record(trade)
        signal = Signal(trade=trade, copy_amount_usd=self.config.copy_amount_usd)
        logger.info("%s", signal)
        return signal

    # ------------------------------------------------------------------ #
    # Internal helpers                                                    #
    # ------------------------------------------------------------------ #

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
