"""
Multi-Sport Bot — Polymarket-First Approach

Flow:
  1. Fetch active sports markets from Polymarket
  2. For each market, find the matching live game on ESPN
  3. If game conditions are met AND price is 0.85-0.96 (4%+ profit) → BET

This ensures we only ever bet on markets that actually exist.
"""
import asyncio, os, sys, time, json, csv
from collections import defaultdict
from datetime import datetime

LOG_FILE   = r'C:\Users\glmar\meetscribe\bets_log.csv'
_bot_start = datetime.now()

ALL_SPORTS = ["BASKETBALL", "FOOTBALL", "HOCKEY", "BASEBALL", "RUGBY", "CRICKET", "GOLF", "CS2"]

stats = {sport: {
    "polymarket_markets": 0,
    "conditions_met":     0,
    "price_too_high":     0,
    "price_too_low":      0,
    "bets_placed":        0,
} for sport in ALL_SPORTS}


def print_summary():
    elapsed = datetime.now() - _bot_start
    hours   = int(elapsed.total_seconds() // 3600)
    mins    = int((elapsed.total_seconds() % 3600) // 60)
    print(f"\n{'='*65}")
    print(f"  BOT SESSION SUMMARY  (ran {hours}h {mins}m)")
    print(f"{'='*65}")
    total_markets = total_cond = total_bets = 0
    for sport in ALL_SPORTS:
        s = stats[sport]
        total_markets += s["polymarket_markets"]
        total_cond    += s["conditions_met"]
        total_bets    += s["bets_placed"]
        print(f"  {sport:<12} | markets on poly: {s['polymarket_markets']:>3} | "
              f"conditions met: {s['conditions_met']:>3} | "
              f"price skip: {s['price_too_high']:>2} high / {s['price_too_low']:>2} low | "
              f"bets: {s['bets_placed']:>2}")
    print(f"{'─'*65}")
    print(f"  {'TOTAL':<12} | markets: {total_markets:>3} | conditions met: {total_cond:>3} | bets: {total_bets:>2}")
    print(f"{'='*65}\n")


def log_bet(sport, title, outcome, price, amount_usd, simulated, order_id, lead="-"):
    payout      = round(amount_usd / price, 4)
    profit_usd  = round(payout - amount_usd, 4)
    profit_pct  = round((1 / price - 1) * 100, 2)
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not file_exists:
            w.writerow(["Timestamp", "Sport", "Market", "Outcome", "Price",
                        "Bet USD", "Potential Payout", "Potential Profit USD",
                        "Profit %", "Lead At Bet", "Simulated", "Order ID"])
        w.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            sport, title[:80], outcome, price, amount_usd,
            payout, profit_usd, f"{profit_pct}%",
            lead, "SIM" if simulated else "LIVE", order_id,
        ])


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
from trading_bot.feed import Trade
from trading_bot.executor import TradeExecutor
from trading_bot.signal_generator import Signal

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API  = "https://clob.polymarket.com"

PANDASCORE_KEY = ""  # Free key at pandascore.co — needed for CS2

# ESPN endpoints per sport
SPORT_ESPN_URLS = {
    "BASKETBALL": [
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
        "https://site.api.espn.com/apis/site/v2/sports/basketball/euroleague/scoreboard",
        "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard",
        "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
    ],
    "FOOTBALL": [
        "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
        "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard",
    ],
    "HOCKEY": [
        "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard",
        "https://site.api.espn.com/apis/site/v2/sports/hockey/college-hockey/scoreboard",
    ],
    "BASEBALL": [
        "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard",
        "https://site.api.espn.com/apis/site/v2/sports/baseball/college-baseball/scoreboard",
    ],
}

# Conditions to bet: period, min lead, max minutes remaining (None = no clock e.g. baseball)
SPORT_CONDITIONS = {
    "BASKETBALL": {"period": 4, "min_lead": 15, "max_mins": 5},
    "FOOTBALL":   {"period": 4, "min_lead": 21, "max_mins": 3},
    "HOCKEY":     {"period": 3, "min_lead": 3,  "max_mins": 5},
    "BASEBALL":   {"period": 9, "min_lead": 6,  "max_mins": None},
}

