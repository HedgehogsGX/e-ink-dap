"""Builds a first 3D model of the player's case (Phase 2) in Blender, from the parts chosen
so far, and writes it into case/:

    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup -P tools/make_case.py

- case/dap_case.blend: the case, assembled, with the parts inside it in the collection
  "Reference parts" (to check the fit; they are not printed). 1 Blender unit = 1 mm.
- case/stl/front_shell.stl, back_cover.stl, volume_key.stl (print 2), power_key.stl,
  play_key.stl: in mm, laid flat for printing.
- case/renders/*.png: front, back, top edge (ports), left and right sides (keys), exploded.
Add `-- --no-render` to skip the renders, `-- --preview` for quick small ones.

Layout, portrait (front face = +Z, top edge = +Y, as the player is held):
- Front: only the 3.7" touch panel, its window centred. No buttons on the face.
- Sides: Vol+ and Vol- on the left; power and, under it, a shorter play/pause key on the
  right. Each key is a
  printed slider held in by a flange inside the wall, pressing a side-push switch at the
  edge of the PCB.
- Back layer: the 606090 battery under the panel. The jacks and USB-C sit in the top
  ~15 mm, where the battery isn't, so the battery's 90 mm plus the 4.4 mm jack's depth set
  the length (~110 mm).
- Between them, one PCB, parts on the side facing the panel. The jacks and USB-C are
  mid-mount (in notches in the board) so they line up on the case's centre line.
- microSD slot in the bottom edge, right of centre (the panel's ribbons fold back at the
  centre).
- Closing: the back cover hooks into the bottom wall and takes 2 M2 screws at the top
  corners, into heat-set inserts (M2, 3.2 mm hole) in the front shell.

Panel numbers are Good Display's (GDEY037T03-T02 page and touch-sensor drawing). The jack,
USB-C and microSD sizes are estimates: replace them with the drawings of the parts you buy,
then re-run. The fit check at the end lists any parts that overlap.
"""
import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "case")
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
RENDER = "--no-render" not in ARGS
PREVIEW = "--preview" in ARGS

# ---- Parts (mm)
PANEL_W, PANEL_L, PANEL_T = 53.00, 92.99, 1.48   # GDEY037T03-T02 with its touch film
AA_W, AA_L = 47.04, 81.54                        # active area
AA_TOP = 2.98                                    # panel's top edge to the active area
BATT_W, BATT_L, BATT_T = 60.0, 90.0, 6.0         # 606090 LiPo
BATT_SWELL = 0.4                                 # room for the cell to swell
PCB_T = 1.2
PARTS_H = 3.3                                    # tallest part: ESP32-S3-WROOM-1 is 3.1
SIDE_SW = (3.5, 6.0, 3.0)                        # side-push switch: depth, length, height (estimate)
# Jacks: body width, body height, depth behind the wall, nose diameter. Estimates.
JACK44 = (10.0, 9.0, 14.0, 7.5)
JACK35 = (6.0, 5.0, 12.0, 5.0)
USBC_W, USBC_H, USBC_D = 8.94, 3.26, 7.35        # 16-pin mid-mount receptacle
SD_W, SD_D, SD_H = 14.0, 15.0, 1.85              # push-push microSD socket (estimate)

# ---- Case
W, L = 65.0, 110.0          # outside width and length
R_PLAN = 6.0                # corner radius, seen from the front
R_FRONT, R_BACK = 2.5, 2.0  # rounding of the front and back edges
WALL, FRONT, BACK = 1.8, 1.2, 1.4
R_INNER = 1.5
GAP = 0.3                   # clearance around parts

# Layers, from the back (z = 0) to the front face (z = T)
Z_BATT = BACK + 0.2
Z_PCB = Z_BATT + BATT_T + BATT_SWELL
Z_PARTS = Z_PCB + PCB_T
Z_PANEL = Z_PARTS + PARTS_H
Z_INNER = Z_PANEL + PANEL_T          # inside of the front face
T = Z_INNER + FRONT
Z_PORT = T / 2                       # jacks and USB-C on the centre line
IX, IY = W / 2 - WALL, L / 2 - WALL  # inside half-width and half-length

