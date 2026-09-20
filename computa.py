#!/usr/bin/env python3
"""
computa.py - Platt Park Brewing
Slack #bar-only + #brew-x-bar -> beers.json -> GitHub -> live board + menu

THE CHAIN
  bartender types "86 chela"
    -> this script sees it (polls every 90s)
    -> rewrites beers.json
    -> commits it to the liveboard repo
    -> the board sees the new stamp within 60s and reloads
  About 90 seconds typical. Nobody downloads or uploads anything.

UNDERSTANDS
  86 chela / chela kicked / chela blew     remove it
  chela is back on                         restore it with all its data
  chela is on last keg                     half-barrel + LAST KEG sash
  boochcraft is now kiwi citrus            swap a flavor line
  nutorious medal: US Open gold 2026       plaque on the tank + menu line (DIBC etc. = record only)
  take the bronze off nutorious wall       older medal steps down to the menu line
  computa add <thing>                      queued for a human

DESIGN RULE
  Removing is automatic. Adding is not - a new beer needs a price, colour,
  vessel and volume only a person can supply. Adds get logged and answered
  in-thread so the bartender knows it landed.

  Removed beers move to a "recent" list inside beers.json so "back on"
  restores the full record instead of making anyone retype it.

SETUP
  export SLACK_BOT_TOKEN="xoxb-..."    # channels:history, chat:write
  export GITHUB_TOKEN="ghp_..."        # repo scope
  python3 computa.py           # one pass
  python3 computa.py --watch   # poll forever (run on the Beelink)
  python3 computa.py --dry     # parse and print, change nothing
"""

import os, re, sys, json, time, base64, urllib.request, urllib.parse, urllib.error
try:
    import newbeer
except ImportError:
    newbeer = None
from datetime import datetime, timezone

CHANNELS = {                       # every channel Computa listens in
    "C0B3E5GF6UR": "bar-only",     # bartenders: 86s, last keg, back on
    "C0AQ68G7DRB": "brew-x-bar",   # brewers (Jules, Greg): new beers
}
ALERT_CHANNEL = "C0B3E5GF6UR"      # where health warnings go
REPO       = "PlattPark/liveboard"
BEERS_PATH = "beers.json"
STATE_PATH = "computa_state.json"
QUEUE_PATH = "computa_queue.json"
POLL_SEC   = 90

