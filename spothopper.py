#!/usr/bin/env python3
"""
spothopper.py - Platt Park Brewing
beers.json -> the "Beer" menu on plattparkbrewing.com (SpotHopper), so the website's beer list is
the same list as the wall, the QR menu and beerlist.html. A beer that's 86'd in Slack goes out of
stock on the site within a couple of minutes; a price or note change lands the same way.

WHAT IT TOUCHES
  Only the SpotHopper menu named "Beer" (id 50820), section "Draft" (218487) - nothing else on the site.
  Per beer: name, description ("Style · ABV · note · medal line"), in_stock, the 10oz + Pint prices.
  A beer on the site but not in beers.json goes in_stock=false (it stays on the page, greyed / hidden
  by SpotHopper's own template). A beer in beers.json with no site item is created.

HOW IT SIGNS IN
  SpotHopper's admin is a cookie session. This logs in with the owner login (SPOTHOPPER_EMAIL /
  SPOTHOPPER_PASSWORD) through the same /api/sessions endpoint the admin app uses, keeps the
  cookie for the run, and logs nothing. It's their internal API, not a published one - if they
  change it this stops working and Computa says so in #bar-only rather than pretending.

SETUP
  export SPOTHOPPER_EMAIL="colby@..."; export SPOTHOPPER_PASSWORD="..."
  python3 spothopper.py --dry        # show the diff, change nothing
  python3 spothopper.py              # sync beers.json (local file) to the site
"""
import os, re, sys, json, http.cookiejar, urllib.request, urllib.error

SPOT = 84243
MENU = 50820            # "Beer"
SECTION = 218487        # "Draft"
BASE = "https://www.spothopperapp.com"
EMAIL = os.environ.get("SPOTHOPPER_EMAIL", "")
PASSWORD = os.environ.get("SPOTHOPPER_PASSWORD", "")

LEAVE_ALONE = re.compile(r"crowler|4[- ]?pack|to go|pitcher|flight", re.I)   # site rows that aren't a tap - never touched

COMP = {"us open": "US Open Beer Championship", "state fair": "Colorado State Fair", "gabf": "Great American Beer Festival",
        "world beer cup": "World Beer Cup", "brewers cup": "Colorado Brewers Cup"}


class SpotHopperError(Exception):
    pass


def enabled():
    return bool(EMAIL and PASSWORD)


_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))


def call(path, method="GET", payload=None, ok=(200, 201, 204)):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode() if payload is not None else None,
                                 method=method,
                                 headers={"Content-Type": "application/json", "Accept": "application/json",
                                          "X-Requested-With": "XMLHttpRequest", "User-Agent": "computa"})
    try:
        with _opener.open(req, timeout=25) as r:
            body = r.read().decode()
            return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:
        raise SpotHopperError("SpotHopper %s %s -> HTTP %s %s" % (method, path, e.code, e.read().decode()[:200]))
    except Exception as e:
        raise SpotHopperError("SpotHopper %s %s -> %s" % (method, path, e))


def login():
    if not enabled():
        raise SpotHopperError("SPOTHOPPER_EMAIL / SPOTHOPPER_PASSWORD not set")
    last = None
    for body in ({"email": EMAIL, "password": PASSWORD},
                 {"user": {"email": EMAIL, "password": PASSWORD}},
                 {"session": {"email": EMAIL, "password": PASSWORD}}):
        try:
            r = call("/api/sessions", "POST", body)
            if r.get("users") or r.get("user") or r.get("id"):
                return True
            last = "unexpected reply %s" % str(r)[:120]
        except SpotHopperError as e:
            last = str(e)
    # already signed in from a cookie? (local testing)
    try:
        me = call("/api/sessions")
        if me.get("users"):
            return True
    except SpotHopperError:
        pass
    raise SpotHopperError("login failed: %s" % last)


def menu():
    """The site's Beer menu as {name_key: {item, prices:{size: price}}}."""
    d = call("/api/spots/%d/food_menus/%d?show_posts=true&menu_type=all&page_size=10000" % (SPOT, MENU))
    linked = d.get("linked", {})
    prices = {p["id"]: p for p in linked.get("food_prices", [])}
    out = {}
    for it in linked.get("food_menu_items", []):
        ps = {}
        for pid in (it.get("links") or {}).get("food_prices", []) or []:
            p = prices.get(pid)
            if p:
                ps[(p.get("size") or "").strip().lower()] = p
        out[norm(it["name"])] = {"item": it, "prices": ps}
    sections = [s["id"] for s in linked.get("food_menu_sections", [])]
    return out, sections


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def cents(x):
    try:
        return int(round(float(x) * 100))
    except Exception:
        return None


