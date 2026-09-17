#!/usr/bin/env python3
"""
newbeer.py — Platt Park Brewing
Turns "New beer: Name — Style, ABV%, description" into a live tap.

WHY THIS CHANGED
----------------
Adds used to be queued for a human because a new beer needs a colour,
a vessel and a tank volume. But a beer that's pouring and missing from
the board is worse than a beer with a guessed colour — patrons can't
order what they can't see, and servers shouldn't have to explain a beer
that isn't on the wall.

So adds publish immediately with sensible defaults, and Computa replies
saying exactly what it assumed and how to correct it. Wrong-but-visible
beats absent.

WHAT GETS INFERRED
  colour       from style, matched against the existing brand palette
  price        from Square if a matching item exists, else by style
  vessel       10 BBL default (most common), 1/2 BBL if "pilot" or "small batch"
  volume       full, since it was just tapped
  tapped       today

WHAT STILL NEEDS A HUMAN
  a Square POS button — Computa checks and says so if it's missing,
  because nobody can ring a beer that has no button
"""

import re, json, unicodedata

# ── style → colour, seeded from the beers already on the board ──
# body colour, then the lighter top/head colour
PALETTE = [
    # darkest first so "imperial stout" doesn't match "stout" generically by accident
    (r"imperial stout|russian stout|pastry stout",      "#241410", "#3d2519"),
    (r"\bporter\b",                                      "#3d2317", "#5c3a26"),
    (r"golden stout|blonde stout|white stout",           "#dfa93c", "#eec468"),
    (r"\bstout\b|nitro stout",                           "#2a1810", "#452a1c"),
    (r"schwarz|dark lager|dunkel|brown ale|\bbrown\b",   "#6e4a2a", "#8a5f38"),
    (r"m[äa]rzen|oktoberfest|festbier",                  "#c77a1e", "#e8a53a"),
    (r"amber|red ale|\bred\b|altbier|vienna",            "#a8542a", "#c97648"),
    (r"cream ale|vanilla|milkshake",                     "#c9973c", "#e6bd6e"),
    (r"hazy|neipa|new england|juicy",                    "#d9a83c", "#efc76a"),
    (r"west coast|\bipa\b|pale ale|\bapa\b",             "#d69a2b", "#eebd55"),
    (r"witbier|blanche|hefe|weiss|wheat",                "#e6d9a0", "#f3ecc4"),
    (r"rice lager|japanese|light lager|lite|helles",     "#e3c25a", "#f2dc8a"),
    (r"pils|pilsner|kolsch|k[öo]lsch|blonde|golden ale", "#e8d58a", "#f5e9b3"),
    (r"gose|berliner|sour|tart|kettle",                  "#e0b84a", "#f0d379"),
    (r"saison|farmhouse|grisette",                       "#ddb85c", "#eed58c"),
    (r"cider",                                           "#e9c766", "#f5e09a"),
]
# fruit words override toward their own colour
FRUIT = [
    (r"raspberry|cherry|cranberry|hibiscus",  "#a8324a", "#c9536b"),
    (r"blackberry|blueberry|plum|grape",      "#5e3560", "#7d4f80"),
    (r"strawberry|watermelon|guava",          "#d2543f", "#e8775f"),
    (r"peach|apricot|mango|orange|tangerine", "#e08a2b", "#f0aa55"),
    (r"lime|kiwi|cucumber|jalape",            "#9fb648", "#bcd06c"),
    (r"pineapple|lemon|passion",              "#e4c23f", "#f2d972"),
]
DEFAULT = ("#d0a04a", "#e4bd78")

PRICE_BY_STYLE = [
    (r"imperial|barrel[- ]aged|double|triple|\bdipa\b", 9.00),
    (r"hazy|neipa|ipa|stout|porter|sour|nitro",         8.50),
    (r"m[äa]rzen|amber|brown|saison|wheat|wit",         7.50),
    (r"lager|lite|light|pils|kolsch|blonde",            6.50),
]



# every style word we can recognise, longest first so "imperial stout" wins over "stout"
STYLE_WORDS = sorted([
 "imperial stout","russian imperial stout","pastry stout","golden stout","blonde stout",
 "white stout","milk stout","oatmeal stout","nitro stout","stout",
 "baltic porter","coffee porter","porter","schwarzbier","dark lager","dunkel","doppelbock","bock",
 "brown ale","mild","altbier","vienna lager","amber ale","amber","red ale","irish red",
 "marzen","märzen","oktoberfest","festbier","cream ale","blonde ale","golden ale",
 "kolsch","kölsch","pilsner","pils","helles","light lager","lite lager","lager",
 "hazy ipa","neipa","new england ipa","west coast ipa","double ipa","dipa","triple ipa",
 "session ipa","black ipa","rye ipa","ipa","pale ale","apa","xpa",
 "hefeweizen","weissbier","witbier","blanche","wheat ale","wheat",
 "berliner weisse","berliner","gose","kettle sour","wild ale","sour ale","sour",
 "saison","farmhouse","grisette","biere de garde",
 "barleywine","tripel","dubbel","quad","belgian strong","belgian",
 "rice lager","japanese rice lager","cider","seltzer","kombucha",
], key=len, reverse=True)


def find_style(text):
    """Pull a recognised style out of free text, wherever it sits."""
    low = text.lower()
    for w in STYLE_WORDS:
        m = re.search(r"\b" + re.escape(w) + r"\b", low)
        if m:
            return text[m.start():m.end()], m.start(), m.end()
    return None, -1, -1


def slugify(name):
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", n.lower()).strip("-")


