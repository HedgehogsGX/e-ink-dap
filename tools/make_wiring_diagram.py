#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# ///
"""Draws the Phase 1 breadboard wiring map from include/pins.h into docs/phase1_wiring.svg:

    uv run tools/make_wiring_diagram.py

Top: the DevKitC-1 as it sits in the breadboard (component side up, USB ports pointing
away from you), every header pin with its silkscreen name and where its wire goes.
Bottom: the FTS02's 2x20 socket seen from the back of the FTS02, as it lies while you plug
the wires in. The header order is Espressif's DevKitC-1 (v1.0/v1.1);
docs/phase1_assembly.md says to check it against the board's own labels.
"""
import re
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs/phase1_wiring.svg"

# DevKitC-1 headers, pin 1 first (the antenna end).
J1 = ["3V3", "3V3", "RST", "4", "5", "6", "7", "15", "16", "17", "18", "8", "3", "46", "9", "10", "11", "12", "13",
      "14", "5V", "G"]
J3 = ["G", "TX", "RX", "1", "2", "42", "41", "40", "39", "38", "37", "36", "35", "0", "45", "48", "47", "21", "20",
      "19", "G", "G"]

GROUPS = {  # key: (colour, legend)
    "epd": ("#1f6fd1", "E-paper (FTS02 socket)"),
    "touch": ("#8b3fc8", "Touch (FTS02 socket)"),
    "sd": ("#14915a", "microSD breakout"),
    "dac": ("#e07000", "DAC board"),
    "btn": ("#0f8b96", "Keys"),
    "3v3": ("#d62828", "3.3 V (red + rail)"),
    "gnd": ("#222222", "GND (blue - rail)"),
}

# pins.h constant -> (group, FTS02 socket pin or None, socket/other-end name)
WIRES = {
    "PIN_EPD_CS": ("epd", 24, "CS"),
    "PIN_EPD_MOSI": ("epd", 19, "SPI_MOSI"),
    "PIN_EPD_SCK": ("epd", 23, "SPI_SCK"),
    "PIN_EPD_DC": ("epd", 22, "D/C"),
    "PIN_EPD_RST": ("epd", 11, "RES"),
    "PIN_EPD_BUSY": ("epd", 18, "BUSY"),
    "PIN_TOUCH_SDA": ("touch", 33, "TP_SDA"),
    "PIN_TOUCH_SCL": ("touch", 31, "TP_SCL"),
    "PIN_TOUCH_INT": ("touch", 35, "TP_INT"),
    "PIN_TOUCH_RST": ("touch", 37, "TP_RST"),
    "PIN_SD_CLK": ("sd", None, "microSD CLK"),
    "PIN_SD_CMD": ("sd", None, "microSD CMD  +10k"),
    "PIN_SD_D0": ("sd", None, "microSD D0  +10k"),
    "PIN_SD_D1": ("sd", None, "microSD D1  +10k"),
    "PIN_SD_D2": ("sd", None, "microSD D2  +10k"),
    "PIN_SD_D3": ("sd", None, "microSD D3  +10k"),
    "PIN_I2S_MCK": ("dac", None, "DAC board MCK"),
    "PIN_I2S_BCK": ("dac", None, "DAC board BCK"),
    "PIN_I2S_LRCK": ("dac", None, "DAC board LRCK"),
    "PIN_I2S_DATA": ("dac", None, "DAC board DATA"),
    "PIN_BTN_PLAY": ("btn", None, "Play key"),
    "PIN_BTN_VOL_UP": ("btn", None, "Vol+ key"),
    "PIN_BTN_VOL_DOWN": ("btn", None, "Vol- key"),
    "PIN_BTN_POWER": ("btn", None, "Power key"),
}
# Socket pins fed from the rails, not from a GPIO.
SOCKET_POWER = {1: ("3v3", "3.3V", "red rail"), 6: ("gnd", "GND", "blue rail"), 25: ("gnd", "GND", "blue rail")}
SOCKET_EMPTY_5V = (2, 4)


