#!/usr/bin/env python3
"""Places the player board's parts (Phase 2, stage 3 draft) on a board shaped like the
case's PCB, then renders it in 3D. Run with KiCad's own Python, which has pcbnew:

    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 tools/make_pcb.py

Run tools/make_schematic.py first: parts, footprints and nets come from the schematic's
netlist. Pass --no-render to skip the pictures.

- hardware/dap.kicad_pcb: 4 layers, 1.2 mm thick, outline and notches from tools/make_case.py,
  every part placed and routed as far as the routers get (see Routing)
- hardware/dap.pretty: stand-in footprints KiCad doesn't have (the two jacks, battery pads)
- hardware/3d: simple 3D models for those, and for parts whose models KiCad doesn't ship
- hardware/renders/pcb_*.png: top, bottom and angled views (kicad-cli pcb render)
- case/pcb.glb: the board as a 3D model, which tools/make_case.py puts into the case

Placement: connectors, keys and ICs sit where PLACE puts them, in the case's frame (mm,
origin at the board's centre, +y towards the top edge, seen from the screen side). The
small parts of each schematic group are then packed around them, each as close as it can
get to the pins it shares a net with, inside the group's area in AREA.

Routing: tools/pcb_router.py gives every ground pad a via to the ground planes on layers 2
and 3, then routes the short local nets, ROUTES and POWER_ROUTES in order on the top and
bottom layers, with rip-up and reroute. Everything still unrouted goes to Freerouting
(FREEROUTING, a Java program downloaded separately; skipped if it isn't there) with the
tracks so far locked; tidy() then cleans up after it. Last, the bottom layer's free area is
filled with 3.3 V. A full run takes about 50 minutes, most of it Freerouting.
"""
import json
import math
import os
import subprocess
import sys
import tempfile

import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kicad_sch as K  # noqa: E402
import make_schematic as M  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HW = os.path.join(ROOT, "hardware")
BOARD_FILE = os.path.join(HW, "dap.kicad_pcb")
FP_LIB = os.path.join(HW, "dap.pretty")
MODELS_3D = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/3dmodels"
RENDER = "--no-render" not in sys.argv

# ---- Board shape and heights, from tools/make_case.py (keep in step with it)
W, L, WALL, GAP, R_INNER = 65.0, 110.0, 1.8, 0.3, 1.5
BACK, BATT_T, BATT_SWELL, PCB_T, PARTS_H = 1.4, 6.0, 0.4, 1.2, 3.3
AA_L, AA_TOP, PANEL_L = 81.54, 2.98, 92.99
JACK35 = (6.0, 5.0, 12.0, 5.0)        # body width, height, depth, nose diameter (estimates)
JACK44 = (10.0, 9.0, 14.0, 7.5)
X_35, X_USB, X_44 = -15.0, 0.0, 15.0
BOSS_R = 2.75
SD_X = 16.0
KEYS = {"SW3": (-1, 32.0), "SW4": (-1, 20.0), "SW2": (1, 30.0), "SW1": (1, 15.0)}  # Vol+, Vol-, Power, Play
FLANGE_T = 0.8

IX, IY = W / 2 - WALL, L / 2 - WALL   # inside of the walls
HX, HY = IX - GAP, IY - GAP           # board half-size: 60.8 x 105.8 mm
R_CORNER = R_INNER - GAP
BOSS_X, BOSS_Y = IX - BOSS_R - GAP, IY - BOSS_R - GAP
Z_PARTS = BACK + 0.2 + BATT_T + BATT_SWELL + PCB_T   # board's top face
Z_PORT = (Z_PARTS + PARTS_H + 1.48 + 1.2) / 2         # jacks and USB-C on the case's centre line
PORT_DROP = Z_PARTS - Z_PORT                          # port centre below the board's top face
PANEL_BOTTOM = AA_L / 2 + AA_TOP - PANEL_L
NOTCHES = [(x - w / 2 - 0.2, x + w / 2 + 0.2, IY - d - 0.2) for x, (w, h, d, n) in
           ((X_35, JACK35), (X_44, JACK44))]          # (x0, x1, bottom); open to the top edge
BOSS_NOTCH = (BOSS_X - BOSS_R - 0.3, BOSS_Y - BOSS_R - 0.3)   # corner cut-outs: |x| >= , y >=

OX, OY = 148.5, 105.0                 # board centre on the A4 sheet

# ---- Where things go. (x, y, rotation in degrees counter-clockwise, side)
KEY_X = IX - FLANGE_T - 0.05 - 2.04   # plunger tip at the key; 2.04 = tip to switch origin
PLACE = {
    "J6": (X_35, HY, 0), "J7": (X_44, HY, 0),          # jacks in their notches, from the case
    "J4": (X_USB, IY - 3.65, 180),                     # USB-C front 0.3 mm past the board edge
    "J1": (-8.5, 44.5, 0, "B"),                        # battery wires, back side, over the battery's end
    "J2": (-2.0, PANEL_BOTTOM + 0.5 + 3.65, 0),        # e-paper FPC: mouth just inside the panel's edge
    "J3": (-17.0, PANEL_BOTTOM + 0.5 + 4.4, 0),        # touch FPC
    "J5": (SD_X, -HY + 6.68, 0),                       # microSD, card slot at the bottom edge
    "U17": (-14.0, 30.5, 180), "U18": (14.0, 30.5, 180),   # CS43131 L / R, outputs facing the jacks
    "Y1": (-2.5, 29.0, 0), "Y2": (2.5, 29.0, 0), "U16": (0.0, 24.5, 0),
    "U3": (2.0, 17.0, 0), "U4": (8.0, 17.0, 0), "U5": (14.0, 17.0, 0),
    "U14": (-17.0, 14.0, 0), "U15": (-9.0, 14.0, 0),
    "U8": (-HX + 12.75, -8.0, 90),                     # ESP32 module, antenna at the left edge;
                                                       # its keep-out strip ends below the Vol- key
    "U1": (14.0, 4.0, 0), "U2": (14.0, -7.0, 0), "U6": (11.0, -17.0, 0), "U7": (20.0, -17.0, 0),
    "U11": (0.0, -17.0, 0),
    "U12": (10.0, -31.0, 0), "U13": (20.0, -31.0, 0),
}
for ref, (side, y) in KEYS.items():
    PLACE[ref] = (side * KEY_X, y, 90 * side)