AA_Y = 0.0                           # window centred on the face
PANEL_TOP = AA_Y + AA_L / 2 + AA_TOP
PANEL_Y = PANEL_TOP - PANEL_L / 2
PANEL_BOTTOM = PANEL_TOP - PANEL_L
assert PANEL_TOP <= IY - GAP and PANEL_BOTTOM >= -IY + GAP, "panel doesn't fit"
WIN_HW, WIN_HH = AA_W / 2 + 0.4, AA_L / 2 + 0.4   # window: active area + 0.4 mm
CHAMFER = 0.6
# Side keys: name, side (-1 left, +1 right), centre y, length
KEYS = (("vol_up", -1, 32.0, 8.0), ("vol_down", -1, 20.0, 8.0),
        ("power", 1, 30.0, 11.0), ("play", 1, 15.0, 6.0))
KEY_H, KEY_PROUD = 2.6, 0.6          # height, how far it stands out of the wall
FLANGE_Y, FLANGE_Z, FLANGE_T = 0.8, 0.25, 0.8   # flange margins and thickness
KEY_Z = Z_PARTS + 1.7                # flange clears the PCB, key lines up with the switch
X_35, X_USB, X_44 = -15.0, 0.0, 15.0
BATT_TOP = IY - max(JACK44[2], JACK35[2], USBC_D) - 0.5
BATT_Y = BATT_TOP - BATT_L / 2
BOSS_R, INSERT_R, INSERT_D = 2.75, 1.6, 4.0
BOSS_X, BOSS_Y = IX - BOSS_R - GAP, IY - BOSS_R - GAP
SCREW_R, HEAD_R = 1.15, 2.1          # M2 countersunk
SD_X, SD_Z = 16.0, Z_PARTS + SD_H / 2
HOOK_X = 18.0


# ---- Geometry helpers

def rrect(hw, hh, r, seg=10):
    """Points of a rounded rectangle centred on 0, counter-clockwise."""
    if r <= 1e-6:
        return [(hw, hh), (-hw, hh), (-hw, -hh), (hw, -hh)]
    r = min(r, hw, hh)
    pts = []
    for cx, cy, a0 in ((hw - r, hh - r, 0), (r - hw, hh - r, 90),
                       (r - hw, r - hh, 180), (hw - r, r - hh, 270)):
        for i in range(seg + 1):
            a = math.radians(a0 + 90 * i / seg)
            p = (cx + r * math.cos(a), cy + r * math.sin(a))
            if not pts or math.dist(p, pts[-1]) > 1e-6:
                pts.append(p)
    if math.dist(pts[0], pts[-1]) < 1e-6:
        pts.pop()
    return pts


def to_object(name, bm, coll):
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    return ob


def loft(name, loops, coll):
    """Closed solid through outlines [(z, points)], bottom to top, all with as many points."""
    bm = bmesh.new()
    rings = [[bm.verts.new((x, y, z)) for x, y in pts] for z, pts in loops]
    n = len(rings[0])
    assert all(len(r) == n for r in rings), name
    for a, b in zip(rings, rings[1:]):
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((a[i], a[j], b[j], b[i]))
    bm.faces.new(list(reversed(rings[0])))
    bm.faces.new(rings[-1])
    return to_object(name, bm, coll)


def quarter(n):
    return [math.pi / 2 * i / n for i in range(n + 1)]


def slab(name, coll, hw, hh, r, z0, z1, at=(0, 0), rb=0.0, rt=0.0, seg=10):
    """Rounded-rectangle prism from z0 to z1, its bottom/top edges rounded by rb/rt."""
    prof = ([(z0 + rb - rb * math.cos(a), rb - rb * math.sin(a)) for a in quarter(6)]
            if rb else [(z0, 0.0)])
    prof += ([(z1 - rt + rt * math.sin(a), rt - rt * math.cos(a)) for a in quarter(6)]
             if rt else [(z1, 0.0)])
    ob = loft(name, [(z, rrect(hw - d, hh - d, r - d, seg)) for z, d in prof], coll)
    ob.location = (at[0], at[1], 0)
    return ob


def box(name, coll, x0, x1, y0, y1, z0, z1):
    return slab(name, coll, (x1 - x0) / 2, (y1 - y0) / 2, 0, z0, z1,
                at=((x0 + x1) / 2, (y0 + y1) / 2))


def cyl(name, coll, r, z0, z1, at=(0, 0), seg=12):
    return slab(name, coll, r, r, r, z0, z1, at=at, seg=seg)


