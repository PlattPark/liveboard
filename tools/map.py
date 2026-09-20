#!/usr/bin/env python3
"""
tools/map.py - draw a seasonal map for the wall from public data.

  python3 tools/map.py abasin          # one place
  python3 tools/map.py all             # every place in PLACES
  python3 tools/map.py ouray --offline # redraw from cache/ without the network

Elevation: SRTM 30 m via api.opentopodata.org (100 points per call, 1 call/s),
           falling back to Open-Meteo's 90 m grid if that is down.
Features:  OpenStreetMap via the Overpass API - lifts, downhill runs, rivers,
           named trails. Drawn from the data, never traced from anyone's map.
Output:    maps/<place>.svg, 1920x1080, same ink and weights as the Ouray map:
           contours, features, place label, benchmark on the high point,
           a true 1-mile scale bar + north arrow, and the OSM credit.
Needs:     numpy scipy matplotlib (pip); network on the runner.
"""
import sys, os, json, math, re, time, pathlib, urllib.request, urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "maps"; CACHE = ROOT / "cache"
W, H = 1920, 1080

# window = (lat_south, lat_north, lon_west, lon_east); the label point is where the name sits
PLACES = {
    "abasin": dict(
        title="ARAPAHOE BASIN", elev_ft=10780,          # base area elevation
        window=(39.626, 39.655, -105.905, -105.835),
        label_at=(39.6425, -105.8717), layers=("lifts", "pistes"),
        wire="the lines behind the tanks are Arapahoe Basin \u2014 every lift and run, on real contours"),
    "platte": dict(
        title="SOUTH PLATTE \u00b7 CHEESMAN CANYON", elev_ft=None,   # from the grid at the label point
        window=(39.197, 39.267, -105.345, -105.184),          # dam to Deckers, 8.7 x 13.9 km
        label_at=(39.2536, -105.2214), layers=("water", "rivers", "trails"),   # Deckers; water = the reservoir shoreline
        wire="the lines behind the tanks are the South Platte through Cheesman Canyon"),
    "lostcreek": dict(
        title="LOST CREEK WILDERNESS", elev_ft=None,
        window=(39.2225, 39.2925, -105.568, -105.407),         # Bison Peak country, 7.8 x 13.9 km
        label_at=(39.2575, -105.4875), layers=("trails", "rivers", "peaks"),   # Bison Peak; peaks = named summits
        wire="the lines behind the tanks are the Lost Creek Wilderness \u2014 real contours and trails"),
    "ouray": dict(
        title="OURAY", elev_ft=7792,
        window=(37.985, 38.060, -107.760, -107.585),
        label_at=(38.0228, -107.6714), layers=("rivers", "trails"),
        wire="the lines behind the tanks are the mountains around Ouray, Colorado"),
}

GRID_W, GRID_H = 96, 54          # sample grid; ~30 m data so this is plenty for 1920 px


# ---------------------------------------------------------------- data ----
def http(url, data=None, timeout=60, tries=4):
    """GET/POST with patience: public data servers 504 when busy, so back off and retry."""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": "plattpark-liveboard map builder"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode()
        except Exception as ex:
            last = ex; print("    %s (try %d/%d)" % (str(ex)[:60], i + 1, tries)); time.sleep(8 * (i + 1))
    raise last


def fetch_dem(win):
    s, n, w, e = win
    pts = [(n - (n - s) * j / (GRID_H - 1), w + (e - w) * i / (GRID_W - 1)) for j in range(GRID_H) for i in range(GRID_W)]
    z = []
    try:
        for k in range(0, len(pts), 100):
            locs = "|".join("%.5f,%.5f" % p for p in pts[k:k + 100])
            d = json.loads(http("https://api.opentopodata.org/v1/srtm30m?locations=" + locs))
            z += [r["elevation"] for r in d["results"]]
            time.sleep(1.05)
        src = "SRTM 30 m"
    except Exception as ex:
        print("  opentopodata failed (%s) - falling back to Open-Meteo 90 m" % ex)
        z = []
        for k in range(0, len(pts), 100):
            chunk = pts[k:k + 100]
            q = "latitude=%s&longitude=%s" % (",".join("%.5f" % p[0] for p in chunk), ",".join("%.5f" % p[1] for p in chunk))
            z += json.loads(http("https://api.open-meteo.com/v1/elevation?" + q))["elevation"]
        src = "Copernicus 90 m"
    return {"w": GRID_W, "h": GRID_H, "z": z, "source": src}


