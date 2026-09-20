#!/usr/bin/env python3
"""
events.py - Platt Park Brewing
What's on, day by day: the Broncos schedule (self-refreshing from ESPN), the taproom's weekly
programming, and anything Colby adds by hand. Feeds the 10:30 pre-shift brief and the Sunday outlook.

events.json
  {
    "broncos": [...]            written by this file from ESPN, refreshed when older than a day
    "weekly": {"mon": "...", "tue": "..."}   the standing programming (edit by hand)
    "extra": [{"date": "2026-10-31", "text": "Halloween - late night, costume contest"}]   one-offs (edit by hand)
  }

  python3 events.py            # refresh events.json from ESPN and print the next 10 days
"""
import json, os, re, urllib.request
from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Denver")
except Exception:
    TZ = timezone(timedelta(hours=-6))

PATH = "events.json"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/den/schedule"
TEAMS = {"KC": "Chiefs", "LV": "Raiders", "LAC": "Chargers", "JAX": "Jaguars", "LAR": "Rams", "SEA": "Seahawks",
         "BUF": "Bills", "MIA": "Dolphins", "NE": "Patriots", "NYJ": "Jets", "BAL": "Ravens", "CIN": "Bengals",
         "CLE": "Browns", "PIT": "Steelers", "HOU": "Texans", "IND": "Colts", "TEN": "Titans", "DAL": "Cowboys",
         "NYG": "Giants", "PHI": "Eagles", "WSH": "Commanders", "CHI": "Bears", "DET": "Lions", "GB": "Packers",
         "MIN": "Vikings", "ATL": "Falcons", "CAR": "Panthers", "NO": "Saints", "TB": "Buccaneers", "ARI": "Cardinals",
         "SF": "49ers", "DEN": "Broncos"}

DEFAULT_WEEKLY = {
    "mon": "Industry Night - 25% off the whole tab, all day, food included · $2 off 32oz pitchers 3-10pm · Double Stars",
    "tue": "Team Trivia 7pm",
    "wed": "Wing Wednesday - a dozen for $12",
    "thu": "", "fri": "", "sat": "", "sun": "",
}


def load():
    try:
        d = json.load(open(PATH))
    except Exception:
        d = {}
    d.setdefault("broncos", []); d.setdefault("weekly", dict(DEFAULT_WEEKLY)); d.setdefault("extra", [])
    return d


def save(d):
    json.dump(d, open(PATH, "w"), indent=1, ensure_ascii=False)


def refresh_broncos(d, force=False):
    """Pull the season from ESPN once a day. Keeps the old list if ESPN is unreachable."""
    stamp = d.get("broncos_fetched")
    if stamp and not force:
        try:
            if datetime.now(timezone.utc) - datetime.fromisoformat(stamp) < timedelta(hours=20):
                return d
        except Exception:
            pass
    try:
        with urllib.request.urlopen(urllib.request.Request(ESPN, headers={"User-Agent": "computa"}), timeout=20) as r:
            j = json.load(r)
    except Exception as e:
        print("  ! espn: %s" % e)
        return d
    games = []
    for e in j.get("events", []):
        try:
            c = e["competitions"][0]
            when = datetime.fromisoformat(e["date"].replace("Z", "+00:00")).astimezone(TZ)
            home = next(t for t in c["competitors"] if t["homeAway"] == "home")["team"]["abbreviation"]
            away = next(t for t in c["competitors"] if t["homeAway"] == "away")["team"]["abbreviation"]
            opp = away if home == "DEN" else home
            tv = ", ".join(x.get("media", {}).get("shortName", "") for x in (c.get("broadcasts") or []) if x.get("media", {}).get("shortName"))
            games.append({
                "date": when.strftime("%Y-%m-%d"), "kick": when.strftime("%-I:%M%p").lower().replace(":00", ""),
                "dow": when.strftime("%a"), "home": home == "DEN", "opp": TEAMS.get(opp, opp),
                "label": "Broncos %s %s" % ("vs" if home == "DEN" else "at", TEAMS.get(opp, opp)),
                "tv": tv, "week": (e.get("week") or {}).get("number"),
                "time_tbd": not e.get("timeValid", True),
            })
        except Exception:
            continue
    if games:
        d["broncos"] = games
        d["broncos_fetched"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return d


def on(d, day):
    """Everything happening on a date (YYYY-MM-DD): list of short strings."""
    out = []
    dow = datetime.strptime(day, "%Y-%m-%d").strftime("%a").lower()
    for g in d.get("broncos", []):
        if g["date"] == day:
            out.append("%s %s%s" % (g["label"], "TBD" if g.get("time_tbd") else g["kick"], (" · " + g["tv"]) if g.get("tv") else ""))
    w = (d.get("weekly") or {}).get(dow, "")
    if w:
        out.append(w)
    for x in d.get("extra", []):
        if x.get("date") == day and x.get("text"):
            out.append(x["text"])
    return out


def game_day(d, day):
    return next((g for g in d.get("broncos", []) if g["date"] == day), None)


if __name__ == "__main__":
    d = refresh_broncos(load(), force=True)
    save(d)
    today = datetime.now(TZ).date()
    for i in range(10):
        day = (today + timedelta(days=i)).isoformat()
        print(day, datetime.strptime(day, "%Y-%m-%d").strftime("%a"), " | ".join(on(d, day)))