# Search terms to find sports markets on Polymarket
SPORT_SEARCH_TERMS = {
    "BASKETBALL": ["nba", "nba championship", "nba finals", "nba playoffs",
                   "nba series", "win the series", "celtics", "thunder",
                   "knicks", "timberwolves", "pacers", "heat", "nuggets"],
    "FOOTBALL":   ["nfl", "super bowl", "nfl championship", "nfl playoffs"],
    "HOCKEY":     ["nhl", "stanley cup", "nhl playoffs", "nhl series",
                   "oilers", "panthers", "stars", "avalanche", "rangers"],
    "BASEBALL":   ["mlb", "world series", "mlb championship", "yankees",
                   "dodgers", "mets", "cubs", "braves", "astros"],
}

# Known team keywords — market must mention at least one to be counted as real
SPORT_TEAM_KEYWORDS = {
    "BASKETBALL": [
        "lakers","warriors","celtics","knicks","nets","heat","bulls","spurs","bucks",
        "suns","clippers","nuggets","jazz","hawks","76ers","sixers","raptors",
        "cavaliers","cavs","pistons","pacers","hornets","magic","wizards",
        "grizzlies","pelicans","thunder","blazers","kings","timberwolves","wolves",
        "mavericks","mavs","rockets","okc","nyk","bos","mia","ind","min",
    ],
    "FOOTBALL": [
        "patriots","cowboys","eagles","49ers","chiefs","bills","bengals","ravens",
        "steelers","titans","colts","jaguars","texans","broncos","raiders",
        "chargers","seahawks","rams","cardinals","falcons","saints","panthers",
        "buccaneers","packers","bears","vikings","lions","giants","commanders","jets",
    ],
    "HOCKEY": [
        "bruins","maple leafs","canadiens","blackhawks","red wings","penguins",
        "flyers","capitals","lightning","hurricanes","islanders","sabres","senators",
        "canucks","flames","oilers","avalanche","blues","predators","wild","ducks",
        "kings","sharks","golden knights","kraken","rangers",
    ],
    "BASEBALL": [
        "yankees","red sox","dodgers","cubs","braves","mets","phillies","padres",
        "astros","rangers","angels","mariners","tigers","guardians","twins",
        "white sox","royals","brewers","pirates","reds","rockies","diamondbacks",
        "orioles","blue jays","rays","marlins",
    ],
}

RUGBY_URLS = [
    "https://site.api.espn.com/apis/site/v2/sports/rugby/international/scoreboard",
    "https://site.api.espn.com/apis/site/v2/sports/rugby/premiership/scoreboard",
]
CRICKET_URL = "https://site.api.espn.com/apis/site/v2/sports/cricket/icc/scoreboard"
GOLF_URL    = "https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard"

rugby_placed   = set()
cricket_placed = set()
golf_placed    = set()
cs2_placed     = set()


def clock_minutes(clock: str) -> float:
    try:
        m, s = clock.split(":")
        return int(m) + int(s) / 60
    except Exception:
        return 99.0


# ── ESPN helper ───────────────────────────────────────────────────────────────

async def _espn_games(session, urls):
    games = []
    for url in urls:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
            for event in data.get("events", []):
                status      = event.get("status", {})
                comp        = event.get("competitions", [{}])[0]
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
                    "home_short": home.get("team", {}).get("shortDisplayName", ""),
                    "away_short": away.get("team", {}).get("shortDisplayName", ""),
                })
        except Exception:
            continue
    return games


# ── Polymarket helpers ────────────────────────────────────────────────────────

async def fetch_gamma_markets(session, query: str) -> list:
    try:
        params = {"q": query, "active": "true", "closed": "false", "limit": 200}
        async with session.get(f"{GAMMA_API}/markets", params=params,
                               timeout=aiohttp.ClientTimeout(total=10)) as r:
            raw = await r.json()
        return raw if isinstance(raw, list) else raw.get("markets", [])
    except Exception:
        return []


