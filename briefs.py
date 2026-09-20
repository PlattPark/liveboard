#!/usr/bin/env python3
"""
briefs.py - Platt Park Brewing
Two scheduled posts, run from Computa's poll loop (computa.py calls tick() every cycle):

  PRE-SHIFT  daily, first cycle after 10:30 MT, to #bar-only (+ email PRESHIFT_MAIL_TO - Victor isn't in Slack)
             weather, hours, what's on tonight, the wall (new / last keg / pick), what's sold out at the
             register, yesterday's number, anything waiting on Colby.
  OUTLOOK    Sundays, first cycle after 4pm MT, to #brew-x-bar (+ email OUTLOOK_MAIL_TO)
             the next seven days: weather, games and programming, last-4-weeks and last-year numbers
             for each weekday, and a plan figure with the reasons behind it.

Both dedupe against the channel's own history (a marker string since midnight), so a runner
restart or a handoff can't double-post. Every data source is optional: no Square token = no
numbers, no ESPN = no games, no weather = no weather. The post still goes out with what it has.

  python3 briefs.py preshift --print      # build today's brief, print it, post nothing
  python3 briefs.py outlook --print
"""
import os, sys, json, urllib.request
from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Denver")
except Exception:
    TZ = timezone(timedelta(hours=-6))

try:
    import square
except ImportError:
    square = None
try:
    import events
except ImportError:
    events = None
try:
    import mailer
except ImportError:
    mailer = None

BAR_ONLY = "C0B3E5GF6UR"
BREW_X_BAR = "C0AQ68G7DRB"
PRESHIFT_MARK = "Pre-shift ·"
OUTLOOK_MARK = "Week ahead ·"
LAT, LON = 39.6826, -104.9809          # 1875 S Pearl St

WMO = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog", 51: "drizzle", 53: "drizzle",
       55: "drizzle", 56: "freezing drizzle", 57: "freezing drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
       66: "freezing rain", 67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
       80: "showers", 81: "showers", 82: "heavy showers", 85: "snow showers", 86: "snow showers", 95: "thunderstorms",
       96: "thunderstorms w/ hail", 99: "thunderstorms w/ hail"}


def now():
    return datetime.now(TZ)


def money(x):
    return "$%s" % format(int(round(x)), ",")


# ---- weather -------------------------------------------------------------------------------
_wx = None
def weather():
    """Open-Meteo daily forecast for the next 8 days, keyed by date. Cached per process."""
    global _wx
    if _wx is not None:
        return _wx
    url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s&timezone=America%%2FDenver"
           "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,snowfall_sum,wind_speed_10m_max"
           "&hourly=temperature_2m,precipitation_probability,weather_code&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch&forecast_days=8" % (LAT, LON))
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "computa"}), timeout=20) as r:
            j = json.load(r)
    except Exception as e:
        print("  ! weather: %s" % e)
        _wx = {}
        return _wx
    out = {}
    d = j.get("daily", {})
    for i, day in enumerate(d.get("time", [])):
        out[day] = {"hi": d["temperature_2m_max"][i], "lo": d["temperature_2m_min"][i], "code": d["weather_code"][i],
                    "pop": d["precipitation_probability_max"][i], "rain": d["precipitation_sum"][i],
                    "snow": d["snowfall_sum"][i], "wind": d["wind_speed_10m_max"][i], "evening": None, "evening_pop": None}
    h = j.get("hourly", {})
    for i, t in enumerate(h.get("time", [])):
        if t.endswith("T18:00") and t[:10] in out:
            out[t[:10]]["evening"] = h["temperature_2m"][i]
            out[t[:10]]["evening_pop"] = h["precipitation_probability"][i]
    _wx = out
    return out


def wx_line(w):
    if not w:
        return "weather unavailable"
    bits = ["%d°/%d° %s" % (round(w["hi"]), round(w["lo"]), WMO.get(w["code"], ""))]
    if (w.get("snow") or 0) >= 0.5:
        bits.append("snow %.1f\"" % w["snow"])
    elif (w.get("pop") or 0) >= 40:
        bits.append("%d%% chance of %s" % (w["pop"], "snow" if (w.get("snow") or 0) > 0 else "rain"))
    if (w.get("wind") or 0) >= 25:
        bits.append("wind %d mph" % round(w["wind"]))
    if w.get("evening") is not None:
        bits.append("%d° at 6pm" % round(w["evening"]))
    return " · ".join(bits)


