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
  86 kettle chips / wings are back         food & anything at the register: sold out / back on
                                           Square Online (gatesdeli.com) and DoorDash follow (square.py)
  86 all wings                             every item with that word
  every beers.json change                  mirrored to plattparkbrewing.com's beer list (spothopper.py)

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
try:
    import square            # 86 -> sold out at the register / gatesdeli.com / DoorDash (needs SQUARE_ACCESS_TOKEN)
except ImportError:
    square = None
try:
    import spothopper        # beers.json -> the website's beer list (needs SPOTHOPPER_EMAIL/PASSWORD)
except ImportError:
    spothopper = None
try:
    import briefs            # 10:30 pre-shift brief + Sunday 4pm outlook (briefs.py)
except ImportError:
    briefs = None
from datetime import datetime, timezone

CHANNELS = {                       # every channel Computa listens in
    "C0B3E5GF6UR": "bar-only",     # bartenders: 86s, last keg, back on
    "C0AQ68G7DRB": "brew-x-bar",   # brewers (Jules, Greg): new beers
    "C0CALA09Z35": "board",        # Oct 20 2026: the admin side - levels, panel edits, tests, shadow reports
}
BOARD_CHANNEL = "C0CALA09Z35"
ALERT_CHANNEL = BOARD_CHANNEL      # health warnings go to #board, never the bartenders' channel
ON_CALL = "U0AQDQ7JH5G"            # Christian: gets a DM when Computa breaks, and texts Colby
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
            slack("chat.postMessage", channel=ON_CALL, text=":white_check_mark: Computa is back - nothing to do.")
        h = {"fails": 0, "alerted": False, "last_ok": now}
    else:
        h["fails"] = h.get("fails", 0) + 1
        h["last_error"] = status
        h["last_fail"] = now
        if h["fails"] >= ALERT_AFTER and not h.get("alerted"):
            msg = (":warning: Computa can't update the wall right now (%s). The board and menu are frozen as they "
                   "are until it's fixed - 86s still work at the register as normal. Christian: please text Colby. "
                   "I'll post here when it's back." % status)
            slack("chat.postMessage", channel=ALERT_CHANNEL, text=msg)
            slack("chat.postMessage", channel=ON_CALL, text=msg)
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
BACK_RE    = re.compile(r"^(?:the\s+)?(?P<item>.{2,48}?)\s+(?:(?:is|are)\s+back(?:\s+on|\s+in\s+stock)?|back\s+on|back\s+in\s+stock|on\s+again|pouring\s+again|back[.!]?$)\b", re.I)
NOLASTKEG_RE = re.compile(r"(?:^(?:remove|clear|take\s+off|drop)\s+(?:the\s+)?last\s*keg(?:\s+sash)?\s+(?:from|off|on)\s+(?:the\s+)?(?P<item>.{2,48}?)"
                          r"|^(?:the\s+)?(?P<item2>.{2,48}?)\s+(?:is\s+)?(?:not|no\s+longer)\s+(?:on\s+)?(?:its\s+)?last\s*keg"
                          r"|^(?:the\s+)?(?P<item3>.{2,48}?)\s+last\s*keg\s+(?:sash\s+)?off"
                          r"|^(?:the\s+)?(?P<item4>.{2,48}?)\s+should\s*(?:n'?t|\s+not)\s+(?:say|be|show|read)\s+(?:on\s+)?last\s*keg)[.!]?\s*$", re.I)
PRICE10_RE = re.compile(r"^(?:the\s+)?(?P<item>.{2,48}?)\s+10\s*oz\s+(?:is\s+now|now|is|=|->|to)\s+\$\s*(?P<price>\d+(?:\.\d{1,2})?)[.!]?\s*$", re.I)
# "Also Pouring" panel (ciders, kombucha, wine, cocktails) - lives in beers.json["also"]; seeded from this list the first time a command touches it
ALSO_DEFAULT = [
    {"name": "BrightCider",      "sub": "2 Towns \u00b7 dry cider",      "price": "$9"},
    {"name": "Pumpkin Cider",    "sub": "2 Towns \u00b7 seasonal",       "price": "$9"},
    {"name": "Boochcraft",       "sub": "kiwi citrus kombucha",         "price": "$9"},
    {"name": "Bravazzi",         "sub": "hard Italian soda",            "price": "$9"},
    {"name": "Wine",             "sub": "red \u00b7 white \u00b7 ros\u00e9", "price": "$9\u201311"},
    {"name": "Draft Cocktail",   "sub": "Craftwell peach mojito",       "price": "$12"},
    {"name": "Frozen Cocktails", "sub": "Mexican Firing Squad \u00b7 Transfusion", "price": "$12"},
]
ALSO_RM_RE  = re.compile(r"^(?:(?:remove|take|drop|pull|delete)\s+(?P<item>.{2,40}?)\s+(?:off|from|off\s+of|out\s+of)\s+(?:the\s+)?(?:also\s+pouring|side\s+panel|also\s+list)|also\s+pouring\s*[:\-]\s*(?:remove|drop|delete)\s+(?P<item2>.{2,40}?))[.!]?\s*$", re.I)
ALSO_ADD_RE = re.compile(r"^(?:add\s+)?(?P<item>.{2,40}?)\s+to\s+(?:the\s+)?(?:also\s+pouring|side\s+panel|also\s+list)(?:\s*[:,\-\u2014]\s*(?P<sub>[^$]{0,70}?))?(?:\s*\$\s*(?P<price>\d+(?:\.\d+)?(?:\s*[-\u2013]\s*\d+(?:\.\d+)?)?))?[.!]?\s*$", re.I)

def style_case(text):
    """Title-case a style but keep the beer acronyms upright: IPA, DIPA, APA, NA, ESB, NEIPA, Marzen stays as typed."""
    KEEP = {"ipa", "dipa", "tipa", "apa", "na", "esb", "neipa", "ddh", "bbl", "n/a"}
    out = []
    for w in (text or "").split():
        core = w.strip("()·,")
        out.append(w.upper() if core.lower() in KEEP else (w if w[:1].isupper() and w[1:].islower() else w.title()))
    return " ".join(out)

def also_list(data):
    lst = data.get("also")
    if not isinstance(lst, list):
        lst = [dict(x) for x in ALSO_DEFAULT]
        data["also"] = lst
    return lst

def match_also(name, lst):
    q = norm(name)
    if not q: return None
    for it in lst:
        n = norm(it.get("name", ""))
        if q == n or q in n or n in q:
            return it
    return None