def game_matches_market(game: dict, question: str) -> bool:
    """True if either team from the game appears in the Polymarket question."""
    q = question.lower()
    for name_key in ("home_name", "away_name", "home_short", "away_short"):
        name = game[name_key]
        words = [w.lower() for w in name.split() if len(w) > 3]
        if any(w in q for w in words):
            return True
    return False


async def get_yes_price(session, market: dict) -> tuple:
    """Returns (yes_token_id, ask_price) or (None, None) if unavailable."""
    clob_ids     = market.get("clobTokenIds", [])
    outcomes_raw = market.get("outcomes", "[]")
    try:
        outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
    except Exception:
        outcomes = []
    yes_idx = next((i for i, o in enumerate(outcomes) if str(o).lower() == "yes"), None)
    if yes_idx is None or yes_idx >= len(clob_ids):
        return None, None
    yes_token_id = clob_ids[yes_idx]
    try:
        async with session.get(f"{CLOB_API}/price",
                               params={"token_id": yes_token_id, "side": "buy"},
                               timeout=aiohttp.ClientTimeout(total=5)) as r:
            price_data = await r.json()
        return yes_token_id, float(price_data.get("price", 0))
    except Exception:
        return None, None


# ── Polymarket-first main scanner ─────────────────────────────────────────────

