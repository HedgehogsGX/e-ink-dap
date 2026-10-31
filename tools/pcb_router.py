"""Small grid router used by tools/make_pcb.py: routes chosen nets of a KiCad board, one
connection at a time, with 45-degree tracks and through vias. Runs in KiCad's Python
(pcbnew, numpy, scipy).

Copper is drawn onto a fine 0.025 mm grid per routing layer: which net covers each cell.
Paths are searched on a coarser 0.1 mm grid. A track of net N may use a cell when no other
net's copper is closer than its half-width + clearance (a distance transform of the fine
grid, worked out in a window around each connection), or when the cell is N's own copper.
A* search over (layer, cell, heading), with costs for turns and vias, gives short, straight
tracks. Then each stretch is widened to the net's full width wherever there is room, so a
track necks down only beside fine-pitch pins.

Units are mm in KiCad's board frame (y down). Run KiCad's DRC on the result.
"""
import heapq
import math

import numpy as np
import pcbnew
from scipy import ndimage
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

PITCH, FINE = 0.1, 0.025     # search grid, copper grid
K = 4                        # fine cells per search cell
MARGIN = 0.025               # the fine grid's error, added to every clearance
THIN = 0.15                  # narrowest track: where a wider one doesn't fit, e.g. leaving a pin
HOLE_GAP = 0.25              # drill edge to drill edge
DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
TURN = {0: 0.0, 1: 1.5, 2: 6.0}   # cost of a 45 / 90 degree turn, in cells; sharper is not allowed
VIA_COST = 25.0                   # a via costs as much as 2.5 mm of track
GREED = 1.3                       # A* leans this much towards the goal: paths within 30 % of the
                                  # best, found far faster when costs vary (waiting pins, pairs)
SQ2 = math.sqrt(2)


def _mm(v):
    return pcbnew.FromMM(float(v))


def _pts(polyset):
    out = []
    for i in range(polyset.OutlineCount()):
        o = polyset.Outline(i)
        out.append([(pcbnew.ToMM(o.CPoint(j).x), pcbnew.ToMM(o.CPoint(j).y)) for j in range(o.PointCount())])
    return out


def _inside(pts, X, Y):
    """Even-odd point-in-polygon test for arrays of points."""
    hit = np.zeros(X.shape, bool)
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        if y1 != y2:
            hit ^= ((y1 > Y) != (y2 > Y)) & (X < (x2 - x1) * (Y - y1) / (y2 - y1) + x1)
    return hit


def _seg_dist(X, Y, a, b):
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else np.clip(((X - ax) * dx + (Y - ay) * dy) / l2, 0, 1)
    return np.hypot(X - (ax + t * dx), Y - (ay + t * dy))


def _edt(mask):
    """Distance (mm) from every fine cell to the nearest True cell of mask."""
    if not mask.any():
        return np.full(mask.shape, 1e3, np.float32)
    return (ndimage.distance_transform_edt(~mask) * FINE).astype(np.float32)


class Window:
    """A box of search cells and the matching fine cells, with 1 mm of extra fine cells
    around it so distances near its border still see copper outside it."""

    def __init__(self, r, iy0, ix0, iy1, ix1):
        self.iy0, self.ix0 = max(iy0, 0), max(ix0, 0)
        self.iy1, self.ix1 = min(iy1, r.ny - 1), min(ix1, r.nx - 1)
        pad = int(1.0 / FINE)
        self.fy0, self.fx0 = max(self.iy0 * K - pad, 0), max(self.ix0 * K - pad, 0)
        self.fy1, self.fx1 = min(self.iy1 * K + pad, r.fny - 1), min(self.ix1 * K + pad, r.fnx - 1)
        self.fine = (slice(self.fy0, self.fy1 + 1), slice(self.fx0, self.fx1 + 1))
        self.coarse = (slice(self.iy0, self.iy1 + 1), slice(self.ix0, self.ix1 + 1))
        # the search cells' places inside the fine window
        self.pick = (slice(self.iy0 * K - self.fy0, self.iy1 * K - self.fy0 + 1, K),
                     slice(self.ix0 * K - self.fx0, self.ix1 * K - self.fx0 + 1, K))

    def at(self, fine_array):
        """Values of a fine-window array at the search cells."""
        return fine_array[self.pick]

    def full(self, r, coarse_window_array, fill=False):
        out = np.full((r.ny, r.nx), fill, coarse_window_array.dtype)
        out[self.coarse] = coarse_window_array
        return out


