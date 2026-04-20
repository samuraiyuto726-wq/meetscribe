"""
NBA Quarter-Tracking Copy Bot

Strategy:
- Track RN1's bets in Q1-Q3 per game
- In Q4: only bet on the team RN1 bet most, IF:
    * That team is winning
    * Lead is 10+ points
    * 8 minutes or less remaining
- Skip if RN1 bets tied or zero in Q1-Q3
- One bet per game max

Run: py C:\Users\glmar\run_nba_bot.py
"""
import asyncio, os, sys, re
from collections import defaultdict
from typing import Optional

asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

os.environ['PROXY_WALLET']          = '0xa1823f3BacCEEF4e4358Af25D2686A03cEe930f5'
os.environ['DRY_RUN']               = 'false'
os.environ['CHAIN_ID']              = '137'
os.environ['COPY_AMOUNT_USD']       = '1.0'
os.environ['POLL_INTERVAL_SECONDS'] = '1'
os.environ['MIN_PRICE']             = '0.01'
os.environ['MAX_PRICE']             = '0.99'
os.environ['MAX_SIGNALS_PER_HOUR']  = '999'
os.environ['MAX_SIGNALS_PER_DAY']   = '999'

with open(r'C:\Users\glmar\.env') as f:
    for line in f:
        line = line.strip()
        if line.startswith('PRIVATE_KEY='):
            os.environ['PRIVATE_KEY'] = line.split('=', 1)[1]

sys.path.insert(0, r'C:\Users\glmar\meetscribe')

import aiohttp
from trading_bot.config import Config
from trading_bot.feed import TradeFeed, Trade
from trading_bot.executor import TradeExecutor
from trading_bot.signal_generator import Signal

TARGET_WALLET = "0x2005d16a84ceefa912d4e380cd32e7ff827875ea"  # RN1
ESPN_URL      = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

NBA_KEYWORDS = [
    "nba", "lakers", "warriors", "celtics", "knicks", "nets", "heat", "bulls",
    "spurs", "bucks", "suns", "clippers", "nuggets", "jazz", "hawks", "76ers",
    "sixers", "raptors", "cavaliers", "cavs", "pistons", "pacers", "hornets",
    "magic", "wizards", "grizzlies", "pelicans", "thunder", "blazers", "kings",
    "timberwolves", "mavericks", "mavs", "rockets", "bobcats", "supersonics",
]

# Per-game state
bet_counts    = defaultdict(lambda: defaultdict(int))  # game_id -> {team: count}
last_trade    = {}   # game_id -> most recent Trade (for token_id)
placed_bets   = set()  # game_ids where Q4 bet already placed
monitoring    = set()  # game_ids being monitored in Q4


# ── NBA API ────────────────────────────────────────────────────────────────────

async def fetch_games() -> list:
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(ESPN_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
        games = []
        for event in data.get("events", []):
            comp       = event.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])
            status     = event.get("status", {})
            if len(competitors) < 2:
                continue
            home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
            away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
            home_score = int(home.get("score", 0) or 0)
            away_score = int(away.get("score", 0) or 0)
            games.append({
                "id":          event.get("id", ""),
                "home":        home.get("team", {}).get("displayName", ""),
                "home_short":  home.get("team", {}).get("shortDisplayName", ""),
                "away":        away.get("team", {}).get("displayName", ""),
                "away_short":  away.get("team", {}).get("shortDisplayName", ""),
                "home_score":  home_score,
                "away_score":  away_score,
                "quarter":     status.get("period", 0),
                "clock":       status.get("displayClock", "12:00"),
                "status":      status.get("type", {}).get("name", ""),
                "lead":        abs(home_score - away_score),
                "leader":      home.get("team", {}).get("shortDisplayName", "")
                               if home_score > away_score
                               else away.get("team", {}).get("shortDisplayName", "")
                               if away_score > home_score else "",
            })
        return games
    except Exception as exc:
        print(f"[NBA API] Error: {exc}")
        return []


def clock_minutes(clock: str) -> float:
    try:
        m, s = clock.split(":")
        return int(m) + int(s) / 60
    except:
        return 12.0


def match_game(title: str, games: list) -> Optional[dict]:
    tl = title.lower()
    for g in games:
        if g["status"] not in ("STATUS_IN_PROGRESS", "STATUS_HALFTIME"):
            continue
        home_words  = [w.lower() for w in g["home"].split() if len(w) > 3]
        away_words  = [w.lower() for w in g["away"].split() if len(w) > 3]
        home_short  = g["home_short"].lower()
        away_short  = g["away_short"].lower()
        home_match  = any(w in tl for w in home_words) or home_short in tl
        away_match  = any(w in tl for w in away_words) or away_short in tl
        if home_match and away_match:
            return g
    return None