async def scan_polymarket_games_loop(config: Config, executor: TradeExecutor):
    """
    Every second:
    1. Fetch active Polymarket sports markets
    2. Find live ESPN games matching those markets
    3. Check conditions + price
    4. Bet if everything lines up
    """
    placed = set()   # market conditionId:leader — prevent double bets

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                # ── Step 1: Fetch Polymarket markets per sport ────────────
                sport_markets: dict[str, list] = {}
                for sport, terms in SPORT_SEARCH_TERMS.items():
                    seen_ids: set  = set()
                    markets: list  = []
                    team_kws       = SPORT_TEAM_KEYWORDS.get(sport, [])
                    for term in terms:
                        for m in await fetch_gamma_markets(session, term):
                            mid = m.get("conditionId") or m.get("id", "")
                            if not mid or mid in seen_ids:
                                continue
                            # only keep markets that mention a real team name
                            q = m.get("question", "").lower()
                            if team_kws and not any(kw in q for kw in team_kws):
                                continue
                            seen_ids.add(mid)
                            markets.append(m)
                    sport_markets[sport] = markets
                    stats[sport]["polymarket_markets"] = len(markets)

                total_markets = sum(len(v) for v in sport_markets.values())
                print(f"[POLY] {total_markets} real sports markets on Polymarket")
                for sport, markets in sport_markets.items():
                    if markets:
                        sample = [m.get('question','')[:60] for m in markets[:3]]
                        print(f"  [{sport}] {len(markets)} markets — {sample}")
                    else:
                        print(f"  [{sport}] 0 markets")

                # ── Step 2: Fetch live ESPN games per sport ───────────────
                sport_games: dict[str, list] = {}
                for sport, urls in SPORT_ESPN_URLS.items():
                    all_games = await _espn_games(session, urls)
                    live = [g for g in all_games if g["status"] == "STATUS_IN_PROGRESS"]
                    sport_games[sport] = live
                    if live:
                        print(f"  [{sport}] {len(live)} live games — e.g.: {live[0]['away_name']} vs {live[0]['home_name']}")
                    else:
                        print(f"  [{sport}] No live games right now")

                # ── Step 3: Match markets → games → check conditions ──────
                for sport, markets in sport_markets.items():
                    cond       = SPORT_CONDITIONS[sport]
                    live_games = sport_games.get(sport, [])

                    if not markets:
                        print(f"[{sport}] No active Polymarket markets")
                        continue
                    if not live_games:
                        continue

                    for market in markets:
                        question = market.get("question", "")
                        if not question:
                            continue

                        for game in live_games:
                            if not game_matches_market(game, question):
                                continue

                            lead   = abs(game["home_score"] - game["away_score"])
                            leader = game["home_name"] if game["home_score"] > game["away_score"] else game["away_name"]
                            period = game["period"]

                            print(f"[{sport}] MATCH FOUND: '{question[:60]}'")
                            print(f"  ESPN: {game['away_name']} {game['away_score']}-{game['home_score']} "
                                  f"{game['home_name']} | P{period} {game['clock']} | Lead:{lead}")

                            # Check score conditions
                            if period < cond["period"]:
                                print(f"  -> Skip: period {period} (need {cond['period']})")
                                continue
                            if lead < cond["min_lead"]:
                                print(f"  -> Skip: lead {lead} (need {cond['min_lead']}+)")
                                continue
                            if cond["max_mins"] is not None:
                                mins = clock_minutes(game["clock"])
                                if mins > cond["max_mins"]:
                                    print(f"  -> Skip: {mins:.1f} min left (need <={cond['max_mins']})")
                                    continue

                            print(f"  -> CONDITION MET! {leader} leading by {lead}")
                            stats[sport]["conditions_met"] += 1

                            # Check price
                            yes_token_id, ask = await get_yes_price(session, market)
                            if yes_token_id is None:
                                print(f"  -> Skip: can't get price")
                                continue

                            print(f"  -> YES price: {ask:.3f}")

                            if ask >= 0.96:
                                print(f"  -> Skip: price {ask:.3f} >= 0.96 (less than 4% profit)")
                                stats[sport]["price_too_high"] += 1
                                continue
                            if ask < 0.85:
                                print(f"  -> Skip: price {ask:.3f} < 0.85 (too uncertain)")
                                stats[sport]["price_too_low"] += 1
                                continue

                            # Prevent double-bet on same market+leader
                            bet_key = f"{market.get('conditionId','')}:{leader}"
                            if bet_key in placed:
                                print(f"  -> Already bet on this — skip")
                                continue
                            placed.add(bet_key)

                            # Place bet
                            synthetic = Trade(
                                trade_id=f"indie_{sport}_{int(time.time())}",
                                proxy_wallet="",
                                condition_id=market.get("conditionId", ""),
                                token_id=yes_token_id,
                                side="BUY",
                                price=ask,
                                size=round(config.copy_amount_usd / ask, 4),
                                usd_size=config.copy_amount_usd,
                                outcome="Yes",
                                title=question,
                            )
                            signal = Signal(trade=synthetic, copy_amount_usd=config.copy_amount_usd)
                            print(f"\n  *** [{sport} BET] PLACING BET *** {leader} @ {ask:.3f}")
                            result = await executor.execute(signal)
                            if result.success:
                                lbl = "[SIM]" if result.is_simulated else "[LIVE]"
                                print(f"  {lbl} Bet placed! order_id={result.order_id}")
                                log_bet(sport, question, "Yes", ask,
                                        config.copy_amount_usd, result.is_simulated,
                                        result.order_id or "", lead)
                                stats[sport]["bets_placed"] += 1
                            else:
                                print(f"  [ERROR] {result.error}")

            except Exception as e:
                print(f"[SCAN] Error: {e}")

            await asyncio.sleep(1)


# ── Rugby/Cricket/Golf/CS2 (unchanged, search Polymarket by team name) ────────