# Area each schematic group's small parts are packed into (x0, y0, x1, y1), by the group's
# first part; groups not listed pack within 12 mm of their pins. Packed in this order.
AREA = [
    ("J6", (-11.3, 38.0, -6.6, 44.0)),                 # net tie by the jacks
    ("SW1", None),                                     # key pull-ups, each beside its key
    ("U17", (-25.4, 21.0, -5.2, 40.5)),
    ("U18", (5.2, 21.0, 25.4, 38.5)),
    ("Y1", (-5.2, 21.0, 5.2, 36.0)),
    ("J4", (-7.0, 34.0, 8.0, 44.2)),
    ("U3", (-3.0, 10.5, 25.4, 21.0)),
    ("U14", (-25.4, 7.0, -3.0, 21.0)),
    ("U8", (-4.6, -13.0, 4.6, 7.5)),
    ("R8", (-4.6, -13.0, 4.6, 7.5)),
    ("R16", (-4.6, -13.0, 4.6, 7.5)),
    ("U1", (5.0, -1.5, 27.0, 11.5)),
    ("U2", (5.0, -12.5, 27.0, -1.5)),
    ("U6", (5.0, -24.0, 27.0, -12.5)),
    ("U11", (-4.6, -21.0, 4.6, -13.0)),
    ("J3", (-26.0, -41.3, -10.0, -35.0)),
    ("J2", (-26.0, -42.3, 4.5, -21.0)),
    ("U12", (4.5, -39.8, 27.0, -23.0)),
    ("U13", (4.5, -39.8, 27.0, -23.0)),
    ("J5", (4.5, -39.8, 27.0, -23.0)),
]
TARGETS = {"R8": ["U8"], "R16": ["U8"]}   # groups with no IC of their own sit by the ESP32
# Strips beside a chip kept free of small parts, where its routed pins leave: (x0, y0, x1, y1)
# from the chip's centre. CS43131 (turned 180 degrees): headphone pins on top, I2S and clock
# below. Its sides are left to the charge-pump and filter capacitors.
DAC_TOP, DAC_BOTTOM = (-0.85, 2.9, 1.4, 6.0), (-1.0, -6.0, 2.4, -2.9)
KEEP_CLEAR = {ref: [DAC_TOP, DAC_BOTTOM] for ref in ("U17", "U18")}
KEEP_CLEAR["J2"] = [(-2.2, 2.6, 1.2, 7.0)]   # e-paper FPC: in front of its signal pins 9-14, towards the ESP32
STEP = 0.25
FANOUT = 0.8   # small parts keep this far beyond the outline of a chip with 0.5 mm pitch or finer

# ---- Routing, in this order: (nets, settings). USB first, since its socket pins leave no
# room to spare. Widths in mm; full_width = widened where there is room. A USB pair: the +
# track keeps a 1 mm corridor free, the - track runs beside it 0.4 mm apart (0.2 mm tracks,
# 0.2 mm gap: about 90 ohm over the ground plane).
ROUTES = [
    (["USB_DP"], dict(order=["J4:A6"], width=0.2, corridor=1.0)),
    (["USB_DM"], dict(order=["J4:A7"], width=0.2, partner="USB_DP", pair_pitch=0.4)),
    (["USB_CC1", "USB_CC2"], {}),
    (["GL_DP"], dict(width=0.2, corridor=1.0)),
    (["GL_DM"], dict(width=0.2, partner="GL_DP", pair_pitch=0.4)),
    (["ESP_USB_DP"], dict(width=0.2, corridor=1.0)),
    (["ESP_USB_DM"], dict(width=0.2, partner="ESP_USB_DP", pair_pitch=0.4)),
    (["MCLK_441", "MCLK_48", "MCLK"], dict(clearance=0.2)),
    (["OUT_LP"], dict(order=["U17:14"], full_width=0.3, clearance=0.15)),
    (["OUT_RP"], dict(order=["U18:14"], full_width=0.3, clearance=0.15)),
    (["OUT_LN"], dict(order=["U17:16"], full_width=0.3, clearance=0.15)),
    (["OUT_RN"], dict(order=["U18:16"], full_width=0.3, clearance=0.15)),
    (["HP_GND"], dict(order=["NT1:1"], full_width=0.5)),
    (["DET_35", "DET_44"], {}),
    (["SCLK_1V8", "LRCK_1V8", "SDIN_1V8", "I2C_SCL_1V8", "I2C_SDA_1V8", "OSC_SEL_1V8", "OSC_SEL_N"], {}),
    (["I2S_SCLK", "I2S_LRCK", "I2S_SDOUT", "OSC_SEL"], {}),
]
# Power, after the signals: switching nodes first (short, tight loops), then each rail from
# its source. Widths: start, widened where there is room, narrowest allowed in a squeeze.
POWER_ROUTES = [
    (["BB_L1", "BB_L2"], dict(order=["U2"], width=0.4, full_width=0.6, min_width=0.25)),
    (["BST_SW"], dict(order=["U6"], width=0.4, full_width=0.6, min_width=0.25)),
    (["EPD_SW"], dict(order=["L3"], width=0.3, full_width=0.5, min_width=0.2)),
    (["VBAT"], dict(order=["J1"], width=0.4, full_width=0.8, min_width=0.25)),
    (["SYS"], dict(order=["U1"], width=0.4, full_width=0.8, min_width=0.2)),
    (["VBUS"], dict(order=["J4"], width=0.4, full_width=0.8, min_width=0.2)),
    (["5V_BOOST"], dict(order=["U6"], width=0.4, full_width=0.6, min_width=0.2)),
    (["+3V3"], dict(order=["U2"], width=0.3, full_width=0.5, min_width=0.15)),
    (["VP"], dict(order=["FB1"], width=0.3, full_width=0.5, min_width=0.15)),
    (["1V8_A"], dict(order=["U3"], width=0.25, full_width=0.4, min_width=0.15)),
    (["1V8_CP"], dict(order=["U4"], width=0.25, full_width=0.4, min_width=0.15)),
    (["1V8_D"], dict(order=["U5"], width=0.25, full_width=0.4, min_width=0.15)),
    (["GL_3V3"], dict(order=["U12"], width=0.25, full_width=0.4, min_width=0.15)),
]
# Every other net is routed too: those whose pins lie within LOCAL mm of each other first of
# all (a chip and its capacitors: the shortest loops matter most and block little), the
# longer ones after power.
LOCAL = 8.0
# The other nets (the longer control and data lines) are routed by Freerouting, after ours
FREEROUTING = os.path.join(ROOT, "tools", "freerouting.nosync", "freerouting-2.5.0.jar")
FREEROUTING_PASSES = 30
# Copper fills: ground on both inner layers, and 3.3 V over the free area of the bottom layer
ZONES = [(pcbnew.In1_Cu, "GND"), (pcbnew.In2_Cu, "GND"), (pcbnew.B_Cu, "+3V3")]
USB_C_BRIDGE = ("USB_DM", ["J4:B7", "J4:A7"])   # the socket's two D- pins straddle a D+ pin
# The same strips are channels while routing: only these nets may use them
DAC_BUS = ["SCLK_1V8", "LRCK_1V8", "SDIN_1V8", "MCLK", "I2C_SCL_1V8", "I2C_SDA_1V8"]
CHANNELS = [("U17", DAC_TOP, ["OUT_LP", "OUT_LN", "HP_GND"]), ("U18", DAC_TOP, ["OUT_RP", "OUT_RN", "HP_GND"]),
            ("U17", DAC_BOTTOM, DAC_BUS), ("U18", DAC_BOTTOM, DAC_BUS)]