def patio_call(w):
    if not w:
        return ""
    if (w.get("snow") or 0) >= 0.5 or (w.get("evening") is not None and w["evening"] < 40):
        return "heaters on, patio will be thin"
    if (w.get("evening_pop") or 0) >= 50:
        return "rain likely this evening - expect the patio to come inside"
    if w.get("evening") is not None and w["evening"] >= 70:
        return "patio evening"
    return ""


# ---- Slack + dedupe ------------------------------------------------------------------------
def already_posted(slack, channel, mark):
    midnight = now().replace(hour=0, minute=0, second=0, microsecond=0)
    hist = slack("conversations.history", channel=channel, oldest="%.6f" % midnight.timestamp(), limit=200)
    for m in (hist or {}).get("messages") or []:
        if mark in (m.get("text") or ""):
            return True
    return False


def post(slack, channel, text, mail_to_env, subject):
    slack("chat.postMessage", channel=channel, text=text)
    to = os.environ.get(mail_to_env, "")
    if mailer and mailer.enabled() and to:
        mailer.send(to, subject, text)


# ---- the pre-shift brief -------------------------------------------------------------------
def hours_line(data, day):
    hours = data.get("hours") or {}
    if day in (hours.get("closed") or []):
        return "*Closed today*"
    dow = datetime.strptime(day, "%Y-%m-%d").weekday()
    late = day in (hours.get("late") or []) or dow in (4, 5)
    return "11am – %s" % ("midnight" if late else "10pm")


def wall_line(data):
    beers = data.get("beers") or []
    new = [b["name"] for b in beers if (b.get("tappedDaysAgo") is not None and b.get("tappedDaysAgo") <= 3)]
    last = [b["name"] for b in beers if b.get("sash") == "last keg"]
    pick = [b["name"] for b in beers if b.get("pick")]
    fest = [b["name"] for b in beers if b.get("sash") and b.get("sash") != "last keg"]
    bits = ["%d on the wall" % len(beers)]
    if new: bits.append("new: " + ", ".join(new))
    if last: bits.append("last keg: " + ", ".join(last))
    if pick: bits.append("brewers' pick: " + ", ".join(pick))
    if fest: bits.append(", ".join("%s (%s)" % (n, next(b["sash"] for b in beers if b["name"] == n)) for n in fest))
    return " · ".join(bits)


def preshift_text(data, queue):
    t = now()
    day = t.strftime("%Y-%m-%d")
    w = weather().get(day)
    lines = ["*%s %s*" % (PRESHIFT_MARK, t.strftime("%a %b %-d"))]
    lines.append(":partly_sunny: " + wx_line(w) + ((" — " + patio_call(w)) if patio_call(w) else ""))
    lines.append(":clock11: " + hours_line(data, day))
    if events:
        ev = events.on(events.load(), day)
        if ev:
            lines.append((":football: " if any("Broncos" in x for x in ev) else ":calendar: ") + " · ".join(ev))
    lines.append(":beers: " + wall_line(data))
    if square and square.enabled():
        try:
            so = square.status()
            lines.append(":no_entry_sign: Sold out at the register: " + (", ".join(n for n, _ in so) if so else "nothing"))
        except Exception as e:
            lines.append(":warning: Couldn't read the register (%s)" % str(e)[:60])
        try:
            y = (t - timedelta(days=1)).strftime("%Y-%m-%d")
            lw = (t - timedelta(days=8)).strftime("%Y-%m-%d")
            ys, ls = square.day_sales(y), square.day_sales(lw)
            lines.append(":moneybag: Yesterday %s net · %d checks · %s avg  (same day last week %s)" %
                         (money(ys["net"]), ys["checks"], "$%.2f" % ys["avg"], money(ls["net"])))
        except Exception as e:
            print("  ! yesterday: %s" % e)
    waiting = [q for q in (queue or []) if q.get("action") in ("report", "add", "needs_button", "remove_unmatched", "restore_unknown", "flavor_offlist")]
    if waiting:
        lines.append(":eyes: Waiting on Colby: " + " · ".join("%s (%s)" % (q.get("item") or "?", q.get("action", "").replace("_", " ")) for q in waiting[:6]))
    return "\n".join(lines)


def preshift(slack, data, queue):
    t = now()
    if t.hour != 10 or t.minute < 30:
        return False
    if already_posted(slack, BAR_ONLY, PRESHIFT_MARK):
        return False
    post(slack, BAR_ONLY, preshift_text(data, queue), "PRESHIFT_MAIL_TO", "Pre-shift · %s" % t.strftime("%a %b %-d"))
    print("pre-shift posted")
    return True


