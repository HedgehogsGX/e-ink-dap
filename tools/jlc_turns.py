#!/usr/bin/env python3
"""Works out how each assembled part's KiCad footprint is turned against JLCPCB's own
footprint for the same part, and writes tools/jlc_turns.json for tools/make_jlc.py. Run with
KiCad's own Python (it has pcbnew), after tools/make_schematic.py and tools/make_pcb.py:

    P=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3
    $P tools/jlc_turns.py            # the table; then: python3 tools/make_jlc.py
    $P tools/jlc_turns.py --check    # the placement file make_jlc.py wrote, against the board

JLCPCB places a part by its library footprint (the one EasyEDA shows for the LCSC number):
the rotation in the placement file turns that footprint, and the position is its origin, the
middle of its pads. KiCad's footprints are often drawn turned 90 or 180 degrees from
JLCPCB's, even between two parts in the same package (JLCPCB's two SOT-23-6 footprints
differ), so a table by package name isn't safe. For each LCSC number this fetches JLCPCB's
footprint from EasyEDA (https://easyeda.com, kept in tools/easyeda.nosync/), lays KiCad's
pads over it each way round and keeps the turn where pads with the same number meet (parts
numbered differently, like the side keys: where the pad patterns meet). Diodes and LEDs are
matched cathode to cathode, whichever pad JLCPCB numbers 1.

Each entry: turn (degrees counter-clockwise from KiCad's footprint to JLCPCB's), dx, dy
(JLCPCB's origin in KiCad's footprint frame, mm, y down), fit (mm left between the pads),
by (number or shape: what the pads were matched on) and JLCPCB's footprint name. EasyEDA refuses requests that come too fast: parts it refused keep
their old entry or stay out, and make_jlc.py lists those to check by eye.

--check puts JLCPCB's footprint on the board for every row of hardware/jlcpcb/dap-cpl.csv,
turned and placed as the row says, and measures how far each of its pads lands from the
board's pad of the same number: the whole chain (table, make_jlc.py, the file's signs)
checked against the copper.
"""
import csv
import json
import math
import os
import subprocess
import sys
import time

import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kicad_sch as K  # noqa: E402
import make_jlc as J  # noqa: E402

CACHE = os.path.join(J.ROOT, "tools", "easyeda.nosync")
OUT = os.path.join(J.ROOT, "tools", "jlc_turns.json")
API = "https://easyeda.com/api/products/{}/components?version=6.4.19.5"
ANODE = {"A", "+", "ANODE"}
POLAR = ("D_", "LED_")     # KiCad footprints whose pad 1 is the cathode
refusing = []              # set once EasyEDA refuses a request: no more are sent in this run


def jlc_pads(lcsc, footprint):
    """(JLCPCB's footprint name, [(pad number, x, y)]) for an LCSC number: mm from the
    footprint's origin, y down, numbered as KiCad's footprint (name) is; None if EasyEDA
    didn't answer."""
    path = os.path.join(CACHE, lcsc + ".json")
    if not os.path.exists(path):
        if refusing:
            return None
        subprocess.run(["curl", "-s", "-m", "30", "-o", path, API.format(lcsc)])
        time.sleep(4)
        if not os.path.exists(path) or os.path.getsize(path) < 2000:   # an error page, not the part
            refusing.append(lcsc)
            if os.path.exists(path):
                os.remove(path)
            return None
    try:
        part = json.load(open(path))["result"]
        data = part["packageDetail"]["dataStr"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    ox, oy = float(data["head"]["x"]), float(data["head"]["y"])
    pads = [(f[8], (float(f[2]) - ox) * 0.254, (float(f[3]) - oy) * 0.254)
            for f in (s.split("~") for s in data["shape"]) if f[0] == "PAD" and f[8]]
    pins = {}       # the symbol's pin names, by number
    for s in part["dataStr"]["shape"]:
        seg = s.split("^^")
        if s.startswith("P~") and len(seg) > 4:
            pins[seg[4].split("~")[4]] = seg[3].split("~")[4]
    if footprint.startswith(POLAR) and pins.get("1", "").upper() in ANODE:   # theirs counts from the anode
        pads = [({"1": "2", "2": "1"}.get(n, n), x, y) for n, x, y in pads]
    return part["packageDetail"]["title"], pads


def kicad_pads(footprint):
    lib, name = footprint.split(":")
    fp = pcbnew.FootprintLoad(os.path.join(J.HW, "dap.pretty") if lib == "dap" else
                              os.path.join(K.KICAD_FOOTPRINTS, lib + ".pretty"), name)
    return [(p.GetNumber(), pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y)) for p in fp.Pads()
            if p.GetNumber() and p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH]