# ---- Stand-in footprints and simple 3D models
METAL, BLACK, GREY, GOLD, BEIGE = (0.58, 0.59, 0.62), (0.07, 0.07, 0.07), (0.45, 0.45, 0.45), \
    (0.85, 0.68, 0.3), (0.55, 0.38, 0.2)
# Footprints whose models KiCad doesn't ship: a model of the same package, or boxes in the
# footprint's frame (x0, x1, y0, y1, z0, z1, colour).
MODEL_SUBST = {
    "Oscillator_SMD_Abracon_ASE-4Pin_3.2x2.5mm": "Crystal.3dshapes/Crystal_SMD_3225-4Pin_3.2x2.5mm.step",
    "Texas_DRC0010J_ThermalVias": "Package_SON.3dshapes/VSON-10-1EP_3x3mm_P0.5mm_EP1.65x2.4mm.step",
    "VQFN-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm": "Package_DFN_QFN.3dshapes/TQFN-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm.step",
}
MODEL_BOXES = {
    "USB_C_Receptacle_HRO_TYPE-C-31-M-12": [("box", -4.47, 4.47, -3.65, 3.65, 0, 3.26, METAL),
                                            ("box", -3.6, 3.6, 3.62, 3.66, 0.45, 2.8, BLACK)],
    "SW_Push_1P1T-MP_NO_Horizontal_Alps_SKRTLAE010": [("box", -2.25, 2.25, -1.35, 1.35, 0, 3.3, METAL),
                                                      ("box", -1.0, 1.0, 1.35, 2.04, 1.0, 2.3, BLACK)],
    "Jushuo_AFC07-S24FCA-00_1x24-1MP_P0.50_Horizontal": [("box", -8.8, 8.8, -0.75, 2.6, 0, 2.0, BEIGE),
                                                         ("box", -8.4, 8.4, 2.6, 3.65, 0.3, 2.0, BLACK)],
    "Texas_X2QFN-12_1.6x1.6mm_P0.4mm": [("box", -0.8, 0.8, -0.8, 0.8, 0, 0.4, BLACK)],
}
BODY_ONLY = {"ESP32-S3-WROOM-1"}   # courtyard also covers the antenna keep-out (a rule area)
COVERS_NOTCH = {"J6", "J7"}        # mid-mount jacks sit over their notches

# JLCPCB's 4-layer limits; KiCad reads them from hardware/dap.kicad_dru
DRC_RULES = """(version 1)
# JLCPCB 4-layer board limits. Written by tools/make_pcb.py.
(rule "clearance" (constraint clearance (min 0.1mm)))
(rule "track width" (constraint track_width (min 0.1mm)))
(rule "hole size" (constraint hole_size (min 0.2mm)))
(rule "hole clearance" (constraint hole_clearance (min 0.2mm)))
(rule "edge clearance" (constraint edge_clearance (min 0.3mm)))
"""


def jack_footprint(name, side_pads, rear_pads, spec, plug, descr):
    """Mid-mount jack sitting in a notch: origin on the board edge at the jack's centre line,
    body reaching into the board (+y). Legs on pads beside the notch (side_pads: number,
    side -1/+1, row from the edge) and in a row behind it (rear_pads: number, x), where the
    tracks from the DACs arrive."""
    w, h, d, nose = spec
    px = w / 2 + 0.2 + 0.5 + 0.6
    ry = d + 1.2                      # rear row: 0.5 mm of copper clearance behind the notch
    pads = [(n, side * px, 2.5 + 3.0 * row, 1.2, 1.6) for n, side, row in side_pads] + \
           [(n, x, ry, 1.2, 1.6) for n, x in rear_pads]
    model = [("box", -w / 2, w / 2, -0.3, d - 0.3, -PORT_DROP - h / 2, -PORT_DROP + h / 2, BLACK),
             ("cyl", 0, -PORT_DROP, nose / 2, -1.8, -0.3, GOLD),
             ("cyl", 0, -PORT_DROP, plug / 2, -1.85, -1.0, BLACK)]
    return dict(name=name, descr=descr, pads=pads,
                courtyard=(-px - 0.85, px + 0.85, -1.8, ry + 1.05), fab=(-w / 2, w / 2, -0.3, d - 0.3),
                model=model)