def fetch_osm(win):
    s, n, w, e = win
    bbox = "%f,%f,%f,%f" % (s, w, n, e)
    q = """[out:json][timeout:90];
(
  way["aerialway"~"chair_lift|gondola|mixed_lift|platter|t-bar|rope_tow|magic_carpet"](%s);
  way["piste:type"="downhill"](%s);
  way["waterway"~"^(river|stream)$"]["name"](%s);
  way["highway"~"^(path|footway|track)$"]["name"](%s);
  node["natural"="peak"]["name"](%s);
  way["natural"="water"]["name"](%s);
  relation["natural"="water"]["name"](%s);
);
out geom;""" % ((bbox,) * 7)
    body = urllib.parse.urlencode({"data": q}).encode()
    try:
        d = json.loads(http("https://overpass-api.de/api/interpreter", data=body, timeout=150))
    except Exception:
        print("  main Overpass server is busy - trying the mirror")
        d = json.loads(http("https://overpass.kumi.systems/api/interpreter", data=body, timeout=150))
    feats = []
    for el in d.get("elements", []):
        t = el.get("tags", {})
        if el.get("type") == "node" and t.get("natural") == "peak":
            try: ele_ft = int(round(float(t.get("ele", "").split()[0]) * 3.28084))
            except Exception: ele_ft = None
            feats.append({"kind": "peaks", "name": t.get("name", ""), "ele_ft": ele_ft, "pts": [(el["lat"], el["lon"])]})
            continue
        if el.get("type") == "relation" and t.get("natural") == "water":
            for m in el.get("members", []):                       # the shoreline is the union of the member ways
                if m.get("type") == "way" and m.get("geometry"):
                    feats.append({"kind": "water", "name": t.get("name", ""), "pts": [(g["lat"], g["lon"]) for g in m["geometry"]]})
            continue
        if el.get("type") != "way" or "geometry" not in el:
            continue
        if "aerialway" in t: kind = "lifts"
        elif t.get("piste:type") == "downhill": kind = "pistes"
        elif "waterway" in t: kind = "rivers"
        elif t.get("natural") == "water": kind = "water"
        else: kind = "trails"
        feats.append({"kind": kind, "name": t.get("name", ""), "pts": [(g["lat"], g["lon"]) for g in el["geometry"]]})
    return feats


# ---------------------------------------------------------------- draw ----
def project(win):
    s, n, w, e = win
    return lambda lat, lon: ((lon - w) / (e - w) * W, (n - lat) / (n - s) * H)


def rel_path(pts):
    X0, Y0 = round(pts[0][0]), round(pts[0][1]); out = "M%d %d" % (X0, Y0); cx, cy = X0, Y0; parts = []
    for x, y in pts[1:]:
        X, Y = round(x), round(y)
        if (X, Y) != (cx, cy):
            parts.append("%d %d" % (X - cx, Y - cy)); cx, cy = X, Y
    return out + ("l" + " ".join(parts) if parts else "")


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# the three strips the tanks and plates leave clear on the wall: under the header, between the rows, above the rail
OPEN = ((200, 8, 1330, 122), (40, 536, 1300, 582), (600, 946, 1290, 1000), (20, 972, 600, 1000))   # the credit and margin note own the bottom-left corner


def open_at(box):
    return any(bx0 <= box[0] and box[2] <= bx1 and by0 <= box[1] and box[3] <= by1 for bx0, by0, bx1, by1 in OPEN)


