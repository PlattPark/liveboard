#!/usr/bin/env python3
"""
menu_build.py - Platt Park Brewing
Keeps the QR menu (menu.html) in step with the wall and the register, so nobody edits it by hand.

WHAT IT OWNS (everything else in menu.html is left exactly as designed)
  beers        the "On the Tanks" list      <- beers.json beers   (same data as the wall)
  also         the "Also Pouring" section   <- beers.json also    (same categories as the wall panel)
  4-packs      the "4-packs to go" sentence <- Square: live 4-pack buttons, grouped by price
  prices       every other priced line      <- Square, checked by exact name.
               MENU_PRICES=apply (default): the register price is written onto the menu and #board is told.
               MENU_PRICES=report: mismatches are posted to #board, nothing changes.
               LINKS below tie a menu line to the register button(s) it is priced from.

RUN
  python3 tools/menu_build.py            # writes menu.html if anything changed
  python3 tools/menu_build.py --check    # print what would change, write nothing
Env: SQUARE_ACCESS_TOKEN (optional - without it only the beer / also sections update),
     SLACK_BOT_TOKEN (optional - for the #board report), MENU_PRICES.
"""
import os, re, sys, json, html, hashlib, difflib, urllib.request, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MENU = ROOT / "menu.html"
BEERS = ROOT / "beers.json"
STATE = ROOT / "menu_state.json"
BOARD_CHANNEL = "C0CALA09Z35"
LOCATION = "1SEFN6DR2HWSV"
GATES_SITE = "CH_aCf602ueFMnyWfOZqBq7NggyDdxQaeOcZEnh5PlQuYC"   # gatesdeli.com channel
MODE = os.environ.get("MENU_PRICES", "apply").strip().lower()

# Menu line -> register button(s). {Register Name} = that button's price; {Register Name|Variation} = one size.
# Any line not listed here is priced from the register button with the same name.
LINKS = {
    "Flying Buffalo": "{Flying Buffalo (Sando)}",
    "Nachos": "{Buffalo Nachos} / \u00bd {1/2 Order Nachos}",
    "Soup": "{Cup of soup (tomato)} / {Bowl of Soup (Tomato)}",
    "Grilled Cheese": "{Regular Grilled Cheese}",
    "Soup & Grilled Cheese": "{Cup tomato & Grilled Cheese} / {Tomato Soup Bowl & Grilled Cheese}",
    "Single Taco": "{Single Pork TACO}",
    "Wings": "{Buffalo Wings}",
    "Packaged Candy & Snacks": "{Candy Bars}",
    "Ros\u00e9": "{Rose}",
    "Sparkling Ros\u00e9": "{Sparkling Rose}",
    "Iced Tea": "{ICE T}",
    "Bottled Root Beer": "{CO Soda ROOT BEER}",
    "Red Wine": "Regular {Red Wine|Regular} / Bottle {Red Wine|Bottle}",
    # Also Pouring categories -> the register button the bar rings
    "Seasonal Cider": "{Fruited Cider}",
    "Hard Italian Soda": "{Italian Soda}",
    "Hard Seltzer": "{Hard Seltzer}",
    "Frozen Drinks": "{Frozen Cocktail}",
}
# Shown on the menu's Also Pouring under the wall's categories (things the wall doesn't need to carry)
ALSO_EXTRAS = [("Cider Taster", "$4", "a small pour of either cider")]       # price is a fallback; the register's wins
# Lines the menu no longer carries (they live in Also Pouring now)
DROP_LINES = ["Frozen Cocktail"]
# Wall categories the menu already covers in its own section
ALSO_SKIP_ON_MENU = {"wine"}
CHECK = "--check" in sys.argv

ITEM = '<div class="it"><div class="ir"><span class="in">{n}</span><span class="dots"></span><span class="ip">{p}</span></div>{d}</div>'
SENT_USING = re.compile(r"\s*\*?Sent using\*?.*$", re.I | re.S)


def esc(s):
    return html.escape(str(s or ""), quote=True)


def money(x):
    try:
        x = float(x)
    except Exception:
        return str(x)
    return "$%d" % x if abs(x - round(x)) < 0.001 else "$%.2f" % x


