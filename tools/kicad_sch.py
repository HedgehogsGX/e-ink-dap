"""Small toolkit for writing KiCad schematics from Python: reads symbols from KiCad's
libraries (and our own), places them, and connects pins with short wires and net labels.
Used by tools/make_schematic.py. Plain Python 3, no dependencies.

Coordinates are in mm, schematic Y grows downward. Symbols are placed unrotated, so a pin
at (px, py) in the library sits at (x + px, y - py) on the sheet.
"""
import math
import os
import re
import uuid as uuidlib

KICAD_SYMBOLS = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"
KICAD_FOOTPRINTS = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
GRID = 1.27
STUB = 2.54


# ---- S-expressions

class Q(str):
    """A quoted string in an S-expression."""


_TOKEN = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+')


def parse(text):
    stack, cur = [], []
    for m in _TOKEN.finditer(text):
        t = m.group(0)
        if t == "(":
            stack.append(cur)
            cur = []
        elif t == ")":
            done = cur
            cur = stack.pop()
            cur.append(done)
        elif t[0] == '"':
            cur.append(Q(t[1:-1].replace('\\"', '"').replace("\\\\", "\\")))
        else:
            cur.append(t)
    return cur


def dump(node, indent=0):
    if isinstance(node, list):
        if not node:
            return "()"
        simple = all(not isinstance(x, list) for x in node)
        if simple:
            return "(" + " ".join(dump(x) for x in node) + ")"
        pad = "\t" * (indent + 1)
        head = []
        rest = []
        for i, x in enumerate(node):
            if not isinstance(x, list) and not rest:
                head.append(dump(x))
            else:
                rest.append(x)
        return ("(" + " ".join(head) + "".join("\n" + pad + dump(x, indent + 1) for x in rest)
                + "\n" + "\t" * indent + ")")
    if isinstance(node, Q):
        return '"' + node.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(node, float):
        s = f"{node:.4f}".rstrip("0").rstrip(".")
        return "0" if s in ("-0", "") else s
    return str(node)


def find(node, key):
    return [x for x in node if isinstance(x, list) and x and x[0] == key]


def first(node, key):
    r = find(node, key)
    return r[0] if r else None


def uid():
    return Q(str(uuidlib.uuid4()))


# ---- Symbol libraries

_LIBS = {}


def load_lib(path):
    if path not in _LIBS:
        with open(path, encoding="utf-8") as f:
            tree = parse(f.read())[0]
        _LIBS[path] = {str(s[1]): s for s in find(tree, "symbol")}
    return _LIBS[path]


def lib_path(nick, project_libs):
    if nick in project_libs:
        return project_libs[nick]
    return os.path.join(KICAD_SYMBOLS, nick + ".kicad_sym")


def flat_symbol(lib_id, project_libs):
    """The library symbol for "Lib:Name", with any `extends` resolved, renamed to lib_id."""
    nick, name = lib_id.split(":", 1)
    syms = load_lib(lib_path(nick, project_libs))
    sym = syms[name]
    ext = first(sym, "extends")
    if ext:
        parent = flat_symbol(f"{nick}:{ext[1]}", project_libs)
        pname = str(ext[1])
        out = [x for x in parent if not (isinstance(x, list) and x[0] == "property")]
        out = [x if not (isinstance(x, list) and x[0] == "symbol")
               else ["symbol", Q(str(x[1]).replace(pname, name, 1))] + x[2:] for x in out]
        props = find(sym, "property")
        out = out[:2] + [x for x in out[2:] if not (isinstance(x, list) and x[0] in
                         ("symbol", "embedded_fonts"))] + props + [
            x for x in out[2:] if isinstance(x, list) and x[0] in ("symbol", "embedded_fonts")]
        sym = out
    sym = [x for x in sym if not (isinstance(x, list) and x[0] == "extends")]
    return ["symbol", Q(lib_id)] + sym[2:]


class Pin:
    def __init__(self, number, name, etype, x, y, angle, unit, hidden):
        self.number, self.name, self.etype = number, name, etype
        self.x, self.y, self.angle, self.unit, self.hidden = x, y, angle, unit, hidden

    def outward(self):
        """Unit vector on the sheet pointing away from the symbol body."""
        return {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}[self.angle % 360]


def symbol_pins(sym):
    pins = []
    for sub in find(sym, "symbol"):
        m = re.match(r".*_(\d+)_(\d+)$", str(sub[1]))
        unit = int(m.group(1)) if m else 1
        for p in find(sub, "pin"):
            at = first(p, "at")
            name = first(p, "name")
            num = first(p, "number")
            hidden = "hide" in p or any(isinstance(x, list) and x[:2] == ["hide", "yes"] for x in p)
            pins.append(Pin(str(num[1]), str(name[1]), str(p[1]), float(at[1]), float(at[2]),
                            int(float(at[3])) if len(at) > 3 else 0, unit, hidden))
    return pins


def symbol_box(sym):
    """Bounding box (x0, y0, x1, y1) of a symbol on the sheet, relative to its origin."""
    xs, ys = [0.0], [0.0]
    for p in symbol_pins(sym):
        xs.append(p.x)
        ys.append(-p.y)
    for sub in find(sym, "symbol"):
        for g in sub[2:]:
            if isinstance(g, list) and g[0] == "rectangle":
                for k in ("start", "end"):
                    pt = first(g, k)
                    xs.append(float(pt[1]))
                    ys.append(-float(pt[2]))
    return min(xs), min(ys), max(xs), max(ys)


