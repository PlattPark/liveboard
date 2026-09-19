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
        window=(39.198, 39.272, -105.335, -105.165),
        label_at=(39.2536, -105.2214), layers=("rivers", "trails"),   # Deckers
        wire="the lines behind the tanks are the South Platte through Cheesman Canyon"),
    "lostcreek": dict(
        title="LOST CREEK WILDERNESS", elev_ft=None,
        window=(39.200, 39.300, -105.575, -105.340),
        label_at=(39.2575, -105.4875), layers=("trails", "rivers"),   # Bison Peak
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
);
out geom;""" % (bbox, bbox, bbox, bbox)
    body = urllib.parse.urlencode({"data": q}).encode()
    try:
        d = json.loads(http("https://overpass-api.de/api/interpreter", data=body, timeout=150))
    except Exception:
        print("  main Overpass server is busy - trying the mirror")
        d = json.loads(http("https://overpass.kumi.systems/api/interpreter", data=body, timeout=150))
    feats = []
    for el in d.get("elements", []):
        if el.get("type") != "way" or "geometry" not in el:
            continue
        t = el.get("tags", {})
        if "aerialway" in t: kind = "lifts"
        elif t.get("piste:type") == "downhill": kind = "pistes"
        elif "waterway" in t: kind = "rivers"
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
             "trails": ('stroke-width="1.3" stroke-opacity=".45" stroke-dasharray="3 5" stroke-linecap="round"', True)}
    labelled = set(); n = 0
    for kind in P["layers"]:
        st, label = style[kind]
        svg.append('<g fill="none" stroke="#293d22" %s stroke-linejoin="round">' % st)
        for f in sorted([f for f in feats if f["kind"] == kind], key=lambda f: -len(f["pts"])):
            pts = [proj(*p) for p in f["pts"]]
            if not any(0 <= x <= W and 0 <= y <= H for x, y in pts): continue
            pid = "f%d" % n; n += 1
            svg.append('<path id="%s" d="%s"/>' % (pid, rel_path(pts)))
            if kind == "lifts":
                svg.append('<circle cx="%d" cy="%d" r="3" fill="#293d22" fill-opacity=".55" stroke="none"/><circle cx="%d" cy="%d" r="3" fill="#293d22" fill-opacity=".55" stroke="none"/>'
                           % (pts[0][0], pts[0][1], pts[-1][0], pts[-1][1]))
            if label and f["name"] and f["name"] not in labelled and len(pts) > 2:
                labelled.add(f["name"])
                svg.append('<text font-family="Barlow,sans-serif" font-size="10.5" font-weight="700" letter-spacing="2.5" fill="#293d22" fill-opacity=".5" stroke="none" dy="-4">'
                           '<textPath href="#%s" startOffset="12%%">%s</textPath></text>' % (pid, esc(f["name"].upper())))
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
    txt += '<text x="%d" y="%d" font-size="11" fill-opacity=".36">%s \u00b7 %s FT</text><circle cx="%d" cy="%d" r="3" fill-opacity=".36"/>' % (lx + 10, ly + 4, esc(P["title"]), "{:,}".format(elev_ft), lx, ly)
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