STANDIN = [
    jack_footprint("Jack_3.5mm_PJ-342_standin", [("1", 1, 1), ("2", 1, 2)],
                   [("5", -2.0), ("4", 0.0), ("3", 2.0)], JACK35, 3.5,
                   "Stand-in for the PJ-342 3.5 mm jack, mid-mount in a board notch; size from the case "
                   "estimate. Replace with the part's drawing."),
    jack_footprint("Jack_4.4mm_standin", [("5", -1, 2), ("6", -1, 3)],
                   [("1", -3.0), ("2", -1.0), ("4", 1.0), ("3", 3.0)], JACK44, 4.4,
                   "Stand-in for a 4.4 mm balanced jack, mid-mount in a board notch; size from the case "
                   "estimate. Replace with the chosen jack's drawing."),
    dict(name="Battery_Pads_1x03", descr="Solder pads for the battery's three wires: 1 +, 2 -, 3 NTC",
         pads=[(str(i + 1), 0, -2.5 + 2.5 * i, 3.0, 1.6) for i in range(3)],
         courtyard=(-1.8, 1.8, -3.6, 3.6), fab=(-1.5, 1.5, -3.3, 3.3), model=None,
         silk=[("+", -2.6, -2.5), ("-", -2.6, 0.0), ("T", -2.6, 2.5)]),
]


def write_wrl(path, solids):
    """Simple VRML model. KiCad's VRML unit is 0.1 inch and its model y axis points the
    opposite way to the footprint's."""
    s = 1 / 2.54
    out = ["#VRML V2.0 utf8"]
    for solid in solids:
        if solid[0] == "box":
            _, x0, x1, y0, y1, z0, z1, rgb = solid
            ring = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            pts = [(x, -y, z) for z in (z0, z1) for x, y in ring]
        else:   # cylinder along the footprint's y axis
            _, cx, cz, r, y0, y1, rgb = solid
            ring = [(cx + r * math.cos(2 * math.pi * i / 24), cz + r * math.sin(2 * math.pi * i / 24))
                    for i in range(24)]
            pts = [(x, -y, z) for y in (y0, y1) for x, z in ring]
        n = len(pts) // 2
        faces = [list(range(n)), list(range(n, 2 * n))] + \
                [[i, (i + 1) % n, n + (i + 1) % n, n + i] for i in range(n)]
        # KiCad draws only the front of a face: turn every face outwards (the solids are convex)
        mid = [sum(p[k] for p in pts) / len(pts) for k in range(3)]
        for j, f in enumerate(faces):
            q = [pts[i] for i in f]
            normal = [sum((a[(k + 1) % 3] - b[(k + 1) % 3]) * (a[(k + 2) % 3] + b[(k + 2) % 3])
                          for a, b in zip(q, q[1:] + q[:1])) for k in range(3)]   # Newell's method
            centre = [sum(p[k] for p in q) / len(q) for k in range(3)]
            if sum(normal[k] * (centre[k] - mid[k]) for k in range(3)) < 0:
                faces[j] = f[::-1]
        out.append("Shape { appearance Appearance { material Material { diffuseColor %.3f %.3f %.3f "
                   "specularColor 0.25 0.25 0.25 shininess 0.4 } }" % rgb)
        out.append("  geometry IndexedFaceSet { creaseAngle 0.6 coord Coordinate { point [")
        out.append(",\n".join("    %.4f %.4f %.4f" % (x * s, y * s, z * s) for x, y, z in pts) + " ] }")
        out.append("  coordIndex [ " + ", ".join(", ".join(map(str, f)) + ", -1" for f in faces) + " ] } }")
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")


def write_standins():
    os.makedirs(FP_LIB, exist_ok=True)
    os.makedirs(os.path.join(HW, "3d"), exist_ok=True)
    font = ["effects", ["font", ["size", 1, 1], ["thickness", 0.15]]]
    for spec in STANDIN:
        x0, x1, y0, y1 = spec["courtyard"]
        fx0, fx1, fy0, fy1 = spec["fab"]
        tree = ["footprint", K.Q(spec["name"]), ["version", 20240108], ["generator", K.Q("make_pcb")],
                ["layer", K.Q("F.Cu")], ["descr", K.Q(spec["descr"])],
                ["property", K.Q("Reference"), K.Q("REF**"), ["at", 0, y0 - 1.2, 0], ["layer", K.Q("F.SilkS")], font],
                ["property", K.Q("Value"), K.Q(spec["name"]), ["at", 0, y1 + 1.2, 0], ["layer", K.Q("F.Fab")], font],
                ["attr", "smd"],
                ["fp_rect", ["start", x0, y0], ["end", x1, y1], ["stroke", ["width", 0.05], ["type", "solid"]],
                 ["fill", "no"], ["layer", K.Q("F.CrtYd")]],
                ["fp_rect", ["start", fx0, fy0], ["end", fx1, fy1], ["stroke", ["width", 0.1], ["type", "solid"]],
                 ["fill", "no"], ["layer", K.Q("F.Fab")]]]
        for text, tx, ty in spec.get("silk", []):
            tree.append(["fp_text", "user", K.Q(text), ["at", tx, ty, 0], ["layer", K.Q("F.SilkS")], font])
        for num, px, py, pw, ph in spec["pads"]:
            tree.append(["pad", K.Q(num), "smd", "roundrect", ["at", px, py], ["size", pw, ph],
                         ["layers", K.Q("F.Cu"), K.Q("F.Paste"), K.Q("F.Mask")], ["roundrect_rratio", 0.25]])
        if spec["model"]:
            wrl = f"{spec['name']}.wrl"
            write_wrl(os.path.join(HW, "3d", wrl), spec["model"])
            tree.append(["model", K.Q("${KIPRJMOD}/3d/" + wrl), ["offset", ["xyz", 0, 0, 0]],
                         ["scale", ["xyz", 1, 1, 1]], ["rotate", ["xyz", 0, 0, 0]]])
        with open(os.path.join(FP_LIB, spec["name"] + ".kicad_mod"), "w") as f:
            f.write(K.dump(tree) + "\n")
    for name, boxes in MODEL_BOXES.items():
        write_wrl(os.path.join(HW, "3d", name + ".wrl"), boxes)


# ---- Netlist from the schematic

