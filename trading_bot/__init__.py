"""
trading_bot – copy-trade mirroring bot.

Quick start (simulation mode, no config needed):
    python -m trading_bot

See trading_bot/config.py and .env.example for all settings.
"""
from .config import Config
from .main import main, run

__all__ = ["Config", "main", "run"]
