#!/usr/bin/env python3
"""Draws the player board's schematic (Phase 2) as a KiCad project in hardware/:

    python3 tools/make_schematic.py

- hardware/dap.kicad_pro, dap.kicad_sch: the project and its top sheet
- hardware/power.kicad_sch, mcu.kicad_sch, display.kicad_sch, usb_storage.kicad_sch,
  audio.kicad_sch: one sheet per block of docs/pcb_plan.md
- hardware/dap.kicad_sym + sym-lib-table: symbols KiCad doesn't ship (CS43131, GL823K,
  SN74AVC4T774, TPS61023, TPS2553, the two headphone jacks); fp-lib-table points at the
  footprints KiCad doesn't have (jacks, microSD socket, battery pads), which
  tools/make_pcb.py writes to hardware/dap.pretty

The design (parts, values, connections) is the DESIGN table below; the drawing is
generated, so change the table and re-run rather than editing the sheets by hand. Pins
connect through short wires and net labels; nets used on more than one sheet get global
labels, supply nets get power symbols. Every pin must be either connected or listed as not
connected (nc), so nothing is left floating by accident.
Check with: kicad-cli sch erc hardware/dap.kicad_sch
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kicad_sch as K  # noqa: E402
from kicad_sch import Q  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "hardware")
PROJECT = "dap"
PROJECT_LIBS = {"dap": os.path.join(OUT, "dap.kicad_sym")}

# Supply nets get power symbols instead of labels.
POWER = {"GND": "power:GND", "+3V3": "power:+3V3"}
POWER_VCC = ["SYS", "VBAT", "VBUS", "VP", "1V8_A", "1V8_CP", "1V8_D", "5V_BOOST", "GL_3V3"]

# ---- Footprints
R0402, C0402 = "Resistor_SMD:R_0402_1005Metric", "Capacitor_SMD:C_0402_1005Metric"
R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603, C0805 = "Capacitor_SMD:C_0603_1608Metric", "Capacitor_SMD:C_0805_2012Metric"
FB0603 = "Inductor_SMD:L_0603_1608Metric"
L3015, L2520 = "Inductor_SMD:L_Cenker_CKCS3015", "Inductor_SMD:L_Cenker_CKCS252010"


class Part:
    def __init__(self, prefix, lib, value, nets, fp="", lcsc="", nc=(), note=""):
        self.prefix, self.lib, self.value = prefix, lib, value
        self.nets, self.fp, self.lcsc, self.nc, self.note = nets, fp, lcsc, set(nc), note
        self.ref = None


# LCSC part numbers for the passives, by (value, footprint), checked on lcsc.com 2026-10-31.
# Resistors UNI-ROYAL 1 %; capacitors Samsung X5R/X7R rated at least 3x their voltage
# (1 uF/50V and 4.7 uF/50V for the e-paper booster, whose rails reach +-20 V).
PASSIVES = {
    ("0.47", R0603): "C23411", ("22", R0402): "C25092", ("1k", R0402): "C11702",
    ("1.1k", R0402): "C25860", ("1.62k", R0402): "C61897", ("4.7k", R0402): "C25900",
    ("4.99k", R0402): "C25903", ("10k", R0402): "C25744", ("47k", R0402): "C25792",
    ("68k", R0402): "C36871", ("100k", R0402): "C25741", ("200k", R0402): "C25764",
    ("768k", R0402): "C27017", ("887k", R0402): "C423127", ("1M", R0402): "C26083",
    ("1M", R0603): "C22935",
    ("100nF", C0402): "C1525", ("1uF", C0402): "C52923", ("1uF", C0603): "C15849",
    ("1uF/50V", C0603): "C15849", ("2.2uF", C0603): "C23630", ("4.7uF", C0603): "C19666",
    ("10uF", C0805): "C15850", ("22uF", C0805): "C45783", ("4.7uF/50V", C0805): "C98192",
    ("1.5uH", L3015): "C5291780", ("10uH", L3015): "C354566", ("1uH", L2520): "C354542",
    ("600R@100MHz", FB0603): "C85833",
}


def R(value, a, b, fp=R0402):
    return Part("R", "Device:R", value, {"1": a, "2": b}, fp, PASSIVES.get((value, fp), ""))


def C(value, a, b="GND", fp=C0402):
    fp = fp if fp != C0402 else (C0805 if value in ("10uF", "22uF") else
                                 C0603 if value in ("2.2uF", "4.7uF") else C0402)
    return Part("C", "Device:C", value, {"1": a, "2": b}, fp, PASSIVES.get((value, fp), ""))


def L(value, a, b, fp):
    return Part("L", "Device:L", value, {"1": a, "2": b}, fp, PASSIVES.get((value, fp), ""))


def FB(a, b):
    return Part("FB", "Device:FerriteBead_Small", "600R@100MHz", {"1": a, "2": b}, FB0603,
                PASSIVES[("600R@100MHz", FB0603)])


# ---- Custom symbols: name, reference, footprint, left pins, right pins.
# Pins are (number, name, type), listed top to bottom; "" leaves a gap.
CUSTOM = {
    "CS43131": ("U", "Package_DFN_QFN:QFN-40-1EP_5x5mm_P0.4mm_EP3.6x3.6mm_ThermalVias",
                "32-bit DAC with Class H headphone amp, Cirrus Logic, QFN-40",
                [("31", "VL", "power_in"), ("4", "VD", "power_in"), ("7", "VA", "power_in"),
                 ("25", "VCP", "power_in"), ("26", "VP", "power_in"), "",
                 ("37", "XTI/MCLK", "input"), ("36", "XTO", "output"), ("33", "CLKOUT", "output"), "",
                 ("34", "SCLK1", "bidirectional"), ("38", "LRCK1", "bidirectional"),
                 ("2", "SDIN1", "input"), ("32", "DSDCLK/SCLK2", "bidirectional"),
                 ("29", "DSDB/LRCK2", "bidirectional"), ("40", "DSDA/SDIN2", "input"), "",
                 ("1", "SCL", "input"), ("39", "SDA", "bidirectional"), ("30", "ADR", "input"),
                 ("28", "~{RESET}", "input"), ("27", "~{INT}", "open_collector"), "",
                 ("35", "GNDD", "power_in"), ("8", "GNDA", "power_in"), ("19", "GNDCP", "power_in"),
                 ("41", "EP", "power_in")],
                [("5", "FILT+", "passive"), ("6", "FILT-", "passive"), ("9", "-VA", "passive"),
                 ("10", "FLYP_VA", "passive"), ("11", "FLYN_VA", "passive"), "",
                 ("21", "VCP_FILT+", "passive"), ("18", "VCP_FILT-", "passive"),
                 ("24", "FLYP_VCP", "passive"), ("23", "FLYC_VCP", "passive"),
                 ("20", "FLYN_VCP", "passive"), "",
                 ("14", "HPOUTA", "output"), ("13", "HPREFA", "passive"),
                 ("16", "HPOUTB", "output"), ("17", "HPREFB", "passive"),
                 ("22", "HP_DETECT", "input"), ("12", "HPINA", "input"), ("15", "HPINB", "input"),
                 "", ("3", "TSO", "output")]),
    "GL823K": ("U", "Package_SO:SSOP-16_3.9x4.9mm_P0.635mm",
               "USB 2.0 SD card reader, Genesys Logic, SSOP-16",
               [("10", "5V", "power_in"), ("9", "VDD", "passive"), ("13", "VDDA", "passive"), "",
                ("15", "DP", "bidirectional"), ("16", "DM", "bidirectional"), "",
                ("11", "GPIO", "input"), ("12", "LED", "output"), ("8", "PMOS", "passive"), "",
                ("1", "VSS", "power_in"), ("14", "VSS", "passive")],
               [("4", "CLK", "output"), ("5", "CMD", "bidirectional"), ("3", "D0", "bidirectional"),
                ("2", "D1", "bidirectional"), ("7", "D2", "bidirectional"), ("6", "D3", "bidirectional")]),
    "SN74AVC4T774": ("U", "Package_SO:TSSOP-16_4.4x5mm_P0.65mm",
                     "4-bit dual-supply level shifter, per-bit direction, TSSOP-16",
                     [("16", "VCCA", "power_in"), ("1", "DIR1", "input"), ("2", "DIR2", "input"),
                      ("7", "DIR3", "input"), ("8", "DIR4", "input"), ("9", "~{OE}", "input"), "",
                      ("3", "A1", "bidirectional"), ("4", "A2", "bidirectional"),
                      ("5", "A3", "bidirectional"), ("6", "A4", "bidirectional"), "",
                      ("10", "GND", "power_in")],
                     [("15", "VCCB", "power_in"), "", "", "", "", "", "",
                      ("14", "B1", "bidirectional"), ("13", "B2", "bidirectional"),
                      ("12", "B3", "bidirectional"), ("11", "B4", "bidirectional")]),
    "TPS61023": ("U", "Package_TO_SOT_SMD:SOT-563", "5 V boost converter, 3.7 A switch, SOT-563",
                 [("3", "VIN", "power_in"), ("5", "SW", "passive"), ("2", "EN", "input"),
                  ("4", "GND", "power_in")],
                 [("6", "VOUT", "power_out"), ("1", "FB", "input")]),
    "TPS2553": ("U", "Package_TO_SOT_SMD:SOT-23-6", "Current-limited power switch, active-high EN, SOT-23-6",
                [("1", "IN", "power_in"), ("3", "EN", "input"), ("5", "ILIM", "passive"),
                 ("2", "GND", "power_in")],
                [("6", "OUT", "power_out"), ("4", "~{FAULT}", "open_collector")]),
    "PJ-342": ("J", "dap:Jack_3.5mm_PJ-342",
               "3.5 mm stereo jack, SHOU HAN PJ-342: tip 3 and ring 6, each with a switch that is closed "
               "while no plug is in (4, 7); 5 and 2 touch the sleeve end of the plug",
               [("3", "T", "passive"), ("4", "TSW", "passive"), ("6", "R", "passive"),
                ("7", "RSW", "passive"), ("5", "S", "passive"), ("2", "S", "passive")], []),
    "KH-PJ-44002": ("J", "dap:Jack_4.4mm_KH-PJ-44002-12DBAP-A",
                    "4.4 mm balanced jack, Kinghelm KH-PJ-44002-12DBAP-A: two pins per pole in Pentaconn "
                    "order (tip L+, L-, R+, R-, sleeve ground) and a separate plug switch 11-12",
                    [("5", "L+", "passive"), ("10", "L+", "passive"), ("4", "L-", "passive"),
                     ("9", "L-", "passive"), ("3", "R+", "passive"), ("8", "R+", "passive"),
                     ("2", "R-", "passive"), ("7", "R-", "passive"), ("1", "S", "passive"),
                     ("6", "S", "passive"), ("11", "SW_A", "passive"), ("12", "SW_B", "passive")], []),
}


def custom_symbol(name, spec):
    ref, fp, desc, left, right = spec
    longest = max([len(p[1]) for p in left + right if p] + [4])
    w = max(10.16, longest * 1.15 * (2 if right else 1) + 5.08)
    w = 5.08 * -(-w // 5.08)              # pins stay on the 2.54 mm grid
    rows = max(len(left), len(right))
    h = 2.54 * (rows + 1)
    top = 2.54 * -(-(rows + 1) // 2)
    pins = []
    for side, plist in ((0, left), (1, right)):
        for i, p in enumerate(plist):
            if not p:
                continue
            num, pname, ptype = p
            x = -w / 2 - 2.54 if side == 0 else w / 2 + 2.54
            y = top - 2.54 * (i + 1)
            pins.append(["pin", ptype, "line", ["at", x, y, 0 if side == 0 else 180], ["length", 2.54],
                         ["name", Q(pname), K.font()], ["number", Q(num), K.font()]])
    props = [["property", Q("Reference"), Q(ref), ["at", 0, top + 2.54, 0], K.font()],
             ["property", Q("Value"), Q(name), ["at", 0, top - h - 2.54, 0], K.font()],
             ["property", Q("Footprint"), Q(fp), ["at", 0, 0, 0], K.font(hide=True)],
             ["property", Q("Datasheet"), Q(""), ["at", 0, 0, 0], K.font(hide=True)],
             ["property", Q("Description"), Q(desc), ["at", 0, 0, 0], K.font(hide=True)]]
    body = ["symbol", Q(f"{name}_0_1"),
            ["rectangle", ["start", -w / 2, top], ["end", w / 2, top - h],
             ["stroke", ["width", 0.254], ["type", "default"]], ["fill", ["type", "background"]]]]
    return (["symbol", Q(name), ["pin_names", ["offset", 1.016]], ["exclude_from_sim", "no"],
             ["in_bom", "yes"], ["on_board", "yes"]] + props + [body, ["symbol", Q(f"{name}_1_1")] + pins])


def write_custom_lib():
    lib = ["kicad_symbol_lib", ["version", 20241209], ["generator", Q("make_schematic")],
           ["generator_version", Q("10.0")]] + [custom_symbol(n, s) for n, s in CUSTOM.items()]
    with open(PROJECT_LIBS["dap"], "w", encoding="utf-8") as f:
        f.write(K.dump(lib) + "\n")
    K._LIBS.pop(PROJECT_LIBS["dap"], None)


# ---- The design, sheet by sheet. Each group is drawn together: the main part, then its
# helpers in rows under it.

def power_sheet():
    return [
        ("Charger and power path: BQ24073, input limit 1.0 A, charge 0.8 A, OUT (SYS) held at 4.4 V on USB", [
            Part("U", "Battery_Management:BQ24073RGT", "BQ24073RGTR",
                 {"IN": "VBUS", "OUT": "SYS", "BAT": "VBAT", "ISET": "CHG_ISET", "ILIM": "CHG_ILIM",
                  "TMR": "CHG_TMR", "TS": "BAT_NTC", "~{CE}": "GND", "EN2": "SYS", "EN1": "BOOST_EN",
                  "~{CHG}": "CHG_N", "VSS": "GND", "TD": "GND"}, lcsc="C15220", nc=["~{PGOOD}"],
                 note="EN2 high (from SYS, so it holds with a dead battery) + EN1 low = input limit set "
                      "by ILIM; BOOST_EN high puts it in standby"),
            R("1.1k", "CHG_ISET", "GND"), R("1.62k", "CHG_ILIM", "GND"), R("68k", "CHG_TMR", "GND"),
            C("1uF", "VBUS", fp=C0603), C("10uF", "SYS"), C("10uF", "VBAT"),
            Part("J", "Connector_Generic:Conn_01x03", "Battery", {"1": "VBAT", "2": "GND", "3": "BAT_NTC"},
                 "dap:Battery_Pads_1x03",
                 note="606090 cell with 10k NTC, wires soldered to pads on the back: a JST PH plug is too "
                      "tall for the gap under the screen. Check the wire order before soldering"),
        ]),
        ("3.3 V buck-boost: TPS63001, power-save mode on", [
            Part("U", "Regulator_Switching:TPS63001", "TPS63001DRCR",
                 {"VIN": "SYS", "VINA": "SYS", "EN": "SYS", "PS/SYNC": "GND", "L1": "BB_L1", "L2": "BB_L2",
                  "VOUT": "+3V3", "FB": "+3V3", "GND": "GND", "PGND": "GND"}, lcsc="C28060"),
            L("1.5uH", "BB_L1", "BB_L2", L3015),
            C("10uF", "SYS"), C("100nF", "SYS"), C("22uF", "+3V3"), C("22uF", "+3V3"),
        ]),
        ("Audio rails: three LP5907 1.8 V LDOs (VA, VCP, VD+VL) and the filtered VP rail, off when AUDIO_EN is low", [
            Part("U", "Regulator_Linear:LP5907MFX-1.8", "LP5907MFX-1.8",
                 {"IN": "SYS", "EN": "AUDIO_EN", "OUT": "1V8_A", "GND": "GND"}, lcsc="C92498"),
            Part("U", "Regulator_Linear:LP5907MFX-1.8", "LP5907MFX-1.8",
                 {"IN": "SYS", "EN": "AUDIO_EN", "OUT": "1V8_CP", "GND": "GND"}, lcsc="C92498"),
            Part("U", "Regulator_Linear:LP5907MFX-1.8", "LP5907MFX-1.8",
                 {"IN": "SYS", "EN": "AUDIO_EN", "OUT": "1V8_D", "GND": "GND"}, lcsc="C92498"),
            C("1uF", "SYS"), C("1uF", "SYS"), C("1uF", "SYS"),
            C("1uF", "1V8_A"), C("1uF", "1V8_CP"), C("1uF", "1V8_D"),
            FB("SYS", "VP"), C("10uF", "VP"),
        ]),
        ("Optional 5 V out for a USB DAC: TPS61023 boost (5.1 V) + TPS2553 limit ~500 mA (47k); leave unassembled if not needed", [
            Part("dap", "dap:TPS61023", "TPS61023DRLR",
                 {"VIN": "SYS", "SW": "BST_SW", "EN": "BOOST_EN", "GND": "GND", "VOUT": "5V_BOOST",
                  "FB": "BST_FB"}, lcsc="C919459"),
            L("1uH", "SYS", "BST_SW", L2520), R("768k", "5V_BOOST", "BST_FB"), R("100k", "BST_FB", "GND"),
            C("10uF", "SYS"), C("22uF", "5V_BOOST"), C("22uF", "5V_BOOST"),
            Part("dap", "dap:TPS2553", "TPS2553DBVR",
                 {"IN": "5V_BOOST", "EN": "BOOST_EN", "ILIM": "SW_ILIM", "GND": "GND", "OUT": "VBUS"},
                 lcsc="C55266", nc=["~{FAULT}"]),
            R("47k", "SW_ILIM", "GND"), C("100nF", "5V_BOOST"),
        ]),
    ]


def mcu_sheet():
    io = {"GND": "GND", "3V3": "+3V3", "EN": "ESP_EN",
          "IO0": "KEY_PLAY", "IO1": "KEY_POWER", "IO2": "I2S_SCLK", "IO3": "VBAT_SENSE",
          "IO4": "I2S_LRCK", "IO5": "I2S_SDOUT", "IO6": "I2C_SDA", "IO7": "I2C_SCL",
          "IO8": "EPD_RST", "IO9": "EPD_DC", "IO10": "EPD_CS", "IO11": "EPD_MOSI", "IO12": "EPD_SCK",
          "IO13": "EPD_BUSY", "IO14": "SD_CLK", "IO15": "SD_CMD", "IO16": "SD_D0", "IO17": "SD_D1",
          "IO18": "SD_D2", "IO21": "SD_D3", "USB_D-": "ESP_USB_DM", "USB_D+": "ESP_USB_DP",
          "IO38": "USB_DISK", "IO39": "DAC_RST", "IO40": "KEY_VOLUP", "IO41": "KEY_VOLDN",
          "IO42": "OSC_SEL", "TXD0": "DEBUG_TX", "RXD0": "CHG_N", "IO45": "BOOST_EN",
          "IO46": "AUDIO_EN", "IO47": "TP_INT", "IO48": "TP_RST"}
    key = "Button_Switch_SMD:SW_Push_1P1T-MP_NO_Horizontal_Alps_SKRTLAE010"
    return [
        ("ESP32-S3-WROOM-1-N16R8 (pin map: docs/pcb_plan.md). IO35-37 belong to the octal PSRAM", [
            Part("U", "RF_Module:ESP32-S3-WROOM-1", "ESP32-S3-WROOM-1-N16R8", io, lcsc="C2913202",
                 nc=["IO35", "IO36", "IO37"]),
            C("10uF", "+3V3"), C("100nF", "+3V3"), R("10k", "+3V3", "ESP_EN"), C("1uF", "ESP_EN"),
        ]),
        ("Boot straps and defaults: IO45 and IO46 must be low at boot; USB_DISK, DAC_RST, AUDIO_EN, BOOST_EN default low", [
            R("100k", "BOOST_EN", "GND"), R("100k", "AUDIO_EN", "GND"), R("100k", "USB_DISK", "GND"),
            R("100k", "DAC_RST", "GND"),
        ]),
        ("Side keys (Alps SKRTLAE010): pressed = low. Play is on IO0, so holding it at power-on starts download mode", [
            Part("SW", "Switch:SW_Push", "Play", {"1": "KEY_PLAY", "2": "GND"}, key, "C110293"),
            Part("SW", "Switch:SW_Push", "Power", {"1": "KEY_POWER", "2": "GND"}, key, "C110293"),
            Part("SW", "Switch:SW_Push", "Vol+", {"1": "KEY_VOLUP", "2": "GND"}, key, "C110293"),
            Part("SW", "Switch:SW_Push", "Vol-", {"1": "KEY_VOLDN", "2": "GND"}, key, "C110293"),
            R("10k", "+3V3", "KEY_PLAY"), R("100k", "+3V3", "KEY_POWER"), R("100k", "+3V3", "KEY_VOLUP"),
            R("100k", "+3V3", "KEY_VOLDN"),
        ]),
        ("Battery voltage (1M/1M divider, about 2 uA), I2C pull-ups (3.3 V side), charge LED on CHG_N, debug pads", [
            R("1M", "VBAT", "VBAT_SENSE"), R("1M", "VBAT_SENSE", "GND"), C("100nF", "VBAT_SENSE"),
            R("4.7k", "+3V3", "I2C_SDA"), R("4.7k", "+3V3", "I2C_SCL"),
            R("1k", "+3V3", "CHG_LED_A"),
            Part("D", "Device:LED", "green", {"A": "CHG_LED_A", "K": "CHG_N"}, "LED_SMD:LED_0603_1608Metric",
                 "C72043"),
            Part("TP", "Connector:TestPoint", "TX", {"1": "DEBUG_TX"}, "TestPoint:TestPoint_Pad_D1.0mm"),
            Part("TP", "Connector:TestPoint", "GND", {"1": "GND"}, "TestPoint:TestPoint_Pad_D1.0mm"),
        ]),
    ]


def display_sheet():
    fpc = {"1": None, "2": "EPD_GDR", "3": "EPD_RESE", "4": "EPD_VGL", "5": "EPD_VGH", "6": None, "7": None,
           "8": "GND", "9": "EPD_BUSY", "10": "EPD_RST", "11": "EPD_DC", "12": "EPD_CS", "13": "EPD_SCK",
           "14": "EPD_MOSI", "15": "+3V3", "16": "+3V3", "17": "GND", "18": "EPD_VDD", "19": None,
           "20": "EPD_VSH", "21": "EPD_PREVGH", "22": "EPD_VSL", "23": "EPD_PREVGL", "24": "EPD_VCOM"}
    c50 = lambda net: C("1uF/50V", net, fp=C0603)  # noqa: E731
    return [
        ("E-paper GDEY037T03 (UC8253), 24-pin FPC: the reference circuit in the GDEY037T03-T02 spec (p. 35), 0.47 R sense for UC driver ICs. BS1 low = 4-wire SPI", [
            Part("J", "Connector_Generic:Conn_01x24", "E-paper FPC",
                 {k: v for k, v in fpc.items() if v}, "Connector_FFC-FPC:Jushuo_AFC07-S24FCA-00_1x24-1MP_P0.50_Horizontal",
                 "C262567", nc=[k for k, v in fpc.items() if not v],
                 note="pin 1 NC, 6/7 temperature sensor I2C unused, 19 VPP (test pin) left open as in the "
                      "reference circuit. Bottom contact: the ribbon's gold faces the display and turns "
                      "towards the board when folded under the panel"),
            L("10uH", "+3V3", "EPD_SW", L3015), C("4.7uF/50V", "+3V3", fp=C0805),
            Part("Q", "Transistor_FET:Q_NMOS_GSD", "Si1308EDL", {"G": "EPD_GDR", "S": "EPD_RESE", "D": "EPD_SW"},
                 "Package_TO_SOT_SMD:SOT-323_SC-70", "C469327"),
            R("1M", "EPD_GDR", "GND", fp=R0603), R("0.47", "EPD_RESE", "GND", fp=R0603),
            Part("D", "Device:D_Schottky", "MBR0530", {"A": "EPD_SW", "K": "EPD_PREVGH"}, "Diode_SMD:D_SOD-123", "C77336"),
            Part("D", "Device:D_Schottky", "MBR0530", {"A": "EPD_NEG", "K": "GND"}, "Diode_SMD:D_SOD-123", "C77336"),
            Part("D", "Device:D_Schottky", "MBR0530", {"A": "EPD_PREVGL", "K": "EPD_NEG"}, "Diode_SMD:D_SOD-123", "C77336"),
            C("4.7uF/50V", "EPD_SW", "EPD_NEG", fp=C0805),
            c50("EPD_VGL"), c50("EPD_VGH"), c50("+3V3"), c50("EPD_VDD"), c50("EPD_VSH"),
            c50("EPD_PREVGH"), c50("EPD_VSL"), c50("EPD_PREVGL"), c50("EPD_VCOM"),
        ]),
        ("Touch FT6336U, 6-pin FPC (Good Display TP037-S02: 1 GND, 2 VDD, 3 RST, 4 INT, 5 SDA, 6 SCL), I2C address 0x38", [
            Part("J", "Connector_Generic:Conn_01x06", "Touch FPC",
                 {"1": "GND", "2": "+3V3", "3": "TP_RST", "4": "TP_INT", "5": "I2C_SDA", "6": "I2C_SCL"},
                 "Connector_FFC-FPC:Jushuo_AFC07-S06FCA-00_1x6-1MP_P0.50_Horizontal", "C262553",
                 note="bottom contact, like the e-paper connector; the 56 mm touch tail folds flat under the panel"),
            C("1uF", "+3V3"), R("10k", "+3V3", "TP_RST"), R("10k", "+3V3", "TP_INT"),
        ]),
    ]


def usb_storage_sheet():
    return [
        ("USB-C (16-pin) with ESD protection; CC handled by TUSB320L (dual-role, I2C 0x47)", [
            Part("J", "Connector:USB_C_Receptacle_USB2.0_16P", "USB-C",
                 {"VBUS": "VBUS", "CC1": "USB_CC1", "CC2": "USB_CC2", "A6": "USB_DP", "B6": "USB_DP",
                  "A7": "USB_DM", "B7": "USB_DM", "GND": "GND", "SHIELD": "GND"},
                 "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12", "C165948", nc=["SBU1", "SBU2"]),
            Part("U", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6",
                 {"1": "USB_DP", "6": "USB_DP", "3": "USB_DM", "4": "USB_DM", "5": "VBUS", "2": "GND"},
                 lcsc="C7519"),
            C("10uF", "VBUS"), C("100nF", "VBUS"),
            Part("U", "Interface_USB:TUSB320", "TUSB320LIRWBR",
                 {"CC1": "USB_CC1", "CC2": "USB_CC2", "VBUS_DET": "TUSB_VDET", "ADDR": "GND",
                  "SDA/OUT1": "I2C_SDA", "SCL/OUT2": "I2C_SCL", "GND": "GND", "~{EN}": "GND", "VDD": "+3V3"},
                 lcsc="C2836598", nc=["PORT", "~{INT}/OUT3", "ID"],
                 note="PORT open = dual role; INT and ID polled over I2C"),
            R("887k", "VBUS", "TUSB_VDET"), C("100nF", "+3V3"),
        ]),
        ("USB switch FSUSB42: USB_DISK low = ESP32, high = card reader", [
            Part("U", "Interface_USB:FSUSB42MUX", "FSUSB42MUX",
                 {"VCC": "+3V3", "SEL": "USB_DISK", "D+": "USB_DP", "D-": "USB_DM", "GND": "GND",
                  "HSD1-": "ESP_USB_DM", "HSD1+": "ESP_USB_DP", "HSD2-": "GL_DM", "HSD2+": "GL_DP",
                  "~{OE}": "GND"}, lcsc="C11355"),
            C("100nF", "+3V3"),
        ]),
        ("Card reader GL823K: runs from VBUS (only when a PC is plugged in), no crystal needed", [
            Part("dap", "dap:GL823K", "GL823K-HCY04",
                 {"5V": "VBUS", "VDD": "GL_3V3", "VDDA": "GL_3V3", "DP": "GL_DP", "DM": "GL_DM", "VSS": "GND",
                  "14": "GND", "CLK": "GL_CLK", "CMD": "GL_CMD", "D0": "GL_D0", "D1": "GL_D1", "D2": "GL_D2",
                  "D3": "GL_D3"}, lcsc="C284879", nc=["GPIO", "LED", "PMOS"],
                 note="VDD/VDDA are its internal 3.3 V; the card itself runs from +3V3"),
            C("4.7uF", "VBUS"), C("1uF", "GL_3V3"), C("100nF", "GL_3V3"),
        ]),
        ("microSD switch TS3A27518E: USB_DISK low = ESP32 (NC side), high = GL823K (NO side)", [
            Part("U", "Analog_Switch:TS3A27518EPW", "TS3A27518EPWR",
                 {"VCC": "+3V3", "GND": "GND", "~{EN}": "GND", "IN1": "USB_DISK", "IN2": "USB_DISK",
                  "COM1": "SDC_CLK", "COM2": "SDC_CMD", "COM3": "SDC_D0", "COM4": "SDC_D1", "COM5": "SDC_D2",
                  "COM6": "SDC_D3", "NC1": "SD_CLK", "NC2": "SD_CMD", "NC3": "SD_D0", "NC4": "SD_D1",
                  "NC5": "SD_D2", "NC6": "SD_D3", "NO1": "GL_CLK", "NO2": "GL_CMD", "NO3": "GL_D0",
                  "NO4": "GL_D1", "NO5": "GL_D2", "NO6": "GL_D3"}, lcsc="C443721"),
            C("100nF", "+3V3"),
        ]),
        ("microSD socket (push-push). 10k pull-ups on CMD and DAT0-3, card powered from +3V3", [
            Part("J", "Connector:Micro_SD_Card", "microSD",
                 {"DAT2": "SDC_D2", "DAT3/CD": "SDC_D3", "CMD": "SDC_CMD", "VDD": "+3V3", "CLK": "SDC_CLK",
                  "VSS": "GND", "DAT0": "SDC_D0", "DAT1": "SDC_D1", "SHIELD": "GND"},
                 "dap:microSD_TF-01A", "C91145",
                 note="Hroparts TF-01A push-push socket; its card-detect contact (pad CD) is not used"),
            R("10k", "+3V3", "SDC_CMD"), R("10k", "+3V3", "SDC_D0"), R("10k", "+3V3", "SDC_D1"),
            R("10k", "+3V3", "SDC_D2"), R("10k", "+3V3", "SDC_D3"), C("10uF", "+3V3"), C("100nF", "+3V3"),
        ]),
    ]


def dac(side, adr, out_a, out_b, detect, master):
    p = f"DAC{side}_"
    nets = {"VL": "1V8_D", "VD": "1V8_D", "VA": "1V8_A", "VCP": "1V8_CP", "VP": "VP",
            "XTI/MCLK": "MCLK", "SCLK1": "SCLK_1V8", "LRCK1": "LRCK_1V8", "SDIN1": "SDIN_1V8",
            "SCL": "I2C_SCL_1V8", "SDA": "I2C_SDA_1V8", "ADR": adr, "~{RESET}": "DAC_RST",
            "GNDD": "GND", "GNDA": "GND", "GNDCP": "GND", "EP": "GND",
            "FILT+": p + "FILTP", "FILT-": p + "FILTN", "-VA": p + "NVA", "FLYP_VA": p + "FLYP_VA",
            "FLYN_VA": p + "FLYN_VA", "VCP_FILT+": p + "VCPF_P", "VCP_FILT-": p + "VCPF_N",
            "FLYP_VCP": p + "FLYP_VCP", "FLYC_VCP": p + "FLYC_VCP", "FLYN_VCP": p + "FLYN_VCP",
            "HPOUTA": out_a, "HPOUTB": out_b, "HPREFA": "HP_GND", "HPREFB": "HP_GND", "HP_DETECT": detect}
    caps = [C("100nF", "1V8_D"), C("100nF", "1V8_D"), C("100nF", "VP"), C("4.7uF", "VP"),
            C("2.2uF", "1V8_A"), C("22uF", p + "FILTP", "1V8_A"), C("22uF", p + "FILTN", p + "NVA"),
            C("2.2uF", p + "NVA"), C("2.2uF", p + "FLYP_VA", p + "FLYN_VA"),
            C("2.2uF", "1V8_CP"), C("2.2uF", p + "VCPF_P"), C("2.2uF", p + "VCPF_N"),
            C("2.2uF", p + "FLYP_VCP", p + "FLYC_VCP"), C("2.2uF", p + "FLYC_VCP", p + "FLYN_VCP")]
    role = "I2S clock master" if master else "I2S clock slave"
    return (f"CS43131 {side} ({role}, mono mode): HPOUTA = {out_a}, HPOUTB = {out_b}. Caps per Cirrus's typical connection diagram", [
        Part("dap", "dap:CS43131", "CS43131-CNZR", nets, lcsc="C965907",
             nc=["XTO", "CLKOUT", "DSDCLK/SCLK2", "DSDB/LRCK2", "DSDA/SDIN2", "~{INT}", "HPINA", "HPINB", "TSO"]),
    ] + caps + ([R("4.99k", "DACR_ADR", "GND")] if adr == "DACR_ADR" else []))


def audio_sheet():
    return [
        ("Level shifting: SN74AVC4T774 (A = 3.3 V ESP32 side, B = 1.8 V DAC side); PCA9306 joins the I2C buses", [
            Part("dap", "dap:SN74AVC4T774", "SN74AVC4T774PWR",
                 {"VCCA": "+3V3", "VCCB": "1V8_D", "DIR1": "GND", "DIR2": "GND", "DIR3": "+3V3", "DIR4": "+3V3",
                  "~{OE}": "GND", "GND": "GND", "A1": "I2S_SCLK", "A2": "I2S_LRCK", "A3": "I2S_SDOUT",
                  "A4": "OSC_SEL", "B1": "SCLK_1V8", "B2": "LRCK_1V8", "B3": "SDIN_1V8", "B4": "OSC_SEL_1V8"},
                 lcsc="C129363", note="bits 1-2 B to A (clocks to ESP32), bits 3-4 A to B"),
            C("100nF", "+3V3"), C("100nF", "1V8_D"),
            Part("U", "Interface:PCA9306", "PCA9306DCUR",
                 {"GND": "GND", "VREF1": "1V8_D", "SCL1": "I2C_SCL_1V8", "SDA1": "I2C_SDA_1V8",
                  "SDA2": "I2C_SDA", "SCL2": "I2C_SCL", "VREF2": "I2C_VREF2", "EN": "I2C_VREF2"},
                 "Package_SO:VSSOP-8_2.3x2mm_P0.5mm", "C33196"),
            R("200k", "+3V3", "I2C_VREF2"), C("100nF", "I2C_VREF2"),
            R("4.7k", "1V8_D", "I2C_SDA_1V8"), R("4.7k", "1V8_D", "I2C_SCL_1V8"),
        ]),
        ("Audio clocks: one oscillator at a time, picked by OSC_SEL (low 22.5792 MHz for 44.1k music, high 24.576 MHz for 48k)", [
            Part("Y", "Oscillator:ASE-xxxMHz", "22.5792MHz",
                 {"EN": "OSC_SEL_N", "GND": "GND", "OUT": "MCLK_441", "Vdd": "1V8_D"}, lcsc="C2901572",
                 note="SX3M22.5792M20F30TNN"),
            Part("Y", "Oscillator:ASE-xxxMHz", "24.576MHz",
                 {"EN": "OSC_SEL_1V8", "GND": "GND", "OUT": "MCLK_48", "Vdd": "1V8_D"}, lcsc="C2901574",
                 note="SX3M24.576M20F30TNN"),
            Part("U", "74xGxx:74LVC1G04", "74LVC1G04",
                 {"2": "OSC_SEL_1V8", "4": "OSC_SEL_N", "GND": "GND", "VCC": "1V8_D"},
                 "Package_TO_SOT_SMD:SOT-23-5", "C33962550"),
            R("22", "MCLK_441", "MCLK"), R("22", "MCLK_48", "MCLK"),
            C("100nF", "1V8_D"), C("100nF", "1V8_D"), C("100nF", "1V8_D"),
        ]),
        dac("L", "GND", "OUT_LP", "OUT_LN", "DET_35", True),
        dac("R", "DACR_ADR", "OUT_RP", "OUT_RN", "DET_44", False),
        ("Headphone jacks, both on the back of the board: they share the outputs; 3.5 mm takes L+ and R+ only. HP_GND joins GND at the jacks", [
            Part("dap", "dap:PJ-342", "PJ-342",
                 {"T": "OUT_LP", "TSW": "DET_35", "R": "OUT_RP", "S": "HP_GND"}, lcsc="C668606", nc=["RSW"],
                 note="TSW touches the tip contact (OUT_LP) while no plug is in and is left floating by a "
                      "plug: the opposite of Cirrus's scheme, so the firmware sets HPDETECT_INV. Hand-soldered"),
            Part("dap", "dap:KH-PJ-44002", "KH-PJ-44002-12DBAP-A",
                 {"L+": "OUT_LP", "L-": "OUT_LN", "R+": "OUT_RP", "R-": "OUT_RN", "S": "HP_GND",
                  "SW_A": "DET_44", "SW_B": "GND"}, lcsc="C42396781",
                 note="its plug switch pulls DET_44 to ground; whether a plug opens or closes it is set "
                      "with HPDETECT_INV once tried. Bought separately and hand-soldered"),
            Part("NT", "Device:NetTie_2", "NetTie", {"1": "HP_GND", "2": "GND"},
                 "NetTie:NetTie-2_SMD_Pad0.5mm"),
        ]),
    ]


SHEETS = [("Power", "power.kicad_sch", power_sheet), ("MCU", "mcu.kicad_sch", mcu_sheet),
          ("Display", "display.kicad_sch", display_sheet), ("USB and storage", "usb_storage.kicad_sch",
                                                                 usb_storage_sheet),
          ("Audio", "audio.kicad_sch", audio_sheet)]


# ---- Drawing

PAPERS = [("A3", 420, 297), ("A2", 594, 420), ("A1", 841, 594)]


def text_w(s):
    return len(s) * 1.3 + 1.5


def wrap(title, width_mm, char_mm=1.3):
    """Splits a group title into lines that fit over the group."""
    n = max(30, int(width_mm / char_mm))
    lines, cur = [], ""
    for word in title.split():
        if cur and len(cur) + 1 + len(word) > n:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return lines + [cur] if cur else lines


class Placed:
    def __init__(self, part, sym, pins):
        self.part, self.sym, self.pins = part, sym, pins


def resolve(part):
    sym = K.flat_symbol(part.lib, PROJECT_LIBS)
    pins = [p for p in K.symbol_pins(sym) if p.unit in (0, 1) and not p.hidden and p.etype != "no_connect"]
    assign = {}
    for key, net in part.nets.items():
        hit = [p for p in pins if p.number == key] or [p for p in pins if p.name == key]
        if not hit:
            sys.exit(f"{part.ref} {part.value}: no pin '{key}'")
        for p in hit:
            assign[p.number] = net
    for key in part.nc:
        hit = [p for p in pins if p.number == key] or [p for p in pins if p.name == key]
        if not hit:
            sys.exit(f"{part.ref} {part.value}: no pin '{key}' (nc)")
        for p in hit:
            assign[p.number] = None
    missing = [f"{p.number}:{p.name}" for p in pins if p.number not in assign]
    if missing:
        sys.exit(f"{part.ref} {part.value}: pins not connected or marked nc: {missing}")
    return sym, pins, assign


def footprint(part, sym):
    if part.fp:
        return part.fp
    props = {str(p[1]): str(p[2]) for p in K.find(sym, "property")}
    return props.get("Footprint", "")


def assign_refs(sheets):
    counters = {}
    for _, _, groups in sheets:
        for _, parts in groups:
            for part in parts:
                prefix = part.prefix
                if prefix == "dap":
                    prefix = CUSTOM[part.lib.split(":")[1]][0]
                part.prefix = prefix
                counters[prefix] = counters.get(prefix, 0) + 1
                part.ref = f"{prefix}{counters[prefix]}"


def build():
    os.makedirs(OUT, exist_ok=True)
    write_custom_lib()
    sheets = [(n, f, fn()) for n, f, fn in SHEETS]
    assign_refs(sheets)

    # Which nets appear on more than one sheet (global labels), which have a driver.
    net_sheets, drivers, power_in = {}, set(), set()
    resolved = {}
    for name, _, groups in sheets:
        for _, parts in groups:
            for part in parts:
                sym, pins, assign = resolve(part)
                resolved[id(part)] = (sym, pins, assign)
                for p in pins:
                    net = assign[p.number]
                    if net:
                        net_sheets.setdefault(net, set()).add(name)
                        if p.etype == "power_out":
                            drivers.add(net)
                        if p.etype == "power_in":
                            power_in.add(net)
    single = [n for n, s in net_sheets.items() if sum(
        1 for _, _, groups in sheets for _, parts in groups for part in parts
        for num, net in resolved[id(part)][2].items() if net == n) < 2 and n not in POWER and n not in POWER_VCC]
    if single:
        sys.exit(f"nets with only one pin: {single}")
    supplies = {n for n in net_sheets if n in POWER or n in POWER_VCC}
    flags = sorted(n for n in supplies | power_in if n not in drivers)

    root_uuid = K.uid()
    pages = []
    report = {"parts": 0, "nets": len(net_sheets), "flags": flags, "fp_missing": []}
    for page, (name, filename, groups) in enumerate(sheets, start=2):
        sheet = K.Sheet(name, filename)
        draw_sheet(sheet, groups, resolved, net_sheets, root_uuid, flags, report)
        pages.append((sheet, page))
        report["parts"] += sum(len(p) for _, p in groups)
    write_root(root_uuid, pages)
    for sheet, _ in pages:
        sheet.write(os.path.join(OUT, sheet.filename), root_uuid)
    with open(os.path.join(OUT, "sym-lib-table"), "w") as f:
        f.write('(sym_lib_table\n\t(version 7)\n\t(lib (name "dap") (type "KiCad") '
                '(uri "${KIPRJMOD}/dap.kicad_sym") (options "") (descr "E-ink DAP parts"))\n)\n')
    with open(os.path.join(OUT, "fp-lib-table"), "w") as f:
        f.write('(fp_lib_table\n\t(version 7)\n\t(lib (name "dap") (type "KiCad") '
                '(uri "${KIPRJMOD}/dap.pretty") (options "") (descr "E-ink DAP stand-in footprints, '
                'written by tools/make_pcb.py"))\n)\n')
    pro = os.path.join(OUT, f"{PROJECT}.kicad_pro")
    if not os.path.exists(pro):
        with open(pro, "w") as f:
            json.dump({"meta": {"filename": f"{PROJECT}.kicad_pro", "version": 3}}, f, indent=2)
    print(f"schematic: {report['parts']} parts, {report['nets']} nets on {len(pages)} sheets")
    print(f"schematic: power flags on {', '.join(report['flags'])}")
    if report["fp_missing"]:
        print("schematic: footprints not in KiCad's libraries:", ", ".join(report["fp_missing"]))
    check(sheets, resolved)


KICAD_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"


def check(sheets, resolved):
    """Runs KiCad's ERC, then reads KiCad's own netlist back and checks that it joins
    exactly the pins the design table joins: no net split in two, no two nets merged."""
    import subprocess
    import tempfile
    if not os.path.exists(KICAD_CLI):
        print("check: kicad-cli not found, skipped")
        return
    sch = os.path.join(OUT, f"{PROJECT}.kicad_sch")
    with tempfile.TemporaryDirectory() as tmp:
        erc = os.path.join(tmp, "erc.json")
        subprocess.run([KICAD_CLI, "sch", "erc", "--format", "json", "--severity-all", "-o", erc, sch],
                       capture_output=True)
        found = [(s["path"], v["type"], v["description"]) for s in json.load(open(erc))["sheets"]
                 for v in s["violations"]]
        print(f"check: ERC {len(found)} violations")
        for v in found[:20]:
            print("   ", *v)
        net = os.path.join(tmp, "dap.net")
        subprocess.run([KICAD_CLI, "sch", "export", "netlist", "-o", net, sch], capture_output=True)
        tree = K.parse(open(net, encoding="utf-8").read())[0]
    kicad = {}  # (ref, pin) -> KiCad net name
    for n in K.find(K.first(tree, "nets"), "net"):
        name = str(K.first(n, "name")[1])
        for node in K.find(n, "node"):
            kicad[(str(K.first(node, "ref")[1]), str(K.first(node, "pin")[1]))] = name
    want = {}  # design net -> pins
    for _, _, groups in sheets:
        for _, parts in groups:
            for part in parts:
                for num, netname in resolved[id(part)][2].items():
                    if netname:
                        want.setdefault(netname, set()).add((part.ref, num))
    problems = []
    seen = {}
    for netname, pins in want.items():
        got = {kicad.get(p, "?") for p in pins}
        if len(got) != 1:
            problems.append(f"{netname} is split across KiCad nets {sorted(got)}")
            continue
        k = got.pop()
        if k in seen:
            problems.append(f"{netname} and {seen[k]} are joined in KiCad net {k}")
        seen[k] = netname
        extra = {p for p, n in kicad.items() if n == k and p not in pins and not p[0].startswith("#")}
        stacked = {p for p in extra if p[0] in {r for r, _ in pins}}
        if extra - stacked:
            problems.append(f"{netname} also reaches {sorted(extra - stacked)}")
    print(f"check: netlist {len(want)} nets compared, {len(problems)} problems")
    for p in problems[:30]:
        print("   ", p)


def draw_sheet(sheet, groups, resolved, net_sheets, root_uuid, flags, report):
    lib_cache = {}

    def lib(lid):
        if lid not in lib_cache:
            lib_cache[lid] = K.flat_symbol(lid, PROJECT_LIBS)
        return lib_cache[lid]

    placements = []  # (part, x, y)
    x, y, band_h = 20.32, 50.8, 0.0
    sheet.paper = PAPERS[-1][0]
    for paper, pw, ph in PAPERS:
        if fits(groups, resolved, pw - 40, ph - 70):
            sheet.paper = paper
            break
    pw = dict((p, w) for p, w, _ in PAPERS)[sheet.paper]
    max_x = pw - 20
    flags_here = []
    for title, parts in groups:
        gw, gh, layout = group_layout(parts, resolved)
        lines = wrap(title, gw)
        th = 2.54 * len(lines)
        if x + gw > max_x and x > 21:
            x, y = 20.32, y + band_h + 12.7
            band_h = 0
        for i, line in enumerate(lines):
            sheet.text(line, x, y - 5.08 + i * 2.54, 1.5)
        for part, dx, dy in layout:
            placements.append((part, K.snap(x + dx), K.snap(y + th + dy)))
        x += gw + 12.7
        band_h = max(band_h, gh + th)

    for part, px, py in placements:
        sym, pins, assign = resolved[id(part)]
        fields = {"Footprint": footprint(part, sym), "Datasheet": ""}
        if part.lcsc:
            fields["LCSC"] = part.lcsc
        if part.note:
            fields["Note"] = part.note
        if fields["Footprint"] and not fields["Footprint"].startswith("dap:") and \
                not K.footprint_exists(fields["Footprint"]):
            report["fp_missing"].append(f"{part.ref} {fields['Footprint']}")
        sheet.symbol(sym, px, py, part.ref, part.value, fields, PROJECT, root_uuid)
        for p in pins:
            net = assign[p.number]
            ex, ey = px + p.x, py - p.y
            dx, dy = p.outward()
            if net is None:
                sheet.no_connect(ex, ey)
                continue
            sx, sy = ex + dx * K.STUB, ey + dy * K.STUB
            sheet.wire(ex, ey, sx, sy)
            if net in POWER or net in POWER_VCC:
                place_power(sheet, net, sx, sy, (dx, dy), root_uuid, lib)
                if net in flags and net not in FLAGGED:
                    flags_here.append(net)
                    FLAGGED.add(net)
            else:
                lbl_dir = (dx, dy) if dy == 0 else (1, 0)
                sheet.label(net, sx, sy, lbl_dir, glob=len(net_sheets[net]) > 1)
                if net in flags and net not in FLAGGED:
                    flags_here.append(net)
                    FLAGGED.add(net)
    # Power flags for nets nothing drives (connectors, ferrite beads), drawn top right
    fx = K.snap(max_x - 15)
    for i, net in enumerate(flags_here):
        fy = 20.32 + i * 10.16
        if net in POWER or net in POWER_VCC:
            place_power(sheet, net, fx, fy, (0, -1) if net != "GND" else (0, 1), root_uuid, lib)
        else:
            sheet.label(net, fx, fy, (-1, 0), glob=len(net_sheets[net]) > 1)
        flag = lib("power:PWR_FLAG")
        _power_count[0] += 1
        sheet.symbol(flag, fx, fy, f"#FLG{_power_count[0]:03d}", "PWR_FLAG", {}, PROJECT, root_uuid,
                     rot=180 if net != "GND" else 0)


FLAGGED = set()
_power_count = [0]


def place_power(sheet, net, x, y, direction, root_uuid, lib):
    lid = POWER.get(net, "power:VCC")
    sym = lib(lid)
    up = lid != "power:GND"   # supply symbols point up, ground points down by default
    body = (0, -1) if up else (0, 1)
    rot = {((0, -1), (0, -1)): 0, ((0, -1), (-1, 0)): 90, ((0, -1), (0, 1)): 180, ((0, -1), (1, 0)): 270,
           ((0, 1), (0, 1)): 0, ((0, 1), (1, 0)): 90, ((0, 1), (0, -1)): 180, ((0, 1), (-1, 0)): 270}[
        (body, direction)]
    _power_count[0] += 1
    # Name beside the symbol's far end, horizontal, clear of the part it hangs off
    dx, dy = direction
    if dy == 0:
        value_at = (x + dx * 4.6, y, "right" if dx < 0 else "left", net == "GND")
    else:
        value_at = (x + 1.0, y + dy * (3.3 if not up or dy < 0 else 4.2), "left", net == "GND")
    sheet.symbol(sym, x, y, f"#PWR0{_power_count[0]:03d}", net, {}, PROJECT, root_uuid, rot=rot,
                 value_at=value_at)


def pin_extent(pins, assign):
    """Room the labels need on each side of a symbol: (left, right, top, bottom)."""
    left = right = top = bottom = 0.0
    for p in pins:
        net = assign[p.number] or ""
        dx, dy = p.outward()
        w = K.STUB + (6 if (net in POWER or net in POWER_VCC) else text_w(net) + 3)
        if dx < 0:
            left = max(left, w)
        elif dx > 0:
            right = max(right, w)
        elif dy < 0:
            top = max(top, K.STUB + 5)
            right = max(right, text_w(net) - 2)
        else:
            bottom = max(bottom, K.STUB + 6)
            right = max(right, text_w(net) - 2)
    return left, right, top, bottom


def group_layout(parts, resolved):
    main, helpers = parts[0], parts[1:]
    sym, pins, assign = resolved[id(main)]
    x0, y0, x1, y1 = K.symbol_box(sym)
    l, r, t, b = pin_extent(pins, assign)
    ref_w = text_w(main.value) + 4
    mw = l + (x1 - x0) + max(r, ref_w)
    layout = [(main, l - x0, t - y0 + 2.54)]
    mh = t + (y1 - y0) + b + 5.08
    # helpers in rows, as wide as the main part allows (at least 120 mm)
    row_w = max(mw, 120.0)
    cx, cy, row_h = 0.0, mh, 0.0
    total_w = mw
    for h in helpers:
        hs, hp, ha = resolved[id(h)]
        hx0, hy0, hx1, hy1 = K.symbol_box(hs)
        hl, hr, ht, hb = pin_extent(hp, ha)
        cw = hl + (hx1 - hx0) + max(hr, text_w(h.value) + 3, text_w(h.ref) + 3) + 2.54
        ch = max(ht + (hy1 - hy0) + hb + 2.54, 15.24)
        if all(p.angle % 180 == 0 for p in hp):  # sideways part: room for its names above
            ht += 7.62
            ch += 7.62
        if cx + cw > row_w and cx > 0:
            cx, cy = 0.0, cy + row_h + 2.54
            row_h = 0.0
        layout.append((h, cx + hl - hx0, cy + ht - hy0))
        cx += cw
        row_h = max(row_h, ch)
        total_w = max(total_w, cx)
    return total_w, cy + row_h, layout


def fits(groups, resolved, w, h):
    x, y, band = 0.0, 0.0, 0.0
    for title, parts in groups:
        gw, gh, _ = group_layout(parts, resolved)
        gh += 2.54 * len(wrap(title, gw))
        if gw > w:
            return False
        if x + gw > w and x > 0:
            x, y, band = 0.0, y + band + 12.7, 0.0
        x += gw + 12.7
        band = max(band, gh)
    return y + band <= h


def write_root(root_uuid, pages):
    items = []
    x, y = 25.4, 60.96
    for sheet, page in pages:
        w, h = 60.96, 30.48
        items.append(["sheet", ["at", x, y], ["size", w, h], ["exclude_from_sim", "no"], ["in_bom", "yes"],
                      ["on_board", "yes"], ["dnp", "no"], ["fields_autoplaced", "yes"],
                      ["stroke", ["width", 0.1524], ["type", "solid"]], ["fill", ["color", 0, 0, 0, 0.0]],
                      ["uuid", sheet.block_uuid],
                      ["property", Q("Sheetname"), Q(sheet.name), ["at", x, y - 0.7, 0],
                       K.font(justify="left bottom")],
                      ["property", Q("Sheetfile"), Q(sheet.filename), ["at", x, y + h + 0.6, 0],
                       K.font(justify="left top")],
                      ["instances", ["project", Q(PROJECT), ["path", Q(f"/{root_uuid}"), ["page", Q(str(page))]]]]])
        x += w + 12.7
        if x > 330:
            x, y = 25.4, y + h + 20.32
    notes = [
        ("E-ink DAP player board, Phase 2", 25.4, 25.4, 3.0),
        ("Generated by tools/make_schematic.py from the plan in docs/pcb_plan.md. Change the script, not the sheets.",
         25.4, 35.56, 1.8),
        ("Sheets connect through global labels with the same name; supply nets use power symbols.", 25.4, 40.64, 1.8),
        ("Footprints are the chosen parts' own (see docs/pcb_plan.md); both headphone jacks sit on the back.",
         25.4, 45.72, 1.8),
    ]
    for s, nx, ny, size in notes:
        items.append(["text", Q(s), ["exclude_from_sim", "no"], ["at", nx, ny, 0], K.font(size, justify="left"),
                      ["uuid", K.uid()]])
    tree = ["kicad_sch", ["version", 20250114], ["generator", Q("eeschema")], ["generator_version", Q("10.0")],
            ["uuid", root_uuid], ["paper", Q("A3")], ["lib_symbols"]] + items + [
        ["sheet_instances", ["path", Q("/"), ["page", Q("1")]]]]
    with open(os.path.join(OUT, f"{PROJECT}.kicad_sch"), "w", encoding="utf-8") as f:
        f.write(K.dump(tree) + "\n")


if __name__ == "__main__":
    build()