def read_netlist():
    sch = os.path.join(HW, "dap.kicad_sch")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "dap.net")
        subprocess.run([M.KICAD_CLI, "sch", "export", "netlist", "-o", path, sch], check=True,
                       capture_output=True)
        tree = K.parse(open(path, encoding="utf-8").read())[0]
    comps = {}
    for c in K.find(K.first(tree, "components"), "comp"):
        ref = str(K.first(c, "ref")[1])
        sheet = K.first(c, "sheetpath")
        comps[ref] = dict(fp=str(K.first(c, "footprint")[1]), value=str(K.first(c, "value")[1]),
                          path=str(K.first(sheet, "tstamps")[1]) + str(K.first(c, "tstamps")[1]),
                          sheet=str(K.first(sheet, "names")[1]).strip("/"))
    pins = {}
    for n in K.find(K.first(tree, "nets"), "net"):
        name = str(K.first(n, "name")[1])
        for node in K.find(n, "node"):
            pins[(str(K.first(node, "ref")[1]), str(K.first(node, "pin")[1]))] = name
    return comps, pins


# ---- Geometry helpers (case frame unless noted)

def mm(v):
    return pcbnew.FromMM(v)


def to_kicad(x, y):
    return pcbnew.VECTOR2I(mm(OX + x), mm(OY - y))


def to_case(p):
    return pcbnew.ToMM(p.x) - OX, OY - pcbnew.ToMM(p.y)


def local_box(fp):
    """Keep-clear box in the footprint's own frame (mm, y down), taken before it is moved:
    the courtyard's bounding box, or for BODY_ONLY parts the part of it within 1 mm of the
    body (their keep-out rule area is added separately, see zone_boxes)."""
    fp.BuildCourtyardCaches()
    poly = fp.GetCourtyard(pcbnew.F_CrtYd)
    bb = poly.BBox() if poly.OutlineCount() else fp.GetBoundingBox()
    box = (pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetRight()),
           pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetBottom()))
    if fp.GetFPID().GetLibItemName().wx_str() in BODY_ONLY:
        shapes = [d for d in fp.GraphicalItems() if isinstance(d, pcbnew.PCB_SHAPE) and d.GetLayer() == pcbnew.F_Fab]
        xs = [pcbnew.ToMM(v) for d in shapes for v in (d.GetStart().x, d.GetEnd().x)]
        ys = [pcbnew.ToMM(v) for d in shapes for v in (d.GetStart().y, d.GetEnd().y)]
        box = (max(box[0], min(xs) - 1), min(box[1], max(xs) + 1),
               max(box[2], min(ys) - 1), min(box[3], max(ys) + 1))
    return box


def zone_boxes(fp):
    """Keep-out rule areas that ban footprints (the ESP32's antenna area), as case-frame
    boxes, once the footprint is in place."""
    out = []
    for z in fp.Zones():
        if z.GetIsRuleArea() and z.GetDoNotAllowFootprints():
            bb = z.GetBoundingBox()
            (x0, y1), (x1, y0) = to_case(bb.GetOrigin()), to_case(bb.GetEnd())
            out.append((x0, x1, y0, y1))
    return out


def turned(box, rot):
    """The local box after rotating by rot degrees, as offsets in the case frame."""
    c, s = round(math.cos(math.radians(rot))), round(math.sin(math.radians(rot)))
    x0, x1, y0, y1 = box
    pts = [(u * c + v * s, u * s - v * c) for u in (x0, x1) for v in (y0, y1)]
    return min(p[0] for p in pts), max(p[0] for p in pts), min(p[1] for p in pts), max(p[1] for p in pts)


def overlaps(a, b):
    return a[0] < b[1] - 1e-6 and b[0] < a[1] - 1e-6 and a[2] < b[3] - 1e-6 and b[2] < a[3] - 1e-6


def board_outline():
    """Outline points: rounded bottom corners, cut-outs at the top corners for the screw
    bosses, notches for the jacks."""
    r, pts = R_CORNER, []
    for cx, cy, a0 in ((-HX + r, -HY + r, 180), (HX - r, -HY + r, 270)):
        pts += [(cx + r * math.cos(math.radians(a0 + 15 * i)), cy + r * math.sin(math.radians(a0 + 15 * i)))
                for i in range(7)]
    bx, by = BOSS_NOTCH
    pts += [(HX, by), (bx, by), (bx, HY)]
    for x0, x1, y0 in sorted(NOTCHES, reverse=True):
        pts += [(x1, HY), (x1, y0), (x0, y0), (x0, HY)]
    return pts + [(-bx, HY), (-bx, by), (-HX, by)]


def keepouts():
    """Board areas nothing may cover: the notches and corner cut-outs, as boxes."""
    bx, by = BOSS_NOTCH
    return [(x0, x1, y0, HY + 5) for x0, x1, y0 in NOTCHES] + [(bx, HX + 5, by, HY + 5), (-HX - 5, -bx, by, HY + 5)]


# ---- Building the board