def along_y(name, coll, hw, hh, r, y0, y1, x, z):
    """Prism whose outline is in the XZ plane, from y0 to y1 (a hole or part in the top wall)."""
    ob = slab(name, coll, hw, hh, r, -y1, -y0)
    ob.matrix_world = Matrix.Translation((x, 0, z)) @ Matrix.Rotation(math.pi / 2, 4, "X")
    return ob


def along_x(name, coll, loops, y, z):
    """Solid through outlines in the YZ plane [(x, half-length, half-height, radius)],
    x increasing (a key or a hole in a side wall)."""
    ob = loft(name, [(x, rrect(hw, hh, r)) for x, hw, hh, r in loops], coll)
    ob.matrix_world = Matrix(((0, 0, 1, 0), (1, 0, 0, y), (0, 1, 0, z), (0, 0, 0, 1)))
    return ob


def mirrored(loops, side):
    """loops built for the right wall (+x), moved to the given side, x still increasing."""
    return loops if side > 0 else [(-x, *rest) for x, *rest in reversed(loops)]


def sphere(name, coll, r, at):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=r)
    ob = to_object(name, bm, coll)
    ob.location = at
    return ob


def boolean(target, others, op):
    """Applies a boolean of target with all of others (then deleted)."""
    tmp = bpy.data.collections.new("_operands")
    bpy.context.scene.collection.children.link(tmp)
    for ob in others:
        for c in list(ob.users_collection):
            c.objects.unlink(ob)
        tmp.objects.link(ob)
    mod = target.modifiers.new("bool", "BOOLEAN")
    mod.operation, mod.solver = op, "EXACT"
    mod.operand_type, mod.collection = "COLLECTION", tmp
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(target.evaluated_get(dg))
    old = target.data
    target.modifiers.remove(mod)
    target.data = me
    me.name = target.name
    bpy.data.meshes.remove(old)
    for ob in others:
        mesh = ob.data
        bpy.data.objects.remove(ob)
        bpy.data.meshes.remove(mesh)
    bpy.data.collections.remove(tmp)


def smooth(ob, angle=35):
    for p in ob.data.polygons:
        p.use_smooth = True
    try:
        ob.data.set_sharp_from_angle(angle=math.radians(angle))
    except AttributeError:
        pass


def material(name, color, rough=0.5, metal=0.0, glass=False, image=None):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    m.diffuse_color = (*color, 0.35 if glass else 1.0)
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    if image:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = image
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if glass:
        bsdf.inputs["Transmission Weight"].default_value = 1.0
        bsdf.inputs["IOR"].default_value = 1.5
        # Shadow rays pass through, so the clear case doesn't throw a black shadow.
        out = nt.nodes["Material Output"]
        mix = nt.nodes.new("ShaderNodeMixShader")
        path = nt.nodes.new("ShaderNodeLightPath")
        clear = nt.nodes.new("ShaderNodeBsdfTransparent")
        clear.inputs["Color"].default_value = (0.9, 0.92, 0.94, 1)
        nt.links.new(path.outputs["Is Shadow Ray"], mix.inputs["Fac"])
        nt.links.new(bsdf.outputs["BSDF"], mix.inputs[1])
        nt.links.new(clear.outputs["BSDF"], mix.inputs[2])
        nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return m


def paint(ob, mat, layer):
    ob.data.materials.clear()
    ob.data.materials.append(mat)
    ob["layer"] = layer
    return ob


# ---- The printed parts

def outer(name, coll):
    return slab(name, coll, W / 2, L / 2, R_PLAN, 0, T, rb=R_BACK, rt=R_FRONT, seg=12)