SLACK_TOKEN  = os.environ.get("SLACK_BOT_TOKEN", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
DRY = "--dry" in sys.argv

VESSELS = {"1/2 BBL": ("keg-half", 1984), "1 BBL": ("keg", 3968),
           "10 BBL": ("tank10", 39680), "20 BBL": ("tank20", 79360)}


def slack(method, **params):
    if not SLACK_TOKEN:
        sys.exit("ERROR: set SLACK_BOT_TOKEN")
    req = urllib.request.Request(
        "https://slack.com/api/" + method,
        data=urllib.parse.urlencode(params).encode(),
        headers={"Authorization": "Bearer " + SLACK_TOKEN,
                 "Content-Type": "application/x-www-form-urlencoded; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=20) as r:
        out = json.load(r)
    if not out.get("ok"):
        print("  ! slack %s: %s" % (method, out.get("error")))
    return out


def gh(path, method="GET", payload=None):
    if not GITHUB_TOKEN:
        sys.exit("ERROR: set GITHUB_TOKEN")
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/%s" % (REPO, path),
        data=json.dumps(payload).encode() if payload else None,
        method=method,
        headers={"Authorization": "Bearer " + GITHUB_TOKEN,
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "computa"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        print("  ! github %s: %s" % (e.code, e.read().decode()[:200]))
        return None


REQUIRED = ("id", "name", "price", "color", "vessel", "remainingOz")

def validate(data):
    """Refuse to publish anything the board can't render."""
    if not isinstance(data, dict) or not isinstance(data.get("beers"), list):
        return False
    ids = set()
    for b in data["beers"]:
        if not isinstance(b, dict) or any(k not in b for k in REQUIRED):
            return False
        if b["id"] in ids:
            return False
        ids.add(b["id"])
    return True


HEALTH_PATH = "computa_health.json"
ALERT_AFTER = 5          # consecutive failures (~7.5 min) before one alert post

def health(status):
    h = load_json(HEALTH_PATH, {"fails": 0, "alerted": False})
    now = datetime.now().isoformat(timespec="seconds")
    if status == "ok":
        if h.get("alerted"):
            slack("chat.postMessage", channel=ALERT_CHANNEL,
                  text=":white_check_mark: Computa is back and caught up.")
        h = {"fails": 0, "alerted": False, "last_ok": now}
    else:
        h["fails"] = h.get("fails", 0) + 1
        h["last_error"] = status
        h["last_fail"] = now
        if h["fails"] >= ALERT_AFTER and not h.get("alerted"):
            slack("chat.postMessage", channel=ALERT_CHANNEL,
                  text=":warning: Computa can't reach GitHub (%s). Board and menu won't "
                       "update until it's fixed - Colby, check the Beelink. "
                       "I'll say when it's back." % status)
            h["alerted"] = True
    if not DRY:
        # only touch the file when fails/alerted actually change - the loop
        # runs every 90s and a rewrite per cycle would mean a commit per cycle
        prev = load_json(HEALTH_PATH, {})
        if (prev.get("fails"), prev.get("alerted")) != (h["fails"], h["alerted"]) or not prev:
            json.dump(h, open(HEALTH_PATH, "w"), indent=1)


def fetch_beers():
    d = gh("contents/" + BEERS_PATH)
    if not d:
        sys.exit("Could not read beers.json from GitHub.")
    return json.loads(base64.b64decode(d["content"]).decode()), d["sha"]


def commit_beers(data, sha, message):
    data["updated"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    data["updatedBy"] = message
    body = json.dumps(data, indent=1, ensure_ascii=False)
    if DRY:
        print("  [dry] would commit: " + message)
        return True
    return bool(gh("contents/" + BEERS_PATH, "PUT", {
        "message": "computa: " + message,
        "content": base64.b64encode(body.encode()).decode(),
        "sha": sha}))


WAKE = r"(?:computa+h?|computer)"
REMOVE_RE  = re.compile(r"(?:^|\b)(?:86|eighty[- ]?six)\b[:\s]*(?:the\s+)?(?P<item>.{2,48}?)"
                        r"(?:\s+(?:please|pls|thx|thanks|for now))?"
                        r"(?:\s+(?:until|til|till|thru|through)\b.*)?[.!]?\s*$", re.I)
KICKED_RE  = re.compile(r"^(?:the\s+)?(?P<item>.{2,48}?)\s+(?:just\s+)?(?:is\s+|has\s+)?"
                        r"(?:kicked|blew|blown|tapped\s+out|ran\s+out|is\s+out|gone)\b[.!]?\s*$", re.I)
BACK_RE    = re.compile(r"^(?:the\s+)?(?P<item>.{2,48}?)\s+(?:is\s+back(?:\s+on)?|back\s+on|on\s+again|pouring\s+again|back[.!]?$)\b", re.I)
NOLASTKEG_RE = re.compile(r"(?:^(?:remove|clear|take\s+off|drop)\s+(?:the\s+)?last\s*keg(?:\s+sash)?\s+(?:from|off|on)\s+(?:the\s+)?(?P<item>.{2,48}?)"
                          r"|^(?:the\s+)?(?P<item2>.{2,48}?)\s+(?:is\s+)?(?:not|no\s+longer)\s+(?:on\s+)?(?:its\s+)?last\s*keg"
                          r"|^(?:the\s+)?(?P<item3>.{2,48}?)\s+last\s*keg\s+(?:sash\s+)?off"
                          r"|^(?:the\s+)?(?P<item4>.{2,48}?)\s+should\s*(?:n'?t|\s+not)\s+(?:say|be|show|read)\s+(?:on\s+)?last\s*keg)[.!]?\s*$", re.I)
PRICE10_RE = re.compile(r"^(?:the\s+)?(?P<item>.{2,48}?)\s+10\s*oz\s+(?:is\s+now|now|is|=|->|to)\s+\$\s*(?P<price>\d+(?:\.\d{1,2})?)[.!]?\s*$", re.I)
PRICE_RE   = re.compile(r"^(?:the\s+)?(?P<item>.{2,48}?)\s+(?:is\s+now|now|is|=|->|to)\s+\$\s*(?P<price>\d+(?:\.\d{1,2})?)(?:\s*(?:a\s+)?(?:pint|pints))?[.!]?\s*$", re.I)
ABV_RE     = re.compile(r"^(?:the\s+)?(?P<item>.{2,48}?)\s+(?:is\s+(?:now\s+)?|abv\s*(?:is|=|:)?\s*)(?P<abv>\d{1,2}(?:\.\d)?)\s*%(?:\s*abv)?[.!]?\s*$", re.I)
FRESHKEG_RE= re.compile(r"^(?:a\s+)?(?:fresh|new)\s+keg\s+(?:of\s+)?(?:the\s+)?(?P<item>.{2,48}?)(?:\s+(?:is\s+)?(?:on|tapped|up|pouring))?[.!]?\s*$", re.I)
# hours: "late night tonight" / "open til midnight on 11/25" / "closed tomorrow" / "closed on 2026-12-25" / "normal hours tonight"
WHEN = r"(?P<when>tonight|today|tomorrow|(?:on\s+)?(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?))"
LATE_RE    = re.compile(r"^(?:late\s+night|open\s+(?:till?|until|to)\s+(?:midnight|12|12\s*am))\s+" + WHEN + r"[.!]?\s*$", re.I)
CLOSED_RE  = re.compile(r"^closed\s+" + WHEN + r"[.!]?\s*$", re.I)
NORMAL_RE  = re.compile(r"^(?:normal|regular|usual)\s+hours\s+" + WHEN + r"[.!]?\s*$", re.I)
# "kakou wall is Golden Stout w/ coconut, coffee & pineapple" / "kakou note: coffee, pineapple and coconut"
WALL_RE    = re.compile(r"^(?:the\s+)?(?P<item>.{2,40}?)\s+(?:wall|board)(?:\s+line)?\s*(?:is|:|=|says|reads)\s+(?P<text>.{2,60}?)[.!]?\s*$", re.I)
NOTE_RE    = re.compile(r"^(?:the\s+)?(?P<item>.{2,40}?)\s+(?:menu\s+)?note\s*(?:is|:|=|says|reads)\s+(?P<text>.{2,90}?)[.!]?\s*$", re.I)
STATUS_RE  = re.compile(r"^(?:status|what'?s\s+(?:on|pouring)|tap\s+list|list)\b[?!.]*$", re.I)
ASKED_RE   = re.compile(r"\b(?:accurate|up\s+to\s+date|correct|status|what'?s\s+(?:on|pouring|low|left))\b", re.I)
LASTKEG_RE = re.compile(r"^(?:(?:put|mark|set|flag)\s+)?(?:the\s+)?(?P<item>.{2,48}?)\s+(?:is\s+)?(?:on\s+)?(?:its\s+)?"
                        r"(?:last\s+keg|almost\s+out|running\s+low|is\s+low|nearly\s+out)\b", re.I)
# "boochcraft is now kiwi citrus" - the "now" is required. Without it, every
# tank update in #brew-x-bar ("tank 3 is fermenting") would read as a flavor change.
FLAVOR_RE  = re.compile(r"^(?:the\s+)?(?P<item>.{2,32}?)\s+is\s+now\s+(?:a\s+)?(?P<flavor>.{2,40}?)"
                        r"(?:\s+(?:flavor|flavour))?[.!]?\s*$", re.I)
ADD_RE     = re.compile(r"\b(?:add|new|put|throw)\b\s+(?:on\s+|in\s+)?(?P<item>.{2,60}?)"
                        r"(?:\s+(?:to|on)\s+the\s+(?P<section>[\w \-]+?))?[.!]?\s*$", re.I)
PICK_RE    = re.compile(r"^(?:brewer'?s'?\s+pick|staff\s+pick|pick\s+of\s+the\s+(?:day|week))\s*(?:is|=|:|-)?\s*(?:the\s+)?(?P<item>.{2,48}?)[.!]?\s*$", re.I)
NOPICK_RE  = re.compile(r"^(?:no|clear|remove|kill)\s+(?:the\s+)?(?:brewer'?s'?|staff)\s+pick\b", re.I)
REPORT_RE  = re.compile(r"^(?:the\s+)?(?:board|tv|menu|wall|screen)?\s*(?:for\s+)?(?P<item>.{2,40}?)?\s*(?:still\s+)?(?:says|shows|reads|is\s+showing|is\s+still\s+showing|is\s+wrong|looks\s+wrong|isn'?t\s+right|is\s+off)\b", re.I)
NOBTN_RE   = re.compile(r"\bno\s+button\s+for\s+(?:the\s+)?(?P<item>.{2,48}?)"
                        r"(?:\s+(?:as\s+of\s+now|right\s+now|yet|currently|atm))?[.!]?\s*$", re.I)
# medals - the tiers Colby set (Sept 2026): judged, top-three-per-category comps earn the
# plaque on the tank + a line on the menu (show "wall"); an older medal for the same beer
# keeps the menu line (show "menu"); points-based comps like DIBC are the record only
# (show "site") - never the wall, never the menu. The board drops a wall medal to the
# menu by itself two seasons after it was won.
#   "nutorious medal: US Open gold 2026"  /  "nutorious won gold at the state fair 2026"
#   "take the bronze off nutorious wall"  /  "put the bronze back on nutorious wall"
MEDAL_COMPS = {   # what people type -> (key beers.json stores, earns the wall?)
    "us open": ("US Open", True), "u.s. open": ("US Open", True), "usopen": ("US Open", True),
    "us open beer championship": ("US Open", True),
    "state fair": ("State Fair", True), "colorado state fair": ("State Fair", True),
    "gabf": ("GABF", True), "great american beer festival": ("GABF", True),
    "world beer cup": ("World Beer Cup", True), "wbc": ("World Beer Cup", True),
    "brewers cup": ("Brewers Cup", True), "colorado brewers cup": ("Brewers Cup", True),
    "dibc": ("DIBC", False), "denver international": ("DIBC", False),
    "denver international beer competition": ("DIBC", False),
}
_COMPS = "|".join(re.escape(k) for k in sorted(MEDAL_COMPS, key=len, reverse=True))
_LEVEL = r"gold|silver|bronze"
_YEAR  = r"(?:19|20)\d{2}"
MEDAL_RE = re.compile(
    r"^(?:the\s+)?(?P<item>.{2,40}?)\s+(?:medal|medals|won|took|got)\s*(?:is|:|=|-|a|the)?\s*"
    r"(?:(?P<comp1>" + _COMPS + r")\s+(?P<level1>" + _LEVEL + r")"
    r"|(?P<level2>" + _LEVEL + r")\s+(?:medal\s+)?(?:at|in|from)?\s*(?:the\s+)?(?P<comp2>" + _COMPS + r"))"
    r"(?:\s+(?:medal\s+)?(?:in\s+|for\s+)?'?(?P<year>" + _YEAR + r"|\d{2}))?[.!]?\s*$", re.I)
OFFWALL_RE = re.compile(
    r"^(?:take|remove|drop|pull|clear)\s+(?:the\s+)?(?P<level>" + _LEVEL + r"|medal|medals|plaque)\s+"
    r"(?:off|from)\s+(?:of\s+)?(?:the\s+)?(?P<item>.{2,40}?)(?:'s|’s)?"
    r"(?:\s+(?:wall|board|tank|plaque))?[.!]?\s*$", re.I)
ONWALL_RE = re.compile(
    r"^(?:put|move|hang)\s+(?:the\s+)?(?P<level>" + _LEVEL + r")\s+(?:back\s+)?(?:on|onto)\s+(?:the\s+)?"
    r"(?P<item>.{2,40}?)(?:'s|’s)?\s+(?:wall|board|tank|plaque)[.!]?\s*$", re.I)
IGNORE = re.compile(r"\b(sink|toilet|restroom|tab|tabs|register|wifi|thermostat|"
                    r"ice machine|dishwasher|shot glass(?:es)?|light bulb)\b", re.I)


NEWBEER_TRIGGER = re.compile(r"^\s*(?:computa+h?\s*[,!:]?\s*)?(?:new\s+beer|new\s+tap|just\s+tapped|now\s+pouring|on\s+tap\s+now)\b", re.I)

def parse(text):
    body = text.strip()
    # Announcements and essays are not commands: long, or formatted with backticks.
    if len(body) > 220 or "`" in body:
        return None
    if newbeer and NEWBEER_TRIGGER.match(body):
        nb = newbeer.parse_new_beer(body)
        if nb and nb.get("name"):
            return "newbeer", nb, body   # handle() turns this into a restore if the name is already known
    # "@Computa 86 chela" arrives as "<@U0C2GMAT8CD> 86 chela" - the mention is the wake word
    woke = re.match(r"^\s*(?:<@U[A-Z0-9]+(?:\|[^>]*)?>|%s\b)[\s,!:.\-]*" % WAKE, body, re.I)
    if woke:
        body = body[woke.end():].strip()
    for line in [l.strip() for l in body.split("\n") if l.strip()]:
        if IGNORE.search(line):
            continue
        if STATUS_RE.search(line) or (woke and ASKED_RE.search(line)):
            return "status", "", None
        if NOPICK_RE.search(line):
            return "nopick", "", None
        # "the board says nutorious is wrong" is a report, not a wall line for a beer called "the"
        if REPORT_RE.search(line) and re.match(r"^(?:the\s+)?(?:board|tv|menu|wall|screen)\b", line, re.I):
            return "report", line, None
        # medals go before the generic patterns: "put the bronze back on nutorious wall"
        # would otherwise read as "back on", and "nutorious medal: ..." as a note
        m = ONWALL_RE.search(line)
        if m:
            return "onwall", m.group("item").strip(" .,-"), m.group("level").lower()
        m = OFFWALL_RE.search(line)
        if m:
            return "offwall", m.group("item").strip(" .,-"), m.group("level").lower()
        m = MEDAL_RE.search(line)
        if m:
            comp = (m.group("comp1") or m.group("comp2")).lower()
            level = (m.group("level1") or m.group("level2")).lower()
            year = m.group("year")
            if year and len(year) == 2:
                year = "20" + year
            return "medal", m.group("item").strip(" .,-"), (comp, level, int(year) if year else None)
        for rx, act in ((WALL_RE, "wall"), (NOTE_RE, "note")):
            m = rx.search(line)
            if m:
                return act, m.group("item").strip(" .,-"), m.group("text").strip()
        for rx, act in ((LATE_RE, "late"), (CLOSED_RE, "closed"), (NORMAL_RE, "normalhours")):
            m = rx.search(line)
            if m:
                return act, when_to_date(m.group("when")), None
        m = REPORT_RE.search(line)
        if m and not NOLASTKEG_RE.search(line):
            return "report", line, None
        m = NOLASTKEG_RE.search(line)
        if m:
            return "nolastkeg", (m.group("item") or m.group("item2") or m.group("item3") or m.group("item4")).strip(" .,-"), None
        m = PICK_RE.search(line)
        if m:
            return "pick", m.group("item").strip(" .,-"), None
        m = PRICE10_RE.search(line)
        if m:
            return "price10", m.group("item").strip(" .,-"), float(m.group("price"))
        m = PRICE_RE.search(line)
        if m:
            return "price", m.group("item").strip(" .,-"), float(m.group("price"))
        m = ABV_RE.search(line)
        if m:
            return "abv", m.group("item").strip(" .,-"), float(m.group("abv"))
        m = FRESHKEG_RE.search(line)
        if m:
            return "back", m.group("item").strip(" .,-"), None
        for rx, act in ((NOBTN_RE, "needs_button"), (REMOVE_RE, "remove"),
                        (KICKED_RE, "remove"), (BACK_RE, "back"), (LASTKEG_RE, "lastkeg")):
            m = rx.search(line)
            if m:
                return act, m.group("item").strip(" .,-"), None
        m = FLAVOR_RE.search(line)
        if m and not re.search(r"\b(back|kicked|out|low|fixed|broken)\b", m.group("flavor"), re.I):
            return "flavor", m.group("item").strip(" .,-"), m.group("flavor").strip(" .,-")
        if woke:
            m = ADD_RE.search(line)
            if m:
                return "add", m.group("item").strip(" .,-"), (m.group("section") or "").strip() or None
    return None


def when_to_date(w):
    """'tonight' -> today's date (Denver), 'tomorrow', '11/25', '2026-11-25' -> YYYY-MM-DD."""
    import datetime as _dt
    w = re.sub(r"^on\s+", "", w.strip().lower())
    try:
        from zoneinfo import ZoneInfo
        today = _dt.datetime.now(ZoneInfo("America/Denver")).date()
    except Exception:
        today = _dt.date.today()
    if w in ("tonight", "today"):
        return today.isoformat()
    if w == "tomorrow":
        return (today + _dt.timedelta(days=1)).isoformat()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", w)
    if m:
        return w
    m = re.match(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$", w)
    if m:
        y = int(m.group(3)) if m.group(3) else today.year
        if y < 100: y += 2000
        d = _dt.date(y, int(m.group(1)), int(m.group(2)))
        if not m.group(3) and d < today:            # "12/31" said in January means next year's
            d = d.replace(year=y + 1)
        return d.isoformat()
    return today.isoformat()


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


BBL_OZ = 3968                       # one barrel in ounces
LEVEL_RE = re.compile(r"(\d+(?:\.\d+)?)\s*bbl(?:\s+in\s+an?\s+(\d+)\s*bbl)?", re.I)

def read_level(text, beer):
    """'9.3bbl in a 10bbl tank' -> remainingOz 36902, vessel tank10.
    Returns a reply fragment, or '' if the message says nothing about level."""
    m = LEVEL_RE.search(text)
    if not m:
        return ""
    have = float(m.group(1))
    beer["remainingOz"] = int(have * BBL_OZ)
    if m.group(2):
        size = int(m.group(2))
        label = "%d BBL" % size
        if label in VESSELS:
            beer["vessel"], _ = VESSELS[label]
            beer["vesselLabel"] = label
    elif have <= 0.5:
        beer["vessel"], _ = VESSELS["1/2 BBL"]; beer["vesselLabel"] = "1/2 BBL"
    return " Tank set to %.1f bbl." % have


import difflib

def match_beers(item, pool):
    """All plausible matches. Exact name wins; then substring; then a close typo
    ('chelas', 'nadara', 'platy') against the whole name or any word of it."""
    t = norm(item)
    if not t:
        return []
    exact = [b for b in pool if norm(b.get("name","")) == t or norm(b.get("id","")) == t]
    if exact:
        return exact[:1]
    if len(t) <= 3:
        return []
    sub = [b for b in pool if t in norm(b.get("name","")) or norm(b.get("name","")) in t]
    if sub:
        return sub
    def close(a, b):
        return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8
    fuzzy = []
    for b in pool:
        words = [norm(w) for w in re.split(r"[\s\-/]+", b.get("name","")) if len(norm(w)) >= 4]
        if close(t, norm(b.get("name",""))) or any(close(t, w) for w in words):
            fuzzy.append(b)
    return fuzzy

SPLIT_RE = re.compile(r"\s*(?:,|&|\+|\band\b)\s*", re.I)

def split_items(item):
    """'witbier and nadare' -> ['witbier', 'nadare']; single names pass through."""
    parts = [p.strip(" .,-") for p in SPLIT_RE.split(item) if p.strip(" .,-")]
    return parts if len(parts) > 1 else [item]


def match_beer(item, pool):
    m = match_beers(item, pool)
    return m[0] if len(m) == 1 else None


MEDAL_RANK = {"gold": 3, "silver": 2, "bronze": 1}
MEDAL_EMOJI = {"gold": ":first_place_medal:", "silver": ":second_place_medal:", "bronze": ":third_place_medal:"}

def beer_medals(b):
    """The beer's medal list, migrating the pre-Sept-2026 shape (medal/medalText) in place."""
    if not isinstance(b.get("medals"), list):
        b["medals"] = []
        if b.get("medal"):
            comp = re.sub(r"\s*(gold|silver|bronze)\s*", " ", b.get("medalText") or "", flags=re.I).strip().title().replace("Us Open", "US Open")
            b["medals"].append({"comp": comp, "level": str(b["medal"]).lower(), "year": b.get("medalYear"), "show": "wall"})
        b.pop("medal", None); b.pop("medalText", None); b.pop("medalYear", None)
    return b["medals"]

def medal_tag(b):
    """':first_place_medal:' for the plaque the tank shows right now, else ''."""
    year = datetime.now().year
    ms = [m for m in (b.get("medals") or []) if m.get("show", "wall") == "wall" and (not m.get("year") or year - m["year"] <= 2)]
    if not ms:
        return ""
    top = sorted(ms, key=lambda m: (MEDAL_RANK.get(m.get("level"), 0), m.get("year") or 0), reverse=True)[0]
    return " " + MEDAL_EMOJI.get(top.get("level"), ":medal:")


def handle(msg, data, queue, channel):
    p = parse(msg.get("text", ""))
    if not p:
        return None
    action, item, extra = p
    # "86 witbier and nadare": run the same action once per name, combine the replies
    if action in ("remove", "back", "lastkeg") and isinstance(item, str) and len(split_items(item)) > 1:
        changes, replies = [], []
        for part in split_items(item):
            r = handle_one(msg, data, queue, channel, action, part, extra)
            if r:
                if r[0]: changes.append(r[0])
                if r[1]: replies.append(r[1][2])
        return ("; ".join(changes) or None), ((channel, msg["ts"], "\n".join(replies)) if replies else None)
    return handle_one(msg, data, queue, channel, action, item, extra)


def handle_one(msg, data, queue, channel, action, item, extra):
    ts = msg["ts"]
    beers  = data.setdefault("beers", [])
    recent = data.setdefault("recent", [])
    reply = change = None

    if action == "remove":
        hits = match_beers(item, beers)
        if len(hits) > 1:
            reply = (":grey_question: *%s* could be %s - which one?" %
                     (item, " or ".join("*"+h["name"]+"*" for h in hits)))
            b = None
        else:
            b = hits[0] if hits else None
        if b:
            beers.remove(b)
            b["offSince"] = datetime.now().strftime("%Y-%m-%d")
            recent.insert(0, b); data["recent"] = recent[:12]
            change = "86 " + b["name"]
            reply = (":white_check_mark: 86'd *%s* - off the board and the menu within a "
                     "couple of minutes.\nSay _\"%s is back on\"_ when it returns." % (b["name"], b["name"]))
        elif not reply:
            queue.append({"ts": ts, "action": "remove_unmatched", "item": item, "text": msg.get("text", "")})
            reply = (":grey_question: Couldn't match *%s* to anything pouring. Flagged it - if it's "
                     "a cocktail, cider or food item it isn't in the tap list." % item)

    elif action == "back":
        b = match_beer(item, recent)
        already = match_beer(item, beers)
        if b:
            recent.remove(b); b.pop("offSince", None)
            b["tappedDaysAgo"] = 0
            lvl = read_level(msg.get("text", ""), b)
            beers.append(b)
            change = b["name"] + " back on"
            reply = ":beer: *%s* is back on - it'll reappear shortly.%s" % (b["name"], lvl)
        elif already:
            lvl = read_level(msg.get("text", ""), already)
            if lvl:
                change = already["name"] + " level"
            reply = ":beer: *%s* is already pouring - nothing to do.%s" % (already["name"], lvl)
        else:
            queue.append({"ts": ts, "action": "restore_unknown", "item": item, "text": msg.get("text", "")})
            reply = (":grey_question: *%s* isn't in the recently-off list, so I don't have its price "
                     "and tank details. Colby needs to add it." % item)

    elif action == "pick":
        b = match_beer(item, beers)
        if b:
            for x in beers: x.pop("pick", None)
            b["pick"] = True
            change = "brewers' pick " + b["name"]
            reply = ":star: *%s* is the brewers' pick - it's on the board, top and centre." % b["name"]
        else:
            reply = ":grey_question: Couldn't find *%s* on the tap list." % item

    elif action == "nopick":
        had = [x["name"] for x in beers if x.pop("pick", None)]
        change = "brewers' pick cleared" if had else None
        reply = ":white_check_mark: Brewers' pick cleared." if had else ":information_source: There wasn't a brewers' pick set."

    elif action == "lastkeg":
        b = match_beer(item, beers)
        if b:
            b["vessel"], cap = VESSELS["1/2 BBL"]
            b["vesselLabel"] = "1/2 BBL"
            b["remainingOz"] = min(b.get("remainingOz", cap), int(cap * 0.55))
            b["sash"] = "last keg"
            change = b["name"] + " last keg"
            reply = ":hourglass: *%s* marked last keg - the sash is up on the board." % b["name"]
        else:
            reply = ":grey_question: Couldn't find *%s* on the tap list." % item

    elif action == "nolastkeg":
        b = match_beer(item, beers)
        if b:
            had = b.pop("sash", None) == "last keg"
            change = (b["name"] + " sash off") if had else None
            reply = (":white_check_mark: LAST KEG sash is off *%s*." % b["name"]) if had else \
                    (":information_source: *%s* wasn't marked last keg." % b["name"])
        else:
            reply = ":grey_question: Couldn't find *%s* on the tap list." % item

    elif action == "medal":
        comp_said, level, year = extra
        comp, earns_wall = MEDAL_COMPS[comp_said]
        b = match_beer(item, beers) or match_beer(item, recent)
        if b:
            ms = beer_medals(b)
            # the same medal said twice (or said first without the year) updates, never duplicates
            hit = next((x for x in ms if x["comp"] == comp and x["level"] == level
                        and (x.get("year") == year or not year or not x.get("year"))), None)
            if hit:
                if year: hit["year"] = year
                hit["show"] = "wall" if earns_wall else "site"
            else:
                ms.append({"comp": comp, "level": level, "year": year, "show": "wall" if earns_wall else "site"})
            if earns_wall:
                # one plaque per tank: an older wall medal on the same beer steps down to the menu
                for x in ms:
                    if x is not hit and x.get("show") == "wall" and x["comp"] == comp and x["level"] == level and (x.get("year") or 0) < (year or 0):
                        x["show"] = "menu"
                yr = (" %d" % year) if year else ""
                change = "%s %s %s%s" % (b["name"], comp, level, yr)
                reply = (":medal: *%s* · %s %s%s - plaque on the tank, line on the menu, both within a couple of minutes."
                         "%s" % (b["name"], comp, level, yr,
                                 "" if year else "\nNo year given, so it never ages off the wall - say _\"%s medal: %s %s YYYY\"_ to date it." % (b["name"], comp, level)))
            else:
                change = "%s %s %s (record)" % (b["name"], comp, level)
                reply = (":ledger: Logged *%s* · %s %s%s for the record. Points-based medals stay off the wall and the "
                         "menu - it's in beers.json for the website and the sell sheet." % (b["name"], comp, level, (" %d" % year) if year else ""))
        else:
            reply = ":grey_question: Couldn't find *%s* on the tap list or the recently-off list." % item

    elif action in ("offwall", "onwall"):
        b = match_beer(item, beers) or match_beer(item, recent)
        if b:
            want = "wall" if action == "onwall" else "menu"
            ms = beer_medals(b)
            hits = [x for x in ms if (extra in ("medal", "medals", "plaque") or x["level"] == extra)
                    and x.get("show") != "site" and x.get("show", "wall") != want]
            if action == "onwall" and any(not MEDAL_COMPS.get(x["comp"].lower(), ("", True))[1] for x in hits):
                hits = [x for x in hits if MEDAL_COMPS.get(x["comp"].lower(), ("", True))[1]]
            for x in hits:
                x["show"] = want
            if hits:
                what = ", ".join("%s %s%s" % (x["comp"], x["level"], (" %d" % x["year"]) if x.get("year") else "") for x in hits)
                change = "%s %s %s" % (b["name"], what, "on wall" if want == "wall" else "off wall")
                reply = ((":white_check_mark: *%s* · %s is back on the wall." if want == "wall" else
                          ":white_check_mark: *%s* · %s is off the wall - it stays on the menu line.") % (b["name"], what))
            else:
                reply = ":information_source: *%s* has no %s to move." % (b["name"], "wall medal" if want == "menu" else "medal for the wall")
        else:
            reply = ":grey_question: Couldn't find *%s* on the tap list." % item

    elif action in ("wall", "note"):
        b = match_beer(item, beers)
        if b:
            b[action] = extra
            change = "%s %s line" % (b["name"], action)
            reply = (":pencil2: *%s* now reads _%s_ on the %s." % (b["name"], extra, "wall" if action == "wall" else "menu"))
        else:
            reply = ":grey_question: Couldn't find *%s* on the tap list." % item

    elif action in ("late", "closed", "normalhours"):
        hours = data.setdefault("hours", {})
        late = hours.setdefault("late", []); closed = hours.setdefault("closed", [])
        for lst in (late, closed):
            while item in lst: lst.remove(item)
        if action == "late":
            late.append(item); change = "late night " + item
            reply = ":night_with_stars: Board stays up till midnight on %s." % item
        elif action == "closed":
            closed.append(item); change = "closed " + item
            reply = ":no_entry: Board shows *Closed today* on %s." % item
        else:
            change = "normal hours " + item
            reply = ":white_check_mark: Normal hours on %s." % item
        hours["late"] = sorted(set(late)); hours["closed"] = sorted(set(closed))

    elif action == "report":
        queue.append({"ts": ts, "action": "report", "item": item, "text": msg.get("text", ""),
                      "logged": datetime.now().strftime("%Y-%m-%d %H:%M")})
        reply = ":eyes: Got it - flagged for Colby. If you want me to change it, tell me what it should say."

    elif action == "status":
        lines = ["%s%s" % (b["name"], (" (last keg)" if b.get("sash") == "last keg" else "") + (" :star:" if b.get("pick") else "") + medal_tag(b))
                 for b in beers]
        reply = ":beers: *%d on the wall:* %s\nLast change: %s" % (len(beers), " \u00b7 ".join(lines), data.get("updatedBy", "?"))

    elif action == "flavor":
        b = match_beer(item, beers)
        if b:
            b["style"] = extra.title()
            change = "%s -> %s" % (b["name"], extra)
            reply = ":arrows_counterclockwise: *%s* updated to _%s_." % (b["name"], extra)
        else:
            queue.append({"ts": ts, "action": "flavor_offlist", "item": item, "flavor": extra,
                          "text": msg.get("text", "")})
            reply = (":pencil: Logged: *%s* is now _%s_. That one lives in the 'Also Pouring' panel, "
                     "not the tap list - Colby will swap it." % (item, extra))

    elif action == "price":
        b = match_beer(item, beers)
        if b:
            old = b.get("price"); b["price"] = extra
            change = "%s $%.2f" % (b["name"], extra)
            reply = ":moneybag: *%s* pint is now $%.2f (was $%.2f). Change the 10oz too if it moved: _\"%s 10oz is now $X\"_" % (b["name"], extra, old or 0, b["name"])
        else:
            reply = ":grey_question: Couldn't find *%s* on the tap list." % item

    elif action == "price10":
        b = match_beer(item, beers)
        if b:
            b["price10"] = extra
            change = "%s 10oz $%.2f" % (b["name"], extra)
            reply = ":moneybag: *%s* 10oz is now $%.2f." % (b["name"], extra)
        else:
            reply = ":grey_question: Couldn't find *%s* on the tap list." % item

    elif action == "abv":
        b = match_beer(item, beers)
        if b:
            b["abv"] = extra
            change = "%s %s%%" % (b["name"], extra)
            reply = ":test_tube: *%s* is now %s%% on the board and menu." % (b["name"], extra)
        else:
            reply = ":grey_question: Couldn't find *%s* on the tap list." % item

    elif action == "newbeer":
        beer, assumed = newbeer.build_beer(item, extra or "")
        known = match_beer(beer["name"], recent)
        if known:   # "just tapped witbier" for a beer we already know: restore it, don't invent it
            recent.remove(known); known.pop("offSince", None); known["tappedDaysAgo"] = 0
            lvl = read_level(msg.get("text", ""), known)
            beers.append(known)
            change = known["name"] + " back on"
            reply = ":beer: *%s* is back on with its old price and tank.%s" % (known["name"], lvl)
        elif match_beer(beer["name"], beers):
            reply = ":information_source: *%s* is already on the tap list." % beer["name"]
        else:
            beers.append(beer)
            change = "added " + beer["name"]
            reply = (":beer: *%s* is live on the board and the menu.\n"
                     "_%s \u00b7 %s%% \u00b7 $%.2f_%s\n\n"
                     "I assumed: %s.\nReply here if any of that's wrong and Colby will fix it. "
                     "Make sure it has a POS button before service."
                     % (beer["name"], beer["style"], beer["abv"], beer["price"],
                        ("\n" + beer["note"]) if beer.get("note") else "",
                        "; ".join(assumed)))

    elif action in ("add", "needs_button"):
        queue.append({"ts": ts, "action": action, "item": item, "section": extra,
                      "text": msg.get("text", ""), "logged": datetime.now().strftime("%Y-%m-%d %H:%M")})
        need = "a POS button" if action == "needs_button" else "a price, tank size and colour"
        reply = (":pencil: Logged: *%s*%s\nNeeds %s before it can go up. Nothing publishes half-built."
                 % (item, (" -> " + extra) if extra else "", need))

    print("  [%s] %s -> %s" % (action, item if isinstance(item, str) else item.get("name"), change or "queued"))
    return change, (channel, ts, reply) if reply else None


def load_json(path, default):
    try:
        return json.load(open(path))
    except FileNotFoundError:
        return default
    except Exception as e:
        print("  ! %s unreadable (%s) - resetting" % (path, e))
        return default


def run_once():
    state = load_json(STATE_PATH, None)
    queue = load_json(QUEUE_PATH, [])
    now_ts = "%.6f" % time.time()

    # First run: mark every channel as read from NOW. Never replay history -
    # the channels have weeks of old 86s and Computa would act on all of them.
    if state is None or "last_ts" not in state:
        state = {"last_ts": {cid: now_ts for cid in CHANNELS},
                 "started": datetime.now().isoformat(timespec="seconds")}
        if not DRY:
            json.dump(state, open(STATE_PATH, "w"), indent=1)
        print("first run - watching %s from now on, old messages ignored"
              % ", ".join("#" + n for n in CHANNELS.values()))
        return
    # older state files stored one channel's stamp as a bare string
    if isinstance(state["last_ts"], str):
        state["last_ts"] = {cid: state["last_ts"] for cid in CHANNELS}
    for cid in CHANNELS:                       # a channel added later starts from now
        state["last_ts"].setdefault(cid, now_ts)

    # gather new messages from every channel, tagged with where they came from
    msgs = []
    # ...and anything typed under a thread we answered in the last 30 minutes
    threads = state.setdefault("threads", {})
    for tts in list(threads):
        th = threads[tts]
        if time.time() - th.get("opened", 0) > 1800:
            threads.pop(tts, None); continue
        r = slack("conversations.replies", channel=th["channel"], ts=tts, oldest=th["last"], limit=20)
        for m in r.get("messages", []) if r.get("ok") else []:
            if m["ts"] != th["last"] and m["ts"] != tts and not m.get("bot_id") and not m.get("subtype"):
                msgs.append((th["channel"], m)); th["last"] = max(th["last"], m["ts"], key=float)
    for cid, cname in CHANNELS.items():
        r = slack("conversations.history", channel=cid, oldest=state["last_ts"][cid], limit=50)
        if not r.get("ok"):
            print("  ! can't read #%s (%s) - is Computa invited there?" % (cname, r.get("error")))
            continue
        for m in r.get("messages", []):
            if (m["ts"] != state["last_ts"][cid] and not m.get("bot_id")
                    and m.get("type") == "message" and not m.get("subtype")):
                msgs.append((cid, m))
    msgs.sort(key=lambda cm: float(cm[1]["ts"]))
    if not msgs:
        print("no new messages"); return

    print("%d new message(s)" % len(msgs))
    data, sha = fetch_beers()
    if not validate(data):
        print("  ! beers.json on GitHub failed validation - not touching it this cycle")
        health("bad_json")
        return
    changes, replies = [], []
    for cid, m in msgs:
        r = handle(m, data, queue, cid)
        if not r:
            continue
        change, rep = r
        if change:
            changes.append(change)
        if rep:
            replies.append(rep)

    if changes:
        if not validate(data):
            print("  ! result failed validation - refusing to commit")
            health("bad_result")
            return
        if not commit_beers(data, sha, "; ".join(changes)):
            # Someone else wrote beers.json between our fetch and our commit
            # (the admin page, most likely). Don't advance state, don't reply -
            # next cycle re-reads and re-applies from scratch. Nothing is lost.
            print("  commit rejected - will retry next cycle")
            health("commit_failed")
            return
        print("committed: " + "; ".join(changes))

    for cid, ts_, text in replies:
        if not DRY:
            slack("chat.postMessage", channel=cid, thread_ts=ts_, text=text)
        # remember the thread so a correction typed under our reply is seen
        state.setdefault("threads", {})[ts_] = {"channel": cid, "last": ts_, "opened": time.time()}

    for cid, m in msgs:
        state["last_ts"][cid] = max(state["last_ts"][cid], m["ts"], key=float)
    if not DRY:
        json.dump(state, open(STATE_PATH, "w"), indent=1)
        json.dump(queue, open(QUEUE_PATH, "w"), indent=1, ensure_ascii=False)
    health("ok")
    if queue:
        print("%d item(s) waiting on a human - see %s" % (len(queue), QUEUE_PATH))


# ---- five-second rule: one post to #bar-only each morning at 10:30 MT ----
FIVE_SEC_CHANNEL = "C0B3E5GF6UR"  # bar-only
FIVE_SEC_MARK = "Five seconds."
FIVE_SEC_UNTIL = "2026-10-20"  # stops on its own after this date; bump it to extend
FIVE_SEC_MSG = (
    "*Five seconds.*\n"
    "Every guest who sits down or walks up to the window gets acknowledged inside "
    "five seconds \u2014 eye contact and \u201cbe right with you\u201d counts. "
    "You don't have to be ready for them. They just have to know you saw them."
)


def five_second_nudge():
    """Post the acknowledgment standard daily at the first poll after 10:30 MT.

    Runs through FIVE_SEC_UNTIL, then goes quiet without anyone having to turn it off.

    Dedupes against the channel's own history rather than local state, so a
    runner restart or a handoff mid-morning can't double-post it.
    """
    try:
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _zi

        now = _dt.now(_zi("America/Denver"))
        if now.strftime("%Y-%m-%d") > FIVE_SEC_UNTIL:
            return
        if now.hour != 10 or now.minute < 30:
            return

        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        hist = slack(
            "conversations.history",
            channel=FIVE_SEC_CHANNEL,
            oldest="%.6f" % midnight.timestamp(),
            limit=200,
        )
        for m in (hist or {}).get("messages") or []:
            if FIVE_SEC_MARK in (m.get("text") or ""):
                return

        slack("chat.postMessage", channel=FIVE_SEC_CHANNEL, text=FIVE_SEC_MSG)
        print("five-second nudge posted")
    except Exception as e:
        print("five_second_nudge: %s" % e)


if __name__ == "__main__":
    if "--status" in sys.argv:
        h = load_json(HEALTH_PATH, {}); st = load_json(STATE_PATH, {}); q = load_json(QUEUE_PATH, [])
        print("last ok:      %s" % h.get("last_ok", "never"))
        print("failures:     %s%s" % (h.get("fails", 0), (" (" + h.get("last_error","") + ")") if h.get("fails") else ""))
        print("watching since: %s" % st.get("started", "?"))
        print("waiting on a human: %d" % len(q))
        for item in q: print("   - %s: %s" % (item.get("action"), item.get("item")))
        sys.exit(0)
    if "--watch" in sys.argv:
        print("watching %s every %ds - ctrl-c to stop" % (", ".join("#"+n for n in CHANNELS.values()), POLL_SEC))
        while True:
            try:
                run_once()
                five_second_nudge()
            except Exception as e:
                print("error: %s" % e)
                try: health("exception")
                except Exception: pass
            time.sleep(POLL_SEC)
    else:
        run_once()
        five_second_nudge()