async def scan_rugby_loop(config: Config, executor: TradeExecutor):
    print("[RUGBY] Scanner started — 20+ pt lead, 2nd half, 35+ min elapsed")
    placed = set()
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
                        comp        = event.get("competitions", [{}])[0]
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
                        hn = home.get("team", {}).get("displayName", "")
                        an = away.get("team", {}).get("displayName", "")
                        if period < 2 or elapsed < 35 or lead < 20:
                            continue
                        leader_name = hn if home_score > away_score else an
                        key = f"{hn}v{an}"
                        if key not in placed:
                            print(f"[RUGBY] CONDITION MET! {leader_name} — lead:{lead} | searching Polymarket...")
                        # Search all active Polymarket markets for rugby teams
                        for term in [leader_name, hn, an]:
                            markets = await fetch_gamma_markets(session, term)
                            for m in markets:
                                q = m.get("question", "").lower()
                                if not any(w in q for w in ("win", "winner", "champion")):
                                    continue
                                yes_token_id, ask = await get_yes_price(session, m)
                                if not yes_token_id or ask is None:
                                    continue
                                if ask < 0.85 or ask >= 0.96:
                                    continue
                                bet_key = f"RUGBY:{m.get('conditionId','')}:{leader_name}"
                                if bet_key in placed:
                                    continue
                                placed.add(bet_key)
                                stats["RUGBY"]["conditions_met"] += 1
                                print(f"[RUGBY] Found market: '{m.get('question','')[:60]}' @ {ask:.3f}")
                                synthetic = Trade(
                                    trade_id=f"indie_RUGBY_{int(time.time())}",
                                    proxy_wallet="", condition_id=m.get("conditionId", ""),
                                    token_id=yes_token_id, side="BUY", price=ask,
                                    size=round(config.copy_amount_usd / ask, 4),
                                    usd_size=config.copy_amount_usd, outcome="Yes",
                                    title=m.get("question", leader_name),
                                )
                                signal = Signal(trade=synthetic, copy_amount_usd=config.copy_amount_usd)
                                result = await executor.execute(signal)
                                if result.success:
                                    lbl = "[SIM]" if result.is_simulated else "[LIVE]"
                                    print(f"  {lbl} Bet placed! order_id={result.order_id}")
                                    log_bet("RUGBY", synthetic.title, "Yes", ask,
                                            config.copy_amount_usd, result.is_simulated,
                                            result.order_id or "", lead)
                                    stats["RUGBY"]["bets_placed"] += 1
                                break
            except Exception as e:
                print(f"[RUGBY] Error: {e}")
            await asyncio.sleep(1)