def medal_line(b):
    ms = [m for m in (b.get("medals") or []) if m and m.get("level") and (m.get("show") or "wall") != "site"]
    if not ms:
        return ""
    groups, order = {}, []
    for m in ms:
        k = (m.get("comp") or "").lower()
        if k not in groups:
            groups[k] = []; order.append(k)
        groups[k].append(m)
    parts = []
    for k in order:
        lst = sorted(groups[k], key=lambda m: -(m.get("year") or 0))
        parts.append("%s %s" % (COMP.get(k, (groups[k][0].get("comp") or "").title()),
                                " & ".join("%s%s" % (m["level"].capitalize(), (" %d" % m["year"]) if m.get("year") else "") for m in lst)))
    return " · ".join(parts)


def description(b):
    bits = []
    if b.get("style"):
        bits.append(b["style"])
    if b.get("abv"):
        bits.append("%s%% ABV" % b["abv"])
    if b.get("note"):
        bits.append(b["note"])
    ml = medal_line(b)
    if ml:
        bits.append(ml)
    if b.get("adjuncts"):
        bits.append("contains " + ", ".join(b["adjuncts"]))
    return " · ".join(bits)


ITEM_URL = "/api/spots/%d/food_menus/%d/food_menu_sections/%d/food_menu_items" % (SPOT, MENU, SECTION)


def sync(beers, dry=False, log=print):
    """Push the beers list onto the site. Returns a list of human-readable changes."""
    site, sections = menu()
    if SECTION not in sections:
        raise SpotHopperError("Draft section %d not found in the Beer menu - the menu was restructured" % SECTION)
    changes = []
    seen = set()
    for b in beers:
        key = norm(b.get("name"))
        if not key:
            continue
        seen.add(key)
        want = {"name": b["name"], "description": description(b), "in_stock": True}
        want_prices = {"10oz": cents(b.get("price10")), "pint": cents(b.get("price"))}
        cur = site.get(key)
        if not cur:
            changes.append("added %s" % b["name"])
            if not dry:
                r = call(ITEM_URL, "POST", {"name": want["name"], "description": want["description"], "in_stock": True,
                                            "food_labels": [], "food_prices": []})
                new = (r.get("food_menu_items") or [r])[0]
                for size, c in (("10oz", want_prices["10oz"]), ("Pint", want_prices["pint"])):
                    if c is not None:
                        call(ITEM_URL + "/%d/food_prices" % new["id"], "POST", {"size": size, "cents": c})
            continue
        it = cur["item"]
        diff = [k for k in ("name", "description") if (it.get(k) or "") != want[k]] + (["in_stock"] if not it.get("in_stock") else [])
        if diff:
            changes.append("%s: %s" % (b["name"], ", ".join(diff)))
            if not dry:
                call(ITEM_URL + "/%d" % it["id"], "PUT", {"name": want["name"], "description": want["description"],
                                                          "in_stock": True, "food_labels": it.get("food_labels") or []})
        for size, c in (("10oz", want_prices["10oz"]), ("pint", want_prices["pint"])):
            if c is None:
                continue
            p = cur["prices"].get(size)
            if p and p.get("cents") == c:
                continue
            changes.append("%s %s $%.2f" % (b["name"], size, c / 100))
            if dry:
                continue
            if p:
                call(ITEM_URL + "/%d/food_prices/%d" % (it["id"], p["id"]), "PUT", {"id": p["id"], "size": p.get("size") or size, "cents": c})
            else:
                call(ITEM_URL + "/%d/food_prices" % it["id"], "POST", {"size": "10oz" if size == "10oz" else "Pint", "cents": c})
    for key, cur in site.items():
        if key in seen or not cur["item"].get("in_stock") or LEAVE_ALONE.search(cur["item"].get("name") or ""):
            continue
        it = cur["item"]
        changes.append("%s: out of stock (not on tap)" % it["name"])
        if not dry:
            call(ITEM_URL + "/%d" % it["id"], "PUT", {"name": it["name"], "description": it.get("description") or "",
                                                      "in_stock": False, "food_labels": it.get("food_labels") or []})
    return changes


def sync_from_file(path="beers.json", dry=False):
    data = json.load(open(path))
    login()
    return sync(data.get("beers", []), dry=dry)


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    try:
        ch = sync_from_file(dry=dry)
    except SpotHopperError as e:
        sys.exit("ERROR: %s" % e)
    print(("[dry] " if dry else "") + ("\n".join(ch) if ch else "site already matches beers.json"))
