#!/usr/bin/env python3
"""
square.py - Platt Park Brewing
"86 kettle chips" in Slack -> the item is marked SOLD OUT at the register, on Square Online
(gatesdeli.com) and on DoorDash, in one move. "kettle chips are back" clears it.

HOW
  Square's catalog carries a per-location "sold out" flag on every item variation
  (ItemVariationLocationOverrides.sold_out). The POS "Mark sold out" button sets the same flag,
  Square Online reads it, and the DoorDash channel that runs through Square Online follows.
  Nothing here touches inventory counts or prices.

RULES (Colby, Sept 18 2026)
  - A Slack 86 stays sold out until someone says it's back. No auto-restore at close.
  - Guest-facing wording: "sold out" for food, "kicked" for beverages. The crew types 86 for both.
  - Never guess: an ambiguous name gets a question back, not a wrong item pulled off DoorDash.

SETUP
  export SQUARE_ACCESS_TOKEN="EAAA..."   # Square Developer > your app > Production access token
                                          # (Catalog: read + write is all it needs)
  python3 square.py find "kettle chips"           # what would match, no change
  python3 square.py 86 "kettle chips"             # mark sold out
  python3 square.py back "kettle chips"           # back in stock
  python3 square.py status                        # everything currently sold out at the location
"""
import os, re, sys, json, uuid, difflib, urllib.request, urllib.error

LOCATION = "1SEFN6DR2HWSV"          # Platt Park Brewing (A8R4AJWWFNY8N is inactive)
API = "https://connect.squareup.com/v2/"
VERSION = "2026-08-20"
TOKEN = os.environ.get("SQUARE_ACCESS_TOKEN", "")

DRINK_WORDS = re.compile(r"\b(beer|draft|draught|pint|crowler|4[- ]?pack|cider|seltzer|wine|cocktail|spirit|liquor|"
                         r"whiskey|vodka|gin|tequila|rum|frozen|booch|kombucha|n/?a\b|non[- ]?alcoholic|soda|drink)", re.I)


class SquareError(Exception):
    pass


def enabled():
    return bool(TOKEN)