def norm(s):
    s = html.unescape(re.sub(r"<[^>]+>", "", str(s or "")))
    s = re.sub(r"^\s*new\s+", "", s, flags=re.I)
    return re.sub(r"[^a-z0-9]", "", s.lower())


# ---------------------------------------------------------------- beers + also, from beers.json
def beer_rows(data):
    out = []
    for b in data.get("beers", []):
        line = SENT_USING.sub("", b.get("wall") or b.get("style") or "").strip()
        bits = [line] if line else []
        desc = " · ".join(bits)
        if b.get("abv") not in (None, ""):
            desc += (" — " if desc else "") + ("%g%%" % float(b["abv"]))
        meds = [m for m in (b.get("medals") or []) if m.get("show", "wall") in ("wall", "menu")]
        if meds:
            m = sorted(meds, key=lambda m: (m.get("year") or 0), reverse=True)[0]
            desc += " · %s %s%s" % (m.get("comp", ""), (m.get("level") or "").lower(), (" %d" % m["year"]) if m.get("year") else "")
        out.append(ITEM.format(n=esc(b["name"]), p=money(b.get("price")), d='<div class="id">%s</div>' % esc(desc) if desc else ""))
    return "".join(out)


def also_rows(data, known=None):
    """known = last register price per category (so the menu shows what guests pay, and doesn't flip each cycle)."""
    known = known or {}
    out = []
    for a in data.get("also") or []:
        if norm(a.get("name")) in ALSO_SKIP_ON_MENU:
            continue
        sub = SENT_USING.sub("", a.get("sub") or "").strip()
        out.append(ITEM.format(n=esc(a.get("name", "")), p=esc(known.get(norm(a.get("name"))) or a.get("price", "")),
                               d='<div class="id">%s</div>' % esc(sub) if sub else ""))
    for name, price, sub in ALSO_EXTRAS:
        out.append(ITEM.format(n=esc(name), p=esc(known.get(norm(name)) or price), d='<div class="id">%s</div>' % esc(sub) if sub else ""))
    return "".join(out)


def replace_between(s, start_pat, end_pat, new, label):
    """Swap what sits between two anchors; keeps both anchors. Raises if either is missing."""
    m1 = re.search(start_pat, s)
    if not m1:
        raise SystemExit("menu_build: can't find the start of the %s section" % label)
    m2 = re.search(end_pat, s[m1.end():])
    if not m2:
        raise SystemExit("menu_build: can't find the end of the %s section" % label)
    a, b = m1.end(), m1.end() + m2.start()
    return s[:a] + new + s[b:], s[a:b]