GUEST_RE    = re.compile(r"^(?:the\s+)?(?P<item>.{2,48}?)\s+(?:is\s+(?:a\s+|our\s+)?guest\s+tap|guest\s+tap\s*[:=]?\s*(?P<state>on|yes|off|no)?|sash\s*[:=]\s*(?P<sash>.{2,24}?))[.!]?\s*$", re.I)
ADJUNCT_RE = re.compile(r"^(?:the\s+)?(?P<item>.{2,48}?)\s+(?:contains|has|allergens?\s*[:=])\s*(?P<what>(?:lactose|wheat|gluten|nuts?|peanuts?|tree\s+nuts?|dairy|honey|coconut|none|nothing)(?:\s*(?:,|and|&|·)\s*(?:lactose|wheat|gluten|nuts?|peanuts?|tree\s+nuts?|dairy|honey|coconut))*)[.!]?\s*$", re.I)
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

# Messages sent through the Claude Slack app arrive with " *Sent using* <@U…|Claude>" on the end of the text
# (inline, not on its own line). It broke every end-anchored command on Sept 30 2026; strip it before parsing.
SENT_USING_RE = re.compile(r"\s*\*?Sent using\*?\s*<@U[A-Z0-9]+(?:\|[^>]*)?>\s*$", re.I)

WOKE_RE = re.compile(r"^\s*(?:<@U[A-Z0-9]+(?:\|[^>]*)?>|%s\b)[\s,!:.\-]*" % WAKE, re.I)

def parse(text):
    """First command in the message (kept for callers that want one)."""
    cmds = parse_all(text)
    return cmds[0] if cmds else None


def mentioned(text):
    return bool(WOKE_RE.match(SENT_USING_RE.sub("", text or "").strip()))


def parse_all(text):
    """Every command in the message, one per line. Oct 13 2026: Jules posted nine tank levels in one
    @Computa message and nothing happened - the old guard dropped any message over 220 chars and the
    line loop returned after the first hit. Now each line is judged on its own; a message that reads
    like an announcement (backticks) is still ignored, as is any single line over 220 chars."""
    body = SENT_USING_RE.sub("", text or "").strip()
    if "`" in body or len(body) > 2000:
        return []
    if newbeer and NEWBEER_TRIGGER.match(body):
        nb = newbeer.parse_new_beer(body)
        if nb and nb.get("name"):
            return [("newbeer", nb, body)]   # handle() turns this into a restore if the name is already known
    # "@Computa 86 chela" arrives as "<@U0C2GMAT8CD> 86 chela" - the mention is the wake word
    woke = WOKE_RE.match(body)
    if woke:
        body = body[woke.end():].strip()
    out = []
    for line in [l.strip() for l in body.split("\n") if l.strip()]:
        if len(line) > 220 or IGNORE.search(line):
            continue
        c = parse_line(line, woke)
        if c:
            out.append(c)
            if c[0] in ("status", "nopick", "report"):
                break
    return out


def parse_line(line, woke):
    if True:
        if STATUS_RE.search(line) or (woke and ASKED_RE.search(line)):
            return "status", "", None
        if re.match(r"^(?:sync|read|pull|check)\s+(?:the\s+)?(?:cellar|sheet|greg'?s?\s+sheet|inventory(?:\s+sheet)?|levels)\b|^levels\s+from\s+(?:the\s+)?sheet\b", line, re.I):
            return "cellar", "", None
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
        m = GUEST_RE.search(line)
        if m:
            st = (m.group("state") or "").lower(); sash = (m.group("sash") or "").strip()
            if sash: return "sash", m.group("item").strip(" .,-"), (None if sash.lower() in ("off", "none", "clear") else sash)
            return "sash", m.group("item").strip(" .,-"), (None if st in ("off", "no") else "guest tap")
        m = ALSO_RM_RE.search(line)
        if m:
            return "also_rm", (m.group("item") or m.group("item2") or "").strip(" .,-"), None
        m = ALSO_ADD_RE.search(line)
        if m:
            return "also_add", m.group("item").strip(" .,-"), {"sub": (m.group("sub") or "").strip(" .,-"), "price": m.group("price")}
        m = ADJUNCT_RE.search(line)
        if m:
            return "adjunct", m.group("item").strip(" .,-"), m.group("what").strip(" .,-")
        m = PRICE_RE.search(line)
        if m:
            return "price", m.group("item").strip(" .,-"), float(m.group("price"))
        m = ABV_RE.search(line)
        if m:
            return "abv", m.group("item").strip(" .,-"), float(m.group("abv"))
        m = FRESHKEG_RE.search(line)
        if m:
            return "back", m.group("item").strip(" .,-"), line
        for rx, act in ((NOBTN_RE, "needs_button"), (REMOVE_RE, "remove"),
                        (KICKED_RE, "remove"), (BACK_RE, "back"), (LASTKEG_RE, "lastkeg")):
            m = rx.search(line)
            if m:
                if act == "back" and not woke and chatter_tail(line[m.end():]):
                    continue   # "Transfusion cider is back in stock for a very short time so I grabbed..." is talk, not a command
                # "back" carries its own line so a multi-line batch reads each beer's level from its line
                item = re.sub(r"^(?:re[- ]?add|add|put|bring)\s+", "", m.group("item").strip(" .,-"), flags=re.I)   # "add kakou back on"
                return act, item.strip(" .,-"), (line if act == "back" else None)
        m = FLAVOR_RE.search(line)
        if m and not re.search(r"\b(back|kicked|out|low|fixed|broken)\b", m.group("flavor"), re.I):
            return "flavor", m.group("item").strip(" .,-"), m.group("flavor").strip(" .,-")
        m = ADD_RE.search(line)
        if m and (woke or re.match(r"^\s*(?:re[- ]?add|add|put)\b", line, re.I)):
            item = re.sub(r"\s+back(?:\s+on|\s+up)?\s*$", "", m.group("item").strip(" .,-"), flags=re.I).strip(" .,-")
            return "add", item, {"section": (m.group("section") or "").strip() or None, "line": line, "woke": bool(woke)}
    return None