def front_shell(coll):
    shell = outer("front_shell", coll)
    chamfer = loft("chamfer", [(T - CHAMFER, rrect(WIN_HW, WIN_HH, 1.0)),
                               (T + 0.01, rrect(WIN_HW + CHAMFER + 0.01, WIN_HH + CHAMFER + 0.01,
                                                1.0 + CHAMFER + 0.01))], coll)
    chamfer.location = (0, AA_Y, 0)
    cut = [
        box("split", coll, -W, W, -L, L, -1, BACK),
        slab("cavity", coll, IX, IY, R_INNER, -1, Z_INNER),
        slab("window", coll, WIN_HW, WIN_HH, 1.0, Z_INNER - 0.5, T + 1, at=(0, AA_Y)),
        chamfer,
        along_y("hole_35", coll, JACK35[3] / 2 + 0.2, JACK35[3] / 2 + 0.2, 9, IY - 0.5, L / 2 + 1,
                X_35, Z_PORT),
        along_y("hole_44", coll, JACK44[3] / 2 + 0.2, JACK44[3] / 2 + 0.2, 9, IY - 0.5, L / 2 + 1,
                X_44, Z_PORT),
        along_y("hole_usb", coll, USBC_W / 2 + 0.2, USBC_H / 2 + 0.2, USBC_H / 2 + 0.2,
                IY - 0.5, L / 2 + 1, X_USB, Z_PORT),
        box("sd_slot", coll, SD_X - 6, SD_X + 6, -L / 2 - 1, -IY + 0.5, SD_Z - 0.75, SD_Z + 0.75),
        sphere("sd_scoop", coll, 5.0, (SD_X, -L / 2 - 4.0, SD_Z)),
    ]
    for name, side, y, length in KEYS:
        hw, hh = length / 2 + 0.15, KEY_H / 2 + 0.15
        cut.append(along_x(name + "_slot", coll,
                           mirrored([(IX - 0.5, hw, hh, hh), (W / 2 + 1, hw, hh, hh)], side), y, KEY_Z))
    for s in (-1, 1):
        cut.append(box("hook_slot", coll, s * HOOK_X - 4.3, s * HOOK_X + 4.3,
                       -IY - 0.95, -IY + 0.5, BACK + 0.65, BACK + 1.55))
    boolean(shell, cut, "DIFFERENCE")

    add = []
    for s in (-1, 1):  # screw bosses in the top corners, joined to both walls
        x, y = s * BOSS_X, BOSS_Y
        z1 = Z_PANEL - 0.3
        add.append(cyl("boss", coll, BOSS_R, BACK, z1, at=(x, y)))
        x0, x1 = sorted((x, s * (IX + 0.3)))
        add.append(box("boss_web", coll, x0, x1, y - BOSS_R, y + BOSS_R, BACK, z1))
        add.append(box("boss_web", coll, x - BOSS_R, x + BOSS_R, y, IY + 0.3, BACK, z1))
    rib_z = (Z_PANEL + 0.1, Z_INNER + 0.2)  # ribs that locate the panel on all 4 sides
    px, yb, yt = PANEL_W / 2 + 0.2, PANEL_BOTTOM - 0.2, PANEL_TOP + 0.2
    for s in (-1, 1):
        for y0 in (-6, -38):  # clear of the side keys' switches
            x0, x1 = sorted((s * px, s * (px + 0.8)))
            add.append(box("rib", coll, x0, x1, y0, y0 + 8, *rib_z))
        x0, x1 = sorted((s * 12, s * 20))
        add.append(box("rib", coll, x0, x1, yb - 0.8, yb, *rib_z))
        add.append(box("rib", coll, x0, x1, yt, yt + 0.8, *rib_z))
    boolean(shell, add, "UNION")

    holes = [cyl("insert", coll, INSERT_R, BACK - 0.5, BACK + INSERT_D, at=(s * BOSS_X, BOSS_Y))
             for s in (-1, 1)]
    boolean(shell, holes, "DIFFERENCE")
    return shell


def back_cover(coll):
    cover = outer("back_cover", coll)
    boolean(cover, [box("split", coll, -W, W, -L, L, BACK, T + 1)], "DIFFERENCE")
    lip_x = BOSS_X - BOSS_R - 0.5
    add = [box("lip", coll, -lip_x, lip_x, IY - 1.15, IY - 0.15, BACK - 0.05, BACK + 1.2)]
    for s in (-1, 1):  # hooks that catch the slots in the bottom wall
        add.append(box("tab", coll, s * HOOK_X - 4, s * HOOK_X + 4,
                       -IY + 0.15, -IY + 1.15, BACK - 0.05, BACK + 1.8))
        add.append(box("nub", coll, s * HOOK_X - 4, s * HOOK_X + 4,
                       -IY - 0.75, -IY + 0.2, BACK + 0.8, BACK + 1.4))
    boolean(cover, add, "UNION")
    cut = []
    for s in (-1, 1):
        at = (s * BOSS_X, BOSS_Y)
        cut.append(cyl("screw", coll, SCREW_R, -1, BACK + 1, at=at))
        sink = loft("sink", [(-0.01, rrect(HEAD_R + 0.01, HEAD_R + 0.01, HEAD_R + 0.01, 12)),
                             (HEAD_R - SCREW_R, rrect(SCREW_R, SCREW_R, SCREW_R, 12))], coll)
        sink.location = (*at, 0)
        cut.append(sink)
    boolean(cover, cut, "DIFFERENCE")
    return cover