# ---------------------------------------------------------------- Square
def square(path, payload=None):
    tok = os.environ.get("SQUARE_ACCESS_TOKEN", "")
    req = urllib.request.Request("https://connect.squareup.com/v2/" + path,
                                 data=json.dumps(payload).encode() if payload is not None else None,
                                 method="POST" if payload is not None else "GET",
                                 headers={"Authorization": "Bearer " + tok, "Square-Version": "2026-08-20",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def catalog():
    items, cursor = [], ""
    while True:
        r = square("catalog/list?types=ITEM" + ("&cursor=" + urllib.parse.quote(cursor) if cursor else ""))
        items += r.get("objects", [])
        cursor = r.get("cursor", "")
        if not cursor:
            return items


def live_here(it):
    d = it.get("item_data") or {}
    if it.get("is_deleted") or d.get("is_archived"):
        return False
    return it.get("present_at_all_locations") or LOCATION in (it.get("present_at_location_ids") or [])


def prices_of(it):
    ps = []
    for v in (it.get("item_data") or {}).get("variations", []):
        vd = v.get("item_variation_data") or {}
        if (vd.get("pricing_type") or "FIXED_PRICING") == "FIXED_PRICING" and vd.get("price_money"):
            ps.append(vd["price_money"]["amount"] / 100.0)
    return sorted(set(ps))


PACK_RE = re.compile(r"\b(?:4[\s-]?pk|4[\s-]?pack|four[\s-]?pack)\b", re.I)


def pack_name(raw, beer_names):
    n = re.sub(r"[^\w\s'&]", " ", raw)                       # emoji and punctuation out
    n = PACK_RE.sub(" ", n)
    n = re.sub(r"\b(ipa|lager|ale)\b", " ", n, flags=re.I)
    n = re.sub(r"\s+", " ", n).strip()
    best, score = n, 0.0
    for b in beer_names:                                       # say it the way the wall says it
        r = difflib.SequenceMatcher(None, norm(n), norm(b)).ratio()
        if norm(b).startswith(norm(n)) or norm(n).startswith(norm(b)):
            r = max(r, 0.9)
        if r > score:
            best, score = b, r
    return best if score >= 0.78 else n


def four_pack_sentence(items, beer_names):
    packs = {}
    for it in items:
        name = (it.get("item_data") or {}).get("name", "")
        if not PACK_RE.search(name) or not live_here(it):
            continue
        ps = prices_of(it)
        if len(ps) != 1:
            continue
        packs.setdefault(ps[0], []).append(pack_name(name, beer_names))
    if not packs:
        return None
    parts = []
    for price in sorted(packs):
        names = sorted(packs[price])
        joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " &amp; " + names[-1]
        parts.append("%s %s" % (joined, money(price)))
    return "4-packs to go: " + " · ".join(parts) + " · also at gatesdeli.com for pickup."


def register_price(template, by):
    """'{Buffalo Nachos} / \u00bd {1/2 Order Nachos}' -> '$16 / \u00bd $8', or None if a button is missing or ambiguous."""
    def one(m):
        name, _, var = m.group(1).partition("|")
        hits = by.get(norm(name), [])
        if len(hits) != 1:
            raise KeyError(name)
        vs = (hits[0].get("item_data") or {}).get("variations", [])
        if var:
            vs = [v for v in vs if norm((v.get("item_variation_data") or {}).get("name")) == norm(var)]
        ps = sorted({(v.get("item_variation_data") or {}).get("price_money", {}).get("amount", 0) / 100.0 for v in vs
                     if (v.get("item_variation_data") or {}).get("price_money")})
        if len(ps) != 1:
            raise KeyError(name)
        return money(ps[0])
    try:
        return re.sub(r"\{([^}]+)\}", one, template)
    except KeyError as e:
        return None


def price_check(menu_html, items, skip_names):
    """Every priced line, against the register button(s) it is linked to (LINKS, else the same name)."""
    by = {}
    for it in items:
        if live_here(it):
            by.setdefault(norm((it.get("item_data") or {}).get("name", "")), []).append(it)
    links = {norm(k): v for k, v in LINKS.items()}
    diffs, unmatched = [], []
    for m in re.finditer(r'<span class="in">(.*?)</span><span class="dots"></span><span class="ip">(.*?)</span>', menu_html):
        raw, shown = m.group(1), html.unescape(m.group(2))
        label = html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
        label = re.sub(r"^NEW\s+", "", label)
        k = norm(raw)
        if k in skip_names:
            continue
        template = links.get(k) or ("{%s}" % label)
        reg = register_price(template, by)
        if reg is None:
            unmatched.append(label)
            continue
        if html.unescape(shown).strip() != html.unescape(reg):
            diffs.append((m.start(2), m.end(2), label, shown, esc(reg)))
    return diffs, unmatched


def slack(text):
    tok = os.environ.get("SLACK_BOT_TOKEN", "")
    if not tok or CHECK:
        print("[slack] " + text)
        return
    req = urllib.request.Request("https://slack.com/api/chat.postMessage",
                                 data=urllib.parse.urlencode({"channel": BOARD_CHANNEL, "text": text}).encode(),
                                 headers={"Authorization": "Bearer " + tok})
    try:
        urllib.request.urlopen(req, timeout=20).read()
    except Exception as e:
        print("slack: %s" % e)


# ---------------------------------------------------------------- main
def main():
    s0 = MENU.read_text(encoding="utf-8")
    data = json.loads(BEERS.read_text(encoding="utf-8"))
    s = s0
    notes = []
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    for gone in DROP_LINES:
        s = re.sub(r'<div class="it"><div class="ir"><span class="in">%s</span>.*?</div>(?:<div class="id">.*?</div>)?</div>' % re.escape(gone), "", s, count=1)

    # beers: everything between the tank intro and the Pitcher line
    s, old = replace_between(s, r'<div class="tankintro">.*?</div></div>',
                             r'<div class="it"><div class="ir"><span class="in">Pitcher', beer_rows(data), "beer")
    # also pouring: the section that used to be "Cider & Kombucha"
    s = s.replace("<section><h2>Cider &amp; Kombucha</h2>", "<section><h2>Also Pouring</h2>")
    s = s.replace("<section><h2>Cider & Kombucha</h2>", "<section><h2>Also Pouring</h2>")
    s, _ = replace_between(s, r'<section><h2>Also Pouring</h2>', r'</section>', also_rows(data, state.get("also_reg")), "Also Pouring")

    import time
    square_due = time.time() - state.get("square_at", 0) >= int(os.environ.get("MENU_SQUARE_EVERY", "600"))
    if os.environ.get("SQUARE_ACCESS_TOKEN") and (square_due or CHECK):
        state["square_at"] = time.time()
        try:
            items = catalog()
        except Exception as e:
            items = None
            print("square: %s" % e)
        if items:
            beer_names = [b["name"] for b in data.get("beers", [])]
            sent = four_pack_sentence(items, beer_names)
            if sent:
                s = re.sub(r"4-packs to go: .*?(?=</div>)", sent, s, count=1)
            skip = {norm(b["name"]) for b in data.get("beers", [])} | {norm("Pitcher (32 oz)")}
            diffs, unmatched = price_check(s, items, skip)
            wall_fix = []
            by = {}
            for it in items:
                if live_here(it):
                    by.setdefault(norm((it.get("item_data") or {}).get("name", "")), []).append(it)
            links = {norm(k): v for k, v in LINKS.items()}
            also_reg = {}
            for name, _, _ in ALSO_EXTRAS:
                r = register_price(links.get(norm(name)) or "{%s}" % name, by)
                if r: also_reg[norm(name)] = r
            for a in data.get("also") or []:
                if norm(a.get("name")) in ALSO_SKIP_ON_MENU:
                    continue
                reg = register_price(links.get(norm(a.get("name"))) or "{%s}" % a.get("name"), by)
                if reg: also_reg[norm(a["name"])] = reg
                if reg and reg != a.get("price"):
                    wall_fix.append("%s: wall %s, register %s - type _%s to also pouring %s_" % (a["name"], a.get("price"), reg, a["name"].lower(), reg))
            state["also_reg"] = also_reg
            if diffs and MODE == "apply":
                for a, b, name, shown, reg in sorted(diffs, reverse=True):
                    s = s[:a] + reg + s[b:]
                notes.append("prices updated from the register: " + "; ".join("%s %s -> %s" % (n, sh, r) for _, _, n, sh, r in diffs))
            report = sorted(["%s: menu %s, register %s" % (n, sh, r) for _, _, n, sh, r in diffs])
            key = hashlib.sha1(json.dumps([report if MODE != "apply" else [], sorted(unmatched), wall_fix]).encode()).hexdigest()
            if key != state.get("report_key"):
                msg = []
                if report and MODE != "apply":
                    msg.append("*QR menu prices that differ from the register* (menu unchanged in report mode):\n" + "\n".join("\u2022 " + r for r in report))
                if wall_fix:
                    msg.append("*Also Pouring price on the wall differs from the register:*\n" + "\n".join("\u2022 " + r for r in wall_fix))
                if unmatched:
                    msg.append("*QR menu lines with no register button to price from* (left as written - add the button or a link in tools/menu_build.py): " + ", ".join(sorted(set(unmatched))))
                if msg:
                    slack(":page_facing_up: " + "\n".join(msg))
                state["report_key"] = key

    if s != s0:
        if CHECK:
            print("menu.html would change (%d -> %d bytes)" % (len(s0), len(s)))
        else:
            MENU.write_text(s, encoding="utf-8")
            print("menu.html updated")
    else:
        print("menu.html already current")
    for n in notes:
        print(n)
        slack(":page_facing_up: QR menu - " + n)
    if not CHECK:
        STATE.write_text(json.dumps(state, indent=1))


if __name__ == "__main__":
    main()