async def scan_cricket_loop(config: Config, executor: TradeExecutor):
    print("[CRICKET] Scanner started — <=10 runs needed, 8+ wickets remaining")
    placed = set()
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(CRICKET_URL, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    data = await r.json()
                for event in data.get("events", []):
                    if event.get("status", {}).get("type", {}).get("name") != "STATUS_IN_PROGRESS":
                        continue
                    comp              = event.get("competitions", [{}])[0]
                    situation         = comp.get("situation", {})
                    runs_needed       = situation.get("runsNeeded")
                    wickets_remaining = situation.get("wicketsRemaining")
                    batting           = situation.get("battingTeam") or {}
                    team_name         = batting.get("displayName", "")
                    if not team_name or runs_needed is None or wickets_remaining is None:
                        continue
                    if runs_needed > 10 or wickets_remaining < 8:
                        continue
                    print(f"[CRICKET] CONDITION MET! {team_name} needs {runs_needed} runs, {wickets_remaining} wickets")
                    stats["CRICKET"]["conditions_met"] += 1
                    markets = await fetch_gamma_markets(session, team_name)
                    for m in markets:
                        q = m.get("question", "").lower()
                        if not any(w in q for w in ("win", "winner", "champion")):
                            continue
                        yes_token_id, ask = await get_yes_price(session, m)
                        if not yes_token_id or ask is None:
                            continue
                        if ask < 0.85 or ask >= 0.96:
                            continue
                        bet_key = f"CRICKET:{m.get('conditionId','')}:{team_name}"
                        if bet_key in placed:
                            continue
                        placed.add(bet_key)
                        print(f"[CRICKET] Found: '{m.get('question','')[:60]}' @ {ask:.3f}")
                        synthetic = Trade(
                            trade_id=f"indie_CRICKET_{int(time.time())}",
                            proxy_wallet="", condition_id=m.get("conditionId", ""),
                            token_id=yes_token_id, side="BUY", price=ask,
                            size=round(config.copy_amount_usd / ask, 4),
                            usd_size=config.copy_amount_usd, outcome="Yes",
                            title=m.get("question", team_name),
                        )
                        signal = Signal(trade=synthetic, copy_amount_usd=config.copy_amount_usd)
                        result = await executor.execute(signal)
                        if result.success:
                            lbl = "[SIM]" if result.is_simulated else "[LIVE]"
                            print(f"  {lbl} Bet placed! order_id={result.order_id}")
                            log_bet("CRICKET", synthetic.title, "Yes", ask,
                                    config.copy_amount_usd, result.is_simulated,
                                    result.order_id or "", runs_needed)
                            stats["CRICKET"]["bets_placed"] += 1
                        break
            except Exception as e:
                print(f"[CRICKET] Error: {e}")
            await asyncio.sleep(1)


async def scan_golf_loop(config: Config, executor: TradeExecutor):
    print("[GOLF] Scanner started — 8+ stroke lead, <=9 holes remaining")
    placed = set()
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(GOLF_URL, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    data = await r.json()
                for event in data.get("events", []):
                    if event.get("status", {}).get("type", {}).get("name") != "STATUS_IN_PROGRESS":
                        continue
                    comp   = event.get("competitions", [{}])[0]
                    scored = []
                    for c in comp.get("competitors", []):
                        raw_score = c.get("score", "0")
                        try:
                            score_val = 0 if raw_score in ("E", "--", "") else int(raw_score)
                        except Exception:
                            score_val = 0
                        thru = int(c.get("status", {}).get("thru") or 0)
                        scored.append({"name": c.get("athlete", {}).get("displayName", ""),
                                       "score": score_val, "thru": thru})
                    if len(scored) < 2:
                        continue
                    scored.sort(key=lambda x: x["score"])
                    lead       = scored[1]["score"] - scored[0]["score"]
                    holes_left = 18 - scored[0]["thru"]
                    if lead < 8 or not (1 <= holes_left <= 9):
                        continue
                    golfer = scored[0]["name"]
                    print(f"[GOLF] CONDITION MET! {golfer} | lead:{lead} | {holes_left} holes left")
                    stats["GOLF"]["conditions_met"] += 1
                    markets = await fetch_gamma_markets(session, golfer)
                    for m in markets:
                        q = m.get("question", "").lower()
                        if not any(w in q for w in ("win", "winner", "champion")):
                            continue
                        yes_token_id, ask = await get_yes_price(session, m)
                        if not yes_token_id or ask is None:
                            continue
                        if ask < 0.85 or ask >= 0.96:
                            continue
                        bet_key = f"GOLF:{m.get('conditionId','')}:{golfer}"
                        if bet_key in placed:
                            continue
                        placed.add(bet_key)
                        print(f"[GOLF] Found: '{m.get('question','')[:60]}' @ {ask:.3f}")
                        synthetic = Trade(
                            trade_id=f"indie_GOLF_{int(time.time())}",
                            proxy_wallet="", condition_id=m.get("conditionId", ""),
                            token_id=yes_token_id, side="BUY", price=ask,
                            size=round(config.copy_amount_usd / ask, 4),
                            usd_size=config.copy_amount_usd, outcome="Yes",
                            title=m.get("question", golfer),
                        )
                        signal = Signal(trade=synthetic, copy_amount_usd=config.copy_amount_usd)
                        result = await executor.execute(signal)
                        if result.success:
                            lbl = "[SIM]" if result.is_simulated else "[LIVE]"
                            print(f"  {lbl} Bet placed! order_id={result.order_id}")
                            log_bet("GOLF", synthetic.title, "Yes", ask,
                                    config.copy_amount_usd, result.is_simulated,
                                    result.order_id or "", lead)
                            stats["GOLF"]["bets_placed"] += 1
                        break
            except Exception as e:
                print(f"[GOLF] Error: {e}")
            await asyncio.sleep(1)


async def scan_cs2_loop(config: Config, executor: TradeExecutor):
    if not PANDASCORE_KEY:
        print("[CS2] Skipping — set PANDASCORE_KEY to enable (free key at pandascore.co)")
        return
    print("[CS2] Scanner started — leading 11-1 at halftime")
    placed = set()
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
                        t1, t2  = teams[0].get("score", 0) or 0, teams[1].get("score", 0) or 0
                        total   = t1 + t2
                        lead    = abs(t1 - t2)
                        if total != 12 or lead < 10:
                            continue
                        leader_name = teams[0].get("name", "") if t1 > t2 else teams[1].get("name", "")
                        print(f"[CS2] CONDITION MET! {leader_name} leads {max(t1,t2)}-{min(t1,t2)} at halftime")
                        stats["CS2"]["conditions_met"] += 1
                        markets = await fetch_gamma_markets(session, leader_name)
                        for m in markets:
                            q = m.get("question", "").lower()
                            if not any(w in q for w in ("win", "winner", "champion")):
                                continue
                            yes_token_id, ask = await get_yes_price(session, m)
                            if not yes_token_id or ask is None:
                                continue
                            if ask < 0.85 or ask >= 0.96:
                                continue
                            bet_key = f"CS2:{m.get('conditionId','')}:{leader_name}"
                            if bet_key in placed:
                                continue
                            placed.add(bet_key)
                            synthetic = Trade(
                                trade_id=f"indie_CS2_{int(time.time())}",
                                proxy_wallet="", condition_id=m.get("conditionId", ""),
                                token_id=yes_token_id, side="BUY", price=ask,
                                size=round(config.copy_amount_usd / ask, 4),
                                usd_size=config.copy_amount_usd, outcome="Yes",
                                title=m.get("question", leader_name),
                            )
                            signal = Signal(trade=synthetic, copy_amount_usd=config.copy_amount_usd)
                            result = await executor.execute(signal)
                            if result.success:
                                lbl = "[SIM]" if result.is_simulated else "[LIVE]"
                                print(f"  {lbl} Bet placed! order_id={result.order_id}")
                                log_bet("CS2", synthetic.title, "Yes", ask,
                                        config.copy_amount_usd, result.is_simulated,
                                        result.order_id or "", lead)
                                stats["CS2"]["bets_placed"] += 1
                            break
            except Exception as e:
                print(f"[CS2] Error: {e}")
            await asyncio.sleep(1)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    config   = Config()
    executor = TradeExecutor(config)

    print("\n[BOT] Multi-Sport Bot — Polymarket-First")
    print("[BOT] Basketball: Q4, 15+ pt lead, <=5 min")
    print("[BOT] Football:   Q4, 21+ pt lead, <=3 min")
    print("[BOT] Hockey:     P3, 3+ goal lead, <=5 min")
    print("[BOT] Baseball:   9th inn+, 6+ run lead")
    print("[BOT] Rugby:      20+ pt lead, 2nd half, 35+ min")
    print("[BOT] Cricket:    <=10 runs needed, 8+ wickets")
    print("[BOT] Golf:       8+ stroke lead, <=9 holes left")
    print("[BOT] CS2:        leading 11-1 at halftime")
    print("[BOT] Min profit: 4%+ (price 0.85-0.96)\n")
    print("[BOT] Strategy: Polymarket markets fetched first, ESPN checked only for those games\n")

    asyncio.create_task(scan_polymarket_games_loop(config, executor))
    asyncio.create_task(scan_rugby_loop(config, executor))
    asyncio.create_task(scan_cricket_loop(config, executor))
    asyncio.create_task(scan_golf_loop(config, executor))
    asyncio.create_task(scan_cs2_loop(config, executor))

    async def heartbeat():
        n = 0
        while True:
            n += 1
            print(f"[BOT] Scanning all sports... (#{n})", flush=True)
            await asyncio.sleep(1)
    asyncio.create_task(heartbeat())

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        print_summary()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
