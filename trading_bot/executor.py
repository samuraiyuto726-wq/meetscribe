"""
Trade executor – simulates (paper) or places (live) copy orders.

The simulation path is the default and safe to run immediately.
The real-execution path raises NotImplementedError until you wire in
your exchange's order API, so there is no accidental live trading.

RISK CHECKLIST before enabling live execution
---------------------------------------------
[ ] Tested end-to-end in simulation for at least several days
[ ] Tested on exchange testnet (separate API keys, virtual funds)
[ ] API key has trade permission only – NO withdrawal permission
[ ] copy_amount_usd is set to a value you can afford to lose in full
[ ] Daily / weekly loss limit implemented at a higher layer
[ ] Slippage budget understood for your chosen symbols
[ ] Exchange fee structure accounted for in profitability model
[ ] Bot can be killed instantly (Ctrl-C / kill signal handled in main)
"""
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
    executed_at: float
    is_simulated: bool
    error: Optional[str] = None


class TradeExecutor:
    def __init__(self, config) -> None:
        self.config = config

    async def execute(self, signal: Signal) -> ExecutionResult:
        if self.config.dry_run or self.config.use_mock:
            return self._simulate(signal)
        return await self._real_execute(signal)

    # ------------------------------------------------------------------ #
    # Simulation (paper trade)                                            #
    # ------------------------------------------------------------------ #

    def _simulate(self, signal: Signal) -> ExecutionResult:
        """
        Log the would-be order without touching any account.

        Quantity is derived from the fixed USD amount and the source
        trade's fill price.  In a real market-order scenario the actual
        fill price will differ; add slippage modelling here if you want
        more realistic simulation.
        """
        t = signal.trade
        qty = round(signal.copy_amount_usd / t.price, 6)
        order_id = f"sim_{int(time.time() * 1000)}"

        logger.info(
            "[SIM] %s %s %s qty=%.6f @ %.4f  notional=$%.2f  order_id=%s",
            t.side.upper(),
            t.symbol,
            "(leverage %dx)" % t.leverage if t.leverage > 1 else "",
            qty,
            t.price,
            signal.copy_amount_usd,
            order_id,
        )

        return ExecutionResult(
            signal=signal,
            success=True,
            order_id=order_id,
            executed_price=t.price,
            executed_at=time.time(),
            is_simulated=True,
        )

    # ------------------------------------------------------------------ #
    # Real execution stub                                                 #
    # ------------------------------------------------------------------ #

    async def _real_execute(self, signal: Signal) -> ExecutionResult:
        """
        WHERE REAL TRADE EXECUTION GOES.

        Steps to implement:
          1. Compute quantity from signal.copy_amount_usd / current_bid_ask
          2. Build the exchange-specific order payload
          3. Sign the request (HMAC or similar)
          4. POST to the order endpoint
          5. Parse the response and return an ExecutionResult

        Bybit V5 example (linear perpetuals):
        -----------------------------------------------
        import hmac, hashlib, time, aiohttp

        ts = str(int(time.time() * 1000))
        qty = str(round(signal.copy_amount_usd / signal.trade.price, 3))
        body = {
            "category": "linear",
            "symbol": signal.trade.symbol,
            "side": signal.trade.side.capitalize(),   # "Buy" | "Sell"
            "orderType": "Market",
            "qty": qty,
        }
        body_str = json.dumps(body)
        sign_str = ts + config.api_key + "5000" + body_str
        signature = hmac.new(
            config.api_secret.encode(), sign_str.encode(), hashlib.sha256
        ).hexdigest()
        headers = {
            "X-BAPI-API-KEY":   config.api_key,
            "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-SIGN":      signature,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=body) as r:
                resp = await r.json()
                ...
        -----------------------------------------------

        Remove the NotImplementedError and fill in the above once you are
        ready to go live.  Always test on testnet first.
        """
        raise NotImplementedError(
            "Live execution is not implemented. "
            "Set USE_MOCK=true or DRY_RUN=true to use paper trading."
        )
