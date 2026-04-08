"""
Configuration for the copy-trading bot.

All settings are driven by environment variables so you can swap between
mock/testnet/live without touching code.  See .env.example for reference.
"""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    # ------------------------------------------------------------------ #
    # API endpoints – replace with real exchange URLs when ready          #
    # ------------------------------------------------------------------ #
    leaderboard_url: str = os.getenv(
        "LEADERBOARD_URL", "https://mock.api/leaderboard"
    )
    trade_feed_url: str = os.getenv(
        "TRADE_FEED_URL", "wss://mock.api/trades"
    )

    # ------------------------------------------------------------------ #
    # Authentication – never hard-code; always use env vars              #
    # ------------------------------------------------------------------ #
    api_key: Optional[str] = os.getenv("API_KEY")
    api_secret: Optional[str] = os.getenv("API_SECRET")

    # ------------------------------------------------------------------ #
    # Strategy                                                            #
    # ------------------------------------------------------------------ #
    # Fixed USD amount to risk per mirrored trade (paper default: $1)
    copy_amount_usd: float = float(os.getenv("COPY_AMOUNT_USD", "1.0"))

    # If set, skip leaderboard lookup and target this username directly
    target_username: Optional[str] = os.getenv("TARGET_USERNAME")

    # ------------------------------------------------------------------ #
    # Safeguards                                                          #
    # ------------------------------------------------------------------ #
    max_signals_per_minute: int = int(os.getenv("MAX_SIGNALS_PER_MINUTE", "5"))
    max_signals_per_hour: int = int(os.getenv("MAX_SIGNALS_PER_HOUR", "20"))

    # How long (seconds) to remember a trade_id for duplicate detection
    duplicate_window_seconds: int = int(
        os.getenv("DUPLICATE_WINDOW_SECONDS", "120")
    )

    # ------------------------------------------------------------------ #
    # Execution mode                                                      #
    # ------------------------------------------------------------------ #
    # True  → use internal mock data (no network required)
    use_mock: bool = os.getenv("USE_MOCK", "true").lower() == "true"

    # True  → log orders but never call the exchange (safe default)
    dry_run: bool = os.getenv("DRY_RUN", "true").lower() == "true"

    # ------------------------------------------------------------------ #
    # Logging                                                             #
    # ------------------------------------------------------------------ #
    log_file: str = os.getenv("LOG_FILE", "trading_bot.log")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
