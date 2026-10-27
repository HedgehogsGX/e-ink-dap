#!/usr/bin/env python3
"""Writes the files JLCPCB needs to make and assemble the player board (stage 4) into
hardware/jlcpcb/, and checks whether the board is ready to order:

    python3 tools/make_jlc.py

Run tools/make_schematic.py and tools/make_pcb.py first.

- dap-gerbers.zip: Gerbers (4 copper layers, mask, paste, silkscreen, outline) and drill
  files. Named dap-gerbers-DRAFT.zip while anything below blocks ordering.
- dap-bom.csv: JLCPCB's BOM columns (Comment, Designator, Footprint, LCSC Part #).
- dap-cpl.csv: JLCPCB's placement columns (Designator, Mid X, Mid Y, Layer, Rotation).
- readiness.txt: what still blocks ordering, and the order settings.

Parts JLCPCB doesn't fit (NOT_ASSEMBLED) stay out of the BOM and placement files.
"""
import collections
import csv
import json
import os
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kicad_sch as K  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HW = os.path.join(ROOT, "hardware")
OUT = os.path.join(HW, "jlcpcb")
BOARD = os.path.join(HW, "dap.kicad_pcb")
SCH = os.path.join(HW, "dap.kicad_sch")
CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"

LAYERS = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu", "F.Paste", "B.Paste", "F.Silkscreen", "B.Silkscreen",
          "F.Mask", "B.Mask", "Edge.Cuts"]
NOT_ASSEMBLED = {"J1": "battery wires, soldered to the pads by hand",
                 "J7": "4.4 mm jack: not in JLCPCB's library, soldered by hand",
                 "TP1": "test pad", "TP2": "test pad", "NT1": "net tie: copper only"}
# Footprints that only stand in for the part that will be fitted
STANDIN = {"J3": "touch FPC: Hirose FH12 outline, the part is a Jushuo AFC07-S06FCA-00 (C262553)",
           "J5": "microSD: Hirose DM3D outline, the part is a TF-01A (C91145)"}
# Points from docs/pcb_plan.md still to check against the parts' datasheets
TO_CONFIRM = ["oscillators: OE high = running, output high-impedance when off (they share MCLK)",
              "GL823K: VDD and VDDA tied together as its internal 3.3 V (Genesys reference design)",
              "15 uF 0805 capacitors at the CS43131 FILT pins: pick a part, or use 22 uF",
              "jacks: the detect contact touches the tip when a plug is in"]
ORDER = ["4 layers, 1.2 mm thick, 60.8 x 105.8 mm (outline in the Gerbers)",
         "surface finish: ENIG (flat pads for the 0.4 mm-pitch QFNs)",
         "impedance control on, a JLCPCB 4-layer 1.2 mm stackup: USB pair 0.2 mm / 0.2 mm gap,"
         " about 90 ohm differential over layer 2 - check with JLCPCB's impedance calculator",
         "min track / space 0.1 / 0.1 mm; vias 0.5 / 0.3 mm; the ESP32 footprint's thermal vias are 0.2 mm",
         "vias tented (covered with solder mask)",
         "assembly: top side only (the battery pads on the back carry no part)"]


def run(*args):
    r = subprocess.run([CLI, *args], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"kicad-cli {' '.join(args[:3])} failed: {r.stderr or r.stdout}")
    return r


def parts():
    """Every symbol from the schematic's netlist: ref -> (value, footprint, LCSC number)."""
    with tempfile.TemporaryDirectory() as tmp:
        net = os.path.join(tmp, "dap.net")
        run("sch", "export", "netlist", "-o", net, SCH)
        tree = K.parse(open(net, encoding="utf-8").read())[0]
    out = {}
    for c in K.find(K.first(tree, "components"), "comp"):
        fields = {}
        for f in K.find(K.first(c, "fields") or [], "field"):
            if len(f) > 2:
                fields[str(K.first(f, "name")[1])] = str(f[2])
        fp = str(K.first(c, "footprint")[1]) if K.first(c, "footprint") else ""
        out[str(K.first(c, "ref")[1])] = (str(K.first(c, "value")[1]), fp, fields.get("LCSC", ""))
    return out


def drc():
    """(problems that matter, unrouted connections) from KiCad's DRC."""
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "drc.json")
        subprocess.run([CLI, "pcb", "drc", "--format", "json", "--severity-all", "-o", out, BOARD],
                       capture_output=True)
        report = json.load(open(out))
    problems = []
    for v in report.get("violations", []):
        descs = [i["description"] for i in v.get("items", [])]
        refs = {d.rsplit(" of ", 1)[-1].split()[0] for d in descs if " of " in d}
        inside_one_footprint = v["type"] == "hole_clearance" and len(refs) == 1 and all(" of " in d for d in descs)
        if v["type"].startswith("silk_") or inside_one_footprint or \
                v["type"] in ("lib_footprint_mismatch", "lib_footprint_issues"):
            continue
        problems.append(f"{v['type']}: {' / '.join(descs)}")
    return problems, len(report.get("unconnected_items", []))


