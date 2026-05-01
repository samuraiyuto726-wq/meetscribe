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
import asyncio, os, sys, time, json
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
    "nba":        {"period": 4, "min_lead": 15, "max_mins": 5,    "early_periods": (1,2,3)},
    "basketball": {"period": 4, "min_lead": 15, "max_mins": 5,    "early_periods": (1,2,3)},
    "nfl":        {"period": 4, "min_lead": 21, "max_mins": 3,    "early_periods": (1,2,3)},
    "nhl":        {"period": 3, "min_lead": 3,  "max_mins": 5,    "early_periods": (1,2)},
    "mlb":        {"period": 9, "min_lead": 6,  "max_mins": None, "early_periods": tuple(range(1,9))},
}

TENNIS_T1_MIN_BETS = 4     # Tier 1: 2-0 sets won (safest)
TENNIS_T1_MIN_USD  = 500
TENNIS_T2_MIN_BETS = 3     # Tier 2: 1-0 sets + winning current set 4-1 (moderate)
TENNIS_T2_MIN_USD  = 300
TENNIS_T3_MIN_BETS = 2     # Tier 3: winning current set by 3+ games (most frequent)
TENNIS_T3_MIN_USD  = 200
GRAND_SLAM_KEYWORDS = ("us open", "wimbledon", "french open", "australian open", "roland garros")

PANDASCORE_KEY = ""  # Free key at pandascore.co — needed for CS2 scanner

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API  = "https://clob.polymarket.com"

RUGBY_URLS = [
    "https://site.api.espn.com/apis/site/v2/sports/rugby/international/scoreboard",
    "https://site.api.espn.com/apis/site/v2/sports/rugby/premiership/scoreboard",
]
CRICKET_URL = "https://site.api.espn.com/apis/site/v2/sports/cricket/icc/scoreboard"
GOLF_URL    = "https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard"

rugby_placed      = set()
cricket_placed    = set()
golf_placed       = set()
cs2_placed        = set()
bball_indie       = set()
football_indie    = set()
hockey_indie      = set()
baseball_indie    = set()

