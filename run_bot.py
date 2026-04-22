"""
RN1 Copy Bot — Multi-Sport Strategy

- Soccer:  BLOCKED
- Tennis:  RN1 bets 2+ times same player + price >= 75c
- NBA:     track Q1-Q3, bet Q4 when top team leads 10+ pts <=8 min
- NFL:     track Q1-Q3, bet Q4 when top team leads 14+ pts <=5 min
- NHL:     track P1-P2, bet P3 when top team leads 2+ goals <=10 min
- MLB:     track inn1-7, bet inn8+ when top team leads 4+ runs
- Other:   copy immediately
"""
import asyncio, os, sys
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
from trading_bot.signal_generator import Signal, SignalGenerator

TARGET_WALLET = "0x2005d16a84ceefa912d4e380cd32e7ff827875ea"  # RN1

# ── Sport conditions ──────────────────────────────────────────────────────────
# period = which period/quarter/inning to bet in
# min_lead = minimum score lead required
# max_mins = max minutes remaining (None = no clock needed e.g. MLB)
# early_periods = periods to track RN1 bets before final period
SPORT_CONDITIONS = {
    "nba": {"period": 4, "min_lead": 10, "max_mins": 8,    "early_periods": (1,2,3)},
    "nfl": {"period": 4, "min_lead": 14, "max_mins": 5,    "early_periods": (1,2,3)},
    "nhl": {"period": 3, "min_lead": 2,  "max_mins": 10,   "early_periods": (1,2)},
    "mlb": {"period": 8, "min_lead": 4,  "max_mins": None, "early_periods": tuple(range(1,8))},
}

TENNIS_MIN_BETS     = 4
TENNIS_MIN_BET_SIZE = 500    # RN1 must have bet $500+ total on this player
GRAND_SLAM_KEYWORDS = ("us open", "wimbledon", "french open", "australian open", "roland garros")

ESPN_URLS = {
    "nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
    "nhl": "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard",
    "mlb": "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard",
    "tennis_atp": "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard",
    "tennis_wta": "https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard",
}

NBA_KEYWORDS = [
    "nba", "lakers", "warriors", "celtics", "knicks", "nets", "heat", "bulls",
    "spurs", "bucks", "suns", "clippers", "nuggets", "jazz", "hawks", "76ers",
    "sixers", "raptors", "cavaliers", "cavs", "pistons", "pacers", "hornets",
    "magic", "wizards", "grizzlies", "pelicans", "thunder", "blazers", "kings",
    "timberwolves", "mavericks", "mavs", "rockets",
]
NFL_KEYWORDS = [
    "nfl", "patriots", "cowboys", "eagles", "49ers", "chiefs", "bills",
    "bengals", "ravens", "steelers", "titans", "colts", "jaguars", "texans",
    "broncos", "raiders", "chargers", "seahawks", "rams", "cardinals", "falcons",
    "saints", "panthers", "buccaneers", "packers", "bears", "vikings", "lions",
    "giants", "commanders", "jets",
]
NHL_KEYWORDS = [
    "nhl", "bruins", "maple leafs", "canadiens", "blackhawks", "red wings",
    "penguins", "flyers", "capitals", "lightning", "hurricanes", "islanders",
    "sabres", "senators", "canucks", "flames", "oilers", "avalanche", "blues",
    "predators", "wild", "ducks", "kings", "sharks", "golden knights", "kraken",
    "rangers",
]
MLB_KEYWORDS = [
    "mlb", "yankees", "red sox", "dodgers", "cubs", "braves", "mets",
    "phillies", "padres", "astros", "rangers", "angels", "mariners", "tigers",
    "guardians", "twins", "white sox", "royals", "brewers", "pirates", "reds",
    "rockies", "diamondbacks", "orioles", "blue jays", "rays", "marlins",
]
TENNIS_KEYWORDS = [
    "atp", "wta", "itf", "us open", "wimbledon", "french open",
    "australian open", "roland garros", "davis cup",
]
SOCCER_KEYWORDS = [
    "premier league", "la liga", "bundesliga", "serie a", "ligue 1",
    "champions league", "europa league", "mls", "world cup",
    "fa cup", "copa del rey", "eredivisie",
    "soccer", " fc ", "arsenal", "chelsea", "liverpool", "barcelona",
    "real madrid", "manchester", "juventus", "milan", "inter", "psg", "bayern",
]

# Per-game state: sport -> game_id -> {team: count}
bet_counts  = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
placed_bets = set()   # "sport:game_id"
monitoring  = set()   # "sport:game_id"

