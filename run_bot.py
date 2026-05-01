"""
Multi-Sport Independent Scanner Bot

Scans live sports scores every second and places bets on Polymarket when
a team meets our high-confidence conditions (4%+ profit required).

Sports: Basketball, Football, Hockey, Baseball, Rugby, Cricket, Golf, CS2
"""
import asyncio, os, sys, time, json, csv
from datetime import datetime

LOG_FILE = r'C:\Users\glmar\meetscribe\bets_log.csv'


def log_bet(sport: str, title: str, outcome: str, price: float,
            amount_usd: float, simulated: bool, order_id: str, lead="-"):
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
            sport, title[:80], outcome,
            price, amount_usd, payout, profit_usd, f"{profit_pct}%",
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

PANDASCORE_KEY = ""  # Free key at pandascore.co — needed for CS2 scanner

GAMMA_API   = "https://gamma-api.polymarket.com"
CLOB_API    = "https://clob.polymarket.com"

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
bball_indie    = set()
football_indie = set()
hockey_indie   = set()
baseball_indie = set()


def clock_minutes(clock: str) -> float:
    try:
        m, s = clock.split(":")
        return int(m) + int(s) / 60
    except Exception:
        return 99.0


# ── Independent bet helper ────────────────────────────────────────────────────

async def find_and_bet_market(label: str, team_name: str, placed_set: set,
                               session: aiohttp.ClientSession,
                               config: Config, executor: TradeExecutor,
                               lead="-") -> bool:
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

        clob_ids     = m.get("clobTokenIds", [])
        outcomes_raw = m.get("outcomes", "[]")
        try:
            outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
        except Exception:
            outcomes = []
        yes_idx = next((i for i, o in enumerate(outcomes) if str(o).lower() == "yes"), None)
        if yes_idx is None or yes_idx >= len(clob_ids):
            continue
        yes_token_id = clob_ids[yes_idx]

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

        if ask >= 0.96:
            print(f"[{label}] Skip — price {ask:.2f} >= 0.96 (less than 4% profit)")
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
            log_bet(label, synthetic.title, synthetic.outcome, ask,
                    config.copy_amount_usd, result.is_simulated, result.order_id or "", lead)
        else:
            print(f"  [ERROR] {result.error}")
        return True

    print(f"[{label}] No suitable market found for '{team_name}'")
    return False


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
                })
        except Exception:
            continue
    return games


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
                        print(f"[RUGBY] {an} vs {hn} | Half:{period} {elapsed:.0f}min | Lead:{lead}")
                        if period < 2:
                            print(f"[RUGBY]  -> Skip: not 2nd half yet")
                            continue
                        if elapsed < 35:
                            print(f"[RUGBY]  -> Skip: only {elapsed:.0f} min elapsed (need 35+)")
                            continue
                        if lead < 20:
                            print(f"[RUGBY]  -> Skip: lead {lead} (need 20+)")
                            continue
                        leader      = home if home_score > away_score else away
                        leader_name = leader.get("team", {}).get("displayName", "")
                        print(f"[RUGBY]  -> CONDITION MET! {leader_name} — searching market...")
                        await find_and_bet_market("RUGBY", leader_name, rugby_placed, session, config, executor, lead)
            except Exception as e:
                print(f"[RUGBY] Error: {e}")
            await asyncio.sleep(1)