def main():
    os.makedirs(OUT, exist_ok=True)
    symbols = parts()
    blockers = []

    problems, unrouted = drc()
    if unrouted:
        blockers.append(f"{unrouted} connections are not routed yet")
    blockers += [f"DRC: {p}" for p in problems[:20]]
    if len(problems) > 20:
        blockers.append(f"DRC: ... and {len(problems) - 20} more")
    for ref, (value, fp, lcsc) in sorted(symbols.items()):
        if "standin" in fp or ref in STANDIN:
            blockers.append(f"{ref} ({value}): stand-in footprint - {STANDIN.get(ref, fp)}")
    missing = sorted(r for r, (v, fp, lcsc) in symbols.items() if not lcsc and r not in NOT_ASSEMBLED)
    if missing:
        blockers.append(f"{len(missing)} parts have no LCSC part number (JLCPCB's BOM tool can match "
                        f"them by value and footprint, but check each): {', '.join(missing[:12])}"
                        + (" ..." if len(missing) > 12 else ""))
    ready = not blockers

    # Gerbers and drill files, zipped
    with tempfile.TemporaryDirectory() as tmp:
        run("pcb", "export", "gerbers", "-o", tmp, "-l", ",".join(LAYERS), "--subtract-soldermask",
            "--check-zones", BOARD)
        run("pcb", "export", "drill", "-o", tmp + os.sep, "--format", "excellon", "--excellon-units", "mm",
            "--excellon-zeros-format", "decimal", "--excellon-separate-th", BOARD)
        for old in os.listdir(OUT):
            if old.startswith("dap-gerbers"):
                os.remove(os.path.join(OUT, old))
        zip_path = os.path.join(OUT, "dap-gerbers.zip" if ready else "dap-gerbers-DRAFT.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for name in sorted(os.listdir(tmp)):
                z.write(os.path.join(tmp, name), name)
        files = sorted(os.listdir(tmp))

    # BOM, grouped by value, footprint and part number
    groups = collections.OrderedDict()
    for ref, (value, fp, lcsc) in sorted(symbols.items(), key=lambda kv: (kv[0].rstrip("0123456789"),
                                                                           int("0" + "".join(ch for ch in kv[0] if ch.isdigit())))):
        if ref in NOT_ASSEMBLED:
            continue
        groups.setdefault((value, fp.split(":")[-1], lcsc), []).append(ref)
    with open(os.path.join(OUT, "dap-bom.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for (value, fp, lcsc), refs in groups.items():
            w.writerow([value, ",".join(refs), fp, lcsc])

    # Placement: KiCad's position file in JLCPCB's columns
    with tempfile.TemporaryDirectory() as tmp:
        pos = os.path.join(tmp, "pos.csv")
        run("pcb", "export", "pos", "-o", pos, "--format", "csv", "--units", "mm", "--side", "both", BOARD)
        rows = list(csv.DictReader(open(pos)))
    with open(os.path.join(OUT, "dap-cpl.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for r in rows:
            if r["Ref"] in NOT_ASSEMBLED:
                continue
            w.writerow([r["Ref"], f"{float(r['PosX']):.4f}mm", f"{float(r['PosY']):.4f}mm",
                        "Top" if r["Side"].lower().startswith("top") else "Bottom", f"{float(r['Rot']):.1f}"])
    placed = sum(1 for r in rows if r["Ref"] not in NOT_ASSEMBLED)

    lines = [("READY TO ORDER" if ready else "NOT READY TO ORDER - the files are a draft"), ""]
    if blockers:
        lines += ["Blocks ordering:"] + [f"  - {b}" for b in blockers] + [""]
    lines += ["Still to confirm against the datasheets (docs/pcb_plan.md):"] + [f"  - {t}" for t in TO_CONFIRM]
    lines += ["", "Order settings:"] + [f"  - {o}" for o in ORDER]
    lines += ["", "Not assembled by JLCPCB:"] + [f"  - {r}: {why}" for r, why in NOT_ASSEMBLED.items()]
    lines += ["", f"Files: {os.path.basename(zip_path)} ({len(files)} files: {', '.join(files)}),",
              f"dap-bom.csv ({len(groups)} lines), dap-cpl.csv ({placed} parts).",
              "In JLCPCB's placement preview, check each part's rotation: some library parts are",
              "drawn turned 90 or 180 degrees from KiCad's footprints."]
    open(os.path.join(OUT, "readiness.txt"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
