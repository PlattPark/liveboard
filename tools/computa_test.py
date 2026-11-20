#!/usr/bin/env python3
"""Checks for computa.py that need no Slack, GitHub or Square:  python3 tools/computa_test.py

Each block is a thing that went wrong on the wall or in the bot in Nov 2026 and the behaviour that replaced it.
Nothing here touches the network; git checks run in throwaway folders."""
import os, sys, json, copy, shutil, tempfile, subprocess, importlib.util
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for k in ("SLACK_BOT_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "SQUARE_ACCESS_TOKEN", "SPOTHOPPER_EMAIL",
          "SPOTHOPPER_PASSWORD", "GITHUB_ACTIONS", "COMPUTA_CAUGHT_UP"):
    os.environ.pop(k, None)
os.environ["COMPUTA_TIMERS"] = os.path.join(tempfile.mkdtemp(prefix="computa_t_"), "timers.json")

def load():
    spec = importlib.util.spec_from_file_location("computa_under_test", os.path.join(ROOT, "computa.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    m.slack = lambda *a, **k: {"ok": True}
    m.gh = lambda *a, **k: None
    m.square = None
    m.spothopper = None
    return m

c = load()
PASS, FAIL = [0], []
def check(name, got, want=True):
    if got == want: PASS[0] += 1
    else: FAIL.append("%s\n      got  %r\n      want %r" % (name, got, want))

def wall():
    """A wall like the one on Nov 18 2026."""
    def b(name, price, p10, vessel="tank10", oz=20000, **kw):
        d = {"id": c.norm(name), "name": name, "price": price, "price10": p10, "color": "#ccaa44", "vessel": vessel,
             "vesselLabel": {"tank10": "10 BBL", "tank20": "20 BBL", "keg-half": "1/2 BBL"}[vessel], "remainingOz": oz,
             "abv": 5.0, "style": "Ale", "levelAt": "2026-10-19T18:10:29.035Z"}
        d.update(kw); return d
    return [b("Platty Lite", 6.5, 4.75, "tank20", 10316), b("Astronaut Amber", 7.5, 5.5), b("Nutorious", 8.5, 6.25),
            b("Madagascar Dream", 8.0, 6.0, "tank20", 25792), b("Grandma's Pumpkin Pie", 8.0, 6.0), b("Witbier", 7.5, 5.5),
            b("Tropical Snow Dance", 8.5, 6.25), b("Nadare", 7.5, 5.5, "keg-half", 1091, sash="last keg"),
            b("Phaded", 7.5, 5.5), b("Half Acre Waybird", 8.5, 5.25, "keg-half", 1984, guest=True, sash="guest tap"),
            b("Plattmosphere", 8.5, 6.25, "tank20", 7936)]

# ---- 1. levels as people type them -------------------------------------------------------------------------------
def lvl(text, vessel="tank20"):
    beer = {"name": "Plattmosphere", "vessel": vessel, "vesselLabel": "20 BBL", "remainingOz": 1}
    out = c.read_level(text, beer)
    return beer["remainingOz"], beer["vessel"], beer["vesselLabel"], out

check("1/2bbl in a 1/2bbl is a full half-barrel keg", lvl("Plattmo is back on, 1/2bbl in a 1/2bbl")[:3], (1984, "keg-half", "1/2 BBL"))
check("1/2 bbl in a 1/2 bbl (spaces)", lvl("plattmo is back on, 1/2 bbl in a 1/2 bbl")[:3], (1984, "keg-half", "1/2 BBL"))
check("half barrel", lvl("waybird is back on, half barrel")[:3], (1984, "keg-half", "1/2 BBL"))
check(".5bbl is half a barrel, not five", lvl("nadare is back on, .5bbl")[:3], (1984, "keg-half", "1/2 BBL"))
check("0.5bbl", lvl("nadare is back on, 0.5bbl")[:3], (1984, "keg-half", "1/2 BBL"))
check("sixtel", lvl("x is back on, 1/6bbl")[:2], (661, "keg-half"))
check("6bbl in a 10bbl", lvl("chela is back on, 6bbl in a 10bbl")[:3], (23808, "tank10", "10 BBL"))
check("9.3bbl in a 10bbl tank", lvl("9.3bbl in a 10bbl tank")[:3], (36902, "tank10", "10 BBL"))
check("12 bbl in a 20 bbl", lvl("platty lite is back on, 12 bbl in a 20 bbl", "tank10")[:3], (47616, "tank20", "20 BBL"))
check("18bbl with no size keeps the 20", lvl("plattmo is back on, 18bbl")[:3], (71424, "tank20", "20 BBL"))
check("more than the vessel holds is capped", lvl("x is back on, 12bbl in a 10bbl")[:3], (39680, "tank10", "10 BBL"))
check("an odd size keeps the vessel", lvl("x is back on, 2bbl in a 15bbl")[:3], (7936, "tank20", "20 BBL"))
check("no level in the message changes nothing", lvl("plattmo is back on"), (1, "tank20", "20 BBL", ""))
r = lvl("plattmo is back on, 18bbl", "keg-half")
check("18bbl said about a keg beer: it is in the 20 now", r[:3], (71424, "tank20", "20 BBL"))
r = lvl("plattmo is back on, 7bbl", "keg-half")
check("7bbl said about a keg beer: drawn as a 10, and it says so", (r[1], "in a 20bbl" in r[3]), ("tank10", True))
check("a price is not a level", c.LEVEL_RE.search("waybird 10oz is now $6.25") is None)
check("barrel-aged is not a level", c.LEVEL_RE.search("New beer: Oak Stout, bourbon barrel aged, 9%") is None)

# ---- 2. the 10oz price follows the wall ---------------------------------------------------------------------------
w = wall(); way = next(b for b in w if b["name"] == "Half Acre Waybird")
check("an $8.50 pint is a $6.25 10oz today", c.ten_oz_for(way, w), 6.25)
check("a pint price nobody else has falls back to the ladder", c.ten_oz_for({"price": 9.0}, w), 6.5)
check("a pint price off the ladder gives nothing", c.ten_oz_for({"price": 7.0}, w), None)
note = c.refresh_ten_oz(way, w)
check("coming back moves a stale 10oz onto the ladder", (way["price10"], ":moneybag:" in note, "$5.25" in note), (6.25, True, True))
check("and leaves a current one alone", c.refresh_ten_oz(next(b for b in w if b["name"] == "Nutorious"), w), "")

# ---- 3. "back on" end to end: price, level, and the reply is shown --------------------------------------------------
data = {"beers": [b for b in wall() if b["name"] not in ("Plattmosphere",)],
        "recent": [dict(next(b for b in wall() if b["name"] == "Plattmosphere"), price10=5.25, offSince="2026-11-10")]}
msg = {"ts": "1.0", "text": "Plattmo is back on, 1/2bbl in a 1/2bbl"}
change, rep = c.handle_one(msg, data, [], "C1", "back", "Plattmo", msg["text"])
pm = next(b for b in data["beers"] if b["name"] == "Plattmosphere")
check("Plattmosphere back on a keg: vessel, level, 10oz", (pm["vessel"], pm["remainingOz"], pm["price10"]), ("keg-half", 1984, 6.25))
check("the change line names the price", "10oz $6.25" in change)
check("the price note is on its own line so it is posted, not swallowed by a tick", "\n:moneybag:" in rep[2])

# a keg beer that kicked and comes back with no level given is a new, full keg, and is no longer on its "last keg"
old_keg = dict(next(b for b in wall() if b["name"] == "Nadare"), offSince="2026-11-12")      # 1091 oz, sash "last keg", levelAt Oct 19
data = {"beers": [b for b in wall() if b["name"] != "Nadare"], "recent": [old_keg]}
c.handle_one({"ts": "1.5", "text": "nadare is back on"}, data, [], "C1", "back", "nadare", "nadare is back on")
nd = next(b for b in data["beers"] if b["name"] == "Nadare")
check("a keg beer back on with no level: a full keg, measured now, last-keg sash gone",
      (nd["remainingOz"], nd.get("sash"), nd["levelAt"] > "2026-11-18"), (1984, None, True))
old_tank = dict(next(b for b in wall() if b["name"] == "Witbier"), offSince="2026-11-12")
data = {"beers": [b for b in wall() if b["name"] != "Witbier"], "recent": [old_tank]}
c.handle_one({"ts": "1.6", "text": "witbier is back on"}, data, [], "C1", "back", "witbier", "witbier is back on")
wt = next(b for b in data["beers"] if b["name"] == "Witbier")
check("a tank beer back on with no level keeps its number until someone measures it", (wt["remainingOz"], wt["levelAt"]), (20000, "2026-10-19T18:10:29.035Z"))
data = {"beers": wall(), "recent": []}
c.handle_one({"ts": "1.7", "text": "phaded is on last keg"}, data, [], "C1", "lastkeg", "phaded", None)
ph = next(b for b in data["beers"] if b["name"] == "Phaded")
check("'last keg' counts as a measurement, so an older sheet reading can't redraw it as a tank",
      (ph["vessel"], ph["sash"], ph["levelAt"] > "2026-11-18"), ("keg-half", "last keg", True))
stale = {"sheet": "November 26", "tab": "wk5", "updated": "2026-11-16T19:58:54.111Z", "levels": [{"name": "Phaded", "sv": "5", "bbls": 8}]}
changes, summary = c.cellar_apply(stale, data, {})
check("...which is what happened to Nadare on Nov 18", (ph["vessel"], changes), ("keg-half", []))

data = {"beers": wall(), "recent": []}
change, rep = c.handle_one({"ts": "2.0", "text": "86 nadare"}, data, [], "C1", "remove", "nadare", None)
check("an 86 says where it lands without promising the website", ("website" in rep[2], "the board and the menu" in rep[2]), (False, True))
class _Site:
    @staticmethod
    def enabled(): return True
c.spothopper = _Site
check("...and names the website when its sync is on", c.reaches(), "the board, the menu and the website")
c.spothopper = None

# ---- 4. a new beer: style casing and the ladder ---------------------------------------------------------------------
data = {"beers": wall(), "recent": []}
out = c.handle({"ts": "3.0", "text": "New beer: Test Haze — hazy ipa, 6.5%, juicy · guest tap"}, data, [], "C0AQ68G7DRB")
nb = next((b for b in data["beers"] if b["name"] == "Test Haze"), None)
check("a new beer goes up", nb is not None)
if nb:
    check("style is 'Hazy IPA', never 'Hazy Ipa'", nb["style"], "Hazy IPA")
    check("its 10oz comes off the ladder for its pint price", nb["price10"], c.ten_oz_for(nb, data["beers"]))
    check("the reply shows the 10oz so someone can correct it", "10oz $" in (out[1][2] if out and out[1] else ""))
import newbeer
check("style_case keeps acronyms", [newbeer.style_case(s) for s in ("hazy ipa", "West Coast IPA", "ddh neipa", "märzen", "Pale Ale")],
      ["Hazy IPA", "West Coast IPA", "DDH NEIPA", "Märzen", "Pale Ale"])

# ---- 5. register names -> whose tank, how many ounces -----------------------------------------------------------------
w = wall()
POS = {
    "\U0001F948 Platty Lite Pint": ("Platty Lite", 16, "pint"), "\U0001F948 Platty Lite 10oz": ("Platty Lite", 10, "10oz"),
    "\U0001F948 Platty Lite Crowler": ("Platty Lite", 32, "crowler"), "\U0001F948 Wednesday Platty Lite Pitcher": ("Platty Lite", 32, "pitcher"),
    "Phaded": ("Phaded", 16, "pint"), "Phaded (10 oz)": ("Phaded", 10, "10oz"), "Phaded Crowler": ("Phaded", 32, "crowler"),
    "Witbier": ("Witbier", 16, "pint"), "Witbier 10oz.": ("Witbier", 10, "10oz"),
    "\U0001F947 Pistachio Cream Ale": ("Nutorious", 16, "pint"), "\U0001F947 Pistachio Cream (10oz)": ("Nutorious", 10, "10oz"),
    "\U0001F947 Pistachio Cream Ale (Crowler)": ("Nutorious", 32, "crowler"), "Pistachio Taster": ("Nutorious", 4, "taster"),
    "\U0001F947 Pistachio 4-Pack": None,
    "Madagascar Dream Cream Ale NITRO Pint": ("Madagascar Dream", 16, "pint"), "Madagascar Dream 10oz.": ("Madagascar Dream", 10, "10oz"),
    "Madagascar Taster": ("Madagascar Dream", 4, "taster"),
    "Grandma's Pumpkin Pie Pumpkin Ale NITRO Pint": ("Grandma's Pumpkin Pie", 16, "pint"), "Nitro Pumpkin Pint\U0001F383": ("Grandma's Pumpkin Pie", 16, "pint"),
    "Grandma's Pumpkin Pie 10oz.": ("Grandma's Pumpkin Pie", 10, "10oz"), "Pumpkin 10 Oz \U0001F383": ("Grandma's Pumpkin Pie", 10, "10oz"),
    "Pumpkin taster \U0001F383": ("Grandma's Pumpkin Pie", 4, "taster"),
    "Tropical Snow Dance Pint": ("Tropical Snow Dance", 16, "pint"), "Tropical Snow Dance 10oz": ("Tropical Snow Dance", 10, "10oz"),
    "Tropical Taster": ("Tropical Snow Dance", 4, "taster"), "Tropical Snowdance IPA - 4 Pack": None,
    "Nadare Pint": ("Nadare", 16, "pint"), "Nadare 10oz": ("Nadare", 10, "10oz"), "Nadare Crowler": ("Nadare", 32, "crowler"),
    "Astronaut Amber Pint": ("Astronaut Amber", 16, "pint"), "Astronaut Amber 10oz": ("Astronaut Amber", 10, "10oz"),
    "Astronaut Amber Ale Crowler": ("Astronaut Amber", 32, "crowler"), "Astronaut Taster": ("Astronaut Amber", 4, "taster"),
    "Astro Amber (4pk)": None,
    "\U0001F948 Plattmosphere Pint": ("Plattmosphere", 16, "pint"), "\U0001F948 Plattmosphere (10oz)": ("Plattmosphere", 10, "10oz"),
    "\U0001F948 Plattmosphere Crowler": ("Plattmosphere", 32, "crowler"), "\U0001F948 Plattmosphere Taster": ("Plattmosphere", 4, "taster"),
    "\U0001F948 Plattmosphere 4pk": None,
    "GUEST Verboten Stealth Haze 16oz.": ("Half Acre Waybird", 16, "pint"), "GUEST Verboten Stealth Haze 10oz.": ("Half Acre Waybird", 10, "10oz"),
    "GUEST Half Acre Waybird 16oz.": ("Half Acre Waybird", 16, "pint"),
    "Wednesday Special Pitcher": (None, 32, "pitcher"), "Pitcher (32 oz)": (None, 32, "pitcher"),
    "Taster Paddle": None, "Chela Pint": None, "Chela Morena 4pk": None, "Pacific Detour Pint": None, "Mango Wheat Taster": None,
    "Turkey": None, "Red Wine": None, "Draft Cocktail": None, "Pint & Glass": None, "Fountain Soda": None, "Hard Kombucha": None,
    "Keg Deposit": None, "N/A Beer": None, "Dry Cider": None, "Italian Job": None, "Pumpkin Bread": None, "Pistachio Muffin": None,
    "$12 Burrito and Crowler \U0001F32F": None, "Build Your Own Case": None, "Witbier Keg": None, "": None,
}
for name, want in POS.items():
    check("register line %r" % name, c.pos_line(name, w), want)
check("every beer on the wall has at least one register name that reaches it",
      sorted(set(v[0] for v in POS.values() if v and v[0])), sorted(b["name"] for b in w))

# ---- 6. the sales ledger: rebuilt from the register, never restarted at zero -----------------------------------------
T0 = datetime(2026, 11, 18, 20, 0, 0, tzinfo=timezone.utc)
clock = {"t": T0}
class FakeDT(datetime):
    @classmethod
    def now(cls, tz=None): return clock["t"].astimezone(tz) if tz else clock["t"].replace(tzinfo=None)
class FakeTime:
    @staticmethod
    def time(): return clock["t"].timestamp()
    @staticmethod
    def sleep(x): pass
orders = []
def order(when, *lines):
    orders.append({"closed_at": when.isoformat().replace("+00:00", "Z"), "line_items": [{"name": n, "quantity": str(q)} for n, q in lines]})
class Sq:
    LOCATION = "L"
    calls = 0
    def enabled(self): return True
    def search(self, q): return []
    def sold_out_state(self, o): return False
    def call(self, path, method="GET", body=None):
        Sq.calls += 1
        f = body["query"]["filter"]["date_time_filter"]["closed_at"]
        a, b = c._iso(f["start_at"]), c._iso(f["end_at"])
        return {"orders": [o for o in orders if a <= c._iso(o["closed_at"]) < b]}
c.datetime, c.time, c.square, c.DRY = FakeDT, FakeTime, Sq(), False
c._mt_now = lambda: clock["t"] - timedelta(hours=7)
w = wall()
for b in w: b["levelAt"] = "2026-11-16T19:58:54.111Z"            # Greg's Monday sheet
data = {"beers": w, "recent": []}
order(datetime(2026, 11, 16, 18, 0, tzinfo=timezone.utc), ("Phaded", 3))                                   # before the count: not counted
order(datetime(2026, 11, 17, 1, 0, tzinfo=timezone.utc), ("Phaded", 2), ("\U0001F947 Pistachio Cream Ale", 1), ("Turkey", 1))
order(datetime(2026, 11, 18, 2, 0, tzinfo=timezone.utc), ("GUEST Verboten Stealth Haze 16oz.", 4), ("Witbier 10oz.", 1), ("Wednesday Special Pitcher", 1))
state = {"shadow": {}}                                              # a lost ledger: no cursor, nothing counted
c.shadow_sales(state, data)
led = state["shadow"]["ledger"]
check("a lost ledger is rebuilt from the register back to each tank's measurement",
      (led["Phaded"]["oz"], led["Nutorious"]["oz"], led["Half Acre Waybird"]["oz"], led["Witbier"]["oz"]), (32, 16, 64, 10))
check("pours rung before the measurement are not counted", led["Phaded"]["pints"], 2)
clock["t"] = T0 + timedelta(minutes=40); open(os.environ["COMPUTA_TIMERS"], "w").write("{}")
order(T0 + timedelta(minutes=10), ("Phaded", 1), ("Pitcher (32 oz)", 2))
c.shadow_sales(state, data)
check("then it counts forward from where it stopped", (state["shadow"]["ledger"]["Phaded"]["oz"], state["shadow"]["pitcher_oz"]), (48, 64))
# Greg re-measures one tank; the sheet is read two hours after he saved it
clock["t"] = T0 + timedelta(hours=6); open(os.environ["COMPUTA_TIMERS"], "w").write("{}")
order(T0 + timedelta(hours=3, minutes=30), ("Phaded", 5))
order(T0 + timedelta(hours=4, minutes=30), ("Phaded", 2))
state["shadow"]["orders_since"] = (T0 + timedelta(hours=5)).isoformat()      # the cursor is already past both orders
next(b for b in w if b["name"] == "Phaded")["levelAt"] = (T0 + timedelta(hours=4)).isoformat()
c.shadow_sales(state, data)
check("a tank measured in the past starts from what sold since that measurement, not from zero",
      (state["shadow"]["ledger"]["Phaded"]["oz"], state["shadow"]["ledger"]["Phaded"]["base"] == (T0 + timedelta(hours=4)).isoformat()), (32, True))
check("the other tanks keep their count through that", state["shadow"]["ledger"]["Half Acre Waybird"]["oz"], 64)
# A ledger kept by the old register matching: Plattmosphere's base still matches its level, so nothing would restart
# its count - and the old matching never counted "🥈 Plattmosphere Pint". The version stamp rebuilds it, once.
clock["t"] = T0 + timedelta(hours=7); open(os.environ["COMPUTA_TIMERS"], "w").write("{}")
next(b for b in w if b["name"] == "Plattmosphere")["levelAt"] = (T0 + timedelta(hours=1)).isoformat()
order(T0 + timedelta(minutes=50), ("\U0001F948 Plattmosphere Pint", 9))                                   # before its level: not counted
order(T0 + timedelta(hours=2), ("\U0001F948 Plattmosphere Pint", 3), ("\U0001F948 Plattmosphere (10oz)", 1))
old = {"shadow": {"orders_since": (T0 + timedelta(hours=6, minutes=30)).isoformat(), "pitcher_oz": 64,
                  "ledger": {b["name"]: {"base": b.get("levelAt") or "", "oz": 0, "pints": 0} for b in w}}}
c.shadow_sales(old, data)
check("a count kept by the old register matching is rebuilt, though its base never changed",
      (old["shadow"]["ledger"]["Plattmosphere"]["oz"], old["shadow"]["ledger"]["Plattmosphere"]["pints"], old["shadow"].get("ledger_v")), (58, 3, c.LEDGER_V))
check("the rebuild reaches the other beers too, and keeps the pitchers already counted",
      (old["shadow"]["ledger"]["Half Acre Waybird"]["oz"], old["shadow"]["pitcher_oz"]), (64, 64))
clock["t"] = T0 + timedelta(hours=8); open(os.environ["COMPUTA_TIMERS"], "w").write("{}")
order(T0 + timedelta(hours=7, minutes=30), ("\U0001F948 Plattmosphere Pint", 1))
c.shadow_sales(old, data)
check("it is rebuilt once: the next pass counts forward from there", old["shadow"]["ledger"]["Plattmosphere"]["oz"], 74)

# Kegs follow the register (Nov 19 2026). Tanks do not.
check("without the wall's file version in hand, nothing above ever wrote a keg", next(b for b in w if b["name"] == "Half Acre Waybird")["remainingOz"], 1984)
commits, posts = [], []
_commit, _slack = c.commit_beers, c.slack
c.commit_beers = lambda d, sha, msg: (commits.append((json.loads(json.dumps(d)), sha, msg)) or True)
c.slack = lambda method, **kw: (posts.append(kw.get("text", "")) or {"ok": True})
kw_ = wall()
for b in kw_: b["levelAt"] = T0.isoformat()
keg = next(b for b in kw_ if b["name"] == "Plattmosphere"); keg.update(vessel="keg-half", vesselLabel="1/2 BBL", remainingOz=1984)
last = next(b for b in kw_ if b["name"] == "Nadare"); last["remainingOz"] = 100
tank = next(b for b in kw_ if b["name"] == "Phaded")
kdata, ks = {"beers": kw_, "recent": []}, {"shadow": {}}
del orders[:]
clock["t"] = T0 + timedelta(hours=1); open(os.environ["COMPUTA_TIMERS"], "w").write("{}")
order(T0 + timedelta(minutes=20), ("\U0001F948 Plattmosphere Pint", 5), ("Nadare Pint", 4), ("Phaded", 6))
c.shadow_sales(ks, kdata, "sha1")
now1 = (T0 + timedelta(hours=1)).isoformat()
check("a keg drops by what the register rang, and is dated to that pass", (keg["remainingOz"], keg["levelAt"]), (1984 - 80, now1))
check("its count restarts from there", ks["shadow"]["ledger"]["Plattmosphere"], {"base": now1, "oz": 0, "pints": 0})
check("a last keg stops at four pints - it is never drawn empty while it is on the wall", last["remainingOz"], 64)
check("a tank is left to Greg's count, and its sales are still tallied", (tank["remainingOz"], ks["shadow"]["ledger"]["Phaded"]["oz"]), (20000, 96))
check("one write carries every keg, against the file version that was read",
      (len(commits), commits[0][1], sorted(b["name"] for b in commits[0][0]["beers"] if b["levelAt"] == now1)), (1, "sha1", ["Nadare", "Plattmosphere"]))
clock["t"] = T0 + timedelta(hours=1, minutes=16)
order(T0 + timedelta(hours=1, minutes=5), ("\U0001F948 Plattmosphere Pint", 4))
c.shadow_sales(ks, kdata, "sha2")
check("kegs are written at most about twice an hour", (len(commits), keg["remainingOz"]), (1, 1904))
clock["t"] = T0 + timedelta(hours=1, minutes=32)
c.shadow_sales(ks, kdata, "sha2")
check("the next write carries what was rung in between", (len(commits), keg["remainingOz"]), (2, 1904 - 64))
clock["t"] = T0 + timedelta(hours=3); keg["remainingOz"] = 40
order(T0 + timedelta(hours=2), ("\U0001F948 Plattmosphere Pint", 5))
c.shadow_sales(ks, kdata, "sha3")
check("more rung than the keg held: a fresh keg is on, and the count carries into it", keg["remainingOz"], 40 - 80 + 1984)
check("#board is told which keg was assumed", (len(posts), "Plattmosphere" in (posts or [""])[0]), (1, True))
c.commit_beers = lambda d, sha, msg: False
clock["t"] = T0 + timedelta(hours=4)
order(T0 + timedelta(hours=3, minutes=30), ("\U0001F948 Plattmosphere Pint", 3))
c.shadow_sales(ks, kdata, "sha4")
check("if the write fails the wall does not move, and the count is kept for the next pass",
      (keg["remainingOz"], ks["shadow"]["ledger"]["Plattmosphere"]["oz"]), (1944, 48))
c.KEG_MODE = "off"; c.commit_beers = lambda d, sha, msg: (commits.append((d, sha, msg)) or True)
clock["t"] = T0 + timedelta(hours=5)
c.shadow_sales(ks, kdata, "sha5")
check("KEG_LEVELS=off leaves the kegs alone", (len(commits), keg["remainingOz"]), (3, 1944))
c.KEG_MODE, c.commit_beers, c.slack = "on", _commit, _slack
c.datetime, c.time = datetime, __import__("time")

# ---- 7. Greg's sheet ---------------------------------------------------------------------------------------------------
w = wall()
next(b for b in w if b["name"] == "Plattmosphere").update(vessel="keg-half", vesselLabel="1/2 BBL", remainingOz=1984, levelAt="2026-11-17T18:32:27+00:00")
data = {"beers": w}
reading = {"sheet": "November 26", "tab": "wk 2", "updated": "2026-11-16T19:58:54.111Z", "levels": [
    {"name": "Tropic", "sv": "8", "bbls": 7}, {"name": "Astronaut", "sv": "3", "bbls": 6.8}, {"name": "Wit", "sv": "1", "bbls": 3.6},
    {"name": "Phaded", "sv": "5", "bbls": 5.8}, {"name": "Chela", "sv": "", "bbls": ""}, {"name": "Platty Lite", "sv": "6", "bbls": 14.4},
    {"name": "Cream", "sv": "4", "bbls": 18.2}, {"name": "Pumpkin", "sv": "2", "bbls": 3.6}, {"name": "Nadare", "sv": "", "bbls": ""},
    {"name": "Pistachio", "sv": "7", "bbls": 1.3}, {"name": "Plattmo", "sv": "", "bbls": ""}, {"name": "", "sv": "", "bbls": ""}]}
st = {}
changes, summary = c.cellar_apply(reading, data, st)
bbl = lambda n: round(next(b for b in w if b["name"] == n)["remainingOz"] / 3968.0, 1)
check("the Nov 16 sheet lands on the eight tanks", [bbl(n) for n in ("Tropical Snow Dance", "Astronaut Amber", "Witbier", "Phaded", "Platty Lite", "Madagascar Dream", "Grandma's Pumpkin Pie", "Nutorious")],
      [7.0, 6.8, 3.6, 5.8, 14.4, 18.2, 3.6, 1.3])
check("eight changes, one summary line", (len(changes), len(summary)), (8, 1))
check("kegs are left alone", (bbl("Nadare"), bbl("Plattmosphere"), bbl("Half Acre Waybird")), (0.3, 0.5, 0.5))
check("the same reading is not applied twice", c.cellar_apply(reading, data, st), ([], []))
r2 = dict(reading, updated="2026-11-23T19:40:00.000Z", levels=[{"name": "Plattmo", "sv": "6", "bbls": 18}, {"name": "Nadare", "sv": "jbt", "bbls": 9},
                                                                  {"name": "Tropic", "sv": "8", "bbls": 12}, {"name": "Wit", "sv": "1", "bbls": 3.6}])
changes, summary = c.cellar_apply(r2, data, st)
pm = next(b for b in w if b["name"] == "Plattmosphere"); nd = next(b for b in w if b["name"] == "Nadare"); ts = next(b for b in w if b["name"] == "Tropical Snow Dance")
check("a keg beer the sheet puts in serving tank 6 becomes a 20 BBL tank", (pm["vessel"], pm["vesselLabel"], bbl("Plattmosphere")), ("tank20", "20 BBL", 18.0))
check("a keg beer sitting in the brite tank stays a keg", (nd["vessel"], bbl("Nadare")), ("keg-half", 0.3))
check("twelve barrels can't be in a 10: it becomes a 20", (ts["vessel"], bbl("Tropical Snow Dance")), ("tank20", 12.0))
check("the summary says what moved", "now drawn as a 20 BBL tank" in summary[0])
w2 = wall(); next(b for b in w2 if b["name"] == "Witbier")["levelAt"] = "2026-11-17T20:00:00+00:00"
changes, summary = c.cellar_apply(reading, {"beers": w2}, {})
check("a level typed in Slack after the sheet was saved wins", ("Witbier" in " ".join(changes), any("Kept the newer Slack number for Witbier" in s for s in summary)), (False, True))

# ---- 8. an unreadable state file falls back to the last good copy -------------------------------------------------------
def git(d, *a):
    return subprocess.run(("git",) + a, cwd=d, capture_output=True, text=True, env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                          GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"))
base = tempfile.mkdtemp(prefix="computa_git_")
origin, a_dir, b_dir = (os.path.join(base, n) for n in ("origin.git", "runner", "other"))
git(base, "init", "-q", "--bare", "-b", "main", origin)
git(base, "clone", "-q", origin, b_dir)
def put(d, name, obj):
    open(os.path.join(d, name), "w").write(obj if isinstance(obj, str) else json.dumps(obj, indent=1))
put(b_dir, "computa_state.json", {"last_ts": {"C": "100.0"}, "shadow": {"ledger": {"Phaded": {"oz": 16}}}})
put(b_dir, "computa_queue.json", []); put(b_dir, "beers.json", {"beers": []}); put(b_dir, "code.txt", "v1")
git(b_dir, "add", "-A"); git(b_dir, "commit", "-qm", "one"); git(b_dir, "push", "-q", "origin", "HEAD:main")
git(base, "clone", "-q", origin, a_dir)                                   # the runner checks out here... and waits in the queue
put(b_dir, "computa_state.json", {"last_ts": {"C": "200.0"}, "shadow": {"ledger": {"Phaded": {"oz": 160}}}})
put(b_dir, "code.txt", "v2")
git(b_dir, "add", "-A"); git(b_dir, "commit", "-qm", "two"); git(b_dir, "push", "-q", "origin", "HEAD:main")
here = os.getcwd(); os.chdir(a_dir)
try:
    put(a_dir, "computa_state.json", "<<<<<<< Updated upstream\n{\"last_ts\": {}}\n=======\n{}\n>>>>>>> Stashed changes\n")
    got = c.load_json("computa_state.json", None)
    check("merge markers in the state file: the committed copy is used", got and got["last_ts"]["C"], "100.0")
    check("and the file is rewritten clean", json.load(open("computa_state.json"))["last_ts"]["C"], "100.0")
    check("a file outside the repo still just defaults", c.load_json(os.path.join(base, "nope.json"), {"d": 1}), {"d": 1})

    # ---- 9. a queued run catches up before it reads anything -----------------------------------------------------------
    git(a_dir, "checkout", "-q", "--", "."); execd = []
    c.os.execv = lambda *a: execd.append(a)
    os.environ["GITHUB_ACTIONS"] = "true"
    c.catch_up()
    check("stale checkout, nothing of its own: fast-forwarded to main and restarted on the fresh code",
          (json.load(open("computa_state.json"))["last_ts"]["C"], open("code.txt").read(), len(execd)), ("200.0", "v2", 1))
    os.environ.pop("COMPUTA_CAUGHT_UP", None)
    # the run has state it never got to push, and main has moved again
    put(a_dir, "computa_state.json", {"last_ts": {"C": "250.0"}, "shadow": {"ledger": {"Phaded": {"oz": 176}}}})
    put(b_dir, "code.txt", "v3"); put(b_dir, "computa_state.json", {"last_ts": {"C": "210.0"}})
    git(b_dir, "add", "-A"); git(b_dir, "commit", "-qm", "three"); git(b_dir, "push", "-q", "origin", "HEAD:main")
    execd[:] = []; c.catch_up()
    check("unpushed state of its own is kept, everything else comes from main, no merge",
          (json.load(open("computa_state.json"))["last_ts"]["C"], open("code.txt").read(), "<<<<" in open("computa_state.json").read()), ("250.0", "v3", False))
    os.environ.pop("COMPUTA_CAUGHT_UP", None)
    # a pull that stopped half way through a rebase
    git(a_dir, "add", "-A"); git(a_dir, "commit", "-qm", "local state")
    put(b_dir, "computa_state.json", {"last_ts": {"C": "260.0"}}); git(b_dir, "add", "-A"); git(b_dir, "commit", "-qm", "four"); git(b_dir, "push", "-q", "origin", "HEAD:main")
    r = git(a_dir, "pull", "--rebase", "origin", "main")
    check("(the test did produce a stuck rebase)", os.path.isdir(".git/rebase-merge") or os.path.isdir(".git/rebase-apply"))
    execd[:] = []; c.catch_up()
    st = json.load(open("computa_state.json"))
    check("a half-finished rebase is backed out and the folder is usable again",
          (os.path.isdir(".git/rebase-merge") or os.path.isdir(".git/rebase-apply"), st["last_ts"]["C"], git(a_dir, "rev-list", "--count", "HEAD..origin/main").stdout.strip()),
          (False, "250.0", "0"))
    os.environ.pop("GITHUB_ACTIONS", None); os.environ.pop("COMPUTA_CAUGHT_UP", None)
    before = git(a_dir, "rev-parse", "HEAD").stdout
    put(b_dir, "code.txt", "v5"); git(b_dir, "add", "-A"); git(b_dir, "commit", "-qm", "five"); git(b_dir, "push", "-q", "origin", "HEAD:main")
    c.catch_up()
    check("off GitHub it never touches git", git(a_dir, "rev-parse", "HEAD").stdout, before)
finally:
    os.chdir(here); shutil.rmtree(base, ignore_errors=True)

# ---- 10. a message Computa already answered is not acted on again -------------------------------------------------------
me = "UBOT"
check("a tick from Computa marks it answered", c.already_answered({"reactions": [{"name": "white_check_mark", "users": ["UBOT"]}]}, me))
check("a reply from Computa marks it answered", c.already_answered({"reply_users": ["U1", "UBOT"]}, me))
check("someone else's reaction does not", c.already_answered({"reactions": [{"name": "eyes", "users": ["U1"]}]}, me), False)
check("no bot id known: nothing is skipped", c.already_answered({"reactions": [{"name": "x", "users": ["UBOT"]}]}, None), False)
work = tempfile.mkdtemp(prefix="computa_run_"); os.chdir(work)
try:
    json.dump({"last_ts": {cid: "100.000000" for cid in c.CHANNELS}, "started": "x"}, open(c.STATE_PATH, "w"))
    handled, commits = [], []
    def fake_slack(method, **k):
        if method == "auth.test": return {"ok": True, "user_id": "UBOT"}
        if method == "conversations.history" and k["channel"] == "C0B3E5GF6UR":
            return {"ok": True, "messages": [
                {"type": "message", "ts": "150.000000", "text": "86 nadare", "reactions": [{"name": "white_check_mark", "users": ["UBOT"]}]},
                {"type": "message", "ts": "160.000000", "text": "86 phaded"}]}
        if method == "conversations.history": return {"ok": True, "messages": []}
        if method == "reactions.add": return {"ok": True}
        return {"ok": True}
    open(os.environ["COMPUTA_TIMERS"], "w").write("{}")
    c.slack = fake_slack; c.square = None
    wd = {"beers": wall(), "recent": []}
    c.fetch_beers = lambda: (wd, "sha")
    c.commit_beers = lambda d, sha, m: commits.append(m) or True
    c.website_sync = lambda *a, **k: None
    c.health = lambda *a, **k: None
    c.run_once()
    names = [b["name"] for b in wd["beers"]]
    check("the replayed 86 is skipped, the new one is done", ("Nadare" in names, "Phaded" in names, commits), (True, False, ["86 Phaded"]))
    check("and its place in the channel still moves past both", json.load(open(c.STATE_PATH))["last_ts"]["C0B3E5GF6UR"], "160.000000")
finally:
    os.chdir(here); shutil.rmtree(work, ignore_errors=True)

# ---- 11. a beer answers to what the crew calls it ("aka" in beers.json) -------------------------------------------------
# Nov 20 2026: the wall says Platt Park Porter, the brewers say coffee porter. "86 coffee porter" found nothing.
def porter_wall():
    w = wall()
    w.append({"id": "platt-park-porter", "name": "Platt Park Porter", "price": 8.0, "price10": 6.0, "color": "#3d2317",
              "vessel": "tank10", "vesselLabel": "10 BBL", "remainingOz": 38886, "abv": 4.8, "style": "Coffee Porter",
              "aka": ["Coffee Porter"], "levelAt": "2026-11-20T18:38:23+00:00"})
    return w

def found(text, pool=None):
    return [b["name"] for b in c.match_beers(text, porter_wall() if pool is None else pool)]

check("the wall name finds it", found("platt park porter"), ["Platt Park Porter"])
check("the crew's name finds it", found("coffee porter"), ["Platt Park Porter"])
check("the crew's name inside a longer phrase", found("the coffee porter keg"), ["Platt Park Porter"])
check("porter alone still finds it", found("porter"), ["Platt Park Porter"])
check("Greg's sheet shorthand still finds it", found("PP Porter"), ["Platt Park Porter"])
check("half an aka is not a match", found("coffee"), [])
check("an aka changes nothing for the other beers", (found("witbier"), found("plattmo"), found("nadara")), (["Witbier"], ["Plattmosphere"], ["Nadare"]))
two = porter_wall(); two[0]["aka"] = ["Coffee Porter"]
check("two beers sharing an aka both come back", sorted(found("coffee porter", two)), ["Platt Park Porter", "Platty Lite"])
check("so nothing is guessed", c.match_beer("coffee porter", two), None)
junk = porter_wall(); junk[-1]["aka"] = "Coffee Porter"            # a string where a list belongs: ignored, not read letter by letter
check("a malformed aka is ignored", (found("coffee porter", junk), found("c", junk)), ([], []))
d11 = {"beers": porter_wall(), "recent": []}
out = c.handle({"ts": "11.0", "text": "86 coffee porter"}, d11, [], "C0AQ68G7DRB")
check("86 by the crew's name takes it off the wall", (out[0], [b["name"] for b in d11["beers"] if "Porter" in b["name"]], [b["name"] for b in d11["recent"]][:1]),
      ("86 Platt Park Porter", [], ["Platt Park Porter"]))
out = c.handle({"ts": "11.1", "text": "coffee porter is back on, 9.5bbl in a 10bbl"}, d11, [], "C0AQ68G7DRB")
check("and the crew's name brings it back with its level", (d11["beers"][-1]["name"], d11["beers"][-1]["remainingOz"], d11["beers"][-1].get("aka")),
      ("Platt Park Porter", int(9.5 * 3968), ["Coffee Porter"]))
sheet = {"beers": porter_wall(), "recent": []}
ch, _ = c.cellar_apply({"sheet": "November 26", "tab": "wk 4", "updated": "2026-11-23T20:00:00.000Z",
                        "levels": [{"name": "Coffee Porter", "bbls": 8.9, "sv": "2"}]}, sheet, {})
check("Greg's sheet can call it coffee porter too", (ch, sheet["beers"][-1]["remainingOz"]), (["Platt Park Porter level 8.9 (sheet)"], int(8.9 * 3968)))

print("%d passed, %d failed" % (PASS[0], len(FAIL)))
for f in FAIL:
    print("  FAIL " + f)
sys.exit(1 if FAIL else 0)