BASKETBALL_URLS = [
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    "https://site.api.espn.com/apis/site/v2/sports/basketball/euroleague/scoreboard",
    "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard",
    "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
]

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
BASKETBALL_KEYWORDS = [
    "euroleague", "eurocup", "ncaa", "wnba", "fiba", "nbl", "cba",
    "basketball", "bball",
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
tennis_counts  = defaultdict(lambda: defaultdict(int))
tennis_usd     = defaultdict(lambda: defaultdict(float))  # total USD bet by RN1 per player
tennis_trades  = {}   # match_key -> latest trade
tennis_placed  = set()   # match_keys already bet on (avoid double-betting)


# ── Sport detection ───────────────────────────────────────────────────────────

def detect_sport(title: str) -> Optional[str]:
    tl = title.lower()
    if any(k in tl for k in SOCCER_KEYWORDS):       return "soccer"
    if any(k in tl for k in NBA_KEYWORDS):          return "nba"
    if any(k in tl for k in BASKETBALL_KEYWORDS):   return "basketball"
    if any(k in tl for k in NFL_KEYWORDS):    return "nfl"
    if any(k in tl for k in NHL_KEYWORDS):    return "nhl"
    if any(k in tl for k in MLB_KEYWORDS):    return "mlb"
    if any(k in tl for k in TENNIS_KEYWORDS): return "tennis"
    # fallback: "X vs Y" pattern without ATP/WTA is likely tennis
    if " vs " in tl and not any(k in tl for k in NBA_KEYWORDS + NFL_KEYWORDS + NHL_KEYWORDS + MLB_KEYWORDS):
        return "tennis"
    return None


async def fetch_tennis_match(player: str) -> Optional[dict]:
    """Check ESPN ATP+WTA scoreboards. Returns player's current match state or None if not found."""
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
                if status != "STATUS_IN_PROGRESS":
                    continue
                for c in competitors:
                    name = c.get("athlete", {}).get("displayName", "").lower()
                    if not any(w in name for w in pl.split() if len(w) > 3):
                        continue
                    linescores = c.get("linescores", [])
                    opp    = next((x for x in competitors if x != c), None)
                    opp_ls = opp.get("linescores", []) if opp else []
                    sets_won = 0
                    cur_my = cur_opp = 0
                    for i, ls in enumerate(linescores):
                        my_g  = int(ls.get("value", 0) or 0)
                        opp_g = int(opp_ls[i].get("value", 0) or 0) if i < len(opp_ls) else 0
                        if i == len(linescores) - 1:   # last entry = current set in progress
                            cur_my, cur_opp = my_g, opp_g
                        if my_g > opp_g and my_g >= 6:
                            sets_won += 1
                    print(f"[TENNIS SCORE] {name}: {sets_won} sets won | current set {cur_my}-{cur_opp}")
                    return {"sets_won": sets_won, "cur_my": cur_my, "cur_opp": cur_opp, "name": name}
        except Exception as exc:
            print(f"[TENNIS SCORE] Error: {exc}")
    return None


# ── ESPN API ──────────────────────────────────────────────────────────────────

async def fetch_games(sport: str) -> list:
    urls = BASKETBALL_URLS if sport == "basketball" else ([ESPN_URLS[sport]] if sport in ESPN_URLS else [])
    if not urls:
        return []
    all_games = []
    try:
        async with aiohttp.ClientSession() as sess:
            for url in urls:
                try:
                    async with sess.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        data = await resp.json()
                except Exception:
                    continue
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
                    all_games.append({
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
        return all_games
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


# ── Independent bet helper ────────────────────────────────────────────────────

async def find_and_bet_market(label: str, team_name: str, placed_set: set,
                               session: aiohttp.ClientSession,
                               config: Config, executor: TradeExecutor) -> bool:
    key = f"{label}:{team_name.lower()}"
    if key in placed_set:
        return False

    try:
        params = {"q": team_name, "active": "true", "closed": "false", "limit": 20}
        async with session.get(f"{GAMMA_API}/markets", params=params,
                               timeout=aiohttp.ClientTimeout(total=10)) as r:
            raw = await r.json()
        markets = raw if isinstance(raw, list) else raw.get("markets", [])
    except Exception as e:
        print(f"[{label}] Market search error: {e}")
        return False

    team_low = team_name.lower()
    for m in markets:
        question = m.get("question", "").lower()
        if team_low not in question:
            continue
        if not any(w in question for w in ("win", "winner", "champion", "title")):
            continue
        if m.get("closed") or not m.get("active"):
            continue

        # Get YES token ID
        clob_ids = m.get("clobTokenIds", [])
        outcomes_raw = m.get("outcomes", "[]")
        try:
            outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
        except Exception:
            outcomes = []
        yes_idx = next((i for i, o in enumerate(outcomes) if str(o).lower() == "yes"), None)
        if yes_idx is None or yes_idx >= len(clob_ids):
            continue
        yes_token_id = clob_ids[yes_idx]

        # Get current ask price
        try:
            async with session.get(f"{CLOB_API}/price",
                                   params={"token_id": yes_token_id, "side": "buy"},
                                   timeout=aiohttp.ClientTimeout(total=5)) as r:
                price_data = await r.json()
            ask = float(price_data.get("price", 0))
        except Exception as e:
            print(f"[{label}] Price fetch error: {e}")
            continue

        print(f"[{label}] Found: '{m.get('question','')[:70]}' — YES ask: {ask:.2f}")

        if ask >= 0.97:
            print(f"[{label}] Skip — price {ask:.2f} >= 0.97 (no profit)")
            return False
        if ask < 0.85:
            print(f"[{label}] Skip — price {ask:.2f} < 0.85 (market too uncertain)")
            return False

        placed_set.add(key)
        synthetic = Trade(
            trade_id=f"indie_{label}_{int(time.time())}",
            proxy_wallet="",
            condition_id=m.get("conditionId", ""),
            token_id=yes_token_id,
            side="BUY",
            price=ask,
            size=round(config.copy_amount_usd / ask, 4),
            usd_size=config.copy_amount_usd,
            outcome="Yes",
            title=m.get("question", team_name),
        )
        signal = Signal(trade=synthetic, copy_amount_usd=config.copy_amount_usd)
        print(f"\n[{label} BET] *** PLACING BET *** {team_name} @ {ask:.2f}")
        result = await executor.execute(signal)
        if result.success:
            lbl = "[SIM]" if result.is_simulated else "[LIVE]"
            print(f"  {lbl} Bet placed! order_id={result.order_id}")
        else:
            print(f"  [ERROR] {result.error}")
        return True

    print(f"[{label}] No suitable market found for '{team_name}'")
    return False


# ── Independent scanners ──────────────────────────────────────────────────────

async def scan_rugby_loop(config: Config, executor: TradeExecutor):
    print("[RUGBY] Scanner started — 20+ pt lead, 2nd half, 35+ min elapsed")
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                for url in RUGBY_URLS:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                        data = await r.json()
                    for event in data.get("events", []):
                        status = event.get("status", {})
                        if status.get("type", {}).get("name") != "STATUS_IN_PROGRESS":
                            continue
                        comp = event.get("competitions", [{}])[0]
                        competitors = comp.get("competitors", [])
                        if len(competitors) < 2:
                            continue
                        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
                        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
                        home_score = int(home.get("score", 0) or 0)
                        away_score = int(away.get("score", 0) or 0)
                        lead    = abs(home_score - away_score)
                        period  = status.get("period", 0)
                        elapsed = clock_minutes(status.get("displayClock", "0:00"))
                        if period < 2 or elapsed < 35 or lead < 20:
                            continue
                        leader = home if home_score > away_score else away
                        leader_name = leader.get("team", {}).get("displayName", "")
                        await find_and_bet_market("RUGBY", leader_name, rugby_placed, session, config, executor)
            except Exception as e:
                print(f"[RUGBY] Error: {e}")
            await asyncio.sleep(60)


async def scan_cricket_loop(config: Config, executor: TradeExecutor):
    print("[CRICKET] Scanner started — <=10 runs needed, 8+ wickets remaining")
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(CRICKET_URL, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    data = await r.json()
                for event in data.get("events", []):
                    if event.get("status", {}).get("type", {}).get("name") != "STATUS_IN_PROGRESS":
                        continue
                    comp = event.get("competitions", [{}])[0]
                    situation = comp.get("situation", {})
                    runs_needed       = situation.get("runsNeeded")
                    wickets_remaining = situation.get("wicketsRemaining")
                    if runs_needed is None or wickets_remaining is None:
                        continue
                    if runs_needed <= 10 and wickets_remaining >= 8:
                        batting = situation.get("battingTeam") or {}
                        team_name = batting.get("displayName", "")
                        if team_name:
                            await find_and_bet_market("CRICKET", team_name, cricket_placed, session, config, executor)
            except Exception as e:
                print(f"[CRICKET] Error: {e}")
            await asyncio.sleep(60)


async def scan_golf_loop(config: Config, executor: TradeExecutor):
    print("[GOLF] Scanner started — 8+ stroke lead, <=9 holes remaining")
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(GOLF_URL, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    data = await r.json()
                for event in data.get("events", []):
                    if event.get("status", {}).get("type", {}).get("name") != "STATUS_IN_PROGRESS":
                        continue
                    comp = event.get("competitions", [{}])[0]
                    scored = []
                    for c in comp.get("competitors", []):
                        raw_score = c.get("score", "0")
                        try:
                            score_val = 0 if raw_score in ("E", "--", "") else int(raw_score)
                        except Exception:
                            score_val = 0
                        thru = c.get("status", {}).get("thru") or 0
                        scored.append({
                            "name":  c.get("athlete", {}).get("displayName", ""),
                            "score": score_val,
                            "thru":  int(thru),
                        })
                    if len(scored) < 2:
                        continue
                    scored.sort(key=lambda x: x["score"])
                    lead = scored[1]["score"] - scored[0]["score"]
                    holes_left = 18 - scored[0]["thru"]
                    if lead >= 8 and 1 <= holes_left <= 9:
                        await find_and_bet_market("GOLF", scored[0]["name"], golf_placed, session, config, executor)
            except Exception as e:
                print(f"[GOLF] Error: {e}")
            await asyncio.sleep(120)


async def scan_cs2_loop(config: Config, executor: TradeExecutor):
    if not PANDASCORE_KEY:
        print("[CS2] Skipping — set PANDASCORE_KEY to enable (free key at pandascore.co)")
        return
    print("[CS2] Scanner started — leading 11-1 at halftime (first to 13)")
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                headers = {"Authorization": f"Bearer {PANDASCORE_KEY}"}
                async with session.get("https://api.pandascore.co/csgo/matches/running",
                                       headers=headers, params={"per_page": 50},
                                       timeout=aiohttp.ClientTimeout(total=10)) as r:
                    matches = await r.json()
                for match in (matches if isinstance(matches, list) else []):
                    for game in match.get("games", []):
                        if game.get("status") != "running":
                            continue
                        teams = game.get("teams", [])
                        if len(teams) < 2:
                            continue
                        t1_score = teams[0].get("score", 0) or 0
                        t2_score = teams[1].get("score", 0) or 0
                        if t1_score + t2_score != 12:
                            continue
                        lead = abs(t1_score - t2_score)
                        if lead < 10:
                            continue
                        leader = teams[0] if t1_score > t2_score else teams[1]
                        await find_and_bet_market("CS2", leader.get("name", ""), cs2_placed, session, config, executor)
            except Exception as e:
                print(f"[CS2] Error: {e}")
            await asyncio.sleep(30)


# ── Main ──────────────────────────────────────────────────────────────────────

async def _espn_games(session, urls):
    games = []
    for url in urls:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
            for event in data.get("events", []):
                status = event.get("status", {})
                comp = event.get("competitions", [{}])[0]
                competitors = comp.get("competitors", [])
                if len(competitors) < 2:
                    continue
                home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
                away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
                games.append({
                    "status":     status.get("type", {}).get("name", ""),
                    "period":     status.get("period", 0),
                    "clock":      status.get("displayClock", "99:00"),
                    "home_score": int(home.get("score", 0) or 0),
                    "away_score": int(away.get("score", 0) or 0),
                    "home_name":  home.get("team", {}).get("displayName", ""),
                    "away_name":  away.get("team", {}).get("displayName", ""),
                })
        except Exception:
            continue
    return games


async def scan_basketball_indie_loop(config: Config, executor: TradeExecutor):
    urls = [
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
        "https://site.api.espn.com/apis/site/v2/sports/basketball/euroleague/scoreboard",
        "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard",
        "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
    ]
    print("[BBALL] Independent scanner started — Q4, 15+ pt lead, <=5 min (NBA/EuroLeague/NCAA/WNBA)")
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                for g in await _espn_games(session, urls):
                    if g["status"] != "STATUS_IN_PROGRESS": continue
                    if g["period"] != 4: continue
                    if clock_minutes(g["clock"]) > 5: continue
                    lead = abs(g["home_score"] - g["away_score"])
                    if lead < 15: continue
                    leader = g["home_name"] if g["home_score"] > g["away_score"] else g["away_name"]
                    await find_and_bet_market("BBALL", leader, bball_indie, session, config, executor)
            except Exception as e:
                print(f"[BBALL] Error: {e}")
            await asyncio.sleep(30)


async def scan_football_indie_loop(config: Config, executor: TradeExecutor):
    urls = [
        "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
        "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard",
    ]
    print("[FOOTBALL] Independent scanner started — Q4, 21+ pt lead, <=3 min (NFL/NCAA)")
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                for g in await _espn_games(session, urls):
                    if g["status"] != "STATUS_IN_PROGRESS": continue
                    if g["period"] != 4: continue
                    if clock_minutes(g["clock"]) > 3: continue
                    lead = abs(g["home_score"] - g["away_score"])
                    if lead < 21: continue
                    leader = g["home_name"] if g["home_score"] > g["away_score"] else g["away_name"]
                    await find_and_bet_market("FOOTBALL", leader, football_indie, session, config, executor)
            except Exception as e:
                print(f"[FOOTBALL] Error: {e}")
            await asyncio.sleep(30)


async def scan_hockey_indie_loop(config: Config, executor: TradeExecutor):
    urls = [
        "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard",
        "https://site.api.espn.com/apis/site/v2/sports/hockey/college-hockey/scoreboard",
    ]
    print("[HOCKEY] Independent scanner started — P3, 3+ goal lead, <=5 min (NHL/college)")
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                for g in await _espn_games(session, urls):
                    if g["status"] != "STATUS_IN_PROGRESS": continue
                    if g["period"] != 3: continue
                    if clock_minutes(g["clock"]) > 5: continue
                    lead = abs(g["home_score"] - g["away_score"])
                    if lead < 3: continue
                    leader = g["home_name"] if g["home_score"] > g["away_score"] else g["away_name"]
                    await find_and_bet_market("HOCKEY", leader, hockey_indie, session, config, executor)
            except Exception as e:
                print(f"[HOCKEY] Error: {e}")
            await asyncio.sleep(30)


async def scan_baseball_indie_loop(config: Config, executor: TradeExecutor):
    urls = [
        "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard",
        "https://site.api.espn.com/apis/site/v2/sports/baseball/college-baseball/scoreboard",
    ]
    print("[BASEBALL] Independent scanner started — 9th inn+, 6+ run lead (MLB/college)")
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                for g in await _espn_games(session, urls):
                    if g["status"] != "STATUS_IN_PROGRESS": continue
                    if g["period"] < 9: continue
                    lead = abs(g["home_score"] - g["away_score"])
                    if lead < 6: continue
                    leader = g["home_name"] if g["home_score"] > g["away_score"] else g["away_name"]
                    await find_and_bet_market("BASEBALL", leader, baseball_indie, session, config, executor)
            except Exception as e:
                print(f"[BASEBALL] Error: {e}")
            await asyncio.sleep(30)


async def main():
    config    = Config()
    executor  = TradeExecutor(config)
    feed      = TradeFeed(config)
    generator = SignalGenerator(config, target_wallet=TARGET_WALLET)

    print("\n[BOT] RN1 Copy Bot — Multi-Sport")
    print("[BOT] Soccer: BLOCKED")
    print(f"[BOT] Tennis T1: R16+, {TENNIS_T1_MIN_BETS}+ bets, ${TENNIS_T1_MIN_USD}+, 2-0 sets (safest)")
    print(f"[BOT] Tennis T2: R16+, {TENNIS_T2_MIN_BETS}+ bets, ${TENNIS_T2_MIN_USD}+, 1-0 sets + winning current 4-1")
    print(f"[BOT] Tennis T3: R16+, {TENNIS_T3_MIN_BETS}+ bets, ${TENNIS_T3_MIN_USD}+, winning current set by 3+")
    print("[BOT] NBA + Basketball (EuroLeague/NCAA/WNBA): Q4, 15+ pt lead, <=5 min (~97.5%)")
    print("[BOT] NFL: Q4, 21+ pt lead, <=3 min  (~97.5%)")
    print("[BOT] NHL: P3, 3+ goal lead, <=5 min (~97.5%)")
    print("[BOT] MLB: 9th inn+, 6+ run lead     (~97.5%)")
    print("[BOT] Rugby:   20+ pt lead, 2nd half, 35+ min elapsed")
    print("[BOT] Cricket: <=10 runs needed, 8+ wickets remaining")
    print("[BOT] Golf:    8+ stroke lead, <=9 holes left")
    print("[BOT] CS2:     leading 11-1 at halftime")
    print("[BOT] Other markets: copy if 0.95 <= price < 0.97\n")

    asyncio.create_task(scan_rugby_loop(config, executor))
    asyncio.create_task(scan_cricket_loop(config, executor))
    asyncio.create_task(scan_golf_loop(config, executor))
    asyncio.create_task(scan_cs2_loop(config, executor))
    asyncio.create_task(scan_basketball_indie_loop(config, executor))
    asyncio.create_task(scan_football_indie_loop(config, executor))
    asyncio.create_task(scan_hockey_indie_loop(config, executor))
    asyncio.create_task(scan_baseball_indie_loop(config, executor))

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
            print(f"\n[TENNIS] RN1 -> {player} ({count}x, ${total_usd:.0f}) | {trade.title[:50]}")

            if match_key in tennis_placed:
                print(f"[TENNIS] Already bet on this match — skip")
                continue

            # Must meet at least Tier 3 minimums before checking scoreboard
            if count < TENNIS_T3_MIN_BETS or total_usd < TENNIS_T3_MIN_USD:
                print(f"[TENNIS] Skip — need {TENNIS_T3_MIN_BETS}+ bets and ${TENNIS_T3_MIN_USD}+ (Tier 3 min)")
                continue

            if trade.price < 0.95:
                print(f"[TENNIS] Skip — price {trade.price:.2f} below 0.95 floor")
                continue

            match_data = await fetch_tennis_match(player)
            if match_data is None:
                print(f"[TENNIS] Skip — player not found in any live match on ESPN")
                continue

            s   = match_data["sets_won"]
            cm  = match_data["cur_my"]
            co  = match_data["cur_opp"]
            gap = cm - co

            # Check tiers from safest to least safe
            tier = None
            if s >= 2 and count >= TENNIS_T1_MIN_BETS and total_usd >= TENNIS_T1_MIN_USD:
                tier = 1
            elif s >= 1 and cm >= 4 and gap >= 3 and count >= TENNIS_T2_MIN_BETS and total_usd >= TENNIS_T2_MIN_USD:
                tier = 2
            elif gap >= 3 and cm >= 3 and count >= TENNIS_T3_MIN_BETS and total_usd >= TENNIS_T3_MIN_USD:
                tier = 3

            if tier:
                tier_desc = {1: "2-0 sets", 2: f"1-0 sets + {cm}-{co} current", 3: f"winning current set {cm}-{co}"}
                print(f"[TENNIS] TIER {tier} — {match_data['name']} ({tier_desc[tier]}) — copying")
                tennis_placed.add(match_key)
                signal = generator.process(trade)
                if signal:
                    result = await executor.execute(signal)
                    if result.success:
                        lbl = "[SIM]" if result.is_simulated else "[LIVE]"
                        print(f"  {lbl} BET COPIED! {trade.outcome} | order_id={result.order_id}")
                    else:
                        print(f"  [ERROR] {result.error}")
            else:
                print(f"[TENNIS] Skip — scoreboard: {s} sets, cur {cm}-{co} — no tier conditions met")
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
                if trade.price < 0.95:
                    print(f"[{sport.upper()}] Skip — price {trade.price:.2f} below 0.95 floor")
                    continue
                if trade.price >= 0.97:
                    print(f"[{sport.upper()}] Skip — price {trade.price:.2f} >= 0.97 (no profit)")
                    continue
                print(f"[{sport.upper()}] Top team = {top_team} — starting monitor")
                monitoring.add(bet_key)
                asyncio.create_task(
                    monitor_and_bet(sport, game["id"], top_team, trade, config, executor)
                )
            continue

        # ── All other markets: copy if 0.95 <= price < 0.97 ─────────────
        if trade.price < 0.95:
            print(f"[SKIP] Price {trade.price:.2f} below 0.95 floor: {trade.title[:60]}")
            continue
        if trade.price >= 0.97:
            print(f"[SKIP] Price {trade.price:.2f} >= 0.97 (no profit): {trade.title[:60]}")
            continue
        print(f"\n[OTHER] RN1 @ {trade.price:.2f} — copying: {trade.title[:60]}")
        signal = generator.process(trade)
        if signal:
            result = await executor.execute(signal)
            if result.success:
                lbl = "[SIM]" if result.is_simulated else "[LIVE]"
                print(f"  {lbl} BET COPIED! {trade.outcome} | order_id={result.order_id}")
            else:
                print(f"  [ERROR] {result.error}")


if __name__ == "__main__":
    asyncio.run(main())