def build():
    write_standins()
    comps, pins = read_netlist()
    sheets = [(n, f, fn()) for n, f, fn in M.SHEETS]
    M.assign_refs(sheets)
    groups = {parts[0].ref: [p.ref for p in parts] for _, _, gs in sheets for _, parts in gs}
    missing = set(comps) ^ {r for g in groups.values() for r in g}
    if missing:
        sys.exit(f"schematic and design table disagree on {sorted(missing)}: re-run make_schematic.py")

    board = pcbnew.CreateEmptyBoard()
    board.SetCopperLayerCount(4)
    board.GetDesignSettings().SetBoardThickness(mm(PCB_T))
    nets = {}
    for name in sorted(set(pins.values())):
        nets[name] = pcbnew.NETINFO_ITEM(board, name)
        board.Add(nets[name])

    pts = [to_kicad(x, y) for x, y in board_outline()]
    for a, b in zip(pts, pts[1:] + pts[:1]):
        seg = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(a)
        seg.SetEnd(b)
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetWidth(mm(0.1))
        board.Add(seg)

    fps, boxes, pad_local = {}, {}, {}
    for ref, c in sorted(comps.items()):
        lib, name = c["fp"].split(":")
        fp = pcbnew.FootprintLoad(FP_LIB if lib == "dap" else os.path.join(K.KICAD_FOOTPRINTS, lib + ".pretty"),
                                  name)
        if fp is None:
            sys.exit(f"{ref}: footprint {c['fp']} not found")
        fp.SetFPID(pcbnew.LIB_ID(lib, name))
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        fp.SetPath(pcbnew.KIID_PATH(c["path"]))
        fp.SetSheetname(c["sheet"])
        fp.Reference().SetLayer(pcbnew.F_Fab)   # no reference text on the silkscreen: too dense
        for pad in fp.Pads():
            net = pins.get((ref, pad.GetNumber()))
            if net:
                pad.SetNet(nets[net])
        if name in MODEL_SUBST or name in MODEL_BOXES:
            fp.Models().clear()
            model = pcbnew.FP_3DMODEL()
            model.m_Filename = ("${KICAD10_3DMODEL_DIR}/" + MODEL_SUBST[name] if name in MODEL_SUBST
                                else f"${{KIPRJMOD}}/3d/{name}.wrl")
            fp.Models().push_back(model)
        boxes[ref] = local_box(fp)
        pad_local[ref] = [(p.GetNetname(), pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y))
                          for p in fp.Pads()]   # still at the origin, unturned
        board.Add(fp)
        fps[ref] = fp

    taken = {"F": [("notch", b) for b in keepouts()], "B": []}
    problems = []

    def fine_pitch(ref):
        pts = [(u, v) for _, u, v in pad_local[ref]]
        if len(pts) < 8:
            return False
        return min(math.hypot(a[0] - b[0], a[1] - b[1]) for i, a in enumerate(pts) for b in pts[i + 1:]
                   if (a[0], a[1]) != (b[0], b[1])) <= 0.55

    def put(ref, x, y, rot, side="F"):
        fp = fps[ref]
        fp.SetPosition(to_kicad(x, y))
        fp.SetOrientationDegrees(rot)
        if side == "B":
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        t = turned(boxes[ref], rot)
        box = (x + t[0], x + t[1], y + t[2], y + t[3])
        for other, b in taken[side]:
            if overlaps(box, b) and not (other == "notch" and ref in COVERS_NOTCH):
                problems.append(f"{ref} overlaps {other}")
        if box[0] < -HX - 0.01 or box[1] > HX + 0.01 or box[2] < -HY - 0.01:
            if ref not in ("U8", "J4", "J5"):
                problems.append(f"{ref} is off the board")
        taken[side].append((ref, box))
        if fine_pitch(ref):   # room around it for the tracks fanning out of its pins
            taken[side].append((f"{ref} fan-out", (box[0] - FANOUT, box[1] + FANOUT, box[2] - FANOUT, box[3] + FANOUT)))
        for z in zone_boxes(fp):
            taken["F"].append((f"{ref} keep-out", z))
            taken["B"].append((f"{ref} keep-out", z))

    for ref, spec in PLACE.items():
        put(ref, *spec)
    for ref, strips in KEEP_CLEAR.items():
        x, y = PLACE[ref][:2]
        taken["F"] += [(f"{ref} pins", (x + x0, x + x1, y + y0, y + y1)) for x0, y0, x1, y1 in strips]

    def goal(ref, targets):
        mine = {p.GetNetname() for p in fps[ref].Pads()} - {"GND", ""}
        pts = [to_case(p.GetPosition()) for t in targets for p in fps[t].Pads() if p.GetNetname() in mine]
        if not pts:
            pts = [to_case(fps[t].GetPosition()) for t in targets]
        return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)

    def pad_aims(ref, targets):
        """For each net of the part (not ground) that the targets share: where those pins are."""
        aims = {}
        for net, _, _ in pad_local[ref]:
            if net not in ("GND", "") and net not in aims:
                pts = [to_case(p.GetPosition()) for t in targets for p in fps[t].Pads() if p.GetNetname() == net]
                if pts:
                    aims[net] = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        return aims

    def pad_cost(ref, x, y, rot, aims):
        """How far each pad sits from the pins of its own net: picks the way round a part
        faces, so that a capacitor between two neighbouring pins doesn't cross its tracks."""
        c, s_ = round(math.cos(math.radians(rot))), round(math.sin(math.radians(rot)))
        return sum(math.hypot(x + u * c + v * s_ - aims[net][0], y + u * s_ - v * c - aims[net][1])
                   for net, u, v in pad_local[ref] if net in aims)

    def area_of(b):
        return (b[1] - b[0]) * (b[3] - b[2])

    placed = set(PLACE)
    order = [g for g, _ in AREA] + [g for g in groups if g not in dict(AREA)]
    for g in order:
        rect = dict(AREA).get(g)
        todo = sorted((r for r in groups[g] if r not in placed), key=lambda r: -area_of(boxes[r]))
        for ref in todo:
            targets = TARGETS.get(g) or [r for r in groups[g] if r in placed]
            gx, gy = goal(ref, targets)
            wx0, wy0, wx1, wy1 = rect or (gx - 12, gy - 12, gx + 12, gy + 12)
            wx0, wy0, wx1, wy1 = max(wx0, -HX), max(wy0, -HY), min(wx1, HX), min(wy1, HY)
            near = [b for _, b in taken["F"] if overlaps(b, (wx0 - 1, wx1 + 1, wy0 - 1, wy1 + 1))]
            aims = pad_aims(ref, targets)
            best = None
            for rot in (0, 90, 180, 270):   # nearest free spot each way round; keep the way whose pads face their pins
                t = turned(boxes[ref], rot)
                xs = [wx0 - t[0] + STEP * i for i in range(int((wx1 - wx0 - t[1] + t[0]) / STEP) + 1)]
                ys = [wy0 - t[2] + STEP * i for i in range(int((wy1 - wy0 - t[3] + t[2]) / STEP) + 1)]
                cands = sorted(((x - gx) ** 2 + (y - gy) ** 2, x, y) for x in xs for y in ys)
                for d, x, y in cands:
                    box = (x + t[0], x + t[1], y + t[2], y + t[3])
                    if not any(overlaps(box, b) for b in near):
                        score = pad_cost(ref, x, y, rot, aims) + 0.5 * math.sqrt(d)
                        if best is None or score < best[0] - 1e-6:
                            best = (score, x, y, rot)
                        break
            if not best:
                sys.exit(f"no room for {ref} ({comps[ref]['value']}) in group {g}'s area")
            put(ref, best[1], best[2], best[3])
            placed.add(ref)

    title = pcbnew.PCB_TEXT(board)
    title.SetText("E-ink DAP  v0.1\ndraft 2026-10-26")
    title.SetLayer(pcbnew.B_SilkS)
    title.SetMirrored(True)
    title.SetTextSize(pcbnew.VECTOR2I(mm(1.6), mm(1.6)))
    title.SetTextThickness(mm(0.25))
    title.SetPosition(to_kicad(0, -20))
    board.Add(title)

    autorouted = route(board, nets)
    pcbnew.SaveBoard(BOARD_FILE, board, True)
    if autorouted:
        widened, removed = tidy(BOARD_FILE)
        print(f"autoroute: {widened} narrow track ends widened to 0.1 mm, {removed} dead-end tracks and vias removed")
    with open(os.path.join(HW, "dap.kicad_dru"), "w") as f:
        f.write(DRC_RULES)
    used = sum(1 for n in nets if not n.startswith("unconnected-"))
    print(f"pcb: {len(fps)} parts placed on {2 * HX:.1f} x {2 * HY:.1f} mm, {used} nets")
    for p in problems:
        print("   ", p)
    check()
    if RENDER:
        render()
    export_glb()