def side_key(name, coll, side, y, length):
    """Pill-shaped key in a side wall: a flange inside the wall holds it in, the outside
    stands KEY_PROUD out of the wall with a rounded edge."""
    hw, hh = length / 2, KEY_H / 2
    fw, fh = hw + FLANGE_Y, hh + FLANGE_Z
    out = W / 2 + KEY_PROUD
    loops = [(IX - FLANGE_T, fw, fh, fh), (IX, fw, fh, fh), (IX, hw, hh, hh)]
    loops += [(out - 0.4 + 0.4 * math.sin(a), hw - d, hh - d, hh - d)
              for a in quarter(4) for d in [0.4 - 0.4 * math.cos(a)]]
    ob = along_x(name, coll, mirrored(loops, side), y, KEY_Z)
    ob["side"] = side
    return ob


# ---- The parts inside (for the fit check and the renders)

def reference_parts(coll, mats, screen_image):
    parts = []

    def add(ob, mat, layer):
        parts.append(paint(ob, mats[mat], layer))
        return ob

    add(slab("panel", coll, PANEL_W / 2, PANEL_L / 2, 0.3, Z_PANEL, Z_INNER, at=(0, PANEL_Y)),
        "panel", "panel")
    # The screen image on the active area
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    hw, hh = AA_W / 2, AA_L / 2
    face = bm.faces.new([bm.verts.new((x, y, Z_INNER + 0.003))
                         for x, y in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))])
    for loop, co in zip(face.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
        loop[uv].uv = co
    screen = to_object("screen", bm, coll)
    screen.location = (0, AA_Y, 0)
    screen.data.materials.append(mats["screen"])
    screen["layer"] = "panel"
    parts.append(screen)

    add(slab("battery_606090", coll, BATT_W / 2, BATT_L / 2, 1.5, Z_BATT, Z_BATT + BATT_T,
             at=(0, BATT_Y), rb=0.8, rt=0.8), "battery", "battery")

    pcb = slab("pcb", coll, IX - GAP, IY - GAP, R_INNER - GAP, Z_PCB, Z_PARTS)
    notches = []
    for x, (w, h, d, nose) in ((X_35, JACK35), (X_44, JACK44), (X_USB, (USBC_W, USBC_H, USBC_D, 0))):
        notches.append(box("notch", coll, x - w / 2 - 0.2, x + w / 2 + 0.2, IY - d - 0.2, IY + 1,
                           Z_PCB - 1, Z_PARTS + 1))
    for s in (-1, 1):
        x0, x1 = sorted((s * (BOSS_X - BOSS_R - 0.3), s * IX))
        notches.append(box("notch", coll, x0, x1, BOSS_Y - BOSS_R - 0.3, IY, Z_PCB - 1, Z_PARTS + 1))
    boolean(pcb, notches, "DIFFERENCE")
    add(pcb, "pcb", "board")

    def chip(name, mat, x, y, w, d, h, z=Z_PARTS):
        add(box(name, coll, x - w / 2, x + w / 2, y - d / 2, y + d / 2, z, z + h), mat, "board")

    chip("esp32s3_module", "module", -12, -10, 18, 25.5, 0.8)
    chip("esp32s3_shield", "metal", -12, -10 - (25.5 - 17.6) / 2 + 0.4, 15.8, 17.6, 2.3, Z_PARTS + 0.8)
    chip("cs43131_L", "chip", -6, 32, 5, 5, 0.9)
    chip("cs43131_R", "chip", 6, 32, 5, 5, 0.9)
    chip("osc_24M576", "metal", -6, 25, 3.2, 2.5, 1.0)
    chip("osc_22M5792", "metal", 6, 25, 3.2, 2.5, 1.0)
    chip("gl823k", "chip", 14, 2, 4, 4, 0.8)
    chip("bq24075", "chip", 20, -12, 3, 3, 0.9)
    chip("inductor", "chip", 20, -20, 4, 4, 2.0)
    chip("fpc_epd_24p", "chip", -2, PANEL_BOTTOM + 3.5, 15.5, 4.2, 1.2)
    chip("fpc_touch_6p", "chip", -15, PANEL_BOTTOM + 3.5, 6.5, 4.2, 1.2)
    chip("microsd_socket", "metal", SD_X, -IY + 0.2 + SD_D / 2, SD_W, SD_D, SD_H)
    depth, length, height = SIDE_SW
    for name, side, y, _ in KEYS:  # side-push switches at the board's edge, facing the keys
        x_act = IX - FLANGE_T - 0.05
        for part, x0, x1, dy, z0, z1 in (
                ("", x_act - 0.6 - depth, x_act - 0.6, length / 2, Z_PARTS, Z_PARTS + height),
                ("_actuator", x_act - 0.6, x_act, 1.0, Z_PARTS + height / 2 - 0.6,
                 Z_PARTS + height / 2 + 0.6)):
            x0, x1 = sorted((side * x0, side * x1))
            add(box("switch_" + name + part, coll, x0, x1, y - dy, y + dy, z0, z1), "chip", "board")

    for name, x, (w, h, d, nose), plug in (("jack_3.5", X_35, JACK35, 3.5),
                                           ("jack_4.4", X_44, JACK44, 4.4)):
        add(box(name, coll, x - w / 2, x + w / 2, IY - d, IY, Z_PORT - h / 2, Z_PORT + h / 2),
            "jack", "board")
        ring = along_y(name + "_nose", coll, nose / 2, nose / 2, 9, IY, L / 2 - 0.3, x, Z_PORT)
        r = plug / 2 + 0.1
        boolean(ring, [along_y("plug", coll, r, r, 9, IY - 1, L, x, Z_PORT)], "DIFFERENCE")
        add(ring, "gold", "board")
    usb = along_y("usb_c", coll, USBC_W / 2, USBC_H / 2, USBC_H / 2,
                  L / 2 - 0.5 - USBC_D, L / 2 - 0.5, X_USB, Z_PORT)
    boolean(usb, [along_y("plug", coll, USBC_W / 2 - 0.35, USBC_H / 2 - 0.4, USBC_H / 2 - 0.4,
                          L / 2 - 6.5, L, X_USB, Z_PORT)], "DIFFERENCE")
    add(usb, "metal", "board")
    for ob in parts:
        if ob.name != "screen":
            smooth(ob, 40)
    return parts


# ---- Checks

def world_bbox(ob):
    pts = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
    return [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]


def overlap_volume(a, b):
    tmp = a.copy()
    tmp.data = a.data.copy()
    bpy.context.scene.collection.objects.link(tmp)
    mod = tmp.modifiers.new("i", "BOOLEAN")
    mod.operation, mod.solver, mod.object = "INTERSECT", "EXACT", b
    dg = bpy.context.evaluated_depsgraph_get()
    bm = bmesh.new()
    bm.from_object(tmp.evaluated_get(dg), dg)
    vol = abs(bm.calc_volume())
    bm.free()
    mesh = tmp.data
    bpy.data.objects.remove(tmp)
    bpy.data.meshes.remove(mesh)
    return vol


def fit_check(objs):
    clashes = []
    for i, a in enumerate(objs):
        (a0, a1) = world_bbox(a)
        for b in objs[i + 1:]:
            (b0, b1) = world_bbox(b)
            if all(a0[k] < b1[k] - 0.01 and b0[k] < a1[k] - 0.01 for k in range(3)):
                v = overlap_volume(a, b)
                if v > 0.05:
                    clashes.append((a.name, b.name, v))
    return clashes


def mesh_report(ob):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bad = sum(not e.is_manifold for e in bm.edges)
    vol = bm.calc_volume()
    bm.free()
    return bad, vol


def export_stl(ob, path, turn=None):
    """Writes ob laid flat for printing: turned by the rotation matrix turn, on z = 0, centred."""
    saved = ob.matrix_world.copy()
    m = turn @ saved if turn else saved
    ob.matrix_world = m
    bpy.context.view_layer.update()
    lo, hi = world_bbox(ob)
    ob.matrix_world = Matrix.Translation((-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2])) @ m
    bpy.context.view_layer.update()
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.wm.stl_export(filepath=path, export_selected_objects=True, apply_modifiers=True)
    ob.matrix_world = saved


