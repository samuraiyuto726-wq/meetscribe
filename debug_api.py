"""
Debug: prints the raw API response for the target wallet.
Run: py C:\Users\glmar\debug_api.py
"""
import asyncio, aiohttp, json
asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

WALLET = "0x492442eab586f242b53bda933fd5de859c8a3782"
URL    = "https://data-api.polymarket.com/activity"

async def main():
    async with aiohttp.ClientSession() as sess:
        async with sess.get(URL, params={"user": WALLET, "limit": 5},
                            timeout=aiohttp.ClientTimeout(total=10)) as resp:
            print("HTTP status:", resp.status)
            raw = await resp.json(content_type=None)

    entries = raw if isinstance(raw, list) else raw.get("data", [])
    print(f"Entries returned: {len(entries)}\n")

    for i, e in enumerate(entries):
        print(f"--- Entry {i+1} ---")
        print(f"  id       : {e.get('id', 'MISSING')}")
        print(f"  title    : {e.get('title', e.get('market', 'MISSING'))[:60]}")
        print(f"  side     : {e.get('side', 'MISSING')}")
        print(f"  price    : {e.get('price', 'MISSING')}")
        print(f"  usdcSize : {e.get('usdcSize', 'MISSING')}")
        print(f"  proxyWallet: {e.get('proxyWallet', 'MISSING')}")
        print()

    print("Raw keys in first entry:", list(entries[0].keys()) if entries else "NO ENTRIES")

asyncio.run(main())
