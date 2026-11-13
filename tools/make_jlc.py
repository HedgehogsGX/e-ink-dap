#!/usr/bin/env python3
"""Writes the files JLCPCB needs to make and assemble the player board (stage 4) into
hardware/jlcpcb/, and checks whether the board is ready to order:

    python3 tools/make_jlc.py

Run tools/make_schematic.py and tools/make_pcb.py first.

- dap-gerbers.zip: Gerbers (6 copper layers, mask, paste, silkscreen, outline) and drill
  files. Named dap-gerbers-DRAFT.zip while anything below blocks ordering.
- dap-bom.csv: JLCPCB's BOM columns (Comment, Designator, Footprint, LCSC Part #).
- dap-cpl.csv: JLCPCB's placement columns (Designator, Mid X, Mid Y, Layer, Rotation). Each
  part's rotation and position are given for JLCPCB's own footprint, which is often drawn
  turned from KiCad's: the turns come from tools/jlc_turns.json, made by tools/jlc_turns.py.
- dap-bom-cn.csv, dap-cpl-cn.csv: the same for 嘉立创 (jlc-smt.com, JLC's site in China),
  after its BOM rules: plain package names (0402, 0603 ...) and the part number as 商品编号;
  the placement file also names each part. UTF-8 with a byte-order mark, for Excel.
- readiness.txt: what still blocks ordering, and the order settings for both sites.

Parts JLCPCB doesn't fit (NOT_ASSEMBLED) stay out of the BOM and placement files.
"""
import collections
import csv
import json
import math
import os
import re
import shutil
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

LAYERS = ["F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "B.Cu", "F.Paste", "B.Paste", "F.Silkscreen",
          "B.Silkscreen", "F.Mask", "B.Mask", "Edge.Cuts"]
NOT_ASSEMBLED = {"J1": "battery wires, soldered to the pads on the back by hand",
                 "J6": "3.5 mm jack PJ-342 (C668606), on the back: soldered by hand (only the top side is "
                       "assembled, and JLCPCB lists this jack as hand-soldered anyway)",
                 "J7": "4.4 mm jack Kinghelm KH-PJ-44002-12DBAP-A (C42396781), on the back: bought separately, "
                       "soldered by hand",
                 "TP1": "test pad", "TP2": "test pad", "NT1": "net tie: copper only",
                 "JP1": "reset pads on the back: bare copper, bridged with tweezers to restart the ESP32"}
TURNS = os.path.join(ROOT, "tools", "jlc_turns.json")   # KiCad's footprints against JLCPCB's, by LCSC number
# Footprints that only stand in for the part that will be fitted (none left)
STANDIN = {}
# Points to check before ordering or when the boards arrive (docs/pcb_plan.md)
TO_CONFIRM = ["stock: JLCPCB had no CS43131-CNZR (C965907) on 2026-10-31 - pre-order 4 into your JLCPCB parts "
              "inventory before the order",
              "touch ribbon: with the display facing up, its gold contacts must face up as well (like the "
              "e-paper ribbon's), so they face the bottom-contact connector once folded under the panel",
              "plug detect: the 3.5 mm jack's switch opens when a plug goes in, the 4.4 mm jack's is "
              "unknown - the firmware sets HPDETECT_INV for each after a try",
              "charge timer (owner's decision, docs/pcb_plan.md, Power tree): R3 = 68 k stops a charge after "
              "6.8 to 11.3 h depending on the chip, and the 5000 mAh cell needs about 7.5 to 8.5 h at 0.8 A - "
              "leave it (re-plug if the LED blinks), charge at about 1 A, or tie TMR to ground",
              "jacks: lay the Kinghelm 4.4 mm jack and a PJ-342 on a 1:1 print of the board before ordering "
              "if you can - their footprints come from the drawings, not from parts in hand"]
ORDER = ["6 layers, 1.2 mm thick, 60.8 x 111.8 mm (outline in the Gerbers); layer order top, ground, signal, "
         "signal, ground, bottom (the Gerbers' file names: F_Cu, In1_Cu ... In4_Cu, B_Cu)",
         "surface finish: ENIG (flat pads for the 0.4 mm-pitch QFNs)",
         "stackup JLC06121H-3313 (free; 1.14 mm finished): the USB pairs, 0.2 mm tracks 0.2 mm apart on the"
         " top and bottom layers, are about 90 ohm differential over the ground planes 0.0994 mm away"
         " (layers 2 and 5); no impedance tolerance needed",
         "min track / space 0.1 / 0.1 mm; vias 0.5 / 0.3 mm; no hole under 0.3 mm (smaller ones cost extra)",
         "plated slots 0.55 mm wide for the 4.4 mm jack, and one cut-out through the board under it",
         "vias filled and capped (free on 6 layers; the chips' centre pads have thermal vias)",
         "quantity 5 boards, 2 assembled, top side only. 嘉立创 puts the ESP32 module on its standard line,"
         " which takes boards of 70 x 70 mm or more: 5 mm rails on the long edges, held by mouse-bite tabs, not"
         " V-cut (the ESP32 is flush with the left edge, the side keys 0.3 mm from both long edges)"]
