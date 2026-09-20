#!/usr/bin/env python3
"""
tools/mapstrip.py - take every word off the wall maps, run by the Board workflow before each build.

Colby, Sept 19: the names, benchmark, scale bar and credit were making the field behind the tanks
muddy - the map is texture, so it keeps only its lines (contours, trails, lifts, rivers, shorelines).
The OpenStreetMap credit the feature lines require moves onto the wire, where it is read rather than
squinted at. Idempotent: a map with nothing to strip is left alone, so the runner can call it on
every build, including right after the Map workflow redraws.
"""
import re, json, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAPS = ROOT / "maps"
CREDIT = " \u00b7 map data \u00a9 OpenStreetMap contributors"


def strip(svg):
    svg = re.sub(r"<text\b[^>]*>.*?</text>", "", svg, flags=re.S)                                          # every word
    svg = re.sub(r'<g font-family="Barlow,sans-serif" font-weight="700" letter-spacing="3"[^>]*>.*?</g>(?=</svg>)', "", svg, flags=re.S)   # margin note, benchmark, scale bar, credit
    svg = re.sub(r'<path d="M-?\d+ -?\d+ l5 9 h-10z"/>', "", svg)                                          # summit triangles
    svg = re.sub(r'<path id="f\d+t" d="[^"]*" stroke="none"/>', "", svg)                                   # the invisible paths the names rode on
    return svg


def main():
    changed = []
    for f in sorted(MAPS.glob("*.svg")):
        s = f.read_text(encoding="utf-8"); t = strip(s)
        if t != s: f.write_text(t, encoding="utf-8"); changed.append(f.name)
    mj = MAPS / "maps.json"
    if mj.exists():
        d = json.loads(mj.read_text(encoding="utf-8")); touched = False
        for v in d.values():
            if "OpenStreetMap" not in v.get("wire", ""): v["wire"] = v.get("wire", "") + CREDIT; touched = True
        if touched: mj.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8"); changed.append("maps.json")
    print("mapstrip: " + (", ".join(changed) if changed else "nothing to strip"))


if __name__ == "__main__":
    main()