def infer_color(style, name="", note=""):
    hay = f"{style} {name} {note}".lower()
    for rx, c, t in FRUIT:
        if re.search(rx, hay):
            return c, t, "fruit"
    for rx, c, t in PALETTE:
        if re.search(rx, hay):
            return c, t, "style"
    return DEFAULT[0], DEFAULT[1], "default"


def infer_price(style, name=""):
    hay = f"{style} {name}".lower()
    for rx, p in PRICE_BY_STYLE:
        if re.search(rx, hay):
            return p
    return 7.50


def infer_vessel(text):
    t = text.lower()
    if re.search(r"pilot|small batch|one[- ]off|single keg|half barrel|1/2", t):
        return "keg-half", "1/2 BBL", 1984
    if re.search(r"\b20\s*bbl\b|big batch|flagship", t):
        return "tank20", "20 BBL", 79360
    return "tank10", "10 BBL", 39680


# ── parsing what a brewer would actually type ──
NEW_RE = re.compile(
    r"^\s*(?:computa+h?\s*[,!:]?\s*)?"
    r"(?:new\s+beer|new\s+tap|new\s+on\s+tap|just\s+tapped|tapping|now\s+pouring|on\s+tap\s+now)\s*[:\-—]?\s*"
    r"(?P<rest>.+)$", re.I | re.S)


def parse_new_beer(text):
    """
    Handles the shapes a brewer actually writes:
      New beer: Fresh Hop Pale — West Coast Pale, 5.8%, piney and bright
      new tap Fresh Hop Pale / West Coast Pale / 5.8% / piney
      Just tapped Fresh Hop Pale, a 5.8% west coast pale, piney and bright
    """
    m = NEW_RE.match(text.strip())
    if not m:
        return None
    rest = m.group("rest").strip()

    abv = None
    a = re.search(r"(\d{1,2}(?:\.\d)?)\s*%", rest)
    if a:
        abv = float(a.group(1))
        rest = (rest[:a.start()] + " " + rest[a.end():]).strip(" ,;/—-")

    parts = [p.strip(" ,;") for p in re.split(r"\s*[—–\-/|]\s*|\s*,\s*", rest) if p.strip(" ,;")]
    if not parts:
        return None

    name  = parts[0]
    style = parts[1] if len(parts) > 1 else ""
    note  = ", ".join(parts[2:]) if len(parts) > 2 else ""

    if style.lower().startswith(("a ", "an ")):
        style = style.split(" ", 1)[1]

    # No delimiters, or the "style" slot isn't a real style: hunt for a style
    # word anywhere and split the sentence around it.
    known, ks, ke = find_style(style)
    if not known:
        known2, s2, e2 = find_style(rest)
        if known2:
            before = rest[:s2].strip(" ,;:-—")
            after  = rest[e2:].strip(" ,;:-—")
            # the style word often sits inside the name: "Kiwi Gose", "Cold Snap Pils"
            if before and len(before.split()) <= 5 and not after:
                name, style, note = before + " " + known2, known2, ""
            elif before:
                name  = before if len(parts) == 1 else name
                style = known2
                note  = after or note
            else:
                style = known2
                note  = after or note
        elif len(parts) == 1:
            # nothing recognisable — first 4 words are the name, rest is the note
            w = rest.split()
            name, note = " ".join(w[:4]), " ".join(w[4:])
            style = ""

    return {"name": name.strip(" ,;-"), "style": style.strip().title(),
            "abv": abv, "note": note.strip(" ,;-")}


def build_beer(parsed, raw_text="", square_price=None):
    name  = parsed["name"]
    style = parsed["style"] or "Ale"
    note  = parsed["note"]
    c, ct, csrc = infer_color(style, name, note)
    vessel, label, cap = infer_vessel(raw_text + " " + style)
    price = square_price if square_price else infer_price(style, name)

    beer = {
        "id": slugify(name),
        "name": name,
        "style": style,
        "abv": parsed["abv"] if parsed["abv"] is not None else 5.0,
        "price": round(price, 2),
        "price10": round(price * 0.63, 2),
        "vessel": vessel,
        "vesselLabel": label,
        "remainingOz": cap,
        "tappedDaysAgo": 0,
        "color": c,
        "colorTop": ct,
        "rating": 0,
    }
    if note:
        beer["note"] = note

    assumed = []
    if not square_price:
        assumed.append(f"price ${price:.2f} (from style)")
    if csrc == "default":
        assumed.append("colour — couldn't read the style, using a mid amber")
    if parsed["abv"] is None:
        assumed.append("ABV 5.0% (none given)")
    assumed.append(f"{label}, full")
    return beer, assumed


if __name__ == "__main__":
    tests = [
        "New beer: Fresh Hop Pale — West Coast Pale Ale, 5.8%, piney and bright",
        "computa new tap Night Swim / Imperial Stout / 9.2% / coconut and cacao",
        "Just tapped Sun Shower, a 4.6% Berliner with raspberry",
        "new beer Cold Snap Pils 5.0% crisp and dry",
        "New beer: Pilot Batch Kiwi Gose, 4.2%, tart and green",
    ]
    for t in tests:
        p = parse_new_beer(t)
        print("\n" + t)
        if not p:
            print("   (not a new-beer message)")
            continue
        b, assumed = build_beer(p, t)
        print(f"   {b['name']}  |  {b['style']} · {b['abv']}% · ${b['price']:.2f}")
        print(f"   colour {b['color']} / {b['colorTop']}   {b['vesselLabel']}   id={b['id']}")
        if b.get("note"):
            print(f"   note: {b['note']}")
        print(f"   assumed: {'; '.join(assumed)}")