# 嘉立创's panel request (其他要求), as sent on 2026-10-31: rails on the long edges only, held by tabs
# that keep clear of the side keys and the ESP32 module
PANEL_NOTE = ("不要V割，只用邮票孔：板边有贴片元件。1. 工艺边只加在两条长边（111.8mm）外，工艺边与板边之间铣出2mm槽；"
              "邮票孔不要伸入板内，板子外形保持60.8×111.8mm。2. 邮票孔避开以下范围（从顶层看，从有耳机座缺口的短边量起）："
              "左长边20–28mm、32–40mm、54–74mm；右长边22–30mm、37–45mm（侧按键SW1–SW4离板边0.3mm，"
              "ESP32模块天线端与板边齐平）。各层铜皮离板边0.35mm。3. MARK点和定位孔加在工艺边上。")
# The same order on 嘉立创 (jlc-smt.com), whose forms are in Chinese: (step, [(field, choice)]), in the
# form's order. Filled in on 2026-10-31, not submitted yet.
ORDER_CN = [
    ("PCB下单 - board order (member.jlc.com, after logging in)", [
        ("上传文件 upload", "dap-gerbers.zip"),
        ("板子层数 layers", "6"), ("板子数量 quantity", "5"),
        ("确认生产稿 confirm production files", "需要（确认2次，收费3元）: you see their files before they start"),
        ("出货方式 shipped as", "单片 at first; after the rails (SMT贴片 below) it reads 拼板 / 嘉立创帮拼, "
                               "7.08 x 11.18 cm"), ("成品板厚 thickness", "1.2"),
        ("板材选项 laminate", "不指定 TG135 (the default; the 0.2 mm hole option switches it to TG155)"),
        ("外层铜厚 / 内层铜厚 copper outer / inner", "1oz / 0.5oz"),
        ("层压顺序 layer order", "指定层压顺序: L1 dap-F_Cu.gtl, L2 dap-In1_Cu.g1, L3 dap-In2_Cu.g2, "
                               "L4 dap-In3_Cu.g3, L5 dap-In4_Cu.g4, L6 dap-B_Cu.gbl"),
        ("需要阻抗 stackup", "JLC06121H-3313 (免费), and 接受差异 for its 1.14 mm: the USB pairs are drawn for "
                           "its 0.0994 mm outer prepreg"), ("阻抗管控 impedance tolerance", "无要求 (none)"),
        ("嘉立创盘中孔 / 阻焊覆盖 vias", "需要 / 过孔塞树脂+过孔电镀盖帽 (filled and capped, the default)"),
        ("焊盘喷镀 surface finish", "沉金 (ENIG), 1u\""), ("最小孔径/外径 smallest hole", "0.3mm (免费)"),
        ("四线低阻过孔 four-wire via test", "无要求 (the 0.2 mm hole option switches it on)"),
        ("交期 lead time", "7-8天"),
        ("SMT贴片 assembly", "需要. It answers that boards under 7 x 7 cm need rails: 加工艺边，补足7*7cm, then "
                            "非常规人工拼板 (¥30): 没有示意图, 我有要求，需要邮票孔拼板, 每大片拼的小片数量 有要求 "
                            "横向1 竖向1, 需要工艺边 5 mm, 阴阳拼板 不需要, 其他要求: the note below"),
        ("其他要求 panel note", PANEL_NOTE),
        ("是否开钢网 stencil", "不需要 (set by itself: the assembly order makes its own)"),
        ("确认订单方式 order confirmation", "手动确认订单: nothing is charged before you approve the final price"),
        ("发货方式 / 快递 shipping", "不同交期订单一起发货; any free courier (优速快递 is the default)"),
        ("收货地址 / 联系方式 address and contact", "your 集运 warehouse in China"),
        ("总价 price (2026-10-31)", "¥378.22: 工程费 200, 喷镀 105.54, 拼板 30, 板费 29.68, 品质赔付 10, 确认生产稿 3; "
                                   "shipping free")]),
    ("SMT下单 - assembly order (jlc-smt.com, SMT在线下单, once the board order has passed review)", [
        ("选择未发货PCB", "the board order above"),
        ("BOM与坐标清单 -> 上传BOM和坐标", "dap-bom-cn.csv and dap-cpl-cn.csv"),
        ("元器件备货方式 how parts are supplied", "嘉立创代采代购 (JLC buys every part, CS43131 included)"),
        ("贴片数量 boards assembled", "2"), ("焊接层 sides", "只贴顶层 (top side only)"),
        ("产品类型 type", "标准型 (standard): ESP32 modules don't go on the economic line (255 °C reflow), and with "
                         "about 25 extended part types it is cheaper anyway (¥8 a type, economic ¥20); it needs "
                         "the rails above"),
        ("匹配选型方式 part matching", "自助匹配选型, free (their matching service is ¥50): every line has its "
                                    "商品编号, check each one matched it, and that C965907, the CS43131, is bought "
                                    "for you"),
        ("分板出货 snapping off the rails", "optional: ¥10 + ¥2 a board"),
        ("price, estimated 2026-10-31", "assembly about ¥420 (¥150 setup, ¥50 stencil, about 25 x ¥8, 1,304 joints "
                                        "x ¥0.01), parts about ¥470: with the boards about ¥1,280 in all")])]


