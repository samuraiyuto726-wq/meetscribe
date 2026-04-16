"""
Multi-wallet test: watch top-10 Polymarket monthly leaderboard traders,
copy the FIRST trade any of them places, then stop.

Run on Windows:
    py C:\Users\glmar\test_multi_wallet.py
"""
import asyncio
import os
import re
import sys

# Windows requires this event loop policy for aiohttp
asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ── env vars ──────────────────────────────────────────────────────────────────
os.environ['PROXY_WALLET']          = '0xa1823f3BacCEEF4e4358Af25D2686A03cEe930f5'
os.environ['DRY_RUN']               = 'false'
os.environ['CHAIN_ID']              = '137'
os.environ['COPY_AMOUNT_USD']       = '1.0'
os.environ['POLL_INTERVAL_SECONDS'] = '5'
os.environ['MIN_PRICE']             = '0.01'   # wide band so we catch more trades
os.environ['MAX_PRICE']             = '0.99'
os.environ['MAX_SIGNALS_PER_HOUR']  = '100'
os.environ['MAX_SIGNALS_PER_DAY']   = '100'

with open(r'C:\Users\glmar\.env') as f:
    for line in f:
        line = line.strip()
        if line.startswith('PRIVATE_KEY='):
            os.environ['PRIVATE_KEY'] = line.split('=', 1)[1]

sys.path.insert(0, r'C:\Users\glmar\meetscribe')

import aiohttp
from trading_bot.config import Config
from trading_bot.feed import TradeFeed
from trading_bot.signal_generator import SignalGenerator
from trading_bot.executor import TradeExecutor

FALLBACK_WALLETS = [
    "0x492442eab586f242b53bda933fd5de859c8a3782",
]


async def fetch_top10() -> list:
    """Scrape top-10 proxy wallets from the Polymarket monthly leaderboard."""
    url = "https://polymarket.com/leaderboard"
    hdrs = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(
                url, headers=hdrs, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                resp.raise_for_status()
                html = await resp.text()

        raw = re.findall(r'"proxyWallet"\s*:\s*"(0x[a-fA-F0-9]{40,})"', html)
        seen, unique = set(), []
        for w in raw:
            wl = w.lower()
            if wl not in seen:
                seen.add(wl)
                unique.append(w)

        top10 = unique[:10]
        if top10:
            print(f"\n[LEADERBOARD] Top {len(top10)} monthly wallets found:")
            for i, w in enumerate(top10, 1):
                print(f"  #{i}: {w}")
            return top10

    except Exception as exc:
        print(f"[LEADERBOARD] Scrape failed: {exc}")

    print("[LEADERBOARD] Using fallback wallet list.")
    return FALLBACK_WALLETS


async def watch_one_wallet(wallet: str, config: Config, executor: TradeExecutor):
    """
    Poll a single wallet forever until a new trade is detected.
    Execute it and return the ExecutionResult.
    """
    feed = TradeFeed(config)
    gen  = SignalGenerator(config, target_wallet=wallet)

    # stream() is an infinite async generator; we break out on first signal
    async for trade in feed.stream(wallet):
        signal = gen.process(trade)
        if signal is None:
            continue

        print(f"\n[HIT] New trade from wallet {wallet[:20]}...")
        result = await executor.execute(signal)
        feed.stop()   # tell the generator to exit cleanly
        return result

    return None   # only reached if feed.stop() was called externally


async def main():
    config   = Config()
    wallets  = await fetch_top10()
    executor = TradeExecutor(config)

    print(
        f"\n[TEST] Polling {len(wallets)} wallets every "
        f"{config.poll_interval_seconds:.0f}s"
    )
    print("[TEST] Will copy ONE trade from ANY of them, then stop.\n")

    tasks = [
        asyncio.create_task(watch_one_wallet(w, config, executor))
        for w in wallets
    ]

    # Block until the first watcher task finishes (= first trade copied)
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    # Cancel every other watcher
    for t in pending:
        t.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    result = list(done)[0].result()

    print("\n" + "=" * 60)
    if result and result.success:
        label = "[SIM]" if result.is_simulated else "[LIVE]"
        sig   = result.signal
        print(f"SUCCESS!  {label} BET COPIED!")
        print(f"  Market  : {sig.trade.title[:70]}")
        print(f"  Outcome : {sig.trade.outcome}")
        print(f"  Price   : {sig.trade.price * 100:.1f}% probability")
        print(f"  Amount  : ${sig.copy_amount_usd:.2f} USDC")
        print(f"  OrderID : {result.order_id}")
        print("=" * 60)
        print("\nTest PASSED. Bot can detect and copy trades from leaderboard traders.")
        print("\nNow go back to run_bot.py which tracks only:")
        print("  0x492442eab586f242b53bda933fd5de859c8a3782")
    elif result:
        print(f"FAILED — trade detected but order failed: {result.error}")
        print("=" * 60)
    else:
        print("No trade was detected before the script stopped.")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