async def scan_cricket_loop(config: Config, executor: TradeExecutor):
    print("[CRICKET] Scanner started — <=10 runs needed, 8+ wickets remaining")
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(CRICKET_URL, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    data = await r.json()
                live_found = False
                for event in data.get("events", []):
                    if event.get("status", {}).get("type", {}).get("name") != "STATUS_IN_PROGRESS":
                        continue
                    live_found = True
                    comp              = event.get("competitions", [{}])[0]
                    situation         = comp.get("situation", {})
                    runs_needed       = situation.get("runsNeeded")
                    wickets_remaining = situation.get("wicketsRemaining")
                    batting           = situation.get("battingTeam") or {}
                    team_name         = batting.get("displayName", "unknown")
                    print(f"[CRICKET] {team_name} needs {runs_needed} runs | {wickets_remaining} wickets left")
                    if runs_needed is None or wickets_remaining is None:
                        print(f"[CRICKET]  -> Skip: no situation data")
                        continue
                    if runs_needed > 10:
                        print(f"[CRICKET]  -> Skip: {runs_needed} runs needed (need <=10)")
                        continue
                    if wickets_remaining < 8:
                        print(f"[CRICKET]  -> Skip: {wickets_remaining} wickets left (need 8+)")
                        continue
                    print(f"[CRICKET]  -> CONDITION MET! {team_name} — searching market...")
                    if team_name and team_name != "unknown":
                        await find_and_bet_market("CRICKET", team_name, cricket_placed, session, config, executor, runs_needed)
                if not live_found:
                    print("[CRICKET] No live games")
            except Exception as e:
                print(f"[CRICKET] Error: {e}")
            await asyncio.sleep(1)


async def scan_golf_loop(config: Config, executor: TradeExecutor):
    print("[GOLF] Scanner started — 8+ stroke lead, <=9 holes remaining")
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(GOLF_URL, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    data = await r.json()
                live_found = False
                for event in data.get("events", []):
                    if event.get("status", {}).get("type", {}).get("name") != "STATUS_IN_PROGRESS":
                        continue
                    live_found = True
                    comp   = event.get("competitions", [{}])[0]
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
                    lead       = scored[1]["score"] - scored[0]["score"]
                    holes_left = 18 - scored[0]["thru"]
                    print(f"[GOLF] Leader: {scored[0]['name']} | Lead:{lead} strokes | {holes_left} holes left")
                    if lead < 8:
                        print(f"[GOLF]  -> Skip: lead {lead} (need 8+)")
                        continue
                    if not (1 <= holes_left <= 9):
                        print(f"[GOLF]  -> Skip: {holes_left} holes left (need 1-9)")
                        continue
                    print(f"[GOLF]  -> CONDITION MET! {scored[0]['name']} — searching market...")
                    await find_and_bet_market("GOLF", scored[0]["name"], golf_placed, session, config, executor, lead)
                if not live_found:
                    print("[GOLF] No live tournaments")
            except Exception as e:
                print(f"[GOLF] Error: {e}")
            await asyncio.sleep(1)


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
                        total    = t1_score + t2_score
                        lead     = abs(t1_score - t2_score)
                        print(f"[CS2] {teams[0].get('name','')} {t1_score}-{t2_score} {teams[1].get('name','')} | Rounds:{total}")
                        if total != 12:
                            print(f"[CS2]  -> Skip: not at halftime ({total} rounds)")
                            continue
                        if lead < 10:
                            print(f"[CS2]  -> Skip: lead {lead} (need 10+ for 11-1)")
                            continue
                        leader = teams[0] if t1_score > t2_score else teams[1]
                        print(f"[CS2]  -> CONDITION MET! {leader.get('name','')} — searching market...")
                        await find_and_bet_market("CS2", leader.get("name", ""), cs2_placed, session, config, executor, lead)
            except Exception as e:
                print(f"[CS2] Error: {e}")
            await asyncio.sleep(1)


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
                games = await _espn_games(session, urls)
                live  = [g for g in games if g["status"] == "STATUS_IN_PROGRESS"]
                if not live:
                    print("[BBALL] No live games")
                for g in live:
                    lead = abs(g["home_score"] - g["away_score"])
                    mins = clock_minutes(g["clock"])
                    print(f"[BBALL] {g['away_name']} vs {g['home_name']} | Q{g['period']} {g['clock']} | Lead:{lead}")
                    if g["period"] != 4:
                        print(f"[BBALL]  -> Skip: not Q4 yet")
                        continue
                    if mins > 5:
                        print(f"[BBALL]  -> Skip: {mins:.1f} min left (need <=5)")
                        continue
                    if lead < 15:
                        print(f"[BBALL]  -> Skip: lead {lead} (need 15+)")
                        continue
                    leader = g["home_name"] if g["home_score"] > g["away_score"] else g["away_name"]
                    print(f"[BBALL]  -> CONDITION MET! {leader} — searching market...")
                    await find_and_bet_market("BBALL", leader, bball_indie, session, config, executor, lead)
            except Exception as e:
                print(f"[BBALL] Error: {e}")
            await asyncio.sleep(1)


async def scan_football_indie_loop(config: Config, executor: TradeExecutor):
    urls = [
        "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
        "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard",
    ]
    print("[FOOTBALL] Independent scanner started — Q4, 21+ pt lead, <=3 min (NFL/NCAA)")
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                games = await _espn_games(session, urls)
                live  = [g for g in games if g["status"] == "STATUS_IN_PROGRESS"]
                if not live:
                    print("[FOOTBALL] No live games")
                for g in live:
                    lead = abs(g["home_score"] - g["away_score"])
                    mins = clock_minutes(g["clock"])
                    print(f"[FOOTBALL] {g['away_name']} vs {g['home_name']} | Q{g['period']} {g['clock']} | Lead:{lead}")
                    if g["period"] != 4:
                        print(f"[FOOTBALL]  -> Skip: not Q4 yet")
                        continue
                    if mins > 3:
                        print(f"[FOOTBALL]  -> Skip: {mins:.1f} min left (need <=3)")
                        continue
                    if lead < 21:
                        print(f"[FOOTBALL]  -> Skip: lead {lead} (need 21+)")
                        continue
                    leader = g["home_name"] if g["home_score"] > g["away_score"] else g["away_name"]
                    print(f"[FOOTBALL]  -> CONDITION MET! {leader} — searching market...")
                    await find_and_bet_market("FOOTBALL", leader, football_indie, session, config, executor, lead)
            except Exception as e:
                print(f"[FOOTBALL] Error: {e}")
            await asyncio.sleep(1)


async def scan_hockey_indie_loop(config: Config, executor: TradeExecutor):
    urls = [
        "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard",
        "https://site.api.espn.com/apis/site/v2/sports/hockey/college-hockey/scoreboard",
    ]
    print("[HOCKEY] Independent scanner started — P3, 3+ goal lead, <=5 min (NHL/college)")
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                games = await _espn_games(session, urls)
                live  = [g for g in games if g["status"] == "STATUS_IN_PROGRESS"]
                if not live:
                    print("[HOCKEY] No live games")
                for g in live:
                    lead = abs(g["home_score"] - g["away_score"])
                    mins = clock_minutes(g["clock"])
                    print(f"[HOCKEY] {g['away_name']} vs {g['home_name']} | P{g['period']} {g['clock']} | Lead:{lead}")
                    if g["period"] != 3:
                        print(f"[HOCKEY]  -> Skip: not P3 yet")
                        continue
                    if mins > 5:
                        print(f"[HOCKEY]  -> Skip: {mins:.1f} min left (need <=5)")
                        continue
                    if lead < 3:
                        print(f"[HOCKEY]  -> Skip: lead {lead} (need 3+)")
                        continue
                    leader = g["home_name"] if g["home_score"] > g["away_score"] else g["away_name"]
                    print(f"[HOCKEY]  -> CONDITION MET! {leader} — searching market...")
                    await find_and_bet_market("HOCKEY", leader, hockey_indie, session, config, executor, lead)
            except Exception as e:
                print(f"[HOCKEY] Error: {e}")
            await asyncio.sleep(1)


async def scan_baseball_indie_loop(config: Config, executor: TradeExecutor):
    urls = [
        "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard",
        "https://site.api.espn.com/apis/site/v2/sports/baseball/college-baseball/scoreboard",
    ]
    print("[BASEBALL] Independent scanner started — 9th inn+, 6+ run lead (MLB/college)")
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                games = await _espn_games(session, urls)
                live  = [g for g in games if g["status"] == "STATUS_IN_PROGRESS"]
                if not live:
                    print("[BASEBALL] No live games")
                for g in live:
                    lead = abs(g["home_score"] - g["away_score"])
                    print(f"[BASEBALL] {g['away_name']} vs {g['home_name']} | Inn{g['period']} | Lead:{lead}")
                    if g["period"] < 9:
                        print(f"[BASEBALL]  -> Skip: inning {g['period']} (need 9+)")
                        continue
                    if lead < 6:
                        print(f"[BASEBALL]  -> Skip: lead {lead} (need 6+)")
                        continue
                    leader = g["home_name"] if g["home_score"] > g["away_score"] else g["away_name"]
                    print(f"[BASEBALL]  -> CONDITION MET! {leader} — searching market...")
                    await find_and_bet_market("BASEBALL", leader, baseball_indie, session, config, executor, lead)
            except Exception as e:
                print(f"[BASEBALL] Error: {e}")
            await asyncio.sleep(1)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    config   = Config()
    executor = TradeExecutor(config)

    print("\n[BOT] Multi-Sport Scanner Bot")
    print("[BOT] Basketball: Q4, 15+ pt lead, <=5 min (NBA/EuroLeague/NCAA/WNBA)")
    print("[BOT] Football:   Q4, 21+ pt lead, <=3 min (NFL/NCAA)")
    print("[BOT] Hockey:     P3, 3+ goal lead, <=5 min (NHL/college)")
    print("[BOT] Baseball:   9th inn+, 6+ run lead (MLB/college)")
    print("[BOT] Rugby:      20+ pt lead, 2nd half, 35+ min elapsed")
    print("[BOT] Cricket:    <=10 runs needed, 8+ wickets remaining")
    print("[BOT] Golf:       8+ stroke lead, <=9 holes left")
    print("[BOT] CS2:        leading 11-1 at halftime")
    print("[BOT] Min profit: 4%+ (price must be 0.85-0.96)\n")

    asyncio.create_task(scan_rugby_loop(config, executor))
    asyncio.create_task(scan_cricket_loop(config, executor))
    asyncio.create_task(scan_golf_loop(config, executor))
    asyncio.create_task(scan_cs2_loop(config, executor))
    asyncio.create_task(scan_basketball_indie_loop(config, executor))
    asyncio.create_task(scan_football_indie_loop(config, executor))
    asyncio.create_task(scan_hockey_indie_loop(config, executor))
    asyncio.create_task(scan_baseball_indie_loop(config, executor))

    async def heartbeat():
        n = 0
        while True:
            n += 1
            print(f"[BOT] Scanning all sports... (#{n})", flush=True)
            await asyncio.sleep(1)
    asyncio.create_task(heartbeat())

    await asyncio.Event().wait()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