def package(footprint):
    """嘉立创's BOM wants plain package names: R_0402_1005Metric -> 0402; other footprints as they are."""
    m = re.match(r"(?:R|C|L|LED|D)_(\d{4})_", footprint)
    return m.group(1) if m else footprint


def for_jlc(row, turn):
    """A row of KiCad's position file as JLCPCB wants it: (x, y, rotation) of its own footprint,
    whose origin is the middle of its pads and which may be drawn turned from KiCad's (turn:
    an entry of tools/jlc_turns.json, or None to leave the row as KiCad gives it)."""
    x, y, rot = float(row["PosX"]), float(row["PosY"]), float(row["Rot"])
    if turn:
        c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        x += turn["dx"] * c + turn["dy"] * s     # the position file's y points up, the footprint's down
        y += turn["dx"] * s - turn["dy"] * c
        rot -= turn["turn"]
    rot = round((rot + 180) % 360 - 180, 1)
    return f"{x:.4f}mm", f"{y:.4f}mm", f"{180.0 if rot == -180 else rot + 0.0:.1f}"


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
            if old.startswith("dap-gerbers"):   # earlier zips, and folders they were unpacked into
                path = os.path.join(OUT, old)
                shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
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
    rows = [r for r in rows if r["Ref"] not in NOT_ASSEMBLED]
    turns = json.load(open(TURNS)) if os.path.exists(TURNS) else {}
    turned, unchecked = [], []
    for r in rows:
        value, fp, lcsc = symbols[r["Ref"]]
        turn = turns.get(lcsc)
        if turn and turn["footprint"] != fp.split(":")[-1]:
            turn = None     # the part's footprint changed since tools/jlc_turns.py last ran
        r["jlc"] = for_jlc(r, turn)
        if turn and turn["turn"]:
            turned.append(r["Ref"])
        if not turn and not re.match(r"(R|C|L|FB)\d", r["Ref"]):   # those look the same either way round
            unchecked.append(r["Ref"])
    with open(os.path.join(OUT, "dap-cpl.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for r in rows:
            w.writerow([r["Ref"], r["jlc"][0], r["jlc"][1],
                        "Top" if r["Side"].lower().startswith("top") else "Bottom", r["jlc"][2]])
    placed = len(rows)

    # The same two files for 嘉立创, after its BOM rules
    with open(os.path.join(OUT, "dap-bom-cn.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "商品编号"])
        for (value, fp, lcsc), refs in groups.items():
            w.writerow([value, ",".join(refs), package(fp), lcsc])
    with open(os.path.join(OUT, "dap-cpl-cn.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Comment", "Footprint", "Mid X", "Mid Y", "Layer", "Rotation"])
        for r in rows:
            value, fp, _ = symbols[r["Ref"]]
            w.writerow([r["Ref"], value, package(fp.split(":")[-1]), r["jlc"][0], r["jlc"][1],
                        "Top" if r["Side"].lower().startswith("top") else "Bottom", r["jlc"][2]])

    lines = [("READY TO ORDER" if ready else "NOT READY TO ORDER - the files are a draft"), ""]
    if blockers:
        lines += ["Blocks ordering:"] + [f"  - {b}" for b in blockers] + [""]
    lines += ["Check before ordering, or when the boards arrive (docs/pcb_plan.md):"] + [f"  - {t}" for t in TO_CONFIRM]
    if unchecked:
        lines.append(f"  - rotation: {', '.join(unchecked)} could not be compared with JLCPCB's own footprints "
                     "(tools/jlc_turns.py: EasyEDA didn't answer) and keep KiCad's rotation - run it again, or "
                     "check pin 1 of each in the placement preview")
    lines += ["", "Order settings (jlcpcb.com):"] + [f"  - {o}" for o in ORDER]
    lines += ["", "Ordering on 嘉立创 (jlc-smt.com) instead, its forms in Chinese:"]
    for step, fields in ORDER_CN:
        lines += [f"  {step}:"] + [f"    - {k}: {v}" for k, v in fields]
    lines += ["", "Not assembled by JLCPCB:"] + [f"  - {r}: {why}" for r, why in NOT_ASSEMBLED.items()]
    lines += ["", f"Files: {os.path.basename(zip_path)} ({len(files)} files: {', '.join(files)}),",
              f"dap-bom.csv and dap-bom-cn.csv ({len(groups)} lines), dap-cpl.csv and dap-cpl-cn.csv ({placed} parts).",
              f"Rotations and positions are for JLCPCB's own footprints (tools/jlc_turns.json): {len(turned)} parts",
              f"are turned from KiCad's ({', '.join(turned)}). Still look at pin 1 of every chip in",
              "JLCPCB's placement preview before approving it."]
    open(os.path.join(OUT, "readiness.txt"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