def turned(x, y, deg):
    """Counter-clockwise as seen on the board; y points down."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return x * c + y * s, -x * s + y * c


def middle(pts):
    return tuple((min(p[i] for p in pts) + max(p[i] for p in pts)) / 2 for i in (0, 1))


def by_number(pads):
    spots = {}
    for n, x, y in pads:
        spots.setdefault(n, []).append((x, y))
    return {n: (sum(p[0] for p in v) / len(v), sum(p[1] for p in v) / len(v)) for n, v in spots.items()}


def apart(ours, theirs):
    """How far our pads are from theirs, mm: (mean over the pad numbers both have, or None;
    mean distance from each of ours to the nearest of theirs)."""
    a, b = by_number(ours), by_number(theirs)
    same = set(a) & set(b)
    numbered = sum(math.hypot(a[n][0] - b[n][0], a[n][1] - b[n][1]) for n in same) / len(same) if same else None
    shape = sum(min(math.hypot(x - u, y - v) for _, u, v in theirs) for _, x, y in ours) / len(ours)
    return numbered, shape


def fit(ours, theirs):
    """Best turn of KiCad's pads onto JLCPCB's: (turn, dx, dy, mm left between the pads,
    "number" or "shape": what they were matched on)."""
    tries = []
    for deg in (0, 90, 180, 270):
        mine = [(n,) + turned(x, y, deg) for n, x, y in ours]
        a, b = by_number(mine), by_number(theirs)
        same = sorted(set(a) & set(b))
        m, e = middle([p[1:] for p in mine]), middle([p[1:] for p in theirs])
        by_shape = (e[0] - m[0], e[1] - m[1])        # shift that lays the pad patterns over each other
        shift = (sum(b[n][0] - a[n][0] for n in same) / len(same),
                 sum(b[n][1] - a[n][1] for n in same) / len(same)) if same else by_shape   # or equal numbers
        numbered = apart([(n, x + shift[0], y + shift[1]) for n, x, y in mine], theirs)[0]
        shape = apart([(n, x + by_shape[0], y + by_shape[1]) for n, x, y in mine], theirs)[1]
        tries.append((deg, numbered, shape, shift, by_shape))
    with_numbers = [t for t in tries if t[1] is not None and t[1] < 0.3]
    if with_numbers:
        (deg, left, _, shift, _), by = min(with_numbers, key=lambda t: t[1]), "number"
    else:       # numbered differently (the side keys): the pad patterns decide
        (deg, _, left, _, shift), by = min(tries, key=lambda t: t[2]), "shape"
    dx, dy = turned(-shift[0], -shift[1], -deg)      # JLCPCB's origin in KiCad's footprint frame
    return deg, round(dx, 3), round(dy, 3), round(left, 3), by


def assembled():
    """{(LCSC number, footprint): [references]} of the parts JLCPCB fits."""
    seen = {}
    for ref, (value, footprint, lcsc) in sorted(J.parts().items()):
        if lcsc and ref not in J.NOT_ASSEMBLED:
            seen.setdefault((lcsc, footprint), []).append(ref)
    return seen


def main():
    os.makedirs(CACHE, exist_ok=True)
    table = json.load(open(OUT)) if os.path.exists(OUT) else {}
    seen, refused = assembled(), []
    for (lcsc, footprint), refs in sorted(seen.items()):
        name = footprint.split(":")[1]
        theirs = jlc_pads(lcsc, name)
        if theirs is None:
            refused.append(f"{lcsc} ({', '.join(refs[:4])})")
            continue
        deg, dx, dy, left, by = fit(kicad_pads(footprint), theirs[1])
        table[lcsc] = dict(footprint=name, jlc=theirs[0], turn=deg, dx=dx, dy=dy, fit=left, by=by)
        note = "" if left < 0.3 else "   <-- pads don't meet: check this one by eye"
        print(f"{lcsc:10} {refs[0]:5} {name[:38]:38} turn {deg:3}  shift {dx:+.2f} {dy:+.2f}  "
              f"fit {left:.2f}  {theirs[0]}{note}")
    table = {k: v for k, v in sorted(table.items()) if any(k == lcsc for lcsc, _ in seen)}
    with open(OUT, "w") as f:
        json.dump(table, f, indent=1)
        f.write("\n")
    print(f"{len(table)} of {len({l for l, _ in seen})} part numbers in {os.path.relpath(OUT, J.ROOT)}")
    if refused:
        print("EasyEDA didn't answer for (run again later): " + ", ".join(refused))


def check(limit=0.25):
    """JLCPCB's footprint, turned and placed as each row of the placement file says, against
    the board's own pads. Prints the parts whose pads land more than limit mm off."""
    board = pcbnew.LoadBoard(J.BOARD)
    on_board = {fp.GetReference(): [(p.GetNumber(), pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y))
                                    for p in fp.Pads() if p.GetNumber() and p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH]
                for fp in board.GetFootprints()}
    parts, worst, bad, skipped = J.parts(), 0.0, [], []
    table = json.load(open(OUT)) if os.path.exists(OUT) else {}
    rows = list(csv.DictReader(open(os.path.join(J.OUT, "dap-cpl.csv"))))
    for r in rows:
        ref = r["Designator"]
        value, footprint, lcsc = parts[ref]
        theirs = jlc_pads(lcsc, footprint.split(":")[1]) if os.path.exists(os.path.join(CACHE, lcsc + ".json")) else None
        if theirs is None:
            skipped.append(ref)
            continue
        x, y, rot = float(r["Mid X"][:-2]), -float(r["Mid Y"][:-2]), float(r["Rotation"])   # the file's y points up
        placed = [(n, x + u, y + v) for n, (u, v) in ((n, turned(u, v, rot)) for n, u, v in theirs[1])]
        numbered, shape = apart(on_board[ref], placed)
        off = shape if numbered is None or table.get(lcsc, {}).get("by") == "shape" else numbered
        worst = max(worst, off)
        if off > limit:
            bad.append(f"{ref} ({value}): pads {off:.2f} mm off")
    print(f"check: {len(rows) - len(skipped)} of {len(rows)} placed parts compared with JLCPCB's footprints on the "
          f"board; pads at most {worst:.2f} mm from the board's; {len(bad)} parts over {limit} mm")
    for b in bad:
        print("    " + b)
    if skipped:
        print("    not compared (no footprint fetched): " + ", ".join(skipped))
    return not bad


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(0 if check() else 1)
    main()