def call(path, method="GET", payload=None):
    if not TOKEN:
        raise SquareError("SQUARE_ACCESS_TOKEN is not set")
    req = urllib.request.Request(API + path, data=json.dumps(payload).encode() if payload is not None else None,
                                 method=method,
                                 headers={"Authorization": "Bearer " + TOKEN, "Square-Version": VERSION,
                                          "Content-Type": "application/json", "User-Agent": "computa"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        raise SquareError("Square %s %s -> HTTP %s %s" % (method, path, e.code, body))
    except Exception as e:
        raise SquareError("Square %s %s -> %s" % (method, path, e))


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


_categories = None
def category_names():
    """id -> name for every category, fetched once per process."""
    global _categories
    if _categories is None:
        _categories, cursor = {}, ""
        while True:
            r = call("catalog/list?types=CATEGORY" + ("&cursor=" + cursor if cursor else ""))
            for o in r.get("objects", []):
                _categories[o["id"]] = (o.get("category_data") or {}).get("name", "")
            cursor = r.get("cursor", "")
            if not cursor:
                break
    return _categories


def search(name):
    """Every catalog item that could be what the bartender meant, best first.
    Returns [(score, item)]; score 1.0 = exact name."""
    words = [w for w in re.split(r"\s+", name.strip()) if w]
    if not words:
        return []
    r = call("catalog/search-catalog-items", "POST", {"text_filter": name.strip(), "limit": 25})
    items = [i for i in r.get("items", []) if not i.get("is_deleted")
             and (i.get("present_at_all_locations") or LOCATION in (i.get("present_at_location_ids") or []))
             and not (i.get("item_data") or {}).get("is_archived")]
    if not items:          # Square's text search wants a prefix; try the longest word alone
        long = max(words, key=len)
        if len(long) >= 4 and long != name.strip():
            r = call("catalog/search-catalog-items", "POST", {"text_filter": long, "limit": 25})
            items = [i for i in r.get("items", []) if not i.get("is_deleted")
                     and (i.get("present_at_all_locations") or LOCATION in (i.get("present_at_location_ids") or []))]
    t = norm(name)
    scored = []
    for it in items:
        n = norm(it["item_data"].get("name", ""))
        if not n:
            continue
        if n == t:
            s = 1.0
        elif t in n or n in t:
            s = 0.9 if len(t) >= 4 else 0.6
        else:
            s = difflib.SequenceMatcher(None, t, n).ratio()
            for v in it["item_data"].get("variations", []):
                vn = norm(v.get("item_variation_data", {}).get("name", ""))
                s = max(s, difflib.SequenceMatcher(None, t, n + vn).ratio())
        scored.append((round(s, 3), it))
    scored.sort(key=lambda x: -x[0])
    return scored


def resolve(name, floor=0.72):
    """One item, or a list of candidates when it's ambiguous, or nothing.
    -> ("one", item) | ("many", [items]) | ("none", [])"""
    hits = search(name)
    hits = [(s, i) for s, i in hits if s >= floor]
    if not hits:
        return "none", []
    top = hits[0][0]
    if top == 1.0 or (len(hits) == 1) or (top - hits[1][0] >= 0.15):
        return "one", hits[0][1]
    return "many", [i for _, i in hits[:4]]


def is_drink(item):
    d = item.get("item_data") or {}
    names = [d.get("name", "")]
    cats = category_names()
    for c in d.get("categories", []) or []:
        names.append(cats.get(c.get("id"), ""))
    rc = (d.get("reporting_category") or {}).get("id")
    if rc:
        names.append(cats.get(rc, ""))
    return bool(DRINK_WORDS.search(" ".join(names)))


def sold_out_state(item):
    """True if every variation is sold out here, False if none, None if mixed."""
    flags = []
    for v in item["item_data"].get("variations", []):
        ov = [o for o in v.get("item_variation_data", {}).get("location_overrides", []) or [] if o.get("location_id") == LOCATION]
        flags.append(bool(ov and ov[0].get("sold_out")))
    if not flags:
        return False
    return True if all(flags) else (False if not any(flags) else None)


def set_sold_out(item, sold_out, dry=False):
    """Flip the flag on every variation of the item at our location. Returns the variation names touched."""
    touched = []
    for v in item["item_data"].get("variations", []):
        fresh = call("catalog/object/" + v["id"])["object"]          # latest version, or the upsert is rejected
        vd = fresh.setdefault("item_variation_data", {})
        overrides = [o for o in vd.get("location_overrides", []) or []]
        mine = next((o for o in overrides if o.get("location_id") == LOCATION), None)
        if mine is None:
            mine = {"location_id": LOCATION}
            overrides.append(mine)
        if bool(mine.get("sold_out")) == bool(sold_out):
            touched.append((vd.get("name") or "Regular", "already"))
            continue
        mine["sold_out"] = bool(sold_out)
        mine.pop("sold_out_valid_until", None)                        # ours is "until someone says it's back"
        vd["location_overrides"] = overrides
        if not dry:
            call("catalog/object", "POST", {"idempotency_key": str(uuid.uuid4()), "object": fresh})
        touched.append((vd.get("name") or "Regular", "set"))
    return touched


def status():
    """Everything sold out at the location right now: [(item name, [variation names])]."""
    out, cursor = [], ""
    while True:
        r = call("catalog/list?types=ITEM" + ("&cursor=" + cursor if cursor else ""))
        for it in r.get("objects", []):
            if it.get("is_deleted"):
                continue
            names = []
            for v in (it.get("item_data") or {}).get("variations", []):
                ov = [o for o in v.get("item_variation_data", {}).get("location_overrides", []) or []
                      if o.get("location_id") == LOCATION and o.get("sold_out")]
                if ov:
                    names.append(v["item_variation_data"].get("name") or "Regular")
            if names:
                out.append((it["item_data"].get("name", "?"), names))
        cursor = r.get("cursor", "")
        if not cursor:
            break
    return sorted(out)


# ---- what computa.py calls ----------------------------------------------------------------

def eighty_six(name, back=False, dry=False):
    """The whole move, with the Slack reply Computa should post.
    Returns (ok, reply_text, item_name_or_None)."""
    if not enabled():
        return False, None, None
    # "86 all wings" - every item whose name carries the word, in one move
    every = re.match(r"^(?:all|every|all the|all of the)\s+(.+)$", name.strip(), re.I)
    if every:
        term = every.group(1).strip()
        items = [i for s, i in search(term) if s >= 0.85]
        if not items:
            return False, None, None
        done, failed = [], []
        for it in items:
            try:
                touched = set_sold_out(it, not back, dry=dry)
                done.append(it["item_data"]["name"])
            except SquareError as e:
                failed.append(it["item_data"]["name"])
        word = "kicked" if all(is_drink(i) for i in items) else "sold out"
        reply = ":white_check_mark: %s: %s - %s at the register, gatesdeli.com and DoorDash." % (
            "Back in stock" if back else word.capitalize(), ", ".join("*%s*" % d for d in done), "in stock" if back else word)
        if failed:
            reply += "\n:warning: Square refused: %s - Colby, check the Square token." % ", ".join(failed)
        return bool(done), reply, ", ".join(done)
    kind, res = resolve(name)
    if kind == "none":
        return False, None, None
    if kind == "many":
        opts = " or ".join("*%s*" % i["item_data"]["name"] for i in res)
        return False, (":grey_question: *%s* could be %s at the register - which one? Say _\"%s\"_ for every one of them.%s"
                       % (name, opts, "all %s are back" % name if back else "86 all %s" % name, "")), None
    item = res
    label = item["item_data"]["name"]
    word = "kicked" if is_drink(item) else "sold out"
    try:
        touched = set_sold_out(item, not back, dry=dry)
    except SquareError as e:
        return False, ":warning: Found *%s* at the register but Square wouldn't take the change (%s). Colby, check the Square token." % (label, str(e)[:80]), label
    changed = [n for n, how in touched if how == "set"]
    if back:
        if changed:
            reply = ":white_check_mark: *%s* is back - in stock at the register, on the website and DoorDash within a couple of minutes." % label
        else:
            reply = ":information_source: *%s* was already in stock at the register." % label
    else:
        if changed:
            reply = (":white_check_mark: *%s* marked %s at the register, gatesdeli.com and DoorDash - takes a couple of minutes to show. "
                     "It stays %s until someone says _\"%s is back\"_." % (label, word, word, label))
        else:
            reply = ":information_source: *%s* was already %s at the register." % (label, word)
    return True, reply, label


# ---- sales, for the pre-shift brief and the Sunday outlook ---------------------------------
from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Denver")
except Exception:
    TZ = timezone(timedelta(hours=-6))


def day_sales(day):
    """Net sales for one business day (YYYY-MM-DD, 6am to 6am Denver): {net, checks, avg, tips, by_hour}.
    net = order totals minus tax and tip - the number Square's dashboard calls Net Sales, near enough."""
    start = datetime.strptime(day, "%Y-%m-%d").replace(hour=6, tzinfo=TZ)
    end = start + timedelta(days=1)
    q = {"location_ids": [LOCATION], "limit": 500, "return_entries": False,
         "query": {"filter": {"state_filter": {"states": ["COMPLETED"]},
                              "date_time_filter": {"closed_at": {"start_at": start.isoformat(), "end_at": end.isoformat()}}},
                   "sort": {"sort_field": "CLOSED_AT", "sort_order": "ASC"}}}
    net = tips = 0; checks = 0; by_hour = {}
    cursor = None
    while True:
        if cursor:
            q["cursor"] = cursor
        r = call("orders/search", "POST", q)
        for o in r.get("orders", []):
            na = o.get("net_amounts") or {}
            amt = (na.get("total_money") or {}).get("amount", 0) - (na.get("tax_money") or {}).get("amount", 0) \
                  - (na.get("tip_money") or {}).get("amount", 0) - (na.get("service_charge_money") or {}).get("amount", 0)
            if amt <= 0:
                continue
            net += amt; checks += 1
            tips += (na.get("tip_money") or {}).get("amount", 0)
            try:
                h = datetime.fromisoformat(o["closed_at"].replace("Z", "+00:00")).astimezone(TZ).hour
                by_hour[h] = by_hour.get(h, 0) + amt
            except Exception:
                pass
        cursor = r.get("cursor")
        if not cursor:
            break
    return {"day": day, "net": net / 100.0, "checks": checks, "avg": (net / checks / 100.0) if checks else 0.0,
            "tips": tips / 100.0, "by_hour": {k: v / 100.0 for k, v in sorted(by_hour.items())}}


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] not in ("find", "86", "back", "status"):
        sys.exit(__doc__)
    if args[0] == "status":
        for n, vs in status():
            print("%-40s %s" % (n, ", ".join(vs)))
        sys.exit(0)
    name = " ".join(args[1:])
    if args[0] == "find":
        for s, it in search(name)[:8]:
            print("%.2f  %-40s %s  %s" % (s, it["item_data"]["name"], "drink" if is_drink(it) else "food",
                                          {True: "SOLD OUT", False: "in stock", None: "mixed"}[sold_out_state(it)]))
        sys.exit(0)
    ok, reply, label = eighty_six(name, back=(args[0] == "back"), dry="--dry" in args)
    print(ok, label); print(reply)
