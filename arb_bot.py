"""
Polymarket Same-Market Arbitrage Bot

Scans all active binary markets every 60 seconds.
When YES_ask + NO_ask < 0.96, buys both sides for guaranteed profit.

Run: py arb_bot.py
"""
import asyncio
import logging
import os
import sys
import time
from typing import Optional

asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

os.environ['PROXY_WALLET'] = '0xa1823f3BacCEEF4e4358Af25D2686A03cEe930f5'
os.environ['CHAIN_ID']     = '137'

with open(r'C:\Users\glmar\.env') as f:
    for line in f:
        line = line.strip()
        if line.startswith('PRIVATE_KEY='):
            os.environ['PRIVATE_KEY'] = line.split('=', 1)[1]

sys.path.insert(0, r'C:\Users\glmar\meetscribe')

import aiohttp

# ── Config ────────────────────────────────────────────────────────────────────
CLOB_HOST     = "https://clob.polymarket.com"
THRESHOLD     = 0.96   # Arb fires when YES ask + NO ask < this
TOTAL_BET_USD = 1.00   # Total USD per arb trade (split equally between YES and NO)
SCAN_INTERVAL = 60     # Seconds between full market scans
DRY_RUN       = False  # True = simulate only, no real orders

PRIVATE_KEY  = os.environ.get('PRIVATE_KEY', '')
PROXY_WALLET = os.environ.get('PROXY_WALLET', '')
CHAIN_ID     = int(os.environ.get('CHAIN_ID', '137'))

# ── State ─────────────────────────────────────────────────────────────────────
placed_arbs: set = set()  # condition_ids already acted on

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("arb_bot.log", mode="a"),
    ],
)
log = logging.getLogger("arb_bot")


# ── CLOB client ───────────────────────────────────────────────────────────────

def get_client():
    from py_clob_client.client import ClobClient
    if PROXY_WALLET:
        client = ClobClient(
            host=CLOB_HOST,
            key=PRIVATE_KEY,
            chain_id=CHAIN_ID,
            signature_type=2,
            funder=PROXY_WALLET,
        )
    else:
        client = ClobClient(host=CLOB_HOST, key=PRIVATE_KEY, chain_id=CHAIN_ID)
    client.set_api_creds(client.create_or_derive_api_creds())
    return client


def place_order(client, token_id: str, price: float, shares: float) -> dict:
    from py_clob_client.clob_types import OrderArgs
    order_args = OrderArgs(
        token_id=token_id,
        price=round(price, 4),
        size=round(shares, 4),
        side="BUY",
    )
    return client.create_and_post_order(order_args)


# ── Market scanning ───────────────────────────────────────────────────────────