# ---- Scene, lights, cameras

def camera(coll, name, loc, target, lens):
    cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
    coll.objects.link(cam)
    cam.data.lens, cam.data.clip_start, cam.data.clip_end = lens, 1, 200000
    cam.location = loc
    cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return cam


def sun(coll, name, strength, rot_deg, angle=8):
    ob = bpy.data.objects.new(name, bpy.data.lights.new(name, "SUN"))
    coll.objects.link(ob)
    ob.data.energy, ob.data.angle = strength, math.radians(angle)
    ob.rotation_euler = [math.radians(a) for a in rot_deg]
    return ob


def setup_scene():
    sc = bpy.context.scene
    us = sc.unit_settings
    us.system, us.scale_length, us.length_unit = "METRIC", 0.001, "MILLIMETERS"
    sc.render.engine = "CYCLES"
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = "METAL"
        prefs.get_devices()
        for d in prefs.devices:
            d.use = True
        sc.cycles.device = "GPU"
    except Exception as e:  # CPU still works, only slower
        print("case: no GPU,", e)
    sc.cycles.samples = 32 if PREVIEW else 192
    sc.cycles.use_denoising = True
    sc.cycles.max_bounces = sc.cycles.transmission_bounces = 16
    sc.cycles.transparent_max_bounces = 16
    sc.render.resolution_x, sc.render.resolution_y = (800, 600) if PREVIEW else (1600, 1200)
    sc.world = bpy.data.worlds.new("Studio")
    sc.world.use_nodes = True
    bg = sc.world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.86, 0.87, 0.89, 1)
    bg.inputs["Strength"].default_value = 0.9
    for screen in bpy.data.screens:  # a sensible viewport when the .blend is opened
        for area in screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces[0]
                space.clip_start, space.clip_end = 0.1, 10000
                space.shading.color_type = "MATERIAL"
                space.region_3d.view_distance = 260
                space.region_3d.view_location = (0, 0, T / 2)