class Router:
    def __init__(self, board, outline, layers, clearance=0.1, edge_clearance=0.3, via=(0.5, 0.3)):
        """outline: the board outline as points (KiCad mm); layers: routing layers, e.g.
        [F_Cu, B_Cu]; via: (diameter, drill) of the through vias it places."""
        self.board, self.layers = board, list(layers)
        self.clear, self.edge_clear = clearance, edge_clearance
        self.via_d, self.via_drill = via
        xs, ys = [p[0] for p in outline], [p[1] for p in outline]
        self.x0, self.y0 = min(xs) - 1.0, min(ys) - 1.0
        self.nx = int((max(xs) + 1.0 - self.x0) / PITCH) + 1
        self.ny = int((max(ys) + 1.0 - self.y0) / PITCH) + 1
        self.fnx, self.fny = (self.nx - 1) * K + 1, (self.ny - 1) * K + 1
        shape = (self.fny, self.fnx)
        self.owner = {lay: np.zeros(shape, np.int32) for lay in self.layers}   # copper: net code, -1 blocked
        self.pads = {lay: np.zeros(shape, np.int32) for lay in self.layers}    # pads only
        self.holes = np.zeros(shape, bool)
        X, Y = self._fgrid((slice(0, self.fny), slice(0, self.fnx)))
        self.edge = _edt(~_inside(outline, X, Y))                               # distance to the edge
        del X, Y
        self.extra = []      # (net, pad, layer, coarse mask): stubs that belong to a pad
        self.routed = {}     # net -> the tracks and vias route_net added for it
        self.failed = {}     # net -> [(pad name, (x, y))] it could not join
        self.reserved = []   # (coarse slice, nets allowed there)
        self.tracks = self.vias = 0
        self.length, self.stub_end, self.stub_track, self.stubs = {}, {}, {}, []
        self.via_end, self.fanouts, self._made = {}, [], None   # via_out's vias
        self.removed = []
        self._load()

    def _load(self):
        """Draws all copper of the board onto the grids: pads, footprint copper, keep-outs,
        and the tracks and vias already on it. Run again after tracks were removed."""
        shape = (self.fny, self.fnx)
        self.owner = {lay: np.zeros(shape, np.int32) for lay in self.layers}   # copper: net code, -1 blocked
        self.pads = {lay: np.zeros(shape, np.int32) for lay in self.layers}    # pads only
        self.holes = np.zeros(shape, bool)
        self.nets, self.own_vias = {}, {}
        for fp in self.board.GetFootprints():
            for pad in fp.Pads():
                self._add_pad(pad)
            if not fp.IsNetTie():   # a net tie's copper bridge joins its own two pads
                for item in fp.GraphicalItems():
                    if isinstance(item, pcbnew.PCB_SHAPE) and item.GetLayer() in self.layers:
                        self._add_shape(item, item.GetLayer(), -1)
            for z in fp.Zones():
                self._add_keepout(z)
        for z in self.board.Zones():
            self._add_keepout(z)
        for t in self.board.GetTracks():
            net, a = t.GetNetCode(), t.GetStart()
            ax, ay = pcbnew.ToMM(a.x), pcbnew.ToMM(a.y)
            if t.GetClass() == "PCB_VIA":
                r = self.via_d / 2
                sl, X, Y = self._fwindow(ax - r, ay - r, ax + r, ay + r)
                m = np.hypot(X - ax, Y - ay) <= r
                for lay in self.layers:
                    self._mark(self.owner[lay], sl, m, net)
                self._add_hole(ax, ay, self.via_drill / 2)
                self.own_vias.setdefault(net, []).append((ax, ay))
            elif t.GetLayer() in self.layers:
                b, r = t.GetEnd(), pcbnew.ToMM(t.GetWidth()) / 2
                bx, by = pcbnew.ToMM(b.x), pcbnew.ToMM(b.y)
                sl, X, Y = self._fwindow(min(ax, bx) - r, min(ay, by) - r, max(ax, bx) + r, max(ay, by) + r)
                self._mark(self.owner[t.GetLayer()], sl, _seg_dist(X, Y, (ax, ay), (bx, by)) <= r, net)
        for net, pad, lay, item in self.extra:
            self.nets.setdefault(net, []).append((pad, lay, item))

    # ---- grids

    def _fgrid(self, sl):
        xs = self.x0 + np.arange(sl[1].start, sl[1].stop) * FINE
        ys = self.y0 + np.arange(sl[0].start, sl[0].stop) * FINE
        return np.meshgrid(xs, ys)

    def _fwindow(self, x0, y0, x1, y1):
        fx0 = max(int(math.floor((x0 - self.x0) / FINE)), 0)
        fx1 = min(int(math.ceil((x1 - self.x0) / FINE)), self.fnx - 1)
        fy0 = max(int(math.floor((y0 - self.y0) / FINE)), 0)
        fy1 = min(int(math.ceil((y1 - self.y0) / FINE)), self.fny - 1)
        sl = (slice(fy0, fy1 + 1), slice(fx0, fx1 + 1))
        X, Y = self._fgrid(sl)
        return sl, X, Y

    def cell(self, x, y):
        return int(round((y - self.y0) / PITCH)), int(round((x - self.x0) / PITCH))

    def fcell(self, x, y):
        return int(round((y - self.y0) / FINE)), int(round((x - self.x0) / FINE))

    def xy(self, iy, ix):
        return self.x0 + ix * PITCH, self.y0 + iy * PITCH

    def window(self, x0, y0, x1, y1):
        a, b = self.cell(x0, y0), self.cell(x1, y1)
        return Window(self, a[0], a[1], b[0], b[1])

    @staticmethod
    def _mark(grid, sl, mask, net):
        sub = grid[sl]
        clash = mask & (sub != 0) & (sub != net)
        sub[mask & (sub == 0)] = net
        sub[clash] = -1

    def _coarse(self, sl, m):
        """Search cells covered by a fine mask: (coarse slice, mask)."""
        fy0, fx0 = sl[0].start, sl[1].start
        oy, ox = (-fy0) % K, (-fx0) % K
        sub = m[oy::K, ox::K]
        iy0, ix0 = (fy0 + oy) // K, (fx0 + ox) // K
        return (slice(iy0, iy0 + sub.shape[0]), slice(ix0, ix0 + sub.shape[1])), sub

    # ---- copper from the board

    def _poly_masks(self, polys):
        out = []
        for pts in polys:
            if len(pts) >= 3:
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                sl, X, Y = self._fwindow(min(xs), min(ys), max(xs), max(ys))
                out.append((sl, _inside(pts, X, Y)))
        return out

    def _add_shape(self, item, layer, net):
        ps = pcbnew.SHAPE_POLY_SET()
        item.TransformShapeToPolygon(ps, layer, 0, _mm(0.005), pcbnew.ERROR_OUTSIDE)
        for sl, m in self._poly_masks(_pts(ps)):
            self._mark(self.owner[layer], sl, m, net)

    def _add_hole(self, x, y, r):
        sl, X, Y = self._fwindow(x - r, y - r, x + r, y + r)
        self.holes[sl] |= np.hypot(X - x, Y - y) <= r

    def _add_pad(self, pad):
        net = pad.GetNetCode() or -1
        pos = pad.GetPosition()
        x, y = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
        if pad.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
            self._add_hole(x, y, pcbnew.ToMM(min(pad.GetDrillSize().x, pad.GetDrillSize().y)) / 2)
        if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
            r = pcbnew.ToMM(pad.GetDrillSize().x) / 2 + 0.1   # holes want 0.2 mm, copper 0.1
            sl, X, Y = self._fwindow(x - r, y - r, x + r, y + r)
            for lay in self.layers:
                self._mark(self.owner[lay], sl, np.hypot(X - x, Y - y) <= r, -1)
            return
        for lay in self.layers:
            if not pad.IsOnLayer(lay):
                continue
            ps = pcbnew.SHAPE_POLY_SET()
            pad.TransformShapeToPolygon(ps, lay, 0, _mm(0.005), pcbnew.ERROR_OUTSIDE)
            for sl, m in self._poly_masks(_pts(ps)):
                self._mark(self.owner[lay], sl, m, net)
                self._mark(self.pads[lay], sl, m, net)
                if net > 0:
                    self.nets.setdefault(net, []).append((pad, lay, self._coarse(sl, m)))

    def _add_keepout(self, z):
        if not (z.GetIsRuleArea() and z.GetDoNotAllowTracks()):
            return
        for lay in self.layers:
            if z.IsOnLayer(lay):
                for sl, m in self._poly_masks(_pts(z.Outline())):
                    self._mark(self.owner[lay], sl, m, -1)

    # ---- adding copper; each returns {layer: (coarse slice, mask)} of what it covers

    def _net_item(self, net):
        return self.board.GetNetInfo().GetNetItem(net)

    def add_track(self, net, layer, a, b, width):
        t = pcbnew.PCB_TRACK(self.board)
        t.SetStart(pcbnew.VECTOR2I(_mm(a[0]), _mm(a[1])))
        t.SetEnd(pcbnew.VECTOR2I(_mm(b[0]), _mm(b[1])))
        t.SetWidth(_mm(width))
        t.SetLayer(layer)
        t.SetNet(self._net_item(net))
        self.board.Add(t)
        self.last_track = t
        if getattr(self, "_recording", None) == net:
            self.routed.setdefault(net, []).append(t)
        if self._made is not None:
            self._made.append(t)
        r = width / 2
        sl, X, Y = self._fwindow(min(a[0], b[0]) - r, min(a[1], b[1]) - r, max(a[0], b[0]) + r, max(a[1], b[1]) + r)
        m = _seg_dist(X, Y, a, b) <= r
        self._mark(self.owner[layer], sl, m, net)
        self.tracks += 1
        self.length[net] = self.length.get(net, 0.0) + math.hypot(b[0] - a[0], b[1] - a[1])
        sl_c, X, Y = self._cwin(sl)
        return {layer: (sl_c, _seg_dist(X, Y, a, b) <= r - 0.005)}   # cells truly on the copper: a route may end there

    def add_via(self, net, p):
        v = pcbnew.PCB_VIA(self.board)
        v.SetPosition(pcbnew.VECTOR2I(_mm(p[0]), _mm(p[1])))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetWidth(_mm(self.via_d))
        v.SetDrill(_mm(self.via_drill))
        v.SetNet(self._net_item(net))
        self.board.Add(v)
        if getattr(self, "_recording", None) == net:
            self.routed.setdefault(net, []).append(v)
        if self._made is not None:
            self._made.append(v)
        r = self.via_d / 2
        sl, X, Y = self._fwindow(p[0] - r, p[1] - r, p[0] + r, p[1] + r)
        m = np.hypot(X - p[0], Y - p[1]) <= r
        for lay in self.layers:
            self._mark(self.owner[lay], sl, m, net)
        self._add_hole(p[0], p[1], self.via_drill / 2)
        self.own_vias.setdefault(net, []).append(p)
        self.vias += 1
        sl_c, X, Y = self._cwin(sl)
        cm = np.hypot(X - p[0], Y - p[1]) <= r - 0.005
        return {lay: (sl_c, cm) for lay in self.layers}

    def _cwin(self, fine_sl):
        iy0, ix0 = fine_sl[0].start // K, fine_sl[1].start // K
        iy1, ix1 = -(-(fine_sl[0].stop - 1) // K), -(-(fine_sl[1].stop - 1) // K)
        sl = (slice(iy0, min(iy1, self.ny - 1) + 1), slice(ix0, min(ix1, self.nx - 1) + 1))
        xs = self.x0 + np.arange(sl[1].start, sl[1].stop) * PITCH
        ys = self.y0 + np.arange(sl[0].start, sl[0].stop) * PITCH
        X, Y = np.meshgrid(xs, ys)
        return sl, X, Y

    # ---- where a net may go, inside a window

    def dists(self, net, win):
        """Fine distances to other nets' copper, per layer, over the window."""
        out = {}
        for lay in self.layers:
            o = self.owner[lay][win.fine]
            out[lay] = _edt((o != 0) & (o != net))
        return out

    def free(self, lay, net, width, d, win, clearance=None):
        """Search cells where a track of this width fits. On the net's own copper (leaving a
        pad) a thin track is enough; _lay narrows the track there."""
        c = (self.clear if clearance is None else clearance) + MARGIN
        dc = win.at(d)
        ok = (dc > width / 2 + c) & \
            (win.at(self.edge[win.fine]) > width / 2 + self.edge_clear + MARGIN + FINE)
        return ok | ((win.at(self.owner[lay][win.fine]) == net) & (dc > THIN / 2 + c))

    def via_ok(self, net, d, win):
        """Search cells where a via of this net fits: clear of other nets' copper, of all
        drill holes, of the edge, and of its own pads (no via in a pad)."""
        r = self.via_d / 2
        ok = win.at(self.edge[win.fine]) > r + self.edge_clear + MARGIN
        ok &= win.at(_edt(self.holes[win.fine])) > self.via_drill + HOLE_GAP + MARGIN
        for lay in self.layers:
            ok &= win.at(d[lay]) > r + self.clear + MARGIN
            ok &= win.at(_edt(self.pads[lay][win.fine] == net)) > r + 0.05
        for sl, allowed in self.reserved:   # no via in another net's channel
            if net not in allowed:
                y0, y1 = max(sl[0].start, win.iy0), min(sl[0].stop, win.iy1 + 1)
                x0, x1 = max(sl[1].start, win.ix0), min(sl[1].stop, win.ix1 + 1)
                if y0 < y1 and x0 < x1:
                    ok[y0 - win.iy0:y1 - win.iy0, x0 - win.ix0:x1 - win.ix0] = False
        return ok

    def _fine_ok(self, lay, net, d, win, pts, half, clearance=None):
        """Every fine cell within `half` of these points is clear of other nets and the edge."""
        c = (self.clear if clearance is None else clearance) + MARGIN
        for x, y in pts:
            fy, fx = self.fcell(x, y)
            n = int(math.ceil(half / FINE)) + 1
            ys, xs = slice(fy - n - win.fy0, fy + n + 1 - win.fy0), slice(fx - n - win.fx0, fx + n + 1 - win.fx0)
            if ys.start < 0 or xs.start < 0:
                return False
            dd, own = d[ys, xs], self.owner[lay][win.fine][ys, xs] == net
            ee = self.edge[win.fine][ys, xs]
            gy, gx = np.mgrid[-n:n + 1, -n:n + 1] * FINE
            disc = np.hypot(gy, gx)[:dd.shape[0], :dd.shape[1]] <= half + FINE   # one cell more: the track's own grid error
            if not np.all(((dd > c) | own)[disc]) or not np.all((ee > self.edge_clear + MARGIN + FINE)[disc]):
                return False
        return True

    # ---- pads

    @staticmethod
    def _centre(pad):
        pos = pad.GetPosition()
        return pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)

    @staticmethod
    def _size(pad):
        bb = pad.GetBoundingBox()
        return pcbnew.ToMM(bb.GetWidth()), pcbnew.ToMM(bb.GetHeight())

    def _outward(self, pad):
        """Unit step along the pad's long side, away from its part's centre, and the pad's
        half-length that way; None for a square pad."""
        w, h = self._size(pad)
        if abs(w - h) < 0.05:
            return None
        (px, py), fp = self._centre(pad), pad.GetParentFootprint().GetPosition()
        cx, cy = pcbnew.ToMM(fp.x), pcbnew.ToMM(fp.y)
        if w > h:
            return (1.0 if px >= cx else -1.0, 0.0), w / 2
        return (0.0, 1.0 if py >= cy else -1.0), h / 2

    def _exposed(self, pad):
        """A chip's exposed pad: big, and at the middle of a part with many pins."""
        w, h = self._size(pad)
        fp = pad.GetParentFootprint()
        (px, py), c = self._centre(pad), fp.GetPosition()
        return w >= 0.9 and h >= 0.9 and len(fp.Pads()) >= 6 and \
            math.hypot(px - pcbnew.ToMM(c.x), py - pcbnew.ToMM(c.y)) < 0.5

    @staticmethod
    def _name(pad):
        return f"{pad.GetParentFootprint().GetReference()}:{pad.GetNumber()}"

    def _key(self, pad):
        """A pad told apart from others of the same part and number (a key's two pads "1",
        joined only inside the switch: KiCad wants copper between them)."""
        return self._name(pad), self._centre(pad)

    def _line(self, a, b, step=0.05):
        n = max(int(math.hypot(b[0] - a[0], b[1] - a[1]) / step), 1)
        return [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n + 1)]

    def _keep(self, pad, net, items):
        """Track copper that now belongs to a pad, for joining it later."""
        for lay, it in items.items():
            self.nets[net].append((pad, lay, it))
            self.extra.append((net, pad, lay, it))

    def reserve(self, x0, y0, x1, y1, nets):
        """A channel only these nets may route through (KiCad mm), e.g. where a chip's
        outputs leave it; other nets' tracks and vias keep out."""
        a, b = self.cell(x0, y0), self.cell(x1, y1)
        self.reserved.append(((slice(a[0], b[0] + 1), slice(a[1], b[1] + 1)), set(nets)))

    def escape(self, nets, length=0.4, width=0.15, parts=()):
        """A short straight stub out of every fine-pitch pin (0.65 mm pitch or less) of these
        nets on a chip, and out of every pin of `parts` whatever its pitch, so that a track
        routed past a pin can't block it. Returns how many."""
        done = 0
        for net in nets:
            for pad, lay, _ in list(self.nets.get(net, [])):
                fp = pad.GetParentFootprint()
                ref = fp.GetReference()
                if self._name(pad) in self.stub_end or not (ref.startswith("U") or ref in parts) \
                        or pad.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                    continue
                px, py = self._centre(pad)
                others = [self._centre(q) for q in fp.Pads() if q.GetNumber() != pad.GetNumber()]
                if ref not in parts and min(math.hypot(px - x, py - y) for x, y in others) > 0.66:
                    continue
                out = self._outward(pad)
                if not out:
                    continue
                (dx, dy), half = out
                a, b = (px + dx * half, py + dy * half), (px + dx * (half + length), py + dy * (half + length))
                win = self.window(b[0] - 1.5, b[1] - 1.5, b[0] + 1.5, b[1] + 1.5)
                d = self.dists(net, win)
                if self._fine_ok(lay, net, d[lay], win, self._line(a, b), width / 2):
                    self._keep(pad, net, self.add_track(net, lay, (px, py), b, width))
                    self.stub_end[self._name(pad)] = b
                    self.stub_track[self._name(pad)] = self.last_track
                    self.stubs.append((net, self.last_track, b, width))
                    done += 1
        return done

    def via_out(self, nets, width=0.15, reach=3.0, yield_to_stuck=False):
        """Gives each stubbed pin of these nets a via of its own: a short track on the pin's
        layer from the stub's tip to the nearest spot where a via fits, taking the pins of each
        chip in turn round its outline. Done before routing, so no track can box a pin in on its
        own layer later; route_net may start a pin from its via, on any layer, and
        drop_unused_vias takes away those it didn't use. yield_to_stuck: a pin that finds no spot
        has its neighbours' vias from this call taken back, so they can leave side by side on
        their own layer. Returns the pins that found no spot."""
        pins = []
        for net in nets:
            for pad, lay, _ in self.nets.get(net, []):
                name = self._name(pad)
                if name in self.stub_end and name not in self.via_end and (name, net) not in [p[:2] for p in pins]:
                    fp = pad.GetParentFootprint().GetPosition()
                    (px, py), (cx, cy) = self._centre(pad), (pcbnew.ToMM(fp.x), pcbnew.ToMM(fp.y))
                    pins.append((name, net, pad, lay, pad.GetParentFootprint().GetReference(),
                                 math.atan2(py - cy, px - cx)))
        none = np.zeros((self.ny, self.nx), bool)
        failed = []
        for name, net, pad, lay, _, _ in sorted(pins, key=lambda p: (p[4], p[5])):
            sx, sy = self.stub_end[name]
            win = self.window(sx - reach, sy - reach, sx + reach, sy + reach)
            d = self.dists(net, win)
            spots = win.full(self, self.via_ok(net, d, win))
            free = {l: win.full(self, self.free(l, net, width, d[l], win)) if l == lay else none for l in self.layers}
            tree = {l: spots if l == lay else none for l in self.layers}
            own = [(l, it) for p, l, it in self.nets[net] if self._name(p) == name]
            path = self._search(free, none, tree, self._starts(own, free, (sx, sy), pad), None, 40000, win) \
                if spots.any() else None
            if path is None:
                failed.append(name)
                continue
            self._made, kept = [], len(self.extra)
            for l, items in self._lay(net, path, width, width, d, win, None).items():
                for it in items:
                    self._keep(pad, net, {l: it})
            end = self.xy(path[-1][1], path[-1][2])
            self._keep(pad, net, self.add_via(net, end))
            self.via_end[name] = end
            # tracks from the stub's tip, then the via; the pin's copper entries; where it came from
            self.fanouts.append((net, end, self._made, self.stub_track[name], self.extra[kept:], name, pad))
            self._made = None
        if yield_to_stuck and failed:
            here = {p[0] for p in pins}
            stuck = [self._centre(p[2]) + (p[2].GetParentFootprint().GetReference(),) for p in pins if p[0] in failed]
            back = [f for f in self.fanouts if f[5] in here and any(
                f[6].GetParentFootprint().GetReference() == ref and math.hypot(self._centre(f[6])[0] - x,
                                                                                self._centre(f[6])[1] - y) < 0.45
                for x, y, ref in stuck)]
            for f in back:
                for o in f[2]:
                    self._remove(o)
                gone = {id(e) for e in f[4]}
                self.extra = [e for e in self.extra if id(e) not in gone]
                del self.via_end[f[5]]
                self.fanouts.remove(f)
            if back:
                self._load()
        return failed

    def drop_unused_vias(self, keep_nets=()):
        """Takes away via_out's vias that nothing of their net touches on another layer (except
        for keep_nets). Tracks on the pin's own layer that end on such a via get a short track
        to its centre instead; if none do, its tracks are cut back to where other copper of the
        net joins them, so nothing is left sticking out. Returns how many vias were removed."""
        dropped = 0
        for net, (vx, vy), objs, stub, _, _, _ in self.fanouts:
            if net in keep_nets:
                continue
            mine = {id(o) for o in objs} | {id(stub)}
            others = [t for t in self.board.GetTracks() if t.GetNetCode() == net and id(t) not in mine
                      and t.GetClass() == "PCB_TRACK"]
            ends = [(pcbnew.ToMM(p.x), pcbnew.ToMM(p.y)) for t in others for p in (t.GetStart(), t.GetEnd())]
            lay = stub.GetLayer()
            on = [(t.GetLayer(), (pcbnew.ToMM(p.x), pcbnew.ToMM(p.y))) for t in others for p in (t.GetStart(), t.GetEnd())
                  if math.hypot(pcbnew.ToMM(p.x) - vx, pcbnew.ToMM(p.y) - vy) <= self.via_d / 2]
            through = any(t.GetLayer() != lay and float(_seg_dist(
                np.array(vx), np.array(vy), (pcbnew.ToMM(t.GetStart().x), pcbnew.ToMM(t.GetStart().y)),
                (pcbnew.ToMM(t.GetEnd().x), pcbnew.ToMM(t.GetEnd().y)))) <= (self.via_d + pcbnew.ToMM(t.GetWidth())) / 2
                for t in others)
            if through:   # a track on another layer ends on it or runs across it: it is used
                continue
            self._remove(objs[-1])
            dropped += 1
            if on:   # only tracks on the pin's layer end on it: join them to its centre directly
                for _, e in on:
                    if math.hypot(e[0] - vx, e[1] - vy) > 0.01:
                        self.add_track(net, lay, e, (vx, vy), THIN)
                continue
            for t in reversed(objs[:-1]):   # from the via end back towards the pin
                s0, s1 = t.GetStart(), t.GetEnd()
                (ax, ay), (bx, by) = (pcbnew.ToMM(s0.x), pcbnew.ToMM(s0.y)), (pcbnew.ToMM(s1.x), pcbnew.ToMM(s1.y))
                if (ax, ay) == (vx, vy) or math.hypot(ax - vx, ay - vy) < math.hypot(bx - vx, by - vy):
                    (ax, ay), (bx, by) = (bx, by), (ax, ay)   # a = the pin's side, b = the via's side
                length = math.hypot(bx - ax, by - ay)
                w = pcbnew.ToMM(t.GetWidth()) / 2
                reach = None
                for x, y in ends:
                    if length and float(_seg_dist(np.array(x), np.array(y), (ax, ay), (bx, by))) <= w:
                        along = ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / length
                        reach = along if reach is None else max(reach, along)
                if reach is None or reach <= 0.01:   # nothing joins it, or only at the pin's end
                    self._remove(t)
                    continue
                if reach < length - 0.01:
                    f = max(reach, 0.0) / length
                    t.SetStart(pcbnew.VECTOR2I(_mm(ax), _mm(ay)))
                    t.SetEnd(pcbnew.VECTOR2I(_mm(ax + (bx - ax) * f), _mm(ay + (by - ay) * f)))
                break
        return dropped

    def bridge(self, net, names, width=0.2):
        """Joins these pads on the bottom layer: a via just behind each pad (away from its
        part's centre), a stub to it, and a straight bottom track between the vias. For
        a USB-C socket, whose two D+ and two D- pins sit interleaved."""
        pads, seen = [], set()
        for pad, _, _ in self.nets[net]:
            if self._name(pad) in names and self._name(pad) not in seen:
                pads.append(pad)
                seen.add(self._name(pad))
        vias = []
        for pad in pads:
            (dx, dy), half = self._outward(pad)
            px, py = self._centre(pad)
            for k in range(12):
                v = (px + dx * (half + self.via_d / 2 + 0.15 + 0.1 * k), py + dy * (half + self.via_d / 2 + 0.15 + 0.1 * k))
                win = self.window(v[0] - 2, v[1] - 2, v[0] + 2, v[1] + 2)
                d = self.dists(net, win)
                iy, ix = self.cell(*v)
                v = self.xy(iy, ix)
                if self.via_ok(net, d, win)[iy - win.iy0, ix - win.ix0] and \
                        self._fine_ok(pcbnew.F_Cu, net, d[pcbnew.F_Cu], win, self._line((px, py), v), width / 2):
                    self._keep(pad, net, self.add_track(net, pcbnew.F_Cu, (px, py), v, width))
                    self._keep(pad, net, self.add_via(net, v))
                    vias.append(v)
                    break
            else:
                return False
        for a, b in zip(vias, vias[1:]):
            self._keep(pads[0], net, self.add_track(net, pcbnew.B_Cu, a, b, width))
        return True

    # ---- ground vias

    def fanout(self, net, pads, width=0.3):
        """Joins each of these surface pads to a plane on an inner layer: vias inside a
        large (exposed) pad; a short track into the part's own exposed pad of the same net;
        else a short track to a via of the net close by, or to a new via beside the pad.
        Returns the pads that found no room."""
        failed = []
        for pad in pads:
            lay = pcbnew.F_Cu if pad.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
            px, py = self._centre(pad)
            w, h = self._size(pad)
            fp = pad.GetParentFootprint()
            if self._exposed(pad):   # a grid of vias 1 mm apart
                nx_, ny_ = int((w - 0.6) // 1.0) + 1, int((h - 0.6) // 1.0) + 1
                for i in range(nx_):
                    for j in range(ny_):
                        self.add_via(net, (px + (i - (nx_ - 1) / 2), py + (j - (ny_ - 1) / 2)))
                continue
            win = self.window(px - 4.5, py - 4.5, px + 4.5, py + 4.5)
            d = self.dists(net, win)
            done = False
            for ep in fp.Pads():
                ew, eh = self._size(ep)
                if ep.GetNetCode() != net or ep.GetNumber() == pad.GetNumber() or not self._exposed(ep):
                    continue
                ex, ey = self._centre(ep)
                tx = min(max(px, ex - ew / 2 + 0.2), ex + ew / 2 - 0.2)
                ty = min(max(py, ey - eh / 2 + 0.2), ey + eh / 2 - 0.2)
                if math.hypot(tx - px, ty - py) < 2 and self._fine_ok(lay, net, d[lay], win,
                                                                       self._line((px, py), (tx, ty)), 0.1):
                    self.add_track(net, lay, (px, py), (tx, ty), 0.2)
                    done = True
                    break
            if done:
                continue
            for vx, vy in sorted(self.own_vias.get(net, []), key=lambda v: math.hypot(v[0] - px, v[1] - py)):
                if math.hypot(vx - px, vy - py) > 1.0:
                    break
                for tw in (width, 0.2):
                    if self._fine_ok(lay, net, d[lay], win, self._line((px, py), (vx, vy)), tw / 2):
                        self.add_track(net, lay, (px, py), (vx, vy), tw)
                        done = True
                        break
                if done:
                    break
            if done:
                continue
            via_ok = self.via_ok(net, d, win)
            centre = fp.GetPosition()
            out = math.atan2(py - pcbnew.ToMM(centre.y), px - pcbnew.ToMM(centre.x))
            cands = []
            for k in range(16):
                ang = 2 * math.pi * k / 16
                away = abs((ang - out + math.pi) % (2 * math.pi) - math.pi)   # 0 = straight out of the part
                for r in np.arange(0.5, 3.5 + 1e-6, 0.1):
                    cands.append((r + 0.6 * away + (2 if r > 2 else 0), px + r * math.cos(ang), py + r * math.sin(ang)))
            for _, vx, vy in sorted(cands):
                iy, ix = self.cell(vx, vy)
                vx, vy = self.xy(iy, ix)
                if not (win.iy0 <= iy <= win.iy1 and win.ix0 <= ix <= win.ix1) or \
                        not via_ok[iy - win.iy0, ix - win.ix0]:
                    continue
                for tw in (width, 0.2):
                    if self._fine_ok(lay, net, d[lay], win, self._line((px, py), (vx, vy)), tw / 2):
                        self.add_track(net, lay, (px, py), (vx, vy), tw)
                        self.add_via(net, (vx, vy))
                        done = True
                        break
                if done:
                    break
            if not done and not self._to_plane(net, pad):
                failed.append(pad)
        return failed

    def _to_plane(self, net, pad, reach=6.0):
        """Routes a pad to the nearest via or through-hole pad of its net."""
        px, py = self._centre(pad)
        win = self.window(px - reach, py - reach, px + reach, py + reach)
        d = self.dists(net, win)
        tree = {lay: np.zeros((self.ny, self.nx), bool) for lay in self.layers}
        X, Y = np.meshgrid(self.x0 + np.arange(self.nx) * PITCH, self.y0 + np.arange(self.ny) * PITCH)
        for vx, vy in self.own_vias.get(net, []):
            if abs(vx - px) < reach and abs(vy - py) < reach:
                hit = np.hypot(X - vx, Y - vy) <= self.via_d / 2
                for lay in self.layers:
                    tree[lay] |= hit
        for p, lay, (sl, m) in self.nets.get(net, []):
            if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                tree[lay][sl] |= m
        free = {lay: win.full(self, self.free(lay, net, 0.2, d[lay], win)) for lay in self.layers}
        own = [(l, it) for p, l, it in self.nets.get(net, []) if p == pad or self._name(p) == self._name(pad)]
        path = self._search(free, win.full(self, self.via_ok(net, d, win)), tree,
                            self._starts(own, free, (px, py), pad), None, 300000, win)
        if path is None:
            return False
        self._lay(net, path, 0.2, 0.3, d, win, None)
        return True

    def drop_unused_stubs(self, nets=None):
        """Tidies the escape stubs (of these nets; all if None): one that nothing of its net
        reached is removed; one that a track joins partway along is cut back to that point, so
        no bit sticks out. Returns how many were removed."""
        dropped = 0
        for net, stub, tip, w in self.stubs:
            if nets is not None and net not in nets:
                continue
            s0, s1 = stub.GetStart(), stub.GetEnd()
            (ax, ay), (bx, by) = seg = ((pcbnew.ToMM(s0.x), pcbnew.ToMM(s0.y)), (pcbnew.ToMM(s1.x), pcbnew.ToMM(s1.y)))
            length = math.hypot(bx - ax, by - ay)
            reach, tip_covered = None, False
            for t in self.board.GetTracks():
                a, b = t.GetStart(), t.GetEnd()
                if t.GetNetCode() != net or (a == s0 and b == s1):
                    continue
                ends = [(pcbnew.ToMM(a.x), pcbnew.ToMM(a.y)), (pcbnew.ToMM(b.x), pcbnew.ToMM(b.y))]
                if float(_seg_dist(np.array(bx), np.array(by), *ends)) <= pcbnew.ToMM(t.GetWidth()) / 2:
                    tip_covered = True
                for x, y in ends:
                    if float(_seg_dist(np.array(x), np.array(y), *seg)) <= w / 2:
                        along = ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / length
                        reach = along if reach is None else max(reach, along)
            if tip_covered:
                continue
            if reach is None:
                self._remove(stub)
                dropped += 1
            elif reach < length - 0.01:
                f = max(reach, 0.0) / length
                stub.SetEnd(pcbnew.VECTOR2I(_mm(ax + (bx - ax) * f), _mm(ay + (by - ay) * f)))
        return dropped

    # ---- routing a net

    def set_waiting(self, nets):
        """Nets still to be routed: tracks and vias pay three times as much within 0.6 mm of
        their pins, so they don't box in a pin that is waiting for its own. A net leaves the
        list when its routing starts."""
        self.waiting = {lay: np.zeros((self.ny, self.nx), np.int16) for lay in self.layers}
        self.waiting_nets = set()
        for net in nets:
            self._wait(net, +1)

    def _wait(self, net, step):
        if (step > 0) == (net in self.waiting_nets):
            return
        for _, lay, (sl, m) in self.nets.get(net, []):
            self.waiting[lay][sl] += step * m.astype(np.int16)
        (self.waiting_nets.add if step > 0 else self.waiting_nets.discard)(net)

    def route_net(self, net, order=None, width=0.15, full_width=None, min_width=None, clearance=None,
                  partner=None, pair_pitch=None, corridor=None, layers=None, max_states=400000):
        """Joins all pads of a net: from the first pad (or the first named in order, as
        "REF:pad" or "REF"), each time the unconnected pad nearest to what is already joined.
        full_width: widen to this where there is room. min_width: if a connection finds no
        room at width, try this narrower one. clearance: more than the board's, except near the
        net's pads. corridor: route as if this wide (room for a pair partner beside it),
        except near the pads. partner + pair_pitch: keep pair_pitch from the partner net's
        tracks where possible (the second track of a differential pair). layers: only these
        of the routing layers (a pair whose impedance was worked out for them). Pins of nets
        still waiting (set_waiting) are kept clear where possible. Returns the number of
        connections that failed."""
        waiting = getattr(self, "waiting", None)
        if waiting:
            self._wait(net, -1)
        self._recording = net
        self.failed[net] = []
        groups = {}   # pad name -> (pad, [(layer, coarse mask)]): its copper, stubs included
        for pad, lay, item in self.nets.get(net, []):
            groups.setdefault(self._key(pad), (pad, []))[1].append((lay, item))
        pads = [g[0] for g in groups.values()]
        if order:
            def rank(p):
                ref = p.GetParentFootprint().GetReference()
                for key in (f"{ref}:{p.GetNumber()}", ref):
                    if key in order:
                        return order.index(key)
                return len(order)
            pads.sort(key=rank)
        if len(pads) < 2:
            return 0
        tree = {lay: np.zeros((self.ny, self.nx), bool) for lay in self.layers}
        spots = []   # points of the joined copper, for the search window

        centre = self._centre

        def join(pad):
            for lay, (sl, m) in groups[self._key(pad)][1]:
                tree[lay][sl] |= m
            spots.append(centre(pad))

        def joined_now(pad):
            cy, cx = self.cell(*centre(pad))
            return any(tree[lay][cy, cx] for lay in self.layers if pad.IsOnLayer(lay))

        joined = [pads[0]]
        join(pads[0])
        todo = pads[1:]
        failed = 0
        while todo:
            todo.sort(key=lambda p: min(math.hypot(centre(p)[0] - s[0], centre(p)[1] - s[1]) for s in spots))
            pad = todo.pop(0)
            if joined_now(pad):
                join(pad)
                joined.append(pad)
                continue
            path = None
            for spread, w_try in [(4.0, width), (12.0, width)] + ([(12.0, min_width)] if min_width else []):
                pts = spots + [centre(pad)]
                win = self.window(min(p[0] for p in pts) - spread, min(p[1] for p in pts) - spread,
                                  max(p[0] for p in pts) + spread, max(p[1] for p in pts) + spread)
                d = self.dists(net, win)
                near = None
                if corridor or (clearance and clearance > self.clear):
                    xs = self.x0 + np.arange(win.ix0, win.ix1 + 1) * PITCH
                    ys = self.y0 + np.arange(win.iy0, win.iy1 + 1) * PITCH
                    X, Y = np.meshgrid(xs, ys)
                    near = np.zeros(X.shape, bool)
                    for q in pads:
                        qx, qy = centre(q)
                        near |= np.hypot(X - qx, Y - qy) < 1.5
                free = {}
                for lay in self.layers:
                    base = self.free(lay, net, w_try, d[lay], win)
                    f = self.free(lay, net, corridor or w_try, d[lay], win, clearance) if near is not None else base
                    free[lay] = win.full(self, f | (base & near) if near is not None else f)
                cost = None
                if partner or waiting:
                    cost = {}
                    for lay in self.layers:
                        c = np.ones((win.iy1 - win.iy0 + 1, win.ix1 - win.ix0 + 1), np.uint8)
                        if partner:
                            dp = _edt(self.owner[lay][win.fine] == partner)
                            c *= np.where(np.abs(win.at(dp) - pair_pitch) <= 0.06, 1, 2).astype(np.uint8)
                        if waiting:
                            w_ = waiting[lay][win.coarse] > 0
                            if w_.any():
                                near_pin = ndimage.distance_transform_edt(~w_) * PITCH < 0.6
                                c *= np.where(near_pin, 3, 1).astype(np.uint8)
                        cost[lay] = win.full(self, c, 2)
                via = win.full(self, self.via_ok(net, d, win))
                for sl, allowed in self.reserved:   # other nets' channels: only own copper there
                    if net not in allowed:
                        fsl = (slice(sl[0].start * K, (sl[0].stop - 1) * K + 1, K),
                               slice(sl[1].start * K, (sl[1].stop - 1) * K + 1, K))
                        for lay in self.layers:
                            free[lay][sl] &= self.owner[lay][fsl] == net
                        via[sl] = False
                for lay in self.layers:
                    if layers is not None and lay not in layers:
                        free[lay][:] = False
                starts = self._starts(groups[self._key(pad)][1], free,
                                      self.stub_end.get(self._name(pad), centre(pad)), pad)
                path = self._search(free, via, tree, starts, cost, max_states, win)
                if path is None and corridor:   # no room for the pair's corridor: plain track
                    free = {lay: win.full(self, self.free(lay, net, w_try, d[lay], win) &
                                          (layers is None or lay in layers)) for lay in self.layers}
                    starts = self._starts(groups[self._key(pad)][1], free,
                                          self.stub_end.get(self._name(pad), centre(pad)), pad)
                    path = self._search(free, via, tree, starts, cost, max_states, win)
                if path is not None:
                    break
            if path is None:
                failed += 1
                self.failed[net].append((self._name(pad), centre(pad), self.why))
                continue
            for lay, items in self._lay(net, path, w_try, full_width or width, d, win, clearance).items():
                for sl, m in items:
                    tree[lay][sl] |= m
            spots.extend(self.xy(c[1], c[2]) for c in path[::20])
            join(pad)
            joined.append(pad)
            for q in list(todo):   # pads the new track ran over are joined too
                if joined_now(q):
                    todo.remove(q)
                    join(q)
                    joined.append(q)
        self._recording = None
        return failed

    def _remove(self, obj):
        """Takes a track or via off the board. Kept referenced: if Python frees a removed
        item of a board loaded from a file, KiCad's bindings break."""
        self.board.Remove(obj)
        self.removed.append(obj)

    def join_ends(self, net, a, b, on_a, on_b, reach=0.3, spread=4.0):
        """Joins two separate pieces of a net's copper by their ends a and b (KiCad mm, as
        KiCad's check names them): from the net's copper within `reach` of a on the layers
        on_a to its copper within `reach` of b on on_b. Returns the tracks and vias added, or
        [] if no way was found."""
        win = self.window(min(a[0], b[0]) - spread, min(a[1], b[1]) - spread,
                          max(a[0], b[0]) + spread, max(a[1], b[1]) + spread)
        d = self.dists(net, win)
        X, Y = np.meshgrid(self.x0 + np.arange(self.nx) * PITCH, self.y0 + np.arange(self.ny) * PITCH)
        free = {lay: win.full(self, self.free(lay, net, THIN, d[lay], win)) for lay in self.layers}
        own = {lay: self.owner[lay][::K, ::K][:self.ny, :self.nx] == net for lay in self.layers}
        near_a, near_b = np.hypot(X - a[0], Y - a[1]) <= reach, np.hypot(X - b[0], Y - b[1]) <= reach
        starts = {lay: own[lay] & near_a & free[lay].astype(bool) & (lay in on_a) for lay in self.layers}
        tree = {lay: own[lay] & near_b & (lay in on_b) for lay in self.layers}
        if not any(starts[lay].any() for lay in self.layers) or not any(tree[lay].any() for lay in self.layers):
            return []
        path = self._search(free, win.full(self, self.via_ok(net, d, win)), tree, starts, None, 400000, win)
        if path is None or len(path) < 2:
            return []
        self._made = []
        self._lay(net, path, THIN, 0.2, d, win, None)
        made, self._made = self._made, None
        return made

    def rip(self, net):
        """Removes the tracks and vias route_net added for a net (stubs stay)."""
        for obj in self.routed.pop(net, []):
            self._remove(obj)
        self.length[net] = 0.0
        self.failed.pop(net, None)

    def route_all(self, plan, rounds=6, reach=2.0, log=print):
        """Routes plan, a list of (net, route_net options), in order. Then, up to `rounds`
        times and while it helps, each net still stuck gets a try at rip-up and reroute
        (try_rip). Returns {net: [(pad name, (x, y), reason)]} still stuck."""
        opts, order = dict(plan), [n for n, _ in plan]
        self.set_waiting(order)
        for net in order:
            self.route_net(net, **opts[net])
        self.retry(opts, order, rounds, reach, log)
        return {n: v for n, v in self.failed.items() if v}

    def retry(self, opts, order, rounds, reach=2.0, log=print, judge=None):
        """Rounds of try_rip on every stuck net of order, until none is left, a round joins
        nothing more, or `rounds` are done. judge: see try_rip."""
        last = None
        for k in range(rounds):
            stuck = [n for n in order if self.failed.get(n)]
            left = sum(len(self.failed[n]) for n in stuck)
            log(f"route: pass {k + 1}: {left} connections on {len(stuck)} nets not made")
            if not stuck or left == last:
                break
            last = left
            for n in stuck:
                if self.failed.get(n):   # not joined meanwhile by another try
                    self.try_rip(n, opts, order, reach, 400000 * min(k + 2, 3), judge)

    def try_rip(self, net, opts, order, reach, budget, judge=None):
        """Takes up the nets routed within `reach` mm of a stuck net's unjoined pins, or within
        half that of its other pins (a pin can be boxed in at the end it was to join), with
        those nets' own pin vias there (via_out's), routes the stuck net with a bigger search
        budget, then those nets again. Kept only if fewer connections are left unmade than
        before (by judge(), the number still unrouted, if given; else by this router's own
        count); otherwise all of it is put back as it was. Returns whether it was kept."""
        spots = [xy for _, xy, _ in self.failed[net]]
        pins = [self._centre(pad) for pad, _, _ in self.nets.get(net, [])]

        def near(objs):
            return any(self._near(o, spots, reach) or self._near(o, pins, reach / 2) for o in objs)
        fans = [f for f in self.fanouts if f[0] != net and f[0] in order and near(f[2])]
        blockers = [n for n in order if n != net and (near(self.routed.get(n, [])) or any(f[0] == n for f in fans))]
        group = [net] + blockers
        before = judge() if judge else sum(len(self.failed.get(n, [])) for n in group)
        saved = {n: (self._shapes(self.routed.get(n, [])), list(self.failed.get(n, [])), self.length.get(n, 0.0))
                 for n in group}
        taken = [self._take_fanout(f) for f in fans]
        for n in group:
            self.rip(n)
        self._load()
        self.set_waiting(group)
        self.route_net(net, **dict(opts[net], max_states=budget))
        for n in blockers:
            self.route_net(n, **opts[n])
        if (judge() if judge else sum(len(self.failed.get(n, [])) for n in group)) < before:
            return True
        for n in group:
            self.rip(n)
        self._load()
        for t in taken:
            self._put_fanout(*t)
        for n, (shapes, failed, length) in saved.items():
            self._recording = n
            for shape in shapes:
                if shape[0] == "via":
                    self.add_via(n, shape[1])
                else:
                    self.add_track(n, *shape[1:])
            self._recording = None
            self.failed[n], self.length[n] = failed, length
        return False

    @staticmethod
    def _shapes(objs):
        """Tracks and vias as data, to put them back later."""
        out = []
        for o in objs:
            if o.GetClass() == "PCB_VIA":
                p = o.GetPosition()
                out.append(("via", (pcbnew.ToMM(p.x), pcbnew.ToMM(p.y))))
            else:
                a, b = o.GetStart(), o.GetEnd()
                out.append(("track", o.GetLayer(), (pcbnew.ToMM(a.x), pcbnew.ToMM(a.y)),
                            (pcbnew.ToMM(b.x), pcbnew.ToMM(b.y)), pcbnew.ToMM(o.GetWidth())))
        return out

    def _take_fanout(self, f):
        """Takes one of via_out's pin vias off the board, with its track; returns what
        _put_fanout needs to put it back."""
        net, end, objs, stub, kept, name, pad = f
        shapes = self._shapes(objs)
        for o in objs:
            self._remove(o)
        gone = {id(e) for e in kept}
        self.extra = [e for e in self.extra if id(e) not in gone]
        del self.via_end[name]
        self.fanouts.remove(f)
        return net, shapes, stub, name, pad

    def _put_fanout(self, net, shapes, stub, name, pad):
        self._made, start = [], len(self.extra)
        for shape in shapes:
            self._keep(pad, net, self.add_via(net, shape[1]) if shape[0] == "via" else self.add_track(net, *shape[1:]))
        self.via_end[name] = shapes[-1][1]
        self.fanouts.append((net, shapes[-1][1], self._made, stub, self.extra[start:], name, pad))
        self._made = None

    @staticmethod
    def _near(obj, spots, reach):
        a, b = obj.GetStart(), obj.GetEnd()
        seg = ((pcbnew.ToMM(a.x), pcbnew.ToMM(a.y)), (pcbnew.ToMM(b.x), pcbnew.ToMM(b.y)))
        return any(float(_seg_dist(np.array(x), np.array(y), *seg)) <= reach for x, y in spots)

    def _starts(self, items, free, at, pad):
        """Where a search for a pad begins: every search cell of its own copper (items: the
        pad, its stub, its via_out via and track, as (layer, (slice, mask))) where a track may
        go. A track then leaves from a cell whose clearance was checked, not from the cell
        nearest a stub's tip. If there is none, the cell nearest `at` on the pad's layers."""
        out = {lay: np.zeros((self.ny, self.nx), bool) for lay in self.layers}
        for lay, (sl, m) in items:
            out[lay][sl] |= m
        for lay in self.layers:
            out[lay] &= free[lay].astype(bool)
        if not any(out[lay].any() for lay in self.layers):
            iy, ix = self.cell(*at)
            for lay in self.layers:
                out[lay][iy, ix] = pad.IsOnLayer(lay)
        return out

    def _distances(self, free, via_ok, tree, ys, xs):
        """For every (layer, cell) of the window: the cost of the cheapest way to the tree
        through free cells, with vias where they fit (Dijkstra, in compiled code), leaving out
        what only the search adds (turns, crowded spots): never more than the real cost, so
        it guides the search straight round obstacles. inf where the tree can't be reached."""
        lays = self.layers
        n_l, h, w = len(lays), ys.stop - ys.start, xs.stop - xs.start
        ok = np.stack([(free[lay][ys, xs] | tree[lay][ys, xs]).astype(bool) for lay in lays])
        idx = np.arange(n_l * h * w).reshape(n_l, h, w)
        lc = np.array([1.0] + [1.15] * (n_l - 1))[:, None, None]
        rows, cols, wts = [], [], []
        for dy, dx, step in ((0, 1, 1.0), (1, 0, 1.0), (1, 1, SQ2), (1, -1, SQ2)):
            ax, bx = (slice(0, w - dx), slice(dx, w)) if dx >= 0 else (slice(-dx, w), slice(0, w + dx))
            m = ok[:, 0:h - dy, ax] & ok[:, dy:h, bx]
            rows.append(idx[:, 0:h - dy, ax][m])
            cols.append(idx[:, dy:h, bx][m])
            wts.append(np.broadcast_to(step * lc, m.shape)[m])
        v = via_ok[ys, xs].astype(bool)
        for i in range(n_l):
            for j in range(i + 1, n_l):
                m = v & ok[i] & ok[j]
                rows.append(idx[i][m])
                cols.append(idx[j][m])
                wts.append(np.full(int(m.sum()), VIA_COST))
        src = idx[np.stack([tree[lay][ys, xs] for lay in lays]).astype(bool) & ok]
        if not src.size:
            return [math.inf] * (n_l * h * w)
        g = csr_matrix((np.concatenate(wts), (np.concatenate(rows), np.concatenate(cols))), shape=(idx.size, idx.size))
        return dijkstra(g, directed=False, indices=src, min_only=True).tolist()

    def _search(self, free, via_ok, tree, starts, cost, max_states, win=None):
        """A* from the cells of starts ({layer: mask}) to any cell of tree, inside win (the
        search window: free is False outside it), guided by _distances."""
        nx, nc = self.nx, self.nx * self.ny
        lays = self.layers
        ys, xs = win.coarse if win is not None else (slice(0, self.ny), slice(0, self.nx))
        y0, x0, h, w = ys.start, xs.start, ys.stop - ys.start, xs.stop - xs.start
        hd = self._distances(free, via_ok, tree, ys, xs)
        inf = math.inf
        free_b = b"".join(np.ascontiguousarray(free[lay], np.uint8).tobytes() for lay in lays)
        goal_b = b"".join(np.ascontiguousarray(tree[lay], np.uint8).tobytes() for lay in lays)
        via_b = np.ascontiguousarray(via_ok, np.uint8).tobytes()
        cost_b = (b"".join(np.ascontiguousarray(cost[lay], np.uint8).tobytes() for lay in lays)
                  if cost else None)
        layer_cost = [1.0] + [1.15] * (len(lays) - 1)   # prefer the top layer, over the ground plane

        heap, g_best, parent = [], {}, {}
        for li, lay in enumerate(lays):
            for c in np.flatnonzero(starts[lay]).tolist():
                iy, ix = divmod(c, nx)
                if not (y0 <= iy < y0 + h and x0 <= ix < x0 + w):
                    continue
                e = hd[(li * h + iy - y0) * w + ix - x0]
                if e == inf:
                    continue
                s = (li * nc + c) * 9 + 8
                g_best[s] = 0.0
                parent[s] = None
                heapq.heappush(heap, (GREED * e, 0.0, s))
        expanded = 0
        while heap:
            f, g, s = heapq.heappop(heap)
            if g > g_best.get(s, 1e18):
                continue
            idx, d = divmod(s, 9)
            if goal_b[idx]:
                return self._unwind(s, parent)
            expanded += 1
            if expanded > max_states:
                self.why = f"gave up after {max_states} steps"
                return None
            li, c = divmod(idx, nc)
            iy, ix = divmod(c, nx)
            for nd in range(8):
                pen = 0.0
                if d != 8:
                    t = (nd - d) % 8
                    t = min(t, 8 - t)
                    if t > 2:
                        continue
                    pen = TURN[t]
                dx, dy = DIRS[nd]
                jx, jy = ix + dx, iy + dy
                if not (x0 <= jx < x0 + w and y0 <= jy < y0 + h):
                    continue
                nidx = li * nc + jy * nx + jx
                if not free_b[nidx]:
                    continue
                e = hd[(li * h + jy - y0) * w + jx - x0]
                if e == inf:
                    continue
                step = (1.0 if dx == 0 or dy == 0 else SQ2) * layer_cost[li]
                if cost_b:
                    step *= cost_b[nidx]
                ng = g + step + pen
                ns = nidx * 9 + nd
                if ng < g_best.get(ns, 1e18):
                    g_best[ns] = ng
                    parent[ns] = s
                    heapq.heappush(heap, (ng + GREED * e, ng, ns))
            if via_b[c]:
                for lj in range(len(lays)):
                    nidx = lj * nc + c
                    if lj != li and free_b[nidx]:
                        e = hd[(lj * h + iy - y0) * w + ix - x0]
                        if e == inf:
                            continue
                        ns = nidx * 9 + 8
                        ng = g + VIA_COST * (cost_b[nidx] if cost_b else 1)   # dearer by waiting pins too
                        if ng < g_best.get(ns, 1e18):
                            g_best[ns] = ng
                            parent[ns] = s
                            heapq.heappush(heap, (ng + GREED * e, ng, ns))
        self.why = "no free path"
        return None

    def _unwind(self, s, parent):
        nc = self.nx * self.ny
        cells = []
        while s is not None:
            li, c = divmod(s // 9, nc)
            cells.append((li, *divmod(c, self.nx)))
            s = parent[s]
        return cells[::-1]

    def _lay(self, net, path, width, full_width, d, win, clearance):
        """Turns a grid path into tracks and vias: straight runs become single tracks,
        split into pieces of up to 1 mm that are widened to full_width where there is room."""
        added = {lay: [] for lay in self.layers}
        runs, cur = [], [path[0]]
        for prev, nxt in zip(path, path[1:]):
            if nxt[0] != prev[0]:
                runs.append(cur)
                cur = [nxt]
                for lay, item in self.add_via(net, self.xy(nxt[1], nxt[2])).items():
                    added[lay].append(item)
            else:
                cur.append(nxt)
        runs.append(cur)
        for run in runs:
            if len(run) < 2:
                continue
            lay = self.layers[run[0][0]]
            corners = [run[0]]
            for a, b, nb in zip(run, run[1:], run[2:]):
                if (b[1] - a[1], b[2] - a[2]) != (nb[1] - b[1], nb[2] - b[2]):
                    corners.append(b)
            corners.append(run[-1])
            for a, b in zip(corners, corners[1:]):
                pa, pb = self.xy(a[1], a[2]), self.xy(b[1], b[2])
                n = max(1, int(math.ceil(math.hypot(pb[0] - pa[0], pb[1] - pa[1]) / 1.0)))
                for k in range(n):
                    qa = (pa[0] + (pb[0] - pa[0]) * k / n, pa[1] + (pb[1] - pa[1]) * k / n)
                    qb = (pa[0] + (pb[0] - pa[0]) * (k + 1) / n, pa[1] + (pb[1] - pa[1]) * (k + 1) / n)
                    line = self._line(qa, qb)
                    w = THIN   # the widest of these that fits
                    for cand in sorted({full_width, width}, reverse=True):
                        if cand > THIN and self._fine_ok(lay, net, d[lay], win, line, cand / 2, clearance):
                            w = cand
                            break
                    for lay_, item in self.add_track(net, lay, qa, qb, w).items():
                        added[lay_].append(item)
        return added
