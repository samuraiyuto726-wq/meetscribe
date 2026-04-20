"""
Multi-wallet test: watch top-10 Polymarket monthly leaderboard traders,
copy the first 2 trades any of them place, then stop.

Run on Windows:
    py C:\Users\glmar\test_multi_wallet.py
"""
import asyncio
import os
import re
import sys

asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

os.environ['PROXY_WALLET']          = '0xa1823f3BacCEEF4e4358Af25D2686A03cEe930f5'
os.environ['DRY_RUN']               = 'false'
os.environ['CHAIN_ID']              = '137'
os.environ['COPY_AMOUNT_USD']       = '1.0'
os.environ['POLL_INTERVAL_SECONDS'] = '5'
os.environ['MIN_PRICE']             = '0.01'
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
    "0x2a2c53bd278c04da9962fcf96490e17f3dfb9bc1",
    "0x2005d16a84ceefa912d4e380cd32e7ff827875ea",
]

TARGET_BETS = 2   # stop after this many successful bets


async def fetch_top10() -> list:
    url = "https://polymarket.com/leaderboard"
    hdrs = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, headers=hdrs, timeout=aiohttp.ClientTimeout(total=20)) as resp:
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


async def watch_one_wallet(wallet, config, executor, result_queue, stop_event):
    feed = TradeFeed(config)
    gen  = SignalGenerator(config, target_wallet=wallet)
    async for trade in feed.stream(wallet):
        if stop_event.is_set():
            feed.stop()
            return
        signal = gen.process(trade)
        if signal is None:
            continue
        print(f"\n[HIT] New trade from wallet {wallet[:20]}...")
        result = await executor.execute(signal)
        await result_queue.put(result)
        await asyncio.sleep(0)  # yield so main loop can set stop_event before next trade


async def main():
    config   = Config()
    wallets  = await fetch_top10()
    executor = TradeExecutor(config)

    print(f"\n[TEST] Polling {len(wallets)} wallets every {config.poll_interval_seconds:.0f}s")
    print(f"[TEST] Will copy {TARGET_BETS} trades then stop.\n")

    result_queue = asyncio.Queue()
    stop_event   = asyncio.Event()

    tasks = [
        asyncio.create_task(watch_one_wallet(w, config, executor, result_queue, stop_event))
        for w in wallets
    ]

    successes = 0
    bet_num   = 0

    while successes < TARGET_BETS:
        result  = await result_queue.get()
        bet_num += 1
        sig     = result.signal

        print("\n" + "=" * 60)
        if result.success:
            successes += 1
            label = "[SIM]" if result.is_simulated else "[LIVE]"
            print(f"BET {successes}/{TARGET_BETS} COPIED!  {label}")
            print(f"  Market  : {sig.trade.title[:70]}")
            print(f"  Outcome : {sig.trade.outcome}")
            print(f"  Price   : {sig.trade.price * 100:.1f}%")
            print(f"  Shares  : 5")
            print(f"  OrderID : {result.order_id}")
            if successes >= TARGET_BETS:
                stop_event.set()  # stop watchers immediately
        else:
            print(f"BET {bet_num} FAILED: {result.error}")
        print("=" * 60)

    # Done — stop all watchers
    stop_event.set()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    print(f"\nTest PASSED. Bot successfully copied {TARGET_BETS} trades.")
    print("Now go back to run_bot.py which tracks only 0x492442...")


if __name__ == "__main__":
    asyncio.run(main())