# ---- the Sunday outlook --------------------------------------------------------------------
def outlook_text(data):
    t = now()
    start = (t + timedelta(days=1)).date()                      # Monday
    days = [(start + timedelta(days=i)) for i in range(7)]
    ev = events.load() if events else {"broncos": [], "weekly": {}, "extra": []}
    wx = weather()
    lines = ["*%s %s – %s*" % (OUTLOOK_MARK, days[0].strftime("%b %-d"), days[-1].strftime("%b %-d"))]
    sq = square and square.enabled()
    plan_total = 0.0; have_numbers = False
    for d in days:
        key = d.isoformat()
        w = wx.get(key)
        what = events.on(ev, key) if events else []
        game = events.game_day(ev, key) if events else None
        row = ["*%s %d*" % (d.strftime("%a"), d.day), wx_line(w) if w else "", " · ".join(what)]
        base = None; ly = None
        if sq:
            try:
                same = [square.day_sales((d - timedelta(days=7 * k)).isoformat())["net"] for k in (1, 2, 3, 4)]
                base = sum(same) / len(same)
                ly = square.day_sales((d - timedelta(days=364)).isoformat())["net"]
                have_numbers = True
            except Exception as e:
                print("  ! outlook sales %s: %s" % (key, e))
        if base is not None:
            mult, why = 1.0, []
            if game:
                mult *= 1.25; why.append("Broncos")
            if w:
                if (w.get("snow") or 0) >= 1 or (w.get("evening") is not None and w["evening"] < 35):
                    mult *= 0.85; why.append("cold/snow")
                elif (w.get("evening") is not None and w["evening"] >= 70 and d.weekday() >= 4):
                    mult *= 1.10; why.append("patio weather")
                elif (w.get("pop") or 0) >= 60:
                    mult *= 0.92; why.append("rain")
            plan = base * mult
            plan_total += plan
            row.append("last 4 %s avg %s · last year %s → plan *%s*%s" %
                       (d.strftime("%a"), money(base), money(ly) if ly is not None else "n/a", money(plan),
                        (" (" + ", ".join(why) + ")") if why else ""))
        lines.append("  ".join(x for x in row if x))
    if have_numbers:
        lines.append("Week plan: *%s* net." % money(plan_total))
    notes = []
    games = [g for g in ev.get("broncos", []) if g["date"] in [d.isoformat() for d in days]]
    for g in games:
        notes.append("%s %s %s - pitchers and wings, squares board up" % (g["dow"], g["label"], g["kick"]))
    if any(d.weekday() == 2 for d in days):
        notes.append("Wing Wednesday: a dozen for $12 - wings on the Tuesday order")
    if notes:
        lines.append(":clipboard: " + " · ".join(notes))
    return "\n".join(lines)


def outlook(slack, data):
    t = now()
    if t.weekday() != 6 or t.hour < 16:
        return False
    if already_posted(slack, BREW_X_BAR, OUTLOOK_MARK):
        return False
    post(slack, BREW_X_BAR, outlook_text(data), "OUTLOOK_MAIL_TO", "Week ahead · %s" % (t + timedelta(days=1)).strftime("%b %-d"))
    print("outlook posted")
    return True


def tick(slack, data_loader, queue_loader):
    """Called once per Computa cycle. Loads beers.json / the queue only when a post is due."""
    t = now()
    due_pre = (t.hour == 10 and t.minute >= 30)
    due_out = (t.weekday() == 6 and t.hour >= 16)
    if not (due_pre or due_out):
        return
    try:
        if events:
            d = events.refresh_broncos(events.load()); events.save(d)
    except Exception as e:
        print("  ! events: %s" % e)
    try:
        data = data_loader()
    except Exception as e:
        print("  ! briefs: can't load beers.json (%s)" % e); return
    try:
        if due_pre:
            preshift(slack, data, queue_loader())
    except Exception as e:
        print("  ! preshift: %s" % e)
    try:
        if due_out:
            outlook(slack, data)
    except Exception as e:
        print("  ! outlook: %s" % e)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "preshift"
    data = json.load(open("beers.json"))
    try:
        queue = json.load(open("computa_queue.json"))
    except Exception:
        queue = []
    if events:
        d = events.refresh_broncos(events.load()); events.save(d)
    print(preshift_text(data, queue) if which == "preshift" else outlook_text(data))