# Tennis: match_key -> {player: count/usd}
tennis_counts = defaultdict(lambda: defaultdict(int))
tennis_usd    = defaultdict(lambda: defaultdict(float))  # total USD bet by RN1 per player
tennis_trades = {}   # match_key -> latest trade


# ── Sport detection ───────────────────────────────────────────────────────────

def detect_sport(title: str) -> Optional[str]:
    tl = title.lower()
    if any(k in tl for k in SOCCER_KEYWORDS): return "soccer"
    if any(k in tl for k in NBA_KEYWORDS):    return "nba"
    if any(k in tl for k in NFL_KEYWORDS):    return "nfl"
    if any(k in tl for k in NHL_KEYWORDS):    return "nhl"
    if any(k in tl for k in MLB_KEYWORDS):    return "mlb"
    if any(k in tl for k in TENNIS_KEYWORDS): return "tennis"
    # fallback: "X vs Y" pattern without ATP/WTA is likely tennis
    if " vs " in tl and not any(k in tl for k in NBA_KEYWORDS + NFL_KEYWORDS + NHL_KEYWORDS + MLB_KEYWORDS):
        return "tennis"
    return None


async def fetch_tennis_match(player: str) -> Optional[dict]:
    """Check ESPN ATP+WTA scoreboards, return match info if player leads 2-0 in sets."""
    pl = player.lower()
    for url_key in ("tennis_atp", "tennis_wta"):
        url = ESPN_URLS[url_key]
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    data = await resp.json()
            for event in data.get("events", []):
                comp        = event.get("competitions", [{}])[0]
                competitors = comp.get("competitors", [])
                status      = event.get("status", {}).get("type", {}).get("name", "")
                if status not in ("STATUS_IN_PROGRESS",):
                    continue
                for c in competitors:
                    name = c.get("athlete", {}).get("displayName", "").lower()
                    if not any(w in name for w in pl.split() if len(w) > 3):
                        continue
                    # Count sets won
                    linescores = c.get("linescores", [])
                    sets_won   = 0
                    opp        = next((x for x in competitors if x != c), None)
                    for i, ls in enumerate(linescores):
                        my_games  = int(ls.get("value", 0) or 0)
                        opp_games = int((opp.get("linescores", [{}]*10)[i] if opp else {}).get("value", 0) or 0) if opp else 0
                        if my_games > opp_games and my_games >= 6:
                            sets_won += 1
                    print(f"[TENNIS SCORE] {name} sets won: {sets_won}")
                    if sets_won >= 2:
                        return {"sets_won": sets_won, "name": name}
        except Exception as exc:
            print(f"[TENNIS SCORE] Error: {exc}")
    return None


# ── ESPN API ──────────────────────────────────────────────────────────────────

async def fetch_games(sport: str) -> list:
    url = ESPN_URLS.get(sport)
    if not url:
        return []
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
        games = []
        for event in data.get("events", []):
            comp        = event.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])
            status      = event.get("status", {})
            if len(competitors) < 2:
                continue
            home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
            away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
            home_score = int(home.get("score", 0) or 0)
            away_score = int(away.get("score", 0) or 0)
            games.append({
                "id":         event.get("id", ""),
                "home":       home.get("team", {}).get("displayName", ""),
                "home_short": home.get("team", {}).get("shortDisplayName", ""),
                "away":       away.get("team", {}).get("displayName", ""),
                "away_short": away.get("team", {}).get("shortDisplayName", ""),
                "home_score": home_score,
                "away_score": away_score,
                "period":     status.get("period", 0),
                "clock":      status.get("displayClock", "12:00"),
                "status":     status.get("type", {}).get("name", ""),
                "lead":       abs(home_score - away_score),
                "leader":     home.get("team", {}).get("shortDisplayName", "")
                              if home_score > away_score
                              else away.get("team", {}).get("shortDisplayName", "")
                              if away_score > home_score else "",
            })
        return games
    except Exception as exc:
        print(f"[{sport.upper()} API] Error: {exc}")
        return []


def clock_minutes(clock: str) -> float:
    try:
        m, s = clock.split(":")
        return int(m) + int(s) / 60
    except:
        return 99.0


def match_game(title: str, games: list) -> Optional[dict]:
    tl = title.lower()
    for g in games:
        if g["status"] not in ("STATUS_IN_PROGRESS", "STATUS_HALFTIME"):
            continue
        home_words = [w.lower() for w in g["home"].split() if len(w) > 3]
        away_words = [w.lower() for w in g["away"].split() if len(w) > 3]
        home_match = any(w in tl for w in home_words) or g["home_short"].lower() in tl
        away_match = any(w in tl for w in away_words) or g["away_short"].lower() in tl
        if home_match and away_match:
            return g
    return None