def team_from_outcome(outcome: str, game: dict) -> Optional[str]:
    ol = outcome.lower()
    for key in ("home", "home_short", "away", "away_short"):
        name = game[key]
        words = [w.lower() for w in name.split() if len(w) > 3]
        short = name.lower().split()[-1]
        if any(w in ol for w in words) or short in ol:
            return game["home"] if "home" in key else game["away"]
    return None


def team_leading(game: dict, team: str) -> bool:
    tl = team.lower()
    leader = game["leader"].lower()
    return any(w in leader for w in tl.split() if len(w) > 3) or tl.split()[-1] in leader


# ── Q4 monitor ────────────────────────────────────────────────────────────────

async def monitor_and_bet(game_id: str, team: str, trade: Trade,
                          config: Config, executor: TradeExecutor):
    print(f"\n[Q4 MONITOR] Waiting: {team} must lead by 10+ pts with ≤8 min left")
    try:
        while True:
            games = await fetch_games()
            game  = next((g for g in games if g["id"] == game_id), None)

            if game is None or game["status"] == "STATUS_FINAL":
                print("[Q4 MONITOR] Game ended — conditions never met. Skipping.")
                break

            if game["quarter"] != 4:
                await asyncio.sleep(15)
                continue

            mins = clock_minutes(game["clock"])
            lead = game["lead"]
            winning = team_leading(game, team)

            print(f"[Q4 MONITOR] {game['clock']} | Lead:{lead}pts | {team} winning:{winning}")

            if not winning:
                print(f"[Q4 MONITOR] {team} is no longer winning. Abort.")
                break

            if lead < 10:
                print(f"[Q4 MONITOR] Lead {lead} pts — waiting for 10+...")
                await asyncio.sleep(20)
                continue

            if mins > 8:
                print(f"[Q4 MONITOR] {mins:.1f} min left — waiting for ≤8...")
                await asyncio.sleep(20)
                continue

            # ── All conditions met ──
            if game_id in placed_bets:
                break
            placed_bets.add(game_id)

            print(f"\n[Q4 BET] *** PLACING BET ***")
            print(f"  Team  : {team}")
            print(f"  Lead  : {lead} pts")
            print(f"  Clock : {game['clock']}")
            print(f"  Q1-Q3 : {dict(bet_counts[game_id])}")

            signal = Signal(trade=trade, copy_amount_usd=config.copy_amount_usd)
            result = await executor.execute(signal)

            if result.success:
                lbl = "[SIM]" if result.is_simulated else "[LIVE]"
                print(f"  {lbl} Order placed! id={result.order_id}")
            else:
                print(f"  [ERROR] {result.error}")
            break

    finally:
        monitoring.discard(game_id)


# ── Main loop ─────────────────────────────────────────────────────────────────

async def main():
    config   = Config()
    executor = TradeExecutor(config)
    feed     = TradeFeed(config)

    print("\n[NBA BOT] Quarter-tracking strategy | Target: RN1")
    print("[NBA BOT] Will only bet in Q4 when RN1's top team leads by 10+ pts ≤8 min left\n")

    async for trade in feed.stream(TARGET_WALLET):
        tl = trade.title.lower()

        # Only NBA moneyline markets (outcome should be a team name, not Yes/No/Over/Under)
        if not any(kw in tl for kw in NBA_KEYWORDS):
            continue
        if trade.outcome.lower() in ("yes", "no", "over", "under", ""):
            continue

        # Match to a live game
        games = await fetch_games()
        game  = match_game(trade.title, games)

        if game is None:
            print(f"[NBA] No live game matched for: {trade.title[:60]}")
            continue

        quarter = game["quarter"]
        team    = team_from_outcome(trade.outcome, game)

        if not team:
            print(f"[NBA] Can't identify team from outcome: '{trade.outcome}'")
            continue

        last_trade[game["id"]] = trade
        score_str = f"{game['away']} {game['away_score']}-{game['home_score']} {game['home']}"
        print(f"\n[NBA] Q{quarter} | RN1 → {team} | {score_str}")

        if quarter in (1, 2, 3):
            bet_counts[game["id"]][team] += 1
            print(f"[NBA] Counts so far: {dict(bet_counts[game['id']])}")

        elif quarter == 4:
            if game["id"] in placed_bets or game["id"] in monitoring:
                continue

            counts = bet_counts[game["id"]]

            if not counts:
                print("[NBA] Q4: Skip — RN1 made 0 bets in Q1-Q3")
                continue

            vals = sorted(counts.values(), reverse=True)
            if len(vals) >= 2 and vals[0] == vals[1]:
                print("[NBA] Q4: Skip — RN1 bets tied between teams")
                continue

            top_team = max(counts, key=counts.get)
            print(f"[NBA] Q4: RN1's top team is {top_team} — starting monitor")
            monitoring.add(game["id"])
            asyncio.create_task(
                monitor_and_bet(game["id"], top_team, trade, config, executor)
            )


if __name__ == "__main__":
    asyncio.run(main())
