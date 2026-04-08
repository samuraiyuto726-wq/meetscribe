"""
Configuration for the Polymarket copy-trading bot.

All secrets come from environment variables.  Copy .env.example → .env
and fill in your values.  Never commit .env to version control.

Polymarket uses USDC on Polygon (chain ID 137).
Your wallet private key is required for signing orders.
"""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    # ------------------------------------------------------------------ #
    # Polymarket API endpoints (public – no auth needed for reads)        #
    # ------------------------------------------------------------------ #
    leaderboard_url: str = os.getenv(
        "LEADERBOARD_URL",
        "https://data-api.polymarket.com/leaderboard",
    )
    activity_url: str = os.getenv(
        "ACTIVITY_URL",
        "https://data-api.polymarket.com/activity",
    )
    clob_host: str = os.getenv(
        "CLOB_HOST",
        "https://clob.polymarket.com",
    )

    # ------------------------------------------------------------------ #
    # Wallet / auth (required for live trading)                          #
    # ------------------------------------------------------------------ #
    # Your Polygon wallet private key – NEVER commit this
    private_key: Optional[str] = os.getenv("PRIVATE_KEY")

    # Polygon chain ID: 137 = mainnet, 80002 = Amoy testnet
    chain_id: int = int(os.getenv("CHAIN_ID", "137"))

    # Polymarket proxy wallet address (auto-derived if left empty)
    proxy_wallet: Optional[str] = os.getenv("PROXY_WALLET")

    # ------------------------------------------------------------------ #
    # Strategy                                                            #
    # ------------------------------------------------------------------ #
    # Fixed USDC amount to spend per mirrored trade
    copy_amount_usd: float = float(os.getenv("COPY_AMOUNT_USD", "1.0"))

    # Leaderboard window: "1d" | "1w" | "1m" | "all"
    leaderboard_window: str = os.getenv("LEADERBOARD_WINDOW", "1m")

    # Override: skip leaderboard and always mirror this proxy wallet address
    target_wallet: Optional[str] = os.getenv("TARGET_WALLET")

    # ------------------------------------------------------------------ #
    # Polling                                                             #
    # ------------------------------------------------------------------ #
    # How often (seconds) to check the target's activity for new trades
    poll_interval_seconds: float = float(os.getenv("POLL_INTERVAL_SECONDS", "15"))

    # How many recent activity records to fetch per poll
    activity_limit: int = int(os.getenv("ACTIVITY_LIMIT", "20"))

    # ------------------------------------------------------------------ #
    # Safeguards                                                          #
    # ------------------------------------------------------------------ #
    max_signals_per_hour: int = int(os.getenv("MAX_SIGNALS_PER_HOUR", "10"))
    max_signals_per_day: int = int(os.getenv("MAX_SIGNALS_PER_DAY", "30"))

    # Ignore trades where implied probability is above this (too expensive)
    max_price: float = float(os.getenv("MAX_PRICE", "0.95"))

    # Ignore trades where implied probability is below this (too cheap / risky)
    min_price: float = float(os.getenv("MIN_PRICE", "0.05"))

    # How long (seconds) to remember a trade ID to prevent duplicates
    duplicate_window_seconds: int = int(
        os.getenv("DUPLICATE_WINDOW_SECONDS", "3600")
    )

    # ------------------------------------------------------------------ #
    # Execution mode                                                      #
    # ------------------------------------------------------------------ #
    # True → simulate locally, never touch the CLOB
    dry_run: bool = os.getenv("DRY_RUN", "true").lower() == "true"

    # ------------------------------------------------------------------ #
    # Logging                                                             #
    # ------------------------------------------------------------------ #
    log_file: str = os.getenv("LOG_FILE", "trading_bot.log")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