def team_from_outcome(outcome: str, game: dict) -> Optional[str]:
    ol = outcome.lower()
    for key in ("home", "home_short", "away", "away_short"):
        name  = game[key]
        words = [w.lower() for w in name.split() if len(w) > 3]
        short = name.lower().split()[-1]
        if any(w in ol for w in words) or short in ol:
            return game["home"] if "home" in key else game["away"]
    return None


def team_leading(game: dict, team: str) -> bool:
    tl     = team.lower()
    leader = game["leader"].lower()
    return any(w in leader for w in tl.split() if len(w) > 3) or tl.split()[-1] in leader


# ── Generic sport monitor ─────────────────────────────────────────────────────

async def monitor_and_bet(sport: str, game_id: str, team: str, trade: Trade,
                          config: Config, executor: TradeExecutor):
    cond = SPORT_CONDITIONS[sport]
    bet_key = f"{sport}:{game_id}"
    label   = sport.upper()
    print(f"\n[{label} MONITOR] Waiting: {team} | lead>={cond['min_lead']} | period={cond['period']}")

    try:
        while True:
            games = await fetch_games(sport)
            game  = next((g for g in games if g["id"] == game_id), None)

            if game is None or game["status"] == "STATUS_FINAL":
                print(f"[{label} MONITOR] Game ended — conditions never met.")
                break

            period = game["period"]
            lead   = game["lead"]

            # MLB has no clock — just check inning and lead
            if cond["max_mins"] is None:
                if period < cond["period"]:
                    await asyncio.sleep(30)
                    continue
                winning = team_leading(game, team)
                print(f"[{label} MONITOR] Inning {period} | Lead:{lead} | {team} winning:{winning}")
                if not winning:
                    print(f"[{label} MONITOR] {team} not winning. Abort.")
                    break
                if lead < cond["min_lead"]:
                    print(f"[{label} MONITOR] Lead {lead} — need {cond['min_lead']}+...")
                    await asyncio.sleep(30)
                    continue
            else:
                if period != cond["period"]:
                    await asyncio.sleep(15)
                    continue
                mins    = clock_minutes(game["clock"])
                winning = team_leading(game, team)
                print(f"[{label} MONITOR] {game['clock']} | Lead:{lead} | {team} winning:{winning}")
                if not winning:
                    print(f"[{label} MONITOR] {team} not winning. Abort.")
                    break
                if lead < cond["min_lead"]:
                    print(f"[{label} MONITOR] Lead {lead} — need {cond['min_lead']}+...")
                    await asyncio.sleep(20)
                    continue
                if mins > cond["max_mins"]:
                    print(f"[{label} MONITOR] {mins:.1f} min left — need <={cond['max_mins']}...")
                    await asyncio.sleep(20)
                    continue

            if bet_key in placed_bets:
                break
            placed_bets.add(bet_key)

            print(f"\n[{label} BET] *** PLACING BET *** {team} | Lead:{lead} | Period:{period}")

            signal = Signal(trade=trade, copy_amount_usd=config.copy_amount_usd)
            result = await executor.execute(signal)

            if result.success:
                lbl = "[SIM]" if result.is_simulated else "[LIVE]"
                print(f"  {lbl} Order placed! id={result.order_id}")
            else:
                print(f"  [ERROR] {result.error}")
            break

    finally:
        monitoring.discard(f"{sport}:{game_id}")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    config    = Config()
    executor  = TradeExecutor(config)
    feed      = TradeFeed(config)
    generator = SignalGenerator(config, target_wallet=TARGET_WALLET)

    print("\n[BOT] RN1 Copy Bot — Multi-Sport")
    print("[BOT] Soccer: BLOCKED")
    print(f"[BOT] Tennis: R16+, {TENNIS_MIN_BETS}+ bets, price >= {TENNIS_MIN_PRICE:.0%}")
    print("[BOT] NBA: Q4, 10+ pt lead, <=8 min")
    print("[BOT] NFL: Q4, 14+ pt lead, <=5 min")
    print("[BOT] NHL: P3, 2+ goal lead, <=10 min")
    print("[BOT] MLB: inn8+, 4+ run lead")
    print("[BOT] Other: SKIPPED\n")

    async for trade in feed.stream(TARGET_WALLET):

        # ── Block SELL orders ─────────────────────────────────────────────
        if trade.side == "SELL":
            print(f"[SKIP] Sell order ignored: {trade.title[:60]}")
            continue

        # ── Block qualification matches ───────────────────────────────────
        tl = trade.title.lower()
        if any(k in tl for k in ("qualification", "qualifying", "qualifier", "q1 ", "q2 ", "q3 ")):
            print(f"[SKIP] Qualification match: {trade.title[:60]}")
            continue

        sport = detect_sport(trade.title)

        # ── Block soccer ──────────────────────────────────────────────────
        if sport == "soccer":
            print(f"[SKIP] Soccer blocked: {trade.title[:60]}")
            continue

        # ── Tennis ────────────────────────────────────────────────────────
        if sport == "tennis":
            if trade.outcome.lower() in ("yes", "no", "over", "under", ""):
                continue
            tl2        = trade.title.lower()
            is_slam    = any(k in tl2 for k in GRAND_SLAM_KEYWORDS)
            is_r16plus = any(k in tl2 for k in (
                "round of 16", "quarterfinal", "semifinal", "semi-final",
                "final", "quarter-final", "r16", "qf", "sf",
            ))
            if not is_slam and not is_r16plus:
                print(f"[SKIP] Tennis early round: {trade.title[:60]}")
                continue
            match_key = trade.title[:80].lower()
            player    = trade.outcome.strip()
            tennis_counts[match_key][player] += 1
            tennis_usd[match_key][player]    += trade.usd_size
            tennis_trades[match_key] = trade
            count     = tennis_counts[match_key][player]
            total_usd = tennis_usd[match_key][player]
            print(f"\n[TENNIS] RN1 -> {player} ({count}x, ${total_usd:.0f}) @ {trade.price:.2f} | {trade.title[:50]}")

            if count >= TENNIS_MIN_BETS and total_usd >= TENNIS_MIN_BET_SIZE:
                # Check real scoreboard — player must lead 2-0 in sets
                match_data = await fetch_tennis_match(player)
                if match_data:
                    print(f"[TENNIS] Scoreboard: {player} leads {match_data['sets_won']}-0 in sets — copying")
                    signal = generator.process(trade)
                    if signal:
                        result = await executor.execute(signal)
                        if result.success:
                            lbl = "[SIM]" if result.is_simulated else "[LIVE]"
                            print(f"  {lbl} BET COPIED! {trade.outcome} | order_id={result.order_id}")
                        else:
                            print(f"  [ERROR] {result.error}")
                else:
                    print(f"[TENNIS] Skip — player not leading 2-0 on scoreboard")
            else:
                print(f"[TENNIS] Skip — need {TENNIS_MIN_BETS}+ bets and ${TENNIS_MIN_BET_SIZE}+")
            continue

        # ── NBA / NFL / NHL / MLB ─────────────────────────────────────────
        if sport in SPORT_CONDITIONS:
            if trade.outcome.lower() in ("yes", "no", "over", "under", ""):
                continue

            games = await fetch_games(sport)
            game  = match_game(trade.title, games)

            if game is None:
                print(f"[{sport.upper()}] No live game matched: {trade.title[:60]}")
                continue

            period = game["period"]
            team   = team_from_outcome(trade.outcome, game)
            cond   = SPORT_CONDITIONS[sport]

            if not team:
                print(f"[{sport.upper()}] Can't identify team: '{trade.outcome}'")
                continue

            score_str = f"{game['away']} {game['away_score']}-{game['home_score']} {game['home']}"
            print(f"\n[{sport.upper()}] P{period} | RN1 -> {team} | {score_str}")

            if period in cond["early_periods"]:
                bet_counts[sport][game["id"]][team] += 1
                print(f"[{sport.upper()}] Counts: {dict(bet_counts[sport][game['id']])}")

            elif period >= cond["period"]:
                bet_key = f"{sport}:{game['id']}"
                if bet_key in placed_bets or bet_key in monitoring:
                    continue
                counts = bet_counts[sport][game["id"]]
                if not counts:
                    print(f"[{sport.upper()}] Skip — 0 early bets tracked")
                    continue
                vals = sorted(counts.values(), reverse=True)
                if len(vals) >= 2 and vals[0] == vals[1]:
                    print(f"[{sport.upper()}] Skip — bets tied")
                    continue
                top_team = max(counts, key=counts.get)
                print(f"[{sport.upper()}] Top team = {top_team} — starting monitor")
                monitoring.add(bet_key)
                asyncio.create_task(
                    monitor_and_bet(sport, game["id"], top_team, trade, config, executor)
                )
            continue

        # ── Unknown sport: skip ───────────────────────────────────────────
        print(f"[SKIP] No strategy for: {trade.title[:60]}")


if __name__ == "__main__":
    asyncio.run(main())
