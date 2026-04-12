"""
Trade executor – paper-trades or live-trades on Polymarket's CLOB.

Simulation (DRY_RUN=true, default)
------------------------------------
Logs the would-be order without touching any account or funds.

Live execution (DRY_RUN=false)
------------------------------------
Uses Polymarket's official Python client (py-clob-client) to:
  1. Initialise an API key from your wallet's private key
  2. Create a market-buy order for the outcome token
  3. Post it to the CLOB

RISK CHECKLIST before going live
---------------------------------
[ ] Ran in dry-run for several days and signals looked sensible
[ ] Wallet funded with USDC on Polygon (not Ethereum mainnet)
[ ] USDC approved for the CTF Exchange contract on Polygon
[ ] copy_amount_usd is money you can afford to lose entirely
[ ] Daily signal cap (max_signals_per_day) set conservatively
[ ] Tested with $1 per trade for at least a week before scaling up
[ ] Understood that prediction-market prices are extremely volatile
    near resolution and that copy-trading adds execution lag risk

HOW TO APPROVE USDC (one-time setup)
--------------------------------------
  from py_clob_client.client import ClobClient
  client = ClobClient(host, key=private_key, chain_id=137)
  client.set_api_creds(client.create_or_derive_api_creds())
  # Then approve the CTF Exchange to spend your USDC:
  client.approve_collateral()       # USDC → CTF Exchange
  client.approve_conditional_tokens()  # outcome tokens
"""
import json
import logging
import time
from dataclasses import dataclass
from typing import Optional

from .signal_generator import Signal

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    signal: Signal
    success: bool
    order_id: Optional[str]
    executed_price: Optional[float]
    shares_bought: Optional[float]
    executed_at: float
    is_simulated: bool
    error: Optional[str] = None


class TradeExecutor:
    def __init__(self, config) -> None:
        self.config = config
        self._clob_client = None  # initialised lazily on first live order

    async def execute(self, signal: Signal) -> ExecutionResult:
        if self.config.dry_run:
            return self._simulate(signal)
        return await self._live_execute(signal)

    # ------------------------------------------------------------------ #
    # Simulation                                                          #
    # ------------------------------------------------------------------ #

    def _simulate(self, signal: Signal) -> ExecutionResult:
        t = signal.trade
        # How many shares $1 buys at the current price
        shares = round(signal.copy_amount_usd / t.price, 4) if t.price > 0 else 0
        order_id = f"sim_{int(time.time() * 1000)}"

        logger.info(
            "[SIM] %s %s shares of \"%s\" (%s) @ %.3f  cost=$%.2f USDC  order_id=%s",
            t.side,
            shares,
            t.title[:50],
            t.outcome,
            t.price,
            signal.copy_amount_usd,
            order_id,
        )

        return ExecutionResult(
            signal=signal,
            success=True,
            order_id=order_id,
            executed_price=t.price,
            shares_bought=shares,
            executed_at=time.time(),
            is_simulated=True,
        )

    # ------------------------------------------------------------------ #
    # Live execution via py-clob-client                                   #
    # ------------------------------------------------------------------ #

    async def _live_execute(self, signal: Signal) -> ExecutionResult:
        """
        Place a real order on Polymarket's CLOB.

        Requirements:
          pip install py-clob-client
          PRIVATE_KEY set in your .env
          USDC approved (run the one-time approval steps in the module docstring)

        The client is initialised once and reused across calls.
        """
        try:
            client = self._get_client()
        except Exception as exc:
            return ExecutionResult(
                signal=signal, success=False, order_id=None,
                executed_price=None, shares_bought=None,
                executed_at=time.time(), is_simulated=False,
                error=f"Client init failed: {exc}",
            )

        t = signal.trade
        shares = round(signal.copy_amount_usd / t.price, 4)

        try:
            from py_clob_client.clob_types import OrderArgs, OrderType

            # py-clob-client ≥0.19 removed BUY/SELL constants; use strings directly
            side = "BUY" if t.side == "BUY" else "SELL"

            order_args = OrderArgs(
                token_id=t.token_id,
                price=round(t.price, 4),
                size=shares,
                side=side,
            )

            # create_and_post_order builds, signs, and submits in one call
            resp = client.create_and_post_order(order_args)

            order_id = resp.get("orderID") or resp.get("id", "unknown")
            logger.info(
                "[LIVE] Order placed | %s %s shares \"%s\" @ %.3f | order_id=%s",
                t.side, shares, t.title[:50], t.price, order_id,
            )

            return ExecutionResult(
                signal=signal,
                success=True,
                order_id=order_id,
                executed_price=t.price,
                shares_bought=shares,
                executed_at=time.time(),
                is_simulated=False,
            )

        except Exception as exc:
            logger.error("Order placement failed: %s", exc)
            return ExecutionResult(
                signal=signal, success=False, order_id=None,
                executed_price=None, shares_bought=None,
                executed_at=time.time(), is_simulated=False,
                error=str(exc),
            )

    def _get_client(self):
        """Lazily initialise and cache the ClobClient."""
        if self._clob_client is not None:
            return self._clob_client

        try:
            from py_clob_client.client import ClobClient
        except ImportError:
            raise RuntimeError(
                "py-clob-client not installed. Run: pip install py-clob-client"
            )

        if not self.config.private_key:
            raise RuntimeError(
                "PRIVATE_KEY is not set. Add it to your .env file."
            )

        # If PROXY_WALLET is set, sign as the proxy (signature_type=2).
        # This is needed when the funds live in a Polymarket proxy wallet
        # (created automatically when you log in via MetaMask on polymarket.com).
        if self.config.proxy_wallet:
            client = ClobClient(
                host=self.config.clob_host,
                key=self.config.private_key,
                chain_id=self.config.chain_id,
                signature_type=2,
                funder=self.config.proxy_wallet,
            )
            logger.info("Using proxy wallet signing (signature_type=2, funder=%s)", self.config.proxy_wallet)
        else:
            client = ClobClient(
                host=self.config.clob_host,
                key=self.config.private_key,
                chain_id=self.config.chain_id,
            )

        # Derive L2 API credentials from the wallet key (creates them if new)
        client.set_api_creds(client.create_or_derive_api_creds())

        self._clob_client = client
        logger.info("ClobClient initialised (chain_id=%d)", self.config.chain_id)
        return client