def label_run(pts, need):
    """Pick the straightest stretch of a polyline long enough for a label, or None.
    Text on a switchback piles its letters up, so a run must stay within 20 percent of straight and
    its first and last thirds must point within 60 degrees of each other; the run is smoothed before
    the letters ride it (pixel-rounded segments jitter). A name only goes where the wall can show it
    whole - the three strips the tanks and plates leave clear - because a name half-hidden behind a
    price tag reads as litter. Near-vertical runs lose ties. Returns (points, box)."""
    n = len(pts)
    if n < 3: return None
    seg = [math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(n - 1)]
    cum = [0.0]
    for d in seg: cum.append(cum[-1] + d)
    if cum[-1] < need: return None
    def heading(a, b): return math.atan2(pts[b][1] - pts[a][1], pts[b][0] - pts[a][0])
    best = None; j = 0
    for i in range(n - 1):
        while j < n - 1 and cum[j] - cum[i] < need: j += 1
        if cum[j] - cum[i] < need: break
        L = cum[j] - cum[i]; chord = math.hypot(pts[j][0] - pts[i][0], pts[j][1] - pts[i][1])
        if chord < 0.8 * L: continue
        k1, k2 = i + max(1, (j - i) // 3), j - max(1, (j - i) // 3)
        turn = abs((heading(i, k1) - heading(k2, j) + math.pi) % (2 * math.pi) - math.pi)
        if turn > math.radians(60): continue
        xs = [q[0] for q in pts[i:j + 1]]; ys = [q[1] for q in pts[i:j + 1]]
        x0, y0, x1, y1 = min(xs), min(ys) - 14, max(xs), max(ys) + 4
        if x0 < 30 or x1 > W - 30 or y0 < 8 or y1 > H - 85: continue          # off the wall or under the rail
        open_band = open_at((x0, y0, x1, y1))
        if not open_band: continue                                            # a half-hidden name reads as litter; none is better
        vertical = abs(pts[j][0] - pts[i][0]) < abs(pts[j][1] - pts[i][1])
        score = turn + 4 * (1 - chord / L) + (1.0 if vertical else 0)
        if best is None or score < best[0]:
            best = (score, i, j)
    if best is None: return None
    _, i, j = best
    run = pts[i:j + 1]
    if run[-1][0] < run[0][0]: run = run[::-1]                                 # read left to right, never upside down
    sm = [(sum(q[0] for q in run[max(0, k - 9):k + 10]) / len(run[max(0, k - 9):k + 10]),
           sum(q[1] for q in run[max(0, k - 9):k + 10]) / len(run[max(0, k - 9):k + 10])) for k in range(len(run))]
    xs = [q[0] for q in sm]; ys = [q[1] for q in sm]
    return sm, (min(xs) - 8, min(ys) - 14, max(xs) + 8, max(ys) + 4)


def draw(place, dem, feats):
    import numpy as np
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    from scipy.ndimage import zoom, gaussian_filter, maximum_filter

    P = PLACES[place]; win = P["window"]; proj = project(win)
    z = np.array(dem["z"], dtype=float).reshape(dem["h"], dem["w"])
    zz = gaussian_filter(zoom(z, 8, order=3), sigma=4); h, w = zz.shape
    relief = z.max() - z.min()
    step = 20 if relief < 300 else 40 if relief < 700 else 60 if relief < 1400 else 100   # Ouray (1,800 m relief) -> 100 m, a ski hill -> 60 m
    levels = np.arange(math.floor(z.min() / step) * step, z.max() + step, step)
    cs = plt.contour(zz, levels=levels)

    reg, idx = [], []
    for lev, segs in zip(cs.levels, cs.allsegs):
        for seg in segs:
            pts = [(float(x) / w * W, float(y) / h * H) for x, y in seg]
            if len(pts) < 8: continue
            out = [pts[0]]
            for p in pts[1:]:
                if abs(p[0] - out[-1][0]) + abs(p[1] - out[-1][1]) >= 7: out.append(p)
            if len(out) < 8: continue
            (idx if int(round(lev)) % (step * 5) == 0 else reg).append(rel_path(out))

    svg = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d">' % (W, H),
           '<g fill="none" stroke="#293d22" stroke-width="1.1" stroke-opacity=".17" stroke-linejoin="round">' + "".join('<path d="%s"/>' % d for d in reg) + "</g>",
           '<g fill="none" stroke="#293d22" stroke-width="1.9" stroke-opacity=".27" stroke-linejoin="round">' + "".join('<path d="%s"/>' % d for d in idx) + "</g>"]
    # features, only the layers this place asked for; labels ride along the line
    style = {"lifts":  ('stroke-width="2.2" stroke-opacity=".55"', True),
             "pistes": ('stroke-width="1" stroke-opacity=".28" stroke-dasharray="4 3"', False),
             "rivers": ('stroke-width="2.4" stroke-opacity=".45" stroke-linecap="round"', True),
             "trails": ('stroke-width="1.3" stroke-opacity=".45" stroke-dasharray="3 5" stroke-linecap="round"', True),
             "water":  ('stroke-width="1.8" stroke-opacity=".42" stroke-linecap="round"', True),
             "peaks":  ('stroke-width="1.4" stroke-opacity=".5"', True)}
    labelled = set(); boxes = []; n = 0
    def clear(box):
        return not any(box[0] < b[2] and box[2] > b[0] and box[1] < b[3] and box[3] > b[1] for b in boxes)
    for kind in P["layers"]:
        st, label = style[kind]
        svg.append('<g fill="none" stroke="#293d22" %s stroke-linejoin="round">' % st)
        for f in sorted([f for f in feats if f["kind"] == kind], key=lambda f: -len(f["pts"])):
            pts = [proj(*p) for p in f["pts"]]
            if not any(0 <= x <= W and 0 <= y <= H for x, y in pts): continue
            if kind == "peaks":                                   # a summit: small triangle, name and height beside it
                x, y = pts[0]
                if not (40 < x < W - 40 and 30 < y < H - 90) or f["name"] in labelled: continue
                labelled.add(f["name"])
                tag = f["name"].upper() + (" \u00b7 %s" % "{:,}".format(f["ele_ft"]) if f.get("ele_ft") else "")
                svg.append('<path d="M%d %d l5 9 h-10z"/>' % (x, y - 5))
                box = (x + 8, y - 8, x + 12 + 9 * len(tag), y + 6)
                if open_at(box) and clear(box):                       # the name only where nothing on the wall covers it
                    boxes.append(box)
                    svg.append('<text x="%d" y="%d" font-family="Barlow,sans-serif" font-size="10" font-weight="700" letter-spacing="2.5" fill="#293d22" fill-opacity=".5" stroke="none">%s</text>'
                               % (x + 10, y + 4, esc(tag)))
                continue
            pid = "f%d" % n; n += 1
            svg.append('<path id="%s" d="%s"/>' % (pid, rel_path(pts)))
            if kind == "lifts":
                svg.append('<circle cx="%d" cy="%d" r="3" fill="#293d22" fill-opacity=".55" stroke="none"/><circle cx="%d" cy="%d" r="3" fill="#293d22" fill-opacity=".55" stroke="none"/>'
                           % (pts[0][0], pts[0][1], pts[-1][0], pts[-1][1]))
            if label and f["name"] and f["name"] not in labelled and len(pts) > 2:
                run = label_run(pts, 9.2 * len(f["name"]) + 10)                 # ~9.2 px per letter at this size and tracking
                if run and clear(run[1]):
                    labelled.add(f["name"]); boxes.append(run[1]); lid = pid + "t"
                    svg.append('<path id="%s" d="%s" stroke="none"/>' % (lid, rel_path(run[0])))
                    svg.append('<text font-family="Barlow,sans-serif" font-size="10.5" font-weight="700" letter-spacing="2.5" fill="#293d22" fill-opacity=".5" stroke="none" dy="-4" text-anchor="middle">'
                               '<textPath href="#%s" startOffset="50%%">%s</textPath></text>' % (lid, esc(f["name"].upper())))
        svg.append("</g>")

    # marks: place label, benchmark on the highest interior high point, scale bar, north arrow, credit
    lx, ly = proj(*P["label_at"])
    if P.get("elev_ft") is None:
        gj = int(round((win[1] - P["label_at"][0]) / (win[1] - win[0]) * (dem["h"] - 1)))
        gi = int(round((P["label_at"][1] - win[2]) / (win[3] - win[2]) * (dem["w"] - 1)))
        elev_ft = int(round(z[gj, gi] * 3.28084 / 10) * 10)
    else:
        elev_ft = P["elev_ft"]
    mx = (z == maximum_filter(z, size=7)); mx[:3, :] = mx[-3:, :] = mx[:, :3] = mx[:, -3:] = False
    peaks = sorted([(z[j, i], i, j) for j, i in zip(*np.where(mx))], reverse=True)
    txt = '<g font-family="Barlow,sans-serif" font-weight="700" letter-spacing="3" fill="#293d22" stroke="none">'
    # the name reads like a map margin note (bottom-left, clear of the tanks); the dot stays on the true spot
    txt += '<text x="34" y="%d" font-size="12" letter-spacing="3.5" fill-opacity=".42">%s \u00b7 %s FT</text><circle cx="%d" cy="%d" r="3" fill-opacity=".36"/>' % (H - 136, esc(P["title"]), "{:,}".format(elev_ft), lx, ly)
    if peaks:
        pz, pi, pj = peaks[0]; px, py = pi / (dem["w"] - 1) * W, pj / (dem["h"] - 1) * H
        txt += ('<path d="M%d %d l6 11 h-12z" fill="none" stroke="#293d22" stroke-width="1.4" stroke-opacity=".42"/><circle cx="%d" cy="%d" r="1.4" fill-opacity=".42"/>'
                '<text x="%d" y="%d" font-size="11" letter-spacing="2.5" fill-opacity=".42">BM %s</text>') % (px, py - 7, px, py + 1, px + 12, py + 4, "{:,}".format(int(round(pz * 3.28084))))
    mile_px = 1609.34 / ((win[3] - win[2]) * 111320 * math.cos(math.radians((win[0] + win[1]) / 2))) * W
    sx, sy = 1318, 940
    txt += ('<g fill-opacity=".42" stroke-opacity=".42"><path d="M%d %dh%dM%d %dv6M%d %dv4M%d %dv6" stroke="#293d22" stroke-width="1.4" fill="none"/>'
            '<text x="%d" y="%d" font-size="9" letter-spacing="1.5">0</text><text x="%d" y="%d" font-size="9" letter-spacing="1.5">\u00bd</text><text x="%d" y="%d" font-size="9" letter-spacing="1.5">1 MI</text>'
            '<path d="M%d %d l5 18 -5 -4 -5 4z" fill="none" stroke="#293d22" stroke-width="1.3"/><text x="%d" y="%d" font-size="7">N</text></g>'
            % (sx, sy + 8, mile_px, sx, sy + 2, sx + mile_px / 2, sy + 4, sx + mile_px, sy + 2,
               sx - 8, sy, sx + mile_px / 2 - 6, sy, sx + mile_px - 8, sy,
               sx + mile_px + 30, sy - 8, sx + mile_px + 26, sy + 22))
    credit = "map data \u00a9 OpenStreetMap contributors \u00b7 elevation %s" % dem.get("source", "SRTM")
    txt += '<text x="34" y="%d" font-size="8" letter-spacing="1.5" fill-opacity=".28">%s</text></g></svg>' % (H - 118, esc(credit))
    svg.append(txt)
    out = "".join(svg)
    OUT.mkdir(exist_ok=True)
    (OUT / (place + ".svg")).write_text(out, encoding="utf-8")
    print("  maps/%s.svg: %d KB, %d contours (%d m step), %d features, high point %s ft"
          % (place, len(out) // 1024, len(reg) + len(idx), step, n, "{:,}".format(int(peaks[0][0] * 3.28084)) if peaks else "?"))
    return out


def build(place, offline=False):
    P = PLACES[place]; CACHE.mkdir(exist_ok=True)
    cd, co = CACHE / (place + "-dem.json"), CACHE / (place + "-osm.json")
    if offline or (cd.exists() and co.exists()):
        dem, feats = json.load(open(cd)), json.load(open(co))
    else:
        print("  fetching elevation..."); dem = fetch_dem(P["window"]); json.dump(dem, open(cd, "w"))
        print("  fetching OpenStreetMap features..."); feats = fetch_osm(P["window"]); json.dump(feats, open(co, "w"))
    print("  %s: %d elevation points, %d features" % (place, len(dem["z"]), len(feats)))
    draw(place, dem, feats)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    offline = "--offline" in sys.argv
    failed = []
    for p in (PLACES if which == "all" else [which]):
        try:
            build(p, offline)
        except Exception as ex:
            print("  FAILED %s: %s - the others still get drawn and committed" % (p, str(ex)[:80])); failed.append(p)
        time.sleep(3)
    if failed:
        print("re-run for: " + " ".join(failed))
    # the manifest the board reads: which file, which label, which wire line
    json.dump({k: {"file": "maps/%s.svg" % k, "title": v["title"], "wire": v["wire"]} for k, v in PLACES.items()},
              open(OUT / "maps.json", "w"), indent=1, ensure_ascii=False)