def main():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    setup_scene()
    sc = bpy.context.scene
    c_print = bpy.data.collections.new("Print parts")
    c_ref = bpy.data.collections.new("Reference parts")
    c_stage = bpy.data.collections.new("Stage")
    for c in (c_print, c_ref, c_stage):
        sc.collection.children.link(c)

    screen_image = bpy.data.images.load(os.path.join(ROOT, "docs", "previews", "home.png"))
    screen_image.pack()
    mats = {
        "clear": material("Case clear", (0.97, 0.98, 1.0), rough=0.06, glass=True),
        "solid": material("Case solid", (0.88, 0.88, 0.86), rough=0.45),
        "button": material("Button", (0.06, 0.06, 0.065), rough=0.4),
        "panel": material("Panel", (0.8, 0.8, 0.78), rough=0.6),
        "screen": material("Screen", (1, 1, 1), rough=0.65, image=screen_image),
        "battery": material("Battery", (0.75, 0.76, 0.78), rough=0.3, metal=1.0),
        "pcb": material("PCB", (0.02, 0.05, 0.03), rough=0.35),
        "module": material("Module PCB", (0.03, 0.03, 0.08), rough=0.4),
        "metal": material("Metal", (0.8, 0.8, 0.8), rough=0.25, metal=1.0),
        "chip": material("Chip", (0.03, 0.03, 0.03), rough=0.5),
        "jack": material("Jack", (0.04, 0.04, 0.04), rough=0.45),
        "gold": material("Gold", (0.95, 0.75, 0.4), rough=0.25, metal=1.0),
        "floor": material("Floor", (0.8, 0.8, 0.8), rough=0.8),
    }

    shell = paint(front_shell(c_print), mats["clear"], "shell")
    cover = paint(back_cover(c_print), mats["clear"], "cover")
    keys = {name: paint(side_key(name, c_print, side, y, length), mats["button"], "keys")
            for name, side, y, length in KEYS}
    for ob in (shell, cover, *keys.values()):
        smooth(ob)
    parts = reference_parts(c_ref, mats, screen_image)

    print(f"case: outside {W:.1f} x {L:.1f} x {T:.2f} mm (W x L x T)")
    print(f"case: layers z: battery {Z_BATT:.2f}, pcb {Z_PCB:.2f}, parts {Z_PARTS:.2f}, "
          f"panel {Z_PANEL:.2f}, front {Z_INNER:.2f}..{T:.2f}; ports at z {Z_PORT:.2f}, "
          f"side keys at z {KEY_Z:.2f}")
    print(f"case: battery y {BATT_Y - BATT_L / 2:.2f}..{BATT_TOP:.2f}, panel y {PANEL_BOTTOM:.2f}.."
          f"{PANEL_TOP:.2f}, window {2 * WIN_HW:.2f} x {2 * WIN_HH:.2f} at y {AA_Y:.2f}")
    for ob in (shell, cover, keys["vol_up"], keys["power"], keys["play"]):
        bad, vol = mesh_report(ob)
        print(f"case: {ob.name}: {len(ob.data.polygons)} faces, {bad} non-manifold edges, "
              f"{vol / 1000:.2f} cm3")
    solids = [shell, cover, *keys.values()] + [p for p in parts if p.name != "screen"]
    clashes = fit_check(solids)
    for a, b, v in clashes:
        print(f"case: CLASH {a} / {b}: {v:.2f} mm3")
    print(f"case: fit check: {len(clashes)} clashes among {len(solids)} parts")

    os.makedirs(os.path.join(OUT, "stl"), exist_ok=True)
    export_stl(shell, os.path.join(OUT, "stl", "front_shell.stl"), Matrix.Rotation(math.pi, 4, "Y"))
    export_stl(cover, os.path.join(OUT, "stl", "back_cover.stl"))
    for name, stl in (("vol_up", "volume_key.stl"), ("power", "power_key.stl"), ("play", "play_key.stl")):
        side = keys[name]["side"]  # flange down on the bed
        export_stl(keys[name], os.path.join(OUT, "stl", stl), Matrix.Rotation(-side * math.pi / 2, 4, "Y"))

    root = bpy.data.objects.new("DAP", None)
    c_stage.objects.link(root)
    for ob in (shell, cover, *keys.values(), *parts):
        ob.parent = root
    floor = box("floor", c_stage, -50000, 50000, -50000, 50000, -1, 0)
    floor.data.materials.append(mats["floor"])
    sun(c_stage, "Key", 3.2, (38, 0, -32))
    sun(c_stage, "Fill", 0.8, (55, 0, 140), angle=30)
    cams = {
        "front": camera(c_stage, "Cam front", (95, -235, 250), (0, -2, 4), 80),
        "back": camera(c_stage, "Cam back", (95, -235, 250), (0, -2, 4), 80),
        "ports": camera(c_stage, "Cam top edge", (70, 150, 95), (0, 50, 6), 70),
        "side_left": camera(c_stage, "Cam left side", (-170, -10, 95), (-30, 22, 7), 75),
        "side_right": camera(c_stage, "Cam right side", (170, -10, 95), (30, 20, 7), 75),
        "exploded": camera(c_stage, "Cam exploded", (-230, -300, 190), (0, 0, 52), 68),
    }
    sc.camera = cams["front"]

    blend = os.path.join(OUT, "dap_case.blend")
    if os.path.exists(blend):
        os.remove(blend)
    bpy.ops.wm.save_as_mainfile(filepath=blend, compress=True)
    print("case: wrote", blend)
    if not RENDER:
        return

    os.makedirs(os.path.join(OUT, "renders"), exist_ok=True)

    def render(name):
        sc.camera = cams[name]
        sc.render.filepath = os.path.join(OUT, "renders", name + ".png")
        bpy.ops.render.render(write_still=True)
        print("case: rendered", sc.render.filepath)

    render("front")
    root.rotation_euler = (0, math.pi, 0)
    root.location = (0, 0, T)
    render("back")
    root.rotation_euler, root.location = (0, 0, 0), (0, 0, 0)
    for ob in (shell, cover):
        ob.data.materials[0] = mats["solid"]
    render("ports")
    render("side_left")
    render("side_right")
    for ob in (shell, cover):
        ob.data.materials[0] = mats["clear"]
    lift = {"cover": 0, "battery": 16, "board": 32, "panel": 52, "shell": 80, "keys": 80}
    for ob in root.children:
        ob.location.z += lift[ob["layer"]]
        if ob["layer"] == "keys":  # pulled out sideways from their slots
            ob.location.x += 14 * ob["side"]
    render("exploded")


main()