async def fetch_markets(session: aiohttp.ClientSession) -> list:
    """Fetch all active binary markets from Polymarket."""
    markets = []
    next_cursor = ""
    while True:
        params = {"next_cursor": next_cursor} if next_cursor else {}
        async with session.get(
            f"{CLOB_HOST}/markets",
            params=params,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            data = await resp.json()
        for m in data.get("data", []):
            tokens = m.get("tokens", [])
            if (
                len(tokens) == 2
                and m.get("active")
                and not m.get("closed")
                and m.get("enable_order_book")
            ):
                markets.append(m)
        next_cursor = data.get("next_cursor", "")
        if not next_cursor or next_cursor == "LTE=":
            break
        await asyncio.sleep(0.2)
    return markets


async def get_best_ask(session: aiohttp.ClientSession, token_id: str) -> Optional[float]:
    """Return the lowest ask price for a token, or None if no asks exist."""
    async with session.get(
        f"{CLOB_HOST}/book",
        params={"token_id": token_id},
        timeout=aiohttp.ClientTimeout(total=10),
    ) as resp:
        data = await resp.json()
    asks = data.get("asks", [])
    if not asks:
        return None
    return float(asks[0]["price"])


# ── Core scan loop ────────────────────────────────────────────────────────────

async def scan_and_arb(client) -> None:
    async with aiohttp.ClientSession() as session:
        log.info("Scanning all Polymarket markets...")
        try:
            markets = await fetch_markets(session)
        except Exception as exc:
            log.error(f"Failed to fetch markets: {exc}")
            return

        log.info(f"Found {len(markets)} active binary markets — checking prices...")
        opportunities = 0

        for m in markets:
            condition_id = m.get("condition_id", "")
            if condition_id in placed_arbs:
                continue

            tokens = m.get("tokens", [])
            yes_token = next((t for t in tokens if t.get("outcome", "").upper() == "YES"), None)
            no_token  = next((t for t in tokens if t.get("outcome", "").upper() == "NO"),  None)
            if not yes_token or not no_token:
                continue

            try:
                yes_ask = await get_best_ask(session, yes_token["token_id"])
                no_ask  = await get_best_ask(session, no_token["token_id"])
                await asyncio.sleep(0.05)  # stay within API rate limits
            except Exception:
                continue

            if yes_ask is None or no_ask is None:
                continue

            # Filter out extreme prices — very low prices mean illiquid or near-resolved
            if yes_ask < 0.02 or no_ask < 0.02:
                continue
            if yes_ask > 0.98 or no_ask > 0.98:
                continue

            total = yes_ask + no_ask
            if total >= THRESHOLD:
                continue

            # ── Arb opportunity found ─────────────────────────────────────
            opportunities += 1
            profit_usd  = TOTAL_BET_USD * (1.0 / total - 1.0)
            profit_pct  = (1.0 - total) * 100
            shares      = TOTAL_BET_USD / total  # equal shares on each side

            log.info(f"\n{'='*60}")
            log.info(f"[ARB FOUND #{opportunities}] {m.get('question', '')[:70]}")
            log.info(f"  YES ask : {yes_ask:.4f}")
            log.info(f"  NO  ask : {no_ask:.4f}")
            log.info(f"  Sum     : {total:.4f}  (gap = {profit_pct:.2f}%)")
            log.info(f"  Shares  : {shares:.4f} on each side")
            log.info(f"  Cost    : ${TOTAL_BET_USD:.2f}  |  Payout: ${shares:.4f}  |  Profit: ${profit_usd:.4f}")

            if DRY_RUN:
                log.info(f"  [DRY RUN] Skipping real orders.")
                placed_arbs.add(condition_id)
                continue

            # Place YES leg
            try:
                yes_resp = place_order(client, yes_token["token_id"], yes_ask, shares)
                yes_id   = yes_resp.get("orderID") or yes_resp.get("id", "unknown")
                log.info(f"  [LIVE] YES order placed — id={yes_id}")
            except Exception as exc:
                log.error(f"  [ERROR] YES order failed: {exc} — skipping this arb")
                continue

            # Place NO leg
            try:
                no_resp = place_order(client, no_token["token_id"], no_ask, shares)
                no_id   = no_resp.get("orderID") or no_resp.get("id", "unknown")
                log.info(f"  [LIVE] NO order placed  — id={no_id}")
            except Exception as exc:
                log.error(f"  [ERROR] NO order failed: {exc}")
                log.error(f"  [WARNING] YES leg placed but NO leg failed — check Polymarket manually!")
                placed_arbs.add(condition_id)
                continue

            placed_arbs.add(condition_id)
            log.info(f"  [COMPLETE] Locked in ${profit_usd:.4f} profit — waiting for market to resolve.")

        if opportunities == 0:
            log.info("No arb opportunities this scan.")
        else:
            log.info(f"\nScan complete — {opportunities} arb(s) placed.")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    log.info("\n" + "="*60)
    log.info("[ARB BOT] Polymarket Same-Market Arbitrage Bot")
    log.info(f"[ARB BOT] Threshold  : YES+NO ask < {THRESHOLD}")
    log.info(f"[ARB BOT] Bet size   : ${TOTAL_BET_USD:.2f} total per arb")
    log.info(f"[ARB BOT] Mode       : {'DRY RUN (no real orders)' if DRY_RUN else 'LIVE'}")
    log.info(f"[ARB BOT] Scan every : {SCAN_INTERVAL}s")
    log.info("="*60 + "\n")

    client = None
    if not DRY_RUN:
        try:
            client = get_client()
            log.info("[ARB BOT] CLOB client ready.\n")
        except Exception as exc:
            log.error(f"[ARB BOT] Could not init CLOB client: {exc}")
            return

    scan_num = 0
    while True:
        scan_num += 1
        log.info(f"\n[SCAN #{scan_num}] {time.strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            await scan_and_arb(client)
        except Exception as exc:
            log.error(f"Scan error: {exc}")
        log.info(f"Waiting {SCAN_INTERVAL}s until next scan...")
        await asyncio.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
