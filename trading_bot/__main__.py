"""
Entry point: load .env BEFORE importing Config so env vars are set in time.
"""
import os
from dotenv import load_dotenv

# Load the project-level .env (next to setup.py / requirements_bot.txt)
_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(os.path.abspath(_env_path), override=True)

from .main import main  # noqa: E402  (must come after load_dotenv)

main()