def chatter_tail(tail):
    """What follows "X is back (on)" on the same line. A level, a short aside or nothing = a command;
    a sentence that keeps going = someone talking about a beer, not to Computa."""
    t = (tail or "").strip()
    if not t or t[0] in ",;:-(!." or LEVEL_RE.search(t):
        return False
    if re.match(r"^(?:on\s+)?(?:tap|tonight|today|now|again|this\s+(?:morning|afternoon|evening))\b[.!]?\s*$", t, re.I):
        return False
    return len(t.split()) > 2


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
    beer["levelAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
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


COLBY = "U08T34X7G"
_nudged = {}

def nudge_colby(item, text, channel):
    """Anything Computa punts goes to Colby as a DM with the original message - the queue file is only a log now."""
    key = norm(item)[:40]
    if time.time() - _nudged.get(key, 0) < 3600 or DRY:
        return
    _nudged[key] = time.time()
    try:
        slack("chat.postMessage", channel=COLBY,
              text=":grey_question: Couldn't handle *%s* in #%s:\n> %s" % (item, CHANNELS.get(channel, channel), (text or "").replace("\n", " / ")[:300]))
    except Exception as e:
        print("  ! nudge: %s" % e)


def whats_where(data):
    """One line each: what's pouring, what came off recently, what's on the side panel."""
    beers = data.get("beers", []); recent = data.get("recent", [])
    out = ["Pouring: " + (" \u00b7 ".join(b["name"] for b in beers) or "nothing")]
    if recent:
        out.append("Recently off: " + " \u00b7 ".join(b["name"] for b in recent[:8]))
    also = data.get("also") if isinstance(data.get("also"), list) else ALSO_DEFAULT
    out.append("Also pouring: " + " \u00b7 ".join(x["name"] for x in also))
    return "\n".join(out)


def square_move(item, back):
    """An 86 (or a back) for something that isn't on the tap list: try the register.
    -> (ok, reply_or_None, label). Never raises."""
    if not (square and square.enabled()):
        return False, None, None
    try:
        return square.eighty_six(item, back=back, dry=DRY)
    except Exception as e:
        print("  ! square: %s" % e)
        return False, ":warning: Couldn't reach the register (%s) - Colby, check the Square token." % str(e)[:80], None


def square_aside(name, back):
    """A beer that kicked (or came back) also flips its register button - exact name only, never a guess."""
    if not (square and square.enabled()):
        return ""
    try:
        kind, res = square.resolve(name, floor=0.95)
        if kind != "one":
            return ""
        touched = square.set_sold_out(res, not back, dry=DRY)
        if any(how == "set" for _, how in touched):
            return "\n:convenience_store: Register button *%s* %s too." % (res["item_data"]["name"], "back on" if back else "marked kicked")
    except Exception as e:
        print("  ! square aside: %s" % e)
    return ""


def website_sync(data, queue):
    """Mirror beers.json onto plattparkbrewing.com after every commit. Failures are logged once, never fatal."""
    if not (spothopper and spothopper.enabled()) or DRY:
        return
    try:
        spothopper.login()
        ch = spothopper.sync(data.get("beers", []))
        print("  website: " + ("; ".join(ch) if ch else "already matched"))
        queue[:] = [q for q in queue if q.get("action") != "website_sync_failed"]
    except Exception as e:
        print("  ! website sync: %s" % e)
        if not any(q.get("action") == "website_sync_failed" for q in queue):
            queue.append({"action": "website_sync_failed", "item": str(e)[:160],
                          "logged": datetime.now().strftime("%Y-%m-%d %H:%M")})
            try:
                slack("chat.postMessage", channel=ALERT_CHANNEL,
                      text=":warning: The board and menu updated but the website's beer list didn't (%s). "
                           "Colby, the SpotHopper login may need a look. I'll retry on the next change." % str(e)[:100])
            except Exception:
                pass


# ---- the smart read: when the patterns above miss, ask Claude what the message meant ----
# Only when a key exists (repo secret ANTHROPIC_API_KEY), only for messages that name a beer we know or
# @mention Computa, and only through the same actions, validation and replies as the typed commands -
# Claude proposes, the code disposes. A fraction of a cent per message, about two seconds.
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.environ.get("COMPUTA_MODEL", "claude-haiku-5-5")
LLM_SYSTEM = (
    "You translate one Slack message from brewery staff into commands for Computa, the tap-board bot at "
    "Platt Park Brewing. You are given the message, the beers pouring, the beers recently taken off, and the "
    "Also Pouring side panel (ciders, kombucha, wine, cocktails). Reply with JSON only: "
    '{"commands":[...]} where each command is one of:\n'
    '{"action":"remove","item":NAME}  - 86 / kicked / out / gone / take it off\n'
    '{"action":"back","item":NAME,"bbl":NUMBER_OR_NULL,"size":10_OR_20_OR_NULL}  - back on / tapped / level update\n'
    '{"action":"lastkeg","item":NAME}  {"action":"nolastkeg","item":NAME}\n'
    '{"action":"price","item":NAME,"price":NUMBER}  {"action":"price10","item":NAME,"price":NUMBER}\n'
    '{"action":"abv","item":NAME,"abv":NUMBER}\n'
    '{"action":"wall","item":NAME,"text":SHORT_LINE}  {"action":"note","item":NAME,"text":LINE}\n'
    '{"action":"sash","item":NAME,"sash":"guest tap"|null}\n'
    '{"action":"adjunct","item":NAME,"what":"lactose, wheat"}\n'
    '{"action":"also_rm","item":NAME}  {"action":"also_add","item":NAME,"sub":TEXT,"price":"9"}\n'
    '{"action":"status"}\n'
    "Use the exact beer name from the lists. Only commands the message clearly intends; several if it says several. "
    "Conversation, questions, plans for later, maintenance talk, or anything ambiguous -> {\"commands\":[]}. "
    "Food and register items are not beers - leave them out."
)

def llm_parse(text, data, woke):
    if not ANTHROPIC_KEY:
        return []
    beers  = [b["name"] for b in data.get("beers", [])]
    recent = [b["name"] for b in data.get("recent", [])]
    also   = [x.get("name", "") for x in (data.get("also") if isinstance(data.get("also"), list) else ALSO_DEFAULT)]
    payload = {"model": LLM_MODEL, "max_tokens": 500, "system": LLM_SYSTEM,
               "messages": [{"role": "user", "content": json.dumps({
                   "message": text, "pouring": beers, "recently_off": recent, "also_pouring": also,
                   "computa_mentioned": bool(woke)})}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(payload).encode(),
                                 headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                                          "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            out = json.load(r)
        raw = "".join(c.get("text", "") for c in out.get("content", []) if c.get("type") == "text")
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
        cmds = json.loads(raw).get("commands", [])
    except Exception as e:
        print("  ! llm: %s" % e)
        return []
    out = []
    for c in cmds[:12]:
        if not isinstance(c, dict): continue
        a = c.get("action"); item = str(c.get("item") or "").strip()
        try:
            if a == "status": out.append(("status", "", None))
            elif a in ("remove", "lastkeg", "nolastkeg", "also_rm") and item: out.append((a, item, None))
            elif a == "back" and item:
                line = "%s is back on" % item
                if c.get("bbl"):
                    line += ", %sbbl" % c["bbl"] + (" in a %sbbl" % int(c["size"]) if c.get("size") else "")
                out.append(("back", item, line))
            elif a in ("price", "price10") and item: out.append((a, item, float(c["price"])))
            elif a == "abv" and item: out.append(("abv", item, float(c["abv"])))
            elif a in ("wall", "note") and item and c.get("text"): out.append((a, item, str(c["text"]).strip()))
            elif a == "sash" and item: out.append(("sash", item, c.get("sash") or None))
            elif a == "adjunct" and item: out.append(("adjunct", item, str(c.get("what") or "none")))
            elif a == "also_add" and item: out.append(("also_add", item, {"sub": str(c.get("sub") or ""), "price": (str(c["price"]) if c.get("price") else None)}))
        except Exception:
            continue
    return out

def about_a_beer(text, data):
    """Cheap gate before spending an API call: does the message name something we know?"""
    t = norm(text)
    names = [b.get("name", "") for b in data.get("beers", [])] + [b.get("name", "") for b in data.get("recent", [])]
    names += [x.get("name", "") for x in (data.get("also") if isinstance(data.get("also"), list) else ALSO_DEFAULT)]
    toks = [x for x in re.findall(r"[a-z0-9]+", text.lower()) if len(x) >= 3]
    for n in names:
        if not n: continue
        if norm(n) and norm(n) in t: return True
        for w in re.split(r"[\s\-/]+", n):
            w = norm(w)
            if len(w) < 3: continue
            for x in toks:
                # "wit" -> Witbier, "plattmo" -> Plattmosphere, "nadara" -> Nadare
                if x == w or x in ("wit", "tsd") or (len(x) >= 5 and (w.startswith(x) or difflib.SequenceMatcher(None, w, x).ratio() >= 0.8)):
                    return True
    return False

def describe(cmds):
    """'86 Witbier · Plattmosphere back on 9bbl' - what Claude read, so people learn the phrasing."""
    bits = []
    for a, item, extra in cmds:
        if a == "remove": bits.append("86 " + item)
        elif a == "back": bits.append(extra if isinstance(extra, str) else item + " is back on")
        elif a in ("price", "price10"): bits.append("%s %s$%.2f" % (item, "10oz " if a == "price10" else "", extra))
        elif a == "abv": bits.append("%s %s%%" % (item, extra))
        elif a == "lastkeg": bits.append(item + " on last keg")
        elif a == "nolastkeg": bits.append(item + " not on last keg")
        elif a == "status": bits.append("status")
        else: bits.append("%s %s" % (a.replace("_", " "), item))
    return " \u00b7 ".join(bits)


DIDNT_CATCH = (":thinking_face: Didn't catch that. One command per line, like:\n"
               "`86 nadare` · `nadare is back on, 4bbl in a 10bbl` · `nadare is on last keg` · "
               "`nadare is now $8` · `nadare wall line: Rice Lager · crisp` · `New beer: Name — Style, 5.2%, notes`")

def handle(msg, data, queue, channel):
    text = msg.get("text", "")
    cmds = parse_all(text)
    read_as = ""
    if not cmds and ANTHROPIC_KEY and "`" not in text and len(text) <= 600 and (mentioned(text) or about_a_beer(text, data)):
        cmds = llm_parse(SENT_USING_RE.sub("", text), data, mentioned(text))
        if cmds:
            read_as = ":sparkles: Read that as: " + describe(cmds) + "\n"
            print("  [llm] " + describe(cmds))
    if not cmds:
        # @mentioned and nothing understood: say so instead of failing silently (Sept 30 ask)
        if mentioned(text):
            return None, (channel, msg["ts"], DIDNT_CATCH)
        return None
    changes, replies = [], []
    for action, item, extra in cmds:
        # "86 witbier and nadare": run the same action once per name
        parts = split_items(item) if (action in ("remove", "back", "lastkeg") and isinstance(item, str)) else [item]
        for part in parts:
            r = handle_one(msg, data, queue, channel, action, part, extra)
            if r:
                if r[0]: changes.append(r[0])
                if r[1]: replies.append(r[1][2])
    if read_as and replies:
        replies[0] = read_as + replies[0]
    if len(cmds) == 1 and len(changes) <= 1:
        # single command: identical shape to before
        return (changes[0] if changes else None), ((channel, msg["ts"], "\n".join(replies)) if replies else None)
    return ("; ".join(changes) or None), ((channel, msg["ts"], "\n".join(replies)) if replies else None)


def handle_one(msg, data, queue, channel, action, item, extra):
    ts = msg["ts"]
    beers  = data.setdefault("beers", [])
    recent = data.setdefault("recent", [])
    reply = change = None

    if action == "cellar":
        try:
            cellar_sync(force=True, reply=(channel, ts))
        except Exception as e:
            print("cellar: %s" % e)
        return None

    if action == "remove":
        hits = match_beers(item, beers)
        if len(hits) > 1:
            reply = (":grey_question: *%s* could be %s - which one?" %
                     (item, " or ".join("*"+h["name"]+"*" for h in hits)))
            b = None
        else:
            b = hits[0] if hits else None
        gone = None if b or reply else match_beer(item, recent)
        if gone:
            reply = ":information_source: *%s* is already off the board%s. Say _\"%s is back on\"_ to bring it back." % (
                gone["name"], (" (since %s)" % gone["offSince"]) if gone.get("offSince") else "", gone["name"])
        if b:
            beers.remove(b)
            b["offSince"] = datetime.now().strftime("%Y-%m-%d")
            recent.insert(0, b); data["recent"] = recent[:12]
            change = "86 " + b["name"]
            reply = (":white_check_mark: 86'd *%s* - off the board, the menu and the website within a "
                     "couple of minutes.\nSay _\"%s is back on\"_ when it returns." % (b["name"], b["name"]))
            reply += square_aside(b["name"], back=False)
        elif not reply and match_also(item, data.get("also") if isinstance(data.get("also"), list) else ALSO_DEFAULT):
            side = match_also(item, also_list(data)); also_list(data).remove(side)
            change = "also pouring: -%s" % side["name"]
            reply = ":white_check_mark: *%s* is off the Also Pouring panel - the wall updates in a couple of minutes." % side["name"]
        elif not reply:
            ok, sq_reply, _ = square_move(item, back=False)
            if sq_reply:
                reply = sq_reply
                if ok: change = None          # nothing in beers.json changed; Square holds the state
            else:
                queue.append({"ts": ts, "action": "remove_unmatched", "item": item, "text": msg.get("text", "")})
                nudge_colby(item, msg.get("text", ""), channel)
                reply = ":grey_question: Didn't find *%s*.\n%s" % (item, whats_where(data))

    elif action == "back":
        b = match_beer(item, recent)
        already = match_beer(item, beers)
        if b:
            recent.remove(b); b.pop("offSince", None)
            b["tappedDaysAgo"] = 0
            lvl = read_level(extra if isinstance(extra, str) else msg.get("text", ""), b)
            beers.append(b)
            change = b["name"] + " back on"
            reply = ":beer: *%s* is back on - it'll reappear shortly.%s" % (b["name"], lvl)
            reply += square_aside(b["name"], back=True)
        elif already:
            lvl = read_level(extra if isinstance(extra, str) else msg.get("text", ""), already)
            if lvl:
                change = already["name"] + " level"
                reply = ":beer: *%s* is pouring -%s" % (already["name"], lvl)
            else:
                reply = ":beer: *%s* is already pouring - nothing to do. Add a level to update it: _\"%s is back on, 6bbl in a 10bbl\"_." % (already["name"], already["name"])
        else:
            ok, sq_reply, _ = square_move(item, back=True)
            if sq_reply:
                reply = sq_reply
            else:
                queue.append({"ts": ts, "action": "restore_unknown", "item": item, "text": msg.get("text", "")})
                nudge_colby(item, msg.get("text", ""), channel)
                reply = (":grey_question: *%s* isn't on the recently-off list, so I don't have its price and tank. "
                         "For a brand-new beer: _\"New beer: Name \u2014 Style, 5.2%%, notes\"_.\n%s" % (item, whats_where(data)))

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
        nudge_colby(item, msg.get("text", ""), channel)
        reply = ":eyes: Got it - flagged for Colby. If you want me to change it, tell me what it should say."

    elif action == "status":
        lines = ["%s%s" % (b["name"], (" (last keg)" if b.get("sash") == "last keg" else "") + (" :star:" if b.get("pick") else "") + medal_tag(b))
                 for b in beers]
        reply = ":beers: *%d on the wall:* %s\nLast change: %s" % (len(beers), " \u00b7 ".join(lines), data.get("updatedBy", "?"))
        if square and square.enabled():
            try:
                so = square.status()
                reply += "\n:no_entry_sign: *Sold out at the register:* " + (" \u00b7 ".join(n for n, _ in so) if so else "nothing")
            except Exception as e:
                reply += "\n:warning: Couldn't read the register (%s)." % str(e)[:60]

    elif action == "flavor":
        b = match_beer(item, beers)
        if b:
            b["style"] = style_case(extra)
            change = "%s -> %s" % (b["name"], extra)
            reply = ":arrows_counterclockwise: *%s* updated to _%s_." % (b["name"], extra)
        else:
            side = match_also(item, also_list(data))
            if side:
                side["sub"] = extra; change = "also pouring: ~%s" % side["name"]
                reply = ":pencil2: *%s* now reads _%s_ on the Also Pouring panel." % (side["name"], extra)
            else:
                queue.append({"ts": ts, "action": "flavor_offlist", "item": item, "flavor": extra,
                              "text": msg.get("text", "")})
                reply = ":grey_question: *%s* isn't on the tap list or the Also Pouring panel - logged for Colby." % item

    elif action == "sash":
        b = match_beer(item, beers)
        if b:
            if extra:
                b["sash"] = extra; b["guest"] = (extra.lower() == "guest tap") or b.get("guest", False)
                change = "%s sash: %s" % (b["name"], extra)
                reply = ":label: *%s* now wears a *%s* sash on the wall." % (b["name"], extra.upper())
            else:
                b.pop("sash", None); b.pop("guest", None); change = b["name"] + " sash off"
                reply = ":white_check_mark: Sash off *%s*." % b["name"]
        else:
            reply = ":grey_question: Couldn't find *%s* on the tap list." % item

    elif action == "also_rm":
        lst = also_list(data); it = match_also(item, lst)
        if it:
            lst.remove(it); change = "also pouring: -%s" % it["name"]
            reply = ":white_check_mark: *%s* is off the Also Pouring panel - the wall updates in a couple of minutes." % it["name"]
        else:
            reply = ":grey_question: *%s* isn't on the Also Pouring panel. It has: %s" % (item, " \u00b7 ".join(x["name"] for x in lst))

    elif action == "also_add":
        lst = also_list(data); it = match_also(item, lst)
        sub = (extra or {}).get("sub") or ""; price = (extra or {}).get("price")
        if it:
            if sub: it["sub"] = sub
            if price: it["price"] = "$" + price.replace(" ", "")
            change = "also pouring: ~%s" % it["name"]
            reply = ":pencil2: *%s* updated on Also Pouring: _%s_ %s" % (it["name"], it.get("sub", ""), it.get("price", ""))
        else:
            new = {"name": item.strip(), "sub": sub, "price": ("$" + price.replace(" ", "")) if price else ""}
            lst.append(new); change = "also pouring: +%s" % new["name"]
            reply = ":white_check_mark: *%s* added to Also Pouring%s." % (new["name"], "" if new["price"] else " - add a price with _\"%s to also pouring $9\"_" % new["name"])

    elif action == "adjunct":
        b = match_beer(item, beers)
        if b:
            adj = [a.strip() for a in re.split(r"\s*(?:,|and|&|·)\s*", extra) if a.strip() and a.strip().lower() not in ("none", "nothing")]
            if adj:
                b["adjuncts"] = adj
                change = "%s contains %s" % (b["name"], ", ".join(adj))
                reply = ":warning: *%s* now shows _contains %s_ under its name on the wall and the menu." % (b["name"], ", ".join(adj))
            else:
                b.pop("adjuncts", None); change = b["name"] + " adjuncts cleared"
                reply = ":white_check_mark: *%s* allergen line cleared." % b["name"]
        else:
            reply = ":grey_question: Couldn't find *%s* on the tap list." % item

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
            if re.search(r"\bguest\s+tap\b", msg.get("text", ""), re.I): beer["sash"] = "guest tap"; beer["guest"] = True
            beers.append(beer)
            change = "added " + beer["name"]
            reply = (":beer: *%s* is live on the board and the menu.\n"
                     "_%s \u00b7 %s%% \u00b7 $%.2f_%s\n\n"
                     "I assumed: %s.\nReply here if any of that's wrong and Colby will fix it. "
                     "Make sure it has a POS button before service."
                     % (beer["name"], beer["style"], beer["abv"], beer["price"],
                        ("\n" + beer["note"]) if beer.get("note") else "",
                        "; ".join(assumed)))

    elif action == "add" and (match_beer(item, recent) or match_beer(item, beers)):
        # "re add tropical snow dance" / "add Oktoberfest back to the menu": it's a restore, not a new beer
        ex = extra if isinstance(extra, dict) else {}
        return handle_one(msg, data, queue, channel, "back", item, ex.get("line") or msg.get("text", ""))

    elif action in ("add", "needs_button"):
        ex = extra if isinstance(extra, dict) else {}
        section = ex.get("section") if isinstance(extra, dict) else extra
        if action == "add" and not ex.get("woke", True):
            return None   # plain chatter with the word "add" in it, no beer we know - stay quiet
        queue.append({"ts": ts, "action": action, "item": item, "section": section,
                      "text": msg.get("text", ""), "logged": datetime.now().strftime("%Y-%m-%d %H:%M")})
        if action == "needs_button":
            reply = ":pencil: Logged: *%s* needs a POS button." % item
        else:
            reply = (":grey_question: *%s* isn't a beer I know. For a brand-new one: _\"New beer: Name \u2014 Style, 5.2%%, notes\"_ "
                     "and it goes up with a default price.\n%s" % (item, whats_where(data)))

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
        website_sync(data, queue)

    for cid, ts_, text in replies:
        if not DRY:
            acknowledge(cid, ts_, text)
        # remember the thread so a correction typed under our reply is seen
        state.setdefault("threads", {})[ts_] = {"channel": cid, "last": ts_, "opened": time.time()}
        if changes:   # and come back to this thread once the wall has actually picked the change up
            state.setdefault("confirm", []).append({"channel": cid, "ts": ts_, "stamp": data.get("updated"), "at": time.time()})

    for cid, m in msgs:
        state["last_ts"][cid] = max(state["last_ts"][cid], m["ts"], key=float)
    if not DRY:
        json.dump(state, open(STATE_PATH, "w"), indent=1)
        json.dump(queue, open(QUEUE_PATH, "w"), indent=1, ensure_ascii=False)
    health("ok")
    if queue:
        print("%d item(s) waiting on a human - see %s" % (len(queue), QUEUE_PATH))


# ---- the receipt: a reaction, not a paragraph (Colby, Oct 20 2026 - the bot's replies were crowding the crew's channel) ----
# A routine command that simply worked gets a :white_check_mark: on the message and no reply. Text still goes in the
# thread when there is something to say: a question, a "read that as", a warning, a status. If the bot lacks the
# reactions:write scope the reply is posted as before, so nothing is lost either way.
QUIET_OK = (":white_check_mark:", ":beer:", ":hourglass:", ":pencil2:", ":moneybag:", ":test_tube:", ":label:", ":arrows_counterclockwise:", ":star:")
_no_reactions = {"flag": False}

def react(cid, ts_, name):
    """Add one reaction; True if it landed. Remembers a missing scope so we stop trying."""
    if _no_reactions["flag"]:
        return False
    r = slack("reactions.add", channel=cid, timestamp=ts_, name=name)
    if r.get("ok") or r.get("error") == "already_reacted":
        return True
    if r.get("error") in ("missing_scope", "not_allowed_token_type", "invalid_auth"):
        _no_reactions["flag"] = True
    return False

def acknowledge(cid, ts_, text):
    """Routine success -> reaction. Anything with a question, warning, read-as or more than one line -> the thread."""
    first = (text or "").strip().split("\n")[0]
    routine = (first.startswith(QUIET_OK) and "\n" not in (text or "").strip() and ":grey_question:" not in text
               and ":warning:" not in text and ":sparkles:" not in text and "which one" not in text)
    # a routine 86 reply has a second line ("Say ... is back on ..."); that line is the only reason it's two lines
    if not routine and first.startswith(QUIET_OK) and ":sparkles:" not in text and ":warning:" not in text and ":grey_question:" not in text:
        rest = [l for l in (text or "").strip().split("\n")[1:] if l.strip()]
        routine = all(l.strip().startswith(("Say _", ":convenience_store:")) for l in rest)
    if routine and react(cid, ts_, "white_check_mark"):
        return
    slack("chat.postMessage", channel=cid, thread_ts=ts_, text=text)


# ---- confirm from the wall: "off the board in two minutes" is checked, not promised ----
WALL_JSON = "https://plattpark.github.io/liveboard/beers.json"
CONFIRM_AFTER = 360     # seconds before we stop waiting and say so

def wall_stamp():
    import urllib.request
    try:
        req = urllib.request.Request(WALL_JSON + "?t=%d" % int(time.time()), headers={"User-Agent": "computa", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return (json.load(r) or {}).get("updated")
    except Exception as e:
        print("  wall: %s" % e)
        return None

def confirm_from_wall():
    state = load_json(STATE_PATH, {}) or {}
    pending = state.get("confirm") or []
    if not pending or DRY:
        return
    live = wall_stamp()
    keep = []
    for c in pending:
        if live and c.get("stamp") and live >= c["stamp"]:
            if not react(c["channel"], c["ts"], "tv"):
                slack("chat.postMessage", channel=c["channel"], thread_ts=c["ts"], text=":tv: On the wall.")
        elif time.time() - c.get("at", 0) > CONFIRM_AFTER:
            slack("chat.postMessage", channel=c["channel"], thread_ts=c["ts"],
                  text=":warning: Six minutes and the wall hasn't picked this up yet. The data is right; the page may be slow to publish - give it a few more, then tell Colby if it still shows the old list.")
        else:
            keep.append(c)
    state["confirm"] = keep
    json.dump(state, open(STATE_PATH, "w"), indent=1)


# ---- cellar sync: Greg's weekly inventory sheet -> tank levels on the wall ----
# Greg keeps one Google Sheet per month ("October 26") with a tab per week ("wk 1".."wk 5");
# column D is the barrels left in the serving tank. A tiny Apps Script web app on Colby's
# account (cellar_levels.gs) serves the newest tab as JSON; the URL lives in computa_config.json
# ({"cellar_url": "..."}). Computa reads it every 30 minutes and only applies a reading once;
# a level someone typed in Slack after the sheet was saved always wins.
CELLAR_EVERY = 1800
CELLAR_NAMES = {   # Greg's shorthand -> the name on the wall (anything else goes through match_beer)
    "tropic": "Tropical Snow Dance", "astronaut": "Astronaut Amber", "wit": "Witbier",
    "chela": "Chela Morena", "platty lite": "Platty Lite", "platty": "Platty Lite",
    "kakou": "K\u0100KOU", "cream": "Madagascar Dream", "pumpkin": "Grandma's Pumpkin Pie",
    "nadare": "Nadare", "pistachio": "Nutorious", "ofest": "Oktoberfest", "plattmo": "Plattmosphere",
    "heffe": "Hefeweizen", "berliner": "Berliner", "phaded": "Phaded", "steam": "Steam",
    "x pale": "X Pale", "west c lager": "West Coast Lager",
}
_cellar = {"checked": 0}

def cellar_config():
    d = gh("contents/computa_config.json")
    if not d:
        return {}
    try:
        return json.loads(base64.b64decode(d["content"]).decode())
    except Exception:
        return {}

def cellar_fetch(url):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "computa"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def cellar_apply(reading, data, state, force=False):
    """Apply one sheet reading. Returns (changes list, summary lines list)."""
    stamp = str(reading.get("updated") or "")
    key = "%s|%s|%s" % (reading.get("sheet"), reading.get("tab"), stamp)
    seen = state.setdefault("cellar", {})
    if not force and seen.get("applied") == key:
        return [], []
    beers = data.setdefault("beers", [])
    changes, lines, skipped, unknown = [], [], [], []
    for row in reading.get("levels", []):
        name = str(row.get("name") or "").strip()
        try:
            bbls = float(row.get("bbls") or 0)
        except Exception:
            bbls = 0
        if not name or bbls <= 0:
            continue
        full = CELLAR_NAMES.get(name.lower())
        b = match_beer(full or name, beers)
        if not b:
            unknown.append("%s %.1f" % (name, bbls))
            continue
        if not force and stamp and b.get("levelAt") and b["levelAt"] > stamp:
            skipped.append(b["name"])          # someone set it in Slack after Greg saved the sheet
            continue
        if b.get("remainingOz") == int(bbls * BBL_OZ):
            lines.append("%s %.1f" % (b["name"], bbls)); continue
        b["remainingOz"] = int(bbls * BBL_OZ)
        b["levelAt"] = stamp or datetime.now(timezone.utc).isoformat(timespec="seconds")
        changes.append("%s level %.1f (sheet)" % (b["name"], bbls))
        lines.append("%s %.1f" % (b["name"], bbls))
    seen["applied"] = key
    seen["at"] = datetime.now().isoformat(timespec="seconds")
    summary = [":bar_chart: Levels from Greg's sheet (%s, %s): %s" % (reading.get("sheet"), reading.get("tab"), " \u00b7 ".join(lines) or "nothing on the wall")]
    if skipped: summary.append("Kept the newer Slack number for " + ", ".join(skipped) + ".")
    if unknown: summary.append("Not on the wall: " + ", ".join(unknown) + ".")
    return changes, summary

def cellar_sync(force=False, reply=None):
    """Every 30 minutes (or on 'sync cellar'): read the sheet, update levels, say what changed."""
    if DRY and not force:
        return
    if not force and time.time() - _cellar["checked"] < CELLAR_EVERY:
        return
    _cellar["checked"] = time.time()
    url = cellar_config().get("cellar_url")
    if not url:
        if reply: slack("chat.postMessage", channel=reply[0], thread_ts=reply[1], text=":grey_question: No cellar sheet is connected yet (computa_config.json has no cellar_url).")
        return
    try:
        reading = cellar_fetch(url)
    except Exception as e:
        print("cellar: fetch failed: %s" % e)
        if reply: slack("chat.postMessage", channel=reply[0], thread_ts=reply[1], text=":warning: Couldn't read the sheet (%s)." % str(e)[:80])
        return
    state = load_json(STATE_PATH, {}) or {}
    data, sha = fetch_beers()
    if not validate(data):
        return
    changes, summary = cellar_apply(reading, data, state, force=force)
    if changes:
        if validate(data) and commit_beers(data, sha, "; ".join(changes)):
            print("cellar: " + "; ".join(changes))
        else:
            print("cellar: commit failed, will retry"); state.get("cellar", {}).pop("applied", None)
    if (changes or force) and summary:
        if reply:
            slack("chat.postMessage", channel=reply[0], thread_ts=reply[1], text="\n".join(summary))
        else:
            slack("chat.postMessage", channel=BOARD_CHANNEL, text="\n".join(summary))   # #board
    if not DRY:
        json.dump(state, open(STATE_PATH, "w"), indent=1)


# ---- SHADOW MODE (Oct 20 2026, built while Colby is away; nothing here changes the wall) ----
# 1. Register mirror: when a bartender marks "<Beer> Pint" sold out at the POS, say in #board what the wall WOULD do.
# 2. Sales-driven levels: pints / 10oz / crowlers rung since the last measured level, turned into barrels, posted
#    once a morning next to the level on the wall - compare with Greg's Monday number before trusting it.
# MIRROR / SALES_LEVELS env: "shadow" (default) posts only; "off" stops; "on" is reserved for after the review.
MIRROR_MODE = os.environ.get("MIRROR", "shadow").strip().lower()
SALES_MODE  = os.environ.get("SALES_LEVELS", "shadow").strip().lower()
OZ_BY_SIZE  = (("pint", 16), ("10oz", 10), ("10 oz", 10), ("crowler", 32), ("taster", 4))

def _mt_now():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Denver"))
    except Exception:
        return datetime.now()

def _pint_items(names):
    """{wall name: Square item id} for '<name> Pint', exact name only - never a guess."""
    out = {}
    for n in names:
        try:
            for score, it in square.search(n + " Pint"):
                if norm(it["item_data"]["name"]) == norm(n + " Pint"):
                    out[n] = it["id"]; break
        except Exception as e:
            print("  shadow map %s: %s" % (n, e))
    return out

def shadow_mirror(state, data):
    if MIRROR_MODE == "off" or not (square and square.enabled()):
        return
    sh = state.setdefault("shadow", {})
    if time.time() - sh.get("mirror_at", 0) < 240:          # every ~4 minutes is plenty
        return
    sh["mirror_at"] = time.time()
    wall = [b["name"] for b in data.get("beers", [])]
    recent = [b["name"] for b in data.get("recent", [])][:12]
    m = sh.setdefault("map", {})
    missing = [n for n in wall + recent if n not in m]
    if missing and time.time() - sh.get("map_at", 0) > 3600:
        sh["map_at"] = time.time(); m.update(_pint_items(missing))
    ids = [m[n] for n in wall + recent if m.get(n)]
    if not ids:
        return
    try:
        objs = square.call("catalog/batch-retrieve", "POST", {"object_ids": ids}).get("objects", [])
    except Exception as e:
        print("  shadow mirror: %s" % e); return
    byid = {o["id"]: o for o in objs}
    last = sh.setdefault("last", {})
    t = _mt_now().strftime("%-I:%M%p").lower()
    for n in wall + recent:
        o = byid.get(m.get(n))
        if not o:
            continue
        so = square.sold_out_state(o)
        prev = last.get(n)
        last[n] = so
        if prev is None or so == prev:
            continue
        if so is True and n in wall:
            msg = ":ghost: Shadow · %s - the register marked *%s Pint* sold out. With the mirror on, I'd take *%s* off the wall now. (It's still up.)" % (t, n, n)
        elif so is False and n in recent:
            msg = ":ghost: Shadow · %s - *%s Pint* is back in stock at the register. With the mirror on, I'd put *%s* back on the wall. (It's still off.)" % (t, n, n)
        elif so is True and n in recent:
            msg = ":ghost: Shadow · %s - the register marked *%s Pint* sold out; the wall already has it off. Match." % (t, n)
        else:
            msg = ":ghost: Shadow · %s - *%s Pint* is back in stock at the register; the wall already shows it. Match." % (t, n)
        if not DRY:
            slack("chat.postMessage", channel=BOARD_CHANNEL, text=msg)
        print("  " + msg)

def shadow_sales(state, data):
    if SALES_MODE == "off" or not (square and square.enabled()):
        return
    sh = state.setdefault("shadow", {})
    if time.time() - sh.get("sales_at", 0) < 900:           # every 15 minutes
        return
    sh["sales_at"] = time.time()
    beers = {b["name"]: b for b in data.get("beers", [])}
    led = sh.setdefault("ledger", {})                         # name -> {"base": levelAt, "oz": sold since}
    for n, b in beers.items():
        base = b.get("levelAt") or ""
        if led.get(n, {}).get("base") != base:
            led[n] = {"base": base, "oz": 0, "pints": 0}
    since = sh.get("orders_since") or (datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    q = {"location_ids": [square.LOCATION], "limit": 500, "return_entries": False,
         "query": {"filter": {"state_filter": {"states": ["COMPLETED"]},
                              "date_time_filter": {"closed_at": {"start_at": since, "end_at": now_iso}}}}}
    cursor, unattributed = None, sh.get("pitcher_oz", 0)
    try:
        while True:
            if cursor: q["cursor"] = cursor
            r = square.call("orders/search", "POST", q)
            for o in r.get("orders", []):
                for li in o.get("line_items", []) or []:
                    nm = (li.get("name") or "").strip(); qty = float(li.get("quantity") or 0)
                    low = nm.lower()
                    if low.startswith("pitcher") or "pitcher" in low:
                        unattributed += 32 * qty; continue
                    for bn, b in beers.items():
                        if low.startswith(bn.lower() + " "):
                            for word, oz in OZ_BY_SIZE:
                                if low.endswith(word):
                                    led[bn]["oz"] += oz * qty
                                    if word == "pint": led[bn]["pints"] += qty
                                    break
                            break
            cursor = r.get("cursor")
            if not cursor: break
    except Exception as e:
        print("  shadow sales: %s" % e); return
    sh["orders_since"] = now_iso; sh["pitcher_oz"] = unattributed
    # one report a morning, before doors
    mt = _mt_now(); day = mt.strftime("%Y-%m-%d")
    if mt.hour == 10 and sh.get("sales_posted") != day:
        lines = []
        for n, b in beers.items():
            l = led.get(n) or {}
            if not l.get("oz"): continue
            wall = (b.get("remainingOz") or 0) / BBL_OZ
            lines.append("%s %.1f -> %.1f bbl (%d pints)" % (n, wall, max(0.0, wall - l["oz"] / BBL_OZ), l.get("pints", 0)))
        if lines:
            msg = (":ghost: Shadow levels · what sales say since each tank's last measured level: " + " \u00b7 ".join(lines)
                   + ("\nPitchers rung without a beer name: %d (%.2f bbl, not counted above)." % (unattributed / 32, unattributed / BBL_OZ) if unattributed else "")
                   + "\nCompare with Greg's Monday numbers - the wall itself is unchanged.")
            if not DRY:
                slack("chat.postMessage", channel=BOARD_CHANNEL, text=msg)
        sh["sales_posted"] = day; sh["pitcher_oz"] = 0

def shadow_tick():
    if not (square and square.enabled()) or (MIRROR_MODE == "off" and SALES_MODE == "off"):
        return
    try:
        state = load_json(STATE_PATH, {}) or {}
        data, _ = fetch_beers()
        shadow_mirror(state, data)
        shadow_sales(state, data)
        if not DRY:
            fresh = load_json(STATE_PATH, {}) or {}          # run_once may have written since we loaded
            fresh["shadow"] = state.get("shadow", {})
            json.dump(fresh, open(STATE_PATH, "w"), indent=1)
    except Exception as e:
        print("shadow: %s" % e)


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


def scheduled_posts():
    """The pre-shift brief and the Sunday outlook (briefs.py) - each posts once, on the first cycle after its time."""
    if not briefs or DRY:
        return
    try:
        briefs.tick(slack, lambda: fetch_beers()[0], lambda: load_json(QUEUE_PATH, []))
    except Exception as e:
        print("scheduled_posts: %s" % e)


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
                confirm_from_wall()
                shadow_tick()
                five_second_nudge()
                scheduled_posts()
                cellar_sync()
            except Exception as e:
                print("error: %s" % e)
                try: health("exception")
                except Exception: pass
            time.sleep(POLL_SEC)
    else:
        run_once()
        confirm_from_wall()
        shadow_tick()
        five_second_nudge()
        scheduled_posts()