def other_nets(r, code):
    """Nets not in ROUTES or POWER_ROUTES, split into short local ones (a chip and its
    capacitors, a feedback divider) and longer lines, each list shortest first."""
    planned = {n for names, _ in ROUTES + POWER_ROUTES for n in names} | {"GND"}
    spans = []
    for name, c in code.items():
        if name in planned or name.startswith("unconnected-"):
            continue
        seen = {}
        for pad, _, _ in r.nets.get(c, []):
            seen[r._name(pad)] = r._centre(pad)
        if len(seen) < 2:
            continue
        xs, ys = [p[0] for p in seen.values()], [p[1] for p in seen.values()]
        spans.append((math.hypot(max(xs) - min(xs), max(ys) - min(ys)), name))
    spans.sort()
    local = [([n], dict(full_width=0.3)) for d, n in spans if d < LOCAL]
    far = [([n], dict(full_width=0.2)) for d, n in spans if d >= LOCAL]
    return local, far


def route(board, nets):
    """Ground vias; every net whose pins lie within LOCAL of each other, then ROUTES, then
    POWER_ROUTES, then all the rest, shortest first; then the copper fills (ZONES)."""
    import pcb_router
    outline = [(OX + x, OY - y) for x, y in board_outline()]
    r = pcb_router.Router(board, outline, [pcbnew.F_Cu, pcbnew.B_Cu])
    code = {name.split("/")[-1]: n.GetNetCode() for name, n in nets.items()}
    for ref, (x0, y0, x1, y1), names in CHANNELS:
        x, y = PLACE[ref][:2]
        r.reserve(OX + x + x0, OY - y - y1, OX + x + x1, OY - y - y0, [code[n] for n in names])
    gnd = code["GND"]
    pads = []
    for fp in board.GetFootprints():
        tht = {p.GetNumber() for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH}
        pads += [p for p in fp.Pads() if p.GetNetCode() == gnd and p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD
                 and p.GetNumber() not in tht]   # pads with vias of their own (thermal pads) are skipped
    failed = r.fanout(gnd, pads)
    print(f"route: {len(pads) - len(failed)} of {len(pads)} ground pads joined to the planes")
    for p in failed:
        print(f"    no room for a via by {p.GetParentFootprint().GetReference()} pad {p.GetNumber()}")
    local, far = other_nets(r, code)
    plan = local + ROUTES + POWER_ROUTES   # the rest (far) goes to Freerouting
    stubs = r.escape([code[n] for names, _ in plan for n in names])
    print(f"route: {stubs} fine-pitch pins given an escape stub")
    if not r.bridge(code[USB_C_BRIDGE[0]], USB_C_BRIDGE[1]):
        print("    no room to bridge the USB-C D- pins")
    jobs = []
    for names, opts in plan:
        opts = dict(opts)
        if "partner" in opts:
            opts["partner"] = code[opts["partner"]]
        jobs += [(code[name], opts) for name in names]
    stuck = r.route_all(jobs)
    r.drop_unused_stubs()
    pieces = list(board.GetTracks())
    vias = sum(1 for t in pieces if t.GetClass() == "PCB_VIA")
    print(f"route: {sum(len(n) for n, _ in plan)} nets, {len(pieces) - vias} track pieces, {vias} vias, "
          f"{sum(len(v) for v in stuck.values())} connections not made")
    for net, pins in stuck.items():
        for name, _, why in pins:
            print(f"    could not join {name} ({board.FindNet(net).GetNetname() if hasattr(board, 'FindNet') else net}): {why}")
    for names, _ in ROUTES + POWER_ROUTES:
        print("    " + ", ".join(f"{n} {r.length.get(code[n], 0):.0f} mm" for n in names))
    total = sum(r.length.get(code[n], 0) for names, _ in local for n in names)
    print(f"    {len(local)} short local nets, {total:.0f} mm")

    # The ground planes go in before Freerouting, which routes around them as planes; the
    # bottom 3.3 V fill after it, so it fills around Freerouting's tracks
    planes = [(lay, net) for lay, net in ZONES if lay != pcbnew.B_Cu]
    for layer, net in planes:
        add_zone(board, outline, layer, nets[net])
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    routed = autoroute(board, len(far))
    for layer, net in ZONES:
        if (layer, net) not in planes:
            add_zone(board, outline, layer, nets[net])
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    return routed


def add_zone(board, outline, layer, net):
    zone = pcbnew.ZONE(board)
    zone.SetLayer(layer)
    zone.SetNet(net)
    zone.SetZoneName(f"{net.GetNetname()} {board.GetLayerName(layer)}")
    outline_poly = zone.Outline()
    outline_poly.NewOutline()
    for x, y in outline:
        outline_poly.Append(mm(x), mm(y))
    zone.SetMinThickness(mm(0.2))
    zone.SetLocalClearance(mm(0.2))
    zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    zone.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    board.Add(zone)