def body_box(sym):
    """Box of a symbol's drawn body (its rectangles), without the pins."""
    xs, ys = [], []
    for sub in find(sym, "symbol"):
        for g in sub[2:]:
            if isinstance(g, list) and g[0] == "rectangle":
                for k in ("start", "end"):
                    pt = first(g, k)
                    xs.append(float(pt[1]))
                    ys.append(-float(pt[2]))
    if not xs:
        return symbol_box(sym)
    return min(xs), min(ys), max(xs), max(ys)


def footprint_exists(fp):
    if not fp or ":" not in fp:
        return False
    lib, name = fp.split(":", 1)
    return os.path.exists(os.path.join(KICAD_FOOTPRINTS, lib + ".pretty", name + ".kicad_mod"))


# ---- Writing a sheet

def font(size=1.27, justify=None, hide=False, bold=False):
    f = ["font", ["size", size, size]]
    if bold:
        f.append(["bold", "yes"])
    e = ["effects", f]
    if justify:
        e.append(["justify"] + justify.split())
    if hide:
        e.append(["hide", "yes"])
    return e


def snap(v):
    return round(v / GRID) * GRID


class Sheet:
    def __init__(self, name, filename, paper="A3"):
        self.name, self.filename, self.paper = name, filename, paper
        self.uuid = uid()        # the sheet file's own uuid
        self.block_uuid = uid()  # the sheet box on the root sheet; symbol paths use this
        self.items = []
        self.lib_symbols = {}
        self.texts = []

    def add_lib(self, sym):
        self.lib_symbols[str(sym[1])] = sym

    def wire(self, x1, y1, x2, y2):
        self.items.append(["wire", ["pts", ["xy", x1, y1], ["xy", x2, y2]],
                           ["stroke", ["width", 0], ["type", "default"]], ["uuid", uid()]])

    def label(self, net, x, y, direction, glob=False):
        """A net label whose connection point is (x, y); text runs in `direction`."""
        angle = {(-1, 0): 180, (1, 0): 0, (0, -1): 90, (0, 1): 270}[direction]
        just = "right" if angle in (180, 270) else "left"
        if glob:
            self.items.append(["global_label", Q(net), ["shape", "bidirectional"],
                               ["at", x, y, angle], ["fields_autoplaced", "yes"],
                               font(justify=just), ["uuid", uid()],
                               ["property", Q("Intersheetrefs"), Q("${INTERSHEET_REFS}"),
                                ["at", x, y, 0], font(hide=True)]])
        else:
            self.items.append(["label", Q(net), ["at", x, y, angle], ["fields_autoplaced", "yes"],
                               font(justify=just), ["uuid", uid()]])

    def no_connect(self, x, y):
        self.items.append(["no_connect", ["at", x, y], ["uuid", uid()]])

    def text(self, s, x, y, size=1.5):
        self.items.append(["text", Q(s), ["exclude_from_sim", "no"], ["at", x, y, 0],
                           font(size, justify="left"), ["uuid", uid()]])

    def symbol(self, sym, x, y, ref, value, fields, project, root_uuid, rot=0, unit=1, value_at=None):
        """value_at: (x, y, justify) for the Value text, e.g. beside a rotated power symbol."""
        lib_id = str(sym[1])
        self.add_lib(sym)
        s_uuid = uid()
        node = ["symbol", ["lib_id", Q(lib_id)], ["at", x, y, rot], ["unit", unit],
                ["exclude_from_sim", "no"], ["in_bom", "yes" if not ref.startswith("#") else "no"],
                ["on_board", "yes" if not ref.startswith("#") else "no"], ["dnp", "no"],
                ["fields_autoplaced", "yes"], ["uuid", s_uuid]]
        x0, y0, x1, y1 = symbol_box(sym)
        hidden_ref = ref.startswith("#")
        pins = symbol_pins(sym)
        small = len(pins) <= 3 and y1 - y0 <= 12
        sideways = small and all(p.angle % 180 == 0 for p in pins)
        if sideways:  # parts lying left-right (keys, LEDs): names above them
            tx, ty = x + x0, y + y0 - 3.81
        elif small:   # upright small parts: names beside them
            tx, ty = x + x1 + 2.54, y + (y0 + y1) / 2
        else:       # over the top-right corner of a chip's body, above its first pin row
            bx0, by0, bx1, by1 = body_box(sym)
            tx, ty = x + bx1 + 1.27, y + by0 - 2.54
        node.append(["property", Q("Reference"), Q(ref), ["at", tx, ty - 1.27, 0],
                     font(justify="left", hide=hidden_ref)])
        if value_at:
            vx, vy, vj, vhide = value_at
            # field angles turn with the symbol: cancel the rotation to keep the text level
            node.append(["property", Q("Value"), Q(value), ["at", vx, vy, (360 - rot) % 360],
                         font(justify=vj, hide=vhide)])
        else:
            node.append(["property", Q("Value"), Q(value), ["at", tx, ty + 1.27, 0],
                         font(justify="left")])
        for k, v in fields.items():
            node.append(["property", Q(k), Q(v), ["at", x, y, 0], font(hide=True)])
        for p in symbol_pins(sym):
            node.append(["pin", Q(p.number), ["uuid", uid()]])
        node.append(["instances", ["project", Q(project),
                                   ["path", Q(f"/{root_uuid}/{self.block_uuid}"), ["reference", Q(ref)],
                                    ["unit", unit]]]])
        self.items.append(node)
        return s_uuid

    def write(self, path, root_uuid, version=20250114):
        tree = ["kicad_sch", ["version", version], ["generator", Q("eeschema")],
                ["generator_version", Q("10.0")], ["uuid", self.uuid], ["paper", Q(self.paper)],
                ["lib_symbols"] + list(self.lib_symbols.values())] + self.items
        with open(path, "w", encoding="utf-8") as f:
            f.write(dump(tree) + "\n")