def read_pins(path):
    """PIN_* constants from pins.h, following its #if DEVKITC_REV branches."""
    text = path.read_text()
    rev = int(re.search(r"#define DEVKITC_REV (\d+)", text).group(1))
    pins, stack = {}, []  # one [some branch taken, this branch active] per open #if
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"#(if|elif) DEVKITC_REV == (\d+)", s)
        if s.startswith(("#ifdef", "#ifndef")):
            stack.append([True, True])
        elif m and m.group(1) == "if":
            active = rev == int(m.group(2))
            stack.append([active, active])
        elif m:
            active = not stack[-1][0] and rev == int(m.group(2))
            stack[-1] = [stack[-1][0] or active, active]
        elif s == "#else":
            stack[-1] = [True, not stack[-1][0]]
        elif s == "#endif":
            stack.pop()
        elif all(active for _, active in stack):
            m = re.match(r"constexpr int (PIN_\w+)\s*=\s*(-?\w+);", s)
            if m:
                v = m.group(2)
                pins[m.group(1)] = int(v) if v.lstrip("-").isdigit() else pins[v]
    return pins


class Svg:
    def __init__(self, w, h):
        self.w, self.h, self.parts = w, h, []

    def add(self, s):
        self.parts.append(s)

    def rect(self, x, y, w, h, fill, stroke="none", rx=0, sw=1):
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" '
                 f'stroke-width="{sw}"/>')

    def circle(self, x, y, r, fill, stroke="none", sw=1.5):
        self.add(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')

    def line(self, x1, y1, x2, y2, stroke, sw=2):
        self.add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{sw}"/>')

    def text(self, x, y, s, size=13, fill="#222", anchor="start", weight="normal"):
        self.add(f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
                 f'font-weight="{weight}">{escape(s)}</text>')

    def save(self, path):
        path.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}" font-family="Helvetica, Arial, sans-serif">\n'
            f'<rect width="100%" height="100%" fill="#ffffff"/>\n' + "\n".join(self.parts) + "\n</svg>\n")


def gpio_wires(pins):
    """GPIO number (as the silkscreen prints it) -> (group, label for the DevKitC map)."""
    out = {}
    for name, (group, socket, what) in WIRES.items():
        label = f"FTS02 socket {socket} · {what}" if socket else what
        out[str(pins[name])] = (group, label)
    return out


def draw_devkit(svg, pins, top):
    wires = gpio_wires(pins)
    pitch, cx = 30, 600
    left_pin, right_pin = cx - 75, cx + 75
    left_hole, right_hole = left_pin - pitch, right_pin + pitch
    y0 = top + 70
    board_top, board_bot = top + 40, y0 + 21 * pitch + 45

    svg.text(cx, top, "DevKitC-1 in the breadboard, seen from above", 18, anchor="middle", weight="bold")
    svg.text(cx, top + 20, "USB ports point to the far end of the breadboard. Rows are counted from that end.",
             13, "#555", "middle")
    for ux in (cx - 45, cx + 15):  # the two USB-C ports
        svg.rect(ux, board_top - 14, 30, 18, "#9aa0a6", "#5f6368", 3)
    svg.rect(cx - 90, board_top, 180, board_bot - board_top, "#1d2127", rx=6)
    svg.rect(cx - 30, board_bot - 220, 60, 205, "#c9ccd1", "#8a8f96", 4)  # module shield
    svg.text(cx, board_bot - 112, "module", 12, "#333", "middle")
    svg.text(cx, board_bot + 18, "antenna end", 12, "#777", "middle")
    svg.text(left_hole + 8, y0 - 26, "free hole", 11, "#777", "end")
    svg.text(right_hole - 8, y0 - 26, "free hole", 11, "#777", "start")
    svg.text(70, y0 - 26, "row", 11, "#777", "middle")
    svg.text(left_hole - 60, y0 - 26, "LEFT side", 13, "#333", "end", "bold")
    svg.text(right_hole + 60, y0 - 26, "RIGHT side", 13, "#333", "start", "bold")
    svg.text(1130, y0 - 26, "row", 11, "#777", "middle")

    sides = (
        (list(reversed(J3)), left_pin, left_hole, -1),
        (list(reversed(J1)), right_pin, right_hole, 1),
    )
    used_3v3 = False
    for names, pin_x, hole_x, d in sides:
        for row, name in enumerate(names):
            y = y0 + row * pitch
            group, label = wires.get(name, (None, ""))
            if name == "3V3" and d == 1 and row == len(names) - 1 and not used_3v3:
                group, label, used_3v3 = "3v3", "red + rail (3.3 V)", True
            if name == "G" and d == -1 and row == 0:
                group, label = "gnd", "blue - rail (GND), over the USB end"
            warn = name == "5V"
            if warn:
                label = "5V: never connect anything"
            colour = GROUPS[group][0] if group else ("#d62828" if warn else "#b0b4ba")
            svg.rect(pin_x - 6, y - 6, 12, 12, "#d8b24a" if group else "#8d7a3c")
            svg.text(pin_x - d * 14, y + 4, name, 12, "#ffffff" if group or warn else "#9aa0a6",
                     "end" if d == 1 else "start", "bold" if group else "normal")
            svg.circle(hole_x, y, 5, colour if group else "#ffffff", colour if group else "#c4c7cc")
            if label:
                svg.line(hole_x + d * 6, y, hole_x + d * 22, y, colour, 2.5)
                svg.text(hole_x + d * 28, y + 4, label, 13, colour, "start" if d == 1 else "end",
                         "bold" if warn else "normal")
            svg.text(70 if d == -1 else 1130, y + 4, str(row + 1), 11, "#999", "middle")
    return board_bot + 30