def autoroute(board, n_nets):
    """Hands every connection not routed yet to Freerouting (FREEROUTING, a Java program; run
    with its usage statistics off): all tracks so far are locked and go out as fixed wiring
    in a Specctra file, the inner layers as ground planes; Freerouting's session comes back
    in. Tracks 0.15 mm, clearance 0.1 mm, vias 0.5/0.3 mm."""
    if not os.path.exists(FREEROUTING):
        print(f"autoroute: {os.path.relpath(FREEROUTING, ROOT)} not found, {n_nets} nets left unrouted")
        return False
    for layer in (pcbnew.In1_Cu, pcbnew.In2_Cu):
        board.SetLayerType(layer, pcbnew.LT_POWER)
    nc = board.GetDesignSettings().m_NetSettings.GetDefaultNetclass()
    nc.SetClearance(mm(0.1))
    nc.SetTrackWidth(mm(0.15))
    nc.SetViaDiameter(mm(0.5))
    nc.SetViaDrill(mm(0.3))
    for t in board.GetTracks():
        t.SetLocked(True)
    with tempfile.TemporaryDirectory() as tmp:
        dsn, ses = os.path.join(tmp, "dap.dsn"), os.path.join(tmp, "dap.ses")
        pcbnew.ExportSpecctraDSN(board, dsn)
        env = dict(os.environ, FREEROUTING__USAGE_AND_DIAGNOSTIC_DATA__DISABLE_ANALYTICS="true")
        run = subprocess.run(["java", "-jar", FREEROUTING, "-de", dsn, "-do", ses,
                              f"--router.autorouter.max_passes={FREEROUTING_PASSES}", "--gui.enabled=false",
                              "--usage_and_diagnostic_data.disable_analytics=true", f"--user_data_path={tmp}"],
                             capture_output=True, text=True, env=env, timeout=3600)
        log = run.stdout + run.stderr
        if run.returncode or not os.path.exists(ses):
            print(f"autoroute: Freerouting failed ({run.returncode}): {log[-800:]}")
            return False
        before = len(board.GetTracks())
        pcbnew.ImportSpecctraSES(board, ses)
        print(f"autoroute: Freerouting routed {n_nets} nets; tracks and vias {before} -> {len(board.GetTracks())}")
        for line in log.splitlines():
            if "Auto-routing stage completed" in line:
                print("    " + line.split("] ", 1)[-1].strip()[:160])
    return True


def tidy(path):
    """After Freerouting, on the saved board: widens its neck-downs below 0.1 mm (the board's
    minimum) to 0.1 mm, then removes tracks and vias that KiCad's own connectivity check finds
    leading nowhere, round after round until none are left (each removal can leave the next
    piece of a dead branch). Works on the file, reloading it each round: the Python bindings
    go wrong if the track list is read again after a removal. Returns (widened, removed)."""
    widened = removed = 0
    for rnd in range(100):
        board = pcbnew.LoadBoard(path)
        if rnd == 0:
            for t in board.GetTracks():
                if t.GetClass() == "PCB_TRACK" and t.GetWidth() < mm(0.1):
                    t.SetWidth(mm(0.1))
                    widened += 1
        board.BuildConnectivity()
        conn = board.GetConnectivity()
        dead = [t for t in board.GetTracks() if conn.TestTrackEndpointDangling(t, True)]
        if not dead and not (rnd == 0 and widened):
            break
        for t in dead:
            board.Remove(t)
        removed += len(dead)
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        pcbnew.SaveBoard(path, board, True)
    return widened, removed


def check():
    """KiCad's DRC, leaving out what an unrouted board is bound to have."""
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "drc.json")
        subprocess.run([M.KICAD_CLI, "pcb", "drc", "--format", "json", "--severity-all", "-o", out, BOARD_FILE],
                       capture_output=True)
        report = json.load(open(out))
    skip = {"unconnected_items", "lib_footprint_mismatch", "lib_footprint_issues"}
    found, silk, own = {}, 0, set()
    for v in report.get("violations", []):
        descs = [i["description"] for i in v.get("items", [])]
        refs = {d.rsplit(" of ", 1)[-1].split()[0] for d in descs if " of " in d}
        if v["type"].startswith("silk_"):
            silk += 1
        elif v["type"] == "hole_clearance" and len(refs) == 1 and all(" of " in d for d in descs):
            own.add(refs.pop())   # inside one library footprint: the maker's land pattern
        elif v["type"] not in skip:
            found.setdefault(v["type"], []).append(" / ".join(descs))
    unrouted = len(report.get("unconnected_items", []))
    print(f"check: DRC {sum(len(v) for v in found.values())} problems besides {unrouted} unrouted connections "
          f"and {silk} silkscreen warnings")
    if own:
        print(f"    (hole clearance inside the library footprints of {', '.join(sorted(own))} not counted)")
    for kind, items in sorted(found.items()):
        print(f"    {kind}: {len(items)}")
        for i in items[:6]:
            print("       ", i)


def export_glb():
    """The board as a 3D model for the case model (tools/make_case.py): case/pcb.glb."""
    path = os.path.join(ROOT, "case", "pcb.glb")
    r = subprocess.run([M.KICAD_CLI, "pcb", "export", "glb", "-f", "--subst-models", "--include-tracks",
                        "--include-pads", "--include-zones", "--include-silkscreen", "--include-soldermask",
                        f"--user-origin={OX}x{OY}mm", "-o", path, BOARD_FILE], capture_output=True, text=True)
    print(f"export: {os.path.relpath(path, ROOT)}" if r.returncode == 0 else f"export glb failed: {r.stderr}")


def render():
    out = os.path.join(HW, "renders")
    os.makedirs(out, exist_ok=True)
    views = [("pcb_top", ["--side", "top", "-w", "1300", "-h", "2100", "--zoom", "0.95"]),
             ("pcb_bottom", ["--side", "bottom", "-w", "1300", "-h", "2100", "--zoom", "0.95"]),
             ("pcb_angle", ["--side", "top", "--perspective", "--rotate", "-55,0,160", "-w", "2000", "-h", "1600",
                            "--zoom", "0.92"])]
    for name, args in views:
        path = os.path.join(out, name + ".png")
        r = subprocess.run([M.KICAD_CLI, "pcb", "render", "--quality", "high", "--background", "opaque",
                            "-o", path] + args + [BOARD_FILE], capture_output=True, text=True)
        print(f"render: {os.path.relpath(path, ROOT)}" if r.returncode == 0 else f"render {name} failed: {r.stderr}")


if __name__ == "__main__":
    build()
