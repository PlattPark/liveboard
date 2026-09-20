#!/usr/bin/env python3
"""
tools/fixart.py - one-time cleanup of the ranger figure, run by the Board workflow before each build.

The tee art came to the board with two things baked in: a cream wedge where the sun's edge meets the
crook of his elbow (paper colour, not transparent - it glowed on every night board) and a 26-px
"BREWED FOR ADVENTURE" line under the figure that turns to mush at 176 px wide. This knocks the
wedge out to transparent and crops the tagline band off; the board draws the tagline as real text
instead. Idempotent: once the file is 1059 px tall with no wedge it does nothing, so the runner can
call it on every build.
"""
import sys, pathlib
from collections import deque

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "img" / "ranger.png"
CROP_AT = 1059           # first row of the gap under the figure (the tagline sits at 1068-1093)
SEED = (180, 407)        # a pixel inside the wedge, (x, y) in the 827x1100 original


def main():
    from PIL import Image
    import numpy as np
    im = Image.open(SRC)
    if im.size[1] <= CROP_AT:
        print("fixart: ranger.png already cleaned (%dx%d)" % im.size); return 0
    a = np.array(im.convert("RGBA")); h, w, _ = a.shape
    light = (a[:, :, 3] > 0) & (a[:, :, :3].min(axis=2) > 200)
    x, y = SEED; n = 0
    if light[y, x]:                                   # flood-fill the wedge only: bounded by ink lines and the sun
        comp = np.zeros_like(light); q = deque([(y, x)]); comp[y, x] = True
        while q:
            cy, cx = q.popleft()
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = cy + dy, cx + dx
                if 0 <= ny < h and 0 <= nx < w and light[ny, nx] and not comp[ny, nx]:
                    comp[ny, nx] = True; q.append((ny, nx))
        n = int(comp.sum())
        if n > 20000: print("fixart: refusing - the fill escaped the wedge (%d px)" % n); return 1
        a[comp] = [232, 234, 206, 0]
    out = Image.fromarray(a[:CROP_AT]).quantize(colors=48, method=Image.Quantize.FASTOCTREE)
    out.save(SRC, optimize=True)
    print("fixart: wedge %d px -> transparent, cropped to %dx%d, %d KB" % (n, w, CROP_AT, SRC.stat().st_size // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