def draw_socket(svg, pins, top):
    wires = {sock: (group, what, f"GPIO{pins[name]}")
             for name, (group, sock, what) in WIRES.items() if sock}
    wires.update(SOCKET_POWER)
    pitch, right = 50, 1075
    inner_y, edge_y = top + 130, top + 180
    left = right - 19 * pitch

    svg.text(600, top, "FTS02 2×20 socket, seen from the back of the FTS02", 18, anchor="middle", weight="bold")
    svg.text(600, top + 20, "Board face-down, socket edge towards you, “P1” at the right (as in your photo). "
             "Column n from the right holds pin 2n−1 (edge row) and 2n (inner row).", 13, "#555", "middle")
    svg.rect(left - 55, top + 80, 19 * pitch + 120, edge_y - top - 35, "#1f4f9c", rx=6)
    svg.rect(left - 22, inner_y - 20, 19 * pitch + 44, 90, "#15171a", rx=3)
    svg.text(left - 30, inner_y + 5, "40", 13, "#ffffff", "end")
    svg.text(left - 30, edge_y + 5, "39", 13, "#ffffff", "end")
    svg.text(right + 30, inner_y + 5, "2", 13, "#ffffff")
    svg.text(right + 30, edge_y + 5, "P1", 13, "#ffffff", weight="bold")
    svg.text(right - 2 * pitch, inner_y - 26, "GND", 11, "#ffffff", "middle")  # silkscreen over pin 6
    svg.text(600, edge_y + 38, "board edge (nearest you)", 11, "#c9d6ee", "middle")

    for col in range(20):
        x = right - col * pitch
        for pin, y in ((2 * col + 1, edge_y), (2 * col + 2, inner_y)):
            group, what, src = wires.get(pin, (None, "", ""))
            five = pin in SOCKET_EMPTY_5V
            fill = GROUPS[group][0] if group else "#2a2d31"
            svg.rect(x - 15, y - 15, 30, 30, fill, "#d62828" if five else "#55595f", 3, 2.5 if five else 1)
            svg.text(x, y + 4, str(pin), 11, "#ffffff" if group else "#8a8f96", "middle")
            if five:
                group, what, src = "3v3", "5V", "empty!"
            if not group:
                continue
            colour = GROUPS[group][0]
            if y == edge_y:
                svg.text(x, edge_y + 68, what, 11, colour, "middle", "bold")
                svg.text(x, edge_y + 82, src, 11, colour, "middle")
            else:
                svg.text(x, top + 52, what, 11, colour, "middle", "bold")
                svg.text(x, top + 66, src, 11, colour, "middle")
    return edge_y + 100


def draw_legend(svg, top):
    x = 60
    for colour, name in GROUPS.values():
        svg.rect(x, top - 11, 14, 14, colour, rx=2)
        svg.text(x + 20, top, name, 13)
        x += 30 + 7.2 * len(name)
    svg.text(600, top + 30, "Every hole not marked stays empty. Never connect the DevKitC's 5V pin or the socket's "
             "5V pins (2, 4).", 13, "#d62828", "middle", "bold")


def main():
    pins = read_pins(ROOT / "include/pins.h")
    svg = Svg(1200, 0)
    svg.text(600, 36, "Phase 1 wiring map", 24, anchor="middle", weight="bold")
    svg.text(600, 58, "Made from include/pins.h by tools/make_wiring_diagram.py · guide: docs/phase1_assembly.md",
             12, "#777", "middle")
    y = draw_devkit(svg, pins, 100)
    y = draw_socket(svg, pins, y + 20)
    draw_legend(svg, y + 30)
    svg.h = y + 90
    svg.save(OUT)
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
