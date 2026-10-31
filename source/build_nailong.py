import bpy, sys, importlib, os, math, json, time
import mathutils
from mathutils import Matrix, Vector

# ---- DragonFF (legacy addon, manual register works on Blender 5.0) ----
sys.path.insert(0, r"D:/Blender/5.0/scripts/addons")
_m = importlib.import_module("dragonff")
importlib.reload(_m)
_m.register()

BASE_PED = r"F:\SCRIPS\SAMPSERVER\OSRP\OSRP\models\WM1.dff"
OUT_DIR  = r"F:\SCRIPS\NAILONG_PED"
os.makedirs(OUT_DIR, exist_ok=True)

LOG = []
def log(*a):
    s = " ".join(str(x) for x in a)
    print("###", s)
    LOG.append(s)

# ============================================================
# 1. nailong mesh
# ============================================================
nail = [o for o in bpy.context.scene.objects if o.type == 'MESH'][0]
log("NAIL_SRC", nail.name, "verts", len(nail.data.vertices), "polys", len(nail.data.polygons))
nail_me = nail.data

# ============================================================
# 2. import base SA ped (skeleton template)
# ============================================================
before = set(bpy.data.objects)
bpy.ops.import_scene.dff(filepath=BASE_PED)
new_objs = [o for o in bpy.data.objects if o not in before]
arm = [o for o in new_objs if o.type == 'ARMATURE'][0]
base_mesh = [o for o in new_objs if o.type == 'MESH'][0]
log("ARM", arm.name, "bones", len(arm.data.bones), "mw_identity", arm.matrix_world == Matrix.Identity(4))
log("BASE_MESH", base_mesh.name, "verts", len(base_mesh.data.vertices))

bpts = [arm.matrix_world @ v.co for v in base_mesh.data.vertices]
bmin = Vector((min(p.x for p in bpts), min(p.y for p in bpts), min(p.z for p in bpts)))
bmax = Vector((max(p.x for p in bpts), max(p.y for p in bpts), max(p.z for p in bpts)))
log("BASE_BOUNDS", [round(v,3) for v in bmin], [round(v,3) for v in bmax])

# ============================================================
# 3. map Blender Z-up -> SA ped axes (X=up, Y=forward, Z=side)
#    (x, y, z)_blender  ->  (z, y, -x)
# ============================================================
M = Matrix(((0,0,1,0), (0,1,0,0), (-1,0,0,0), (0,0,0,1)))
nail.matrix_world = M
pts = [nail.matrix_world @ v.co for v in nail_me.vertices]
nmin = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
nmax = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
log("NAIL_BOUNDS_IN_PEDSPACE", [round(v,3) for v in nmin], [round(v,3) for v in nmax])

s = (bmax.x - bmin.x) / (nmax.x - nmin.x)
tx = bmin.x - s * nmin.x
ty = ((bmin.y + bmax.y) / 2) - s * ((nmin.y + nmax.y) / 2)
tz = ((bmin.z + bmax.z) / 2) - s * ((nmin.z + nmax.z) / 2)
T = Matrix.Translation((tx, ty, tz)) @ Matrix.Scale(s, 4)
nail.matrix_world = T @ M
log("SCALE", round(s,4), "offset", round(tx,3), round(ty,3), round(tz,3))

bpy.context.view_layer.objects.active = nail
nail.select_set(True)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

p2 = [v.co.copy() for v in nail_me.vertices]
log("NAIL_FINAL_BOUNDS",
    [round(min(p.x for p in p2),3), round(min(p.y for p in p2),3), round(min(p.z for p in p2),3)],
    [round(max(p.x for p in p2),3), round(max(p.y for p in p2),3), round(max(p.z for p in p2),3)])

# keep one working copy of the imported ped material (has valid .dff props)
keep_mat = base_mesh.material_slots[0].material if base_mesh.material_slots else None
log("KEEP_MAT", keep_mat.name if keep_mat else None)

# remove base mesh object (skeleton stays)
bpy.data.objects.remove(base_mesh, do_unlink=True)

# ============================================================
# 4. split eyes/mouth off, voxel-remesh the body, decimate both, rejoin
# ============================================================
import bmesh

TARGET_TRIS = 9000
BODY_TRIS_CARVED = 7200
DETAIL_TRIS = 1800

def keep_mats(me, keep):
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    doomed = [f for f in bm.faces if f.material_index not in keep]
    if doomed:
        bmesh.ops.delete(bm, geom=doomed, context='FACES')
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
    bm.to_mesh(me)
    bm.free()
    me.update()

det = nail.copy()
det.data = nail_me.copy()
det.name = "detail"
bpy.context.scene.collection.objects.link(det)
det_me = det.data

keep_mats(nail_me, {0})          # body only (yellow)
keep_mats(det_me, {1, 2, 3})     # mouth + eye shells

# lift the eye/mouth shells slightly so the inflated remeshed body cannot swallow them
for v in det_me.vertices:
    v.co += v.normal * 0.004
det_me.update()

log("SPLIT", "body_polys", len(nail_me.polygons), "detail_polys", len(det_me.polygons))

# close the narrow mouth hole left in the body surface, else voxel remesh degenerates
bpy.ops.object.select_all(action='DESELECT')
nail.select_set(True)
bpy.context.view_layer.objects.active = nail
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.fill_holes(sides=0)
bpy.ops.object.mode_set(mode='OBJECT')
nail_me.update()
log("HOLE_FILLED", "body_polys", len(nail_me.polygons))

# ---- body: voxel remesh kills the belly-center seam ----
tris = sum(len(p.vertices) - 2 for p in nail_me.polygons)
bpy.ops.object.select_all(action='DESELECT')
nail.select_set(True)
bpy.context.view_layer.objects.active = nail

rm = nail.modifiers.new("rm", 'REMESH')
rm.mode = 'VOXEL'
rm.voxel_size = 0.008
rm.use_smooth_shade = True
bpy.ops.object.modifier_apply(modifier=rm.name)
log("REMESHED", len(nail.data.vertices), len(nail.data.polygons))

tris2 = sum(len(p.vertices) - 2 for p in nail.data.polygons)
dec = nail.modifiers.new("dec", 'DECIMATE')
dec.decimate_type = 'COLLAPSE'
dec.ratio = min(1.0, TARGET_TRIS / tris2)
dec.use_collapse_triangulate = True
bpy.ops.object.modifier_apply(modifier=dec.name)

bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.vertices_smooth(factor=0.5, repeat=2)
bpy.ops.object.mode_set(mode='OBJECT')
nail.data.update()
log("DECIMATED_BODY", "tris_before", tris, "verts", len(nail.data.vertices),
    "polys", len(nail.data.polygons))

# ---- detail: keep eye spheres readable ----
dtris = sum(len(p.vertices) - 2 for p in det_me.polygons)
bpy.ops.object.select_all(action='DESELECT')
det.select_set(True)
bpy.context.view_layer.objects.active = det
dmod = det.modifiers.new("dec2", 'DECIMATE')
dmod.decimate_type = 'COLLAPSE'
dmod.ratio = min(1.0, DETAIL_TRIS / dtris)
dmod.use_collapse_triangulate = True
bpy.ops.object.modifier_apply(modifier=dmod.name)
log("DECIMATED_DETAIL", "tris_before", dtris, "verts", len(det.data.vertices),
    "polys", len(det.data.polygons))

# NOTE: the body is skinned only after the flippers have been carved away and
# the shell re-sealed — voxel remesh throws vertex groups away, so skinning any
# earlier would be destroyed by the clean-up pass (see 4.5c).

# ============================================================
# 4.5 cut the welded flipper off the flanks and hang real arms
#     the source model melts its arms into the belly, so any arm bone
#     motion used to drag the whole flank out into a wing. carving the
#     welded mass away leaves a shallow socket, and the slim limb added
#     on top is weighted only to the arm chain, so posing the arms can
#     never deform the torso again.
# ============================================================
byname = {b.name.strip().lower(): b for b in arm.data.bones}

def bone_named(side, part):
    pre = ('l' if side == 'L' else 'r') + part
    for n, b in byname.items():
        if n.replace(' ', '').startswith(pre):
            return b
    raise KeyError(pre)

ARM_PARTS = ('upperarm', 'forearm', 'hand')
CHAIN = {}                             # side -> [shoulder, elbow, wrist, fingertip]
SEGS = []                              # (head, tail, bone name, side, seg index)
for side in ('L', 'R'):
    pts = [arm.matrix_world @ bone_named(side, p).head_local
           for p in ('upperarm', 'forearm', 'hand', 'finger')]
    CHAIN[side] = pts
    log("ARM_CHAIN", side, [[round(c, 3) for c in p] for p in pts])
    for i, part in enumerate(ARM_PARTS):
        SEGS.append((pts[i], pts[i + 1], bone_named(side, part).name, side, i))

def seg_dist(p, h, t):
    ab = t - h
    l2 = ab.length_squared
    u = 0.0 if l2 == 0 else max(0.0, min(1.0, (p - h).dot(ab) / l2))
    return (p - (h + ab * u)).length

# ---- 4.5a carve the welded arm mass off the body ----
# Deleting the faces inside a capsule and stitching the rim by hand leaves thin
# zig-zag sheets welded to the flank that survive every remesh pass. A boolean
# difference against a solid capsule volume instead yields a watertight manifold
# shell with one clean socket wall.
CARVE_PR = (0.185, 0.205, 0.230, 0.310)   # shoulder, elbow, wrist, fingertip
cparts = []
for side in ('L', 'R'):
    pt = CHAIN[side]
    for i in range(4):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=16,
                                             radius=CARVE_PR[i], location=pt[i])
        cparts.append(bpy.context.object)
    for i in range(3):
        h, t = pt[i], pt[i + 1]
        dv = t - h
        bpy.ops.mesh.primitive_cone_add(vertices=24, radius1=CARVE_PR[i],
                                        radius2=CARVE_PR[i + 1], depth=dv.length,
                                        location=(h + t) * 0.5)
        c = bpy.context.object
        c.rotation_mode = 'QUATERNION'
        c.rotation_quaternion = dv.to_track_quat('Z', 'Y')
        cparts.append(c)
bpy.ops.object.select_all(action='DESELECT')
for o in cparts:
    o.select_set(True)
bpy.context.view_layer.objects.active = cparts[0]
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
bpy.ops.object.join()
cutter = bpy.context.object
cutter.name = "arm_cutter"
crm = cutter.modifiers.new("crm", 'REMESH')
crm.mode = 'VOXEL'
crm.voxel_size = 0.012
bpy.ops.object.modifier_apply(modifier=crm.name)
log("CUTTER", "verts", len(cutter.data.vertices), "polys", len(cutter.data.polygons))

boo = nail.modifiers.new("carve", 'BOOLEAN')
boo.operation = 'DIFFERENCE'
boo.solver = 'EXACT'
boo.object = cutter
bpy.ops.object.select_all(action='DESELECT')
nail.select_set(True)
bpy.context.view_layer.objects.active = nail
bpy.ops.object.modifier_apply(modifier=boo.name)
bpy.data.objects.remove(cutter, do_unlink=True)
nail_me.update()
log("CARVED", "verts", len(nail_me.vertices), "polys", len(nail_me.polygons))

bpy.ops.object.select_all(action='DESELECT')
nail.select_set(True)
bpy.context.view_layer.objects.active = nail
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.vertices_smooth(factor=0.4, repeat=2)
bpy.ops.object.mode_set(mode='OBJECT')
nail_me.update()
log("CARVE_SEALED", "verts", len(nail_me.vertices), "polys", len(nail_me.polygons))

# ---- 4.5b keep only the main shell, then voxel-remesh the crater rim flat ----
# the cut leaves a ragged rim plus, at the far tip of the old flipper, a paper
# thin fin that no distance test can catch. dropping every stray island and
# re-meshing the shell melts those leftovers into a smooth socket.
bm = bmesh.new()
bm.from_mesh(nail_me)
bm.faces.ensure_lookup_table()
seen = set()
islands = []
for f in bm.faces:
    if f.index in seen:
        continue
    stack, comp = [f], []
    seen.add(f.index)
    while stack:
        cur = stack.pop()
        comp.append(cur)
        for e in cur.edges:
            for nf in e.link_faces:
                if nf.index not in seen:
                    seen.add(nf.index)
                    stack.append(nf)
    islands.append(comp)
islands.sort(key=len, reverse=True)
junk = [f for comp in islands[1:] for f in comp]
if junk:
    bmesh.ops.delete(bm, geom=junk, context='FACES')
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
bm.to_mesh(nail_me)
bm.free()
nail_me.update()
log("BODY_ISLANDS", "before", len(islands), "dropped_faces", len(junk),
    "verts", len(nail_me.vertices))

bm = bmesh.new()
bm.from_mesh(nail_me)
open_e = sum(1 for e in bm.edges if len(e.link_faces) < 2)
nonman_e = sum(1 for e in bm.edges if len(e.link_faces) > 2)
vol = bm.calc_volume(signed=True)
bm.free()
log("BODY_TOPOLOGY", "open_edges", open_e, "nonmanifold_edges", nonman_e,
    "signed_volume", round(vol, 4))

# side profile of the shell above the waist, so the shoulder cutter can be
# sized from measured geometry instead of guesswork
for i in range(6, 19):
    lo = i * 0.05
    vs = [v.co for v in nail_me.vertices if lo <= v.co.x < lo + 0.05]
    if vs:
        log("PROFILE", round(lo, 2), "n", len(vs),
            "maxZ", round(max(abs(v.z) for v in vs), 3),
            "maxY", round(max(abs(v.y) for v in vs), 3))

bpy.ops.object.select_all(action='DESELECT')
nail.select_set(True)
bpy.context.view_layer.objects.active = nail
rm2 = nail.modifiers.new("rm2", 'REMESH')
rm2.mode = 'VOXEL'
rm2.voxel_size = 0.010
rm2.use_smooth_shade = True
bpy.ops.object.modifier_apply(modifier=rm2.name)
t3 = sum(len(p.vertices) - 2 for p in nail.data.polygons)
log("RESEAL_RAW", "verts", len(nail.data.vertices), "polys", len(nail.data.polygons),
    "tris", t3)
dc3 = nail.modifiers.new("dec3", 'DECIMATE')
dc3.decimate_type = 'COLLAPSE'
dc3.ratio = min(1.0, BODY_TRIS_CARVED / t3)
dc3.use_collapse_triangulate = True
bpy.ops.object.modifier_apply(modifier=dc3.name)
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.vertices_smooth(factor=0.4, repeat=2)
bpy.ops.object.mode_set(mode='OBJECT')
nail_me.update()
log("BODY_RESEALED", "verts", len(nail_me.vertices), "polys", len(nail_me.polygons))

# ---- 4.5c skin the sealed shell (heat weighting needs the final topology) ----
bpy.ops.object.select_all(action='DESELECT')
nail.select_set(True)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.parent_set(type='ARMATURE_AUTO')
body_zero = sum(1 for v in nail.data.vertices
                if not v.groups or sum(g.weight for g in v.groups) < 1e-4)
log("HEAT_BODY", "vgroups", len(nail.vertex_groups), "parent_type", nail.parent_type,
    "zero", body_zero)

# fallback: if heat failed, weight by nearest bone segment
if body_zero == len(nail.data.vertices):
    bones = [b for b in arm.data.bones]
    for v in nail.data.vertices:
        best = None
        bd = 1e9
        for b in bones:
            h = arm.matrix_world @ b.head_local
            t = arm.matrix_world @ b.tail_local
            p = v.co
            ab = t - h
            l2 = ab.length_squared
            u = 0.0 if l2 == 0 else max(0.0, min(1.0, (p - h).dot(ab) / l2))
            q = h + ab * u
            d = (p - q).length
            if d < bd:
                bd, best = d, b.name
        vg = nail.vertex_groups.get(best) or nail.vertex_groups.new(name=best)
        vg.add([v.index], 1.0, 'REPLACE')
    log("FALLBACK_WEIGHTS", "zero",
        sum(1 for v in nail.data.vertices if not v.groups))

# ---- 4.5d body keeps torso bones only ----
ARM_KEY = ('upperarm', 'forearm', 'hand', 'finger')
arm_gidx = set(g.index for g in nail.vertex_groups
               if any(k in g.name.strip().lower() for k in ARM_KEY))
arm_bone_names = set(g.name for g in nail.vertex_groups if g.index in arm_gidx)
torso_bones = [(arm.matrix_world @ b.head_local, arm.matrix_world @ b.tail_local, b.name)
               for b in arm.data.bones if b.name not in arm_bone_names]

def set_weights(ob, v, pairs):
    for gi in [g.group for g in v.groups]:
        ob.vertex_groups[gi].remove([v.index])
    for name, w in pairs:
        if w <= 1e-5:
            continue
        vg = ob.vertex_groups.get(name) or ob.vertex_groups.new(name=name)
        vg.add([v.index], w, 'REPLACE')

n_orphan = 0
for v in nail_me.vertices:
    base = {nail.vertex_groups[g.group].name: g.weight
            for g in v.groups if g.group not in arm_gidx and g.weight > 1e-6}
    if not base:
        best, bd = None, 1e9
        for h, t, bn in torso_bones:
            d = seg_dist(v.co, h, t)
            if d < bd:
                bd, best = d, bn
        base = {best: 1.0}
        n_orphan += 1
    ssum = sum(base.values())
    set_weights(nail, v, [(k, w / ssum) for k, w in base.items()])
nail_me.update()
log("TORSO_WEIGHTS", "verts", len(nail_me.vertices), "orphans", n_orphan)

# ---- 4.5e eyes + mouth ride rigidly on the head, then weld into the body ----
head_bone = [b for b in arm.data.bones if b.name.strip().lower() == 'head'][0]
hvg = det.vertex_groups.get(head_bone.name) or det.vertex_groups.new(name=head_bone.name)
hvg.add(list(range(len(det.data.vertices))), 1.0, 'REPLACE')
log("DETAIL_HEAD", head_bone.name, "verts", len(det.data.vertices))

bpy.ops.object.select_all(action='DESELECT')
nail.select_set(True)
det.select_set(True)
bpy.context.view_layer.objects.active = nail
bpy.ops.object.join()
nail_me = nail.data
nail_me.update()
from collections import Counter
log("JOINED", "verts", len(nail_me.vertices), "polys", len(nail_me.polygons),
    "mats", [m.name if m else None for m in nail_me.materials],
    "mat_faces", dict(Counter(p.material_index for p in nail_me.polygons)))

# ---- 4.5f slim arm meshes along the chain ----
ARM_R = (0.120, 0.095, 0.080, 0.066)      # shoulder, elbow, wrist, fingertip

def arm_blend(co, side):
    ss = sorted((seg_dist(co, h, t), bn) for h, t, bn, s, i in SEGS if s == side)
    w = sorted(((bn, 1.0 / ((d + 0.02) ** 3)) for d, bn in ss),
               key=lambda kv: kv[1], reverse=True)[:2]
    tot = sum(x[1] for x in w) or 1.0
    return [(bn, x / tot) for bn, x in w]

def build_arm(side):
    pt = CHAIN[side]
    parts = []
    # push the shoulder root into the torso, else the limb reads as a floating tube
    root = pt[0] + Vector((0.0, 0.0, -math.copysign(0.095, pt[0].z)))
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=16, radius=0.126,
                                         location=root)
    parts.append(bpy.context.object)
    for i in range(3):
        h, t = pt[i], pt[i + 1]
        dv = t - h
        bpy.ops.mesh.primitive_cone_add(vertices=24, radius1=ARM_R[i], radius2=ARM_R[i + 1],
                                        depth=dv.length, location=(h + t) * 0.5)
        c = bpy.context.object
        c.rotation_mode = 'QUATERNION'
        c.rotation_quaternion = dv.to_track_quat('Z', 'Y')
        parts.append(c)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=12, radius=0.078,
                                         location=pt[3])
    parts.append(bpy.context.object)
    bpy.ops.object.select_all(action='DESELECT')
    for o in parts:
        o.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bpy.ops.object.join()
    ob = bpy.context.object
    ob.name = "arm_" + side

    # The belly is wider than the bone chain, so a limb built straight along it
    # sinks into the torso from mid-forearm down (measured: up to 0.26 inside).
    # Bow only the part below the shoulder outwards — the root ball has to stay
    # buried, otherwise it pops out above the shoulder as a second lobe — so the
    # hanging arm keeps a visible crease instead of melting into the belly.
    seg_len = [(pt[i + 1] - pt[i]).length for i in range(3)]
    total = sum(seg_len)
    knots = [0.0]
    for l in seg_len:
        knots.append(knots[-1] + l / total)
    BOW, T0, T1 = 0.19, 0.12, 0.70
    sgn = 1.0 if pt[0].z > 0 else -1.0

    def bow_at(t):
        if t <= T0:
            return 0.0
        if t >= T1:
            return BOW
        f = (t - T0) / (T1 - T0)
        return BOW * (f * f * (3.0 - 2.0 * f))

    for v in ob.data.vertices:
        best, bu, bi = 1e9, 0.0, 0
        for i in range(3):
            h, t2 = pt[i], pt[i + 1]
            ab = t2 - h
            u = max(0.0, min(1.0, (v.co - h).dot(ab) / ab.length_squared))
            d = (v.co - (h + ab * u)).length
            if d < best:
                best, bu, bi = d, u, i
        v.co.z += sgn * bow_at((knots[bi] * total + bu * seg_len[bi]) / total)
    ob.data.update()

    rm = ob.modifiers.new("arm_rm", 'REMESH')
    rm.mode = 'VOXEL'
    rm.voxel_size = 0.006
    rm.use_smooth_shade = True
    bpy.ops.object.modifier_apply(modifier=rm.name)
    t0 = sum(len(p.vertices) - 2 for p in ob.data.polygons)
    dc = ob.modifiers.new("arm_dec", 'DECIMATE')
    dc.decimate_type = 'COLLAPSE'
    dc.ratio = min(1.0, 2200 / max(1, t0))
    dc.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier=dc.name)

    # a 900-tri budget collapsed the limb into a faceted plank with a hard
    # corner at the shoulder; at 2200 the silhouette stays round, and one gentle
    # relax pass removes the remaining voxel staircase
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.vertices_smooth(factor=0.35, repeat=1)
    bpy.ops.object.mode_set(mode='OBJECT')
    ob.data.update()

    for v in ob.data.vertices:
        for bn, w in arm_blend(v.co, side):
            vg = ob.vertex_groups.get(bn) or ob.vertex_groups.new(name=bn)
            vg.add([v.index], w, 'REPLACE')
    ob.data.update()
    log("ARM_BUILT", ob.name, "verts", len(ob.data.vertices),
        "polys", len(ob.data.polygons), "groups", [g.name for g in ob.vertex_groups])
    return ob

arm_objs = [build_arm('L'), build_arm('R')]

bpy.ops.object.select_all(action='DESELECT')
nail.select_set(True)
for ob in arm_objs:
    ob.select_set(True)
bpy.context.view_layer.objects.active = nail
bpy.ops.object.join()
nail_me = nail.data
nail_me.update()
log("ARMS_REJOINED", "verts", len(nail_me.vertices), "polys", len(nail_me.polygons))

# ============================================================
# 5. fresh UV + smooth shading
# ============================================================
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.normals_make_consistent(inside=False)
bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.03)
bpy.ops.object.mode_set(mode='OBJECT')
for p in nail_me.polygons:
    p.use_smooth = True
log("UV_LAYERS", [u.name for u in nail_me.uv_layers])

# ============================================================
# 6. bake base color -> texture
# ============================================================
img = bpy.data.images.new("nailong", 2048, 2048, alpha=True)
img.generated_color = (0, 0, 0, 1)
for mat in nail_me.materials:
    if not mat or not mat.use_nodes:
        continue
    nt = mat.node_tree
    for n in nt.nodes:
        n.select = False
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.location = (-400, 200)
    tex.select = True
    nt.nodes.active = tex

scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 4
bpy.ops.object.bake(type='DIFFUSE', pass_filter={'COLOR'}, margin=24, use_clear=True)
log("BAKED")
img.scale(1024, 1024)
log("BAKE_DOWNSCALED", img.size[:])

img.filepath_raw = os.path.join(OUT_DIR, "nailong_baked.png")
img.file_format = 'PNG'
img.save()
log("BAKE_SAVED", img.filepath_raw, img.size[:])

# ============================================================
# 7. single material referencing the baked texture
# ============================================================
mat = keep_mat if keep_mat else bpy.data.materials.new("nailong")
mat.name = "nailong"
mat.use_nodes = True
nt = mat.node_tree
nt.nodes.clear()
out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (300, 0)
bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (0, 0)
tex = nt.nodes.new("ShaderNodeTexImage"); tex.location = (-320, 60)
tex.image = img
nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
bsdf.inputs["Roughness"].default_value = 0.85
if "Specular IOR Level" in bsdf.inputs:
    bsdf.inputs["Specular IOR Level"].default_value = 0.2
mat.blend_method = 'OPAQUE'

nail_me.materials.clear()
nail_me.materials.append(mat)
for p in nail_me.polygons:
    p.material_index = 0
nail_me.update()
log("MAT_SLOTS", len(nail_me.materials), [m.name for m in nail_me.materials])

# ============================================================
# 8. cap to 4 influences and renormalise
# ============================================================
groups = nail.vertex_groups
for v in nail_me.vertices:
    items = [(g.group, g.weight) for g in v.groups]
    if not items:
        continue
    items.sort(key=lambda kv: kv[1], reverse=True)
    for gi, _ in items[4:]:
        groups[gi].remove([v.index])
    keep = items[:4]
    s = sum(w for _, w in keep)
    if s > 0:
        for gi, w in keep:
            groups[gi].add([v.index], w / s, 'REPLACE')
log("WEIGHTS_CAPPED", "zero", sum(1 for v in nail_me.vertices if not v.groups),
    "vgroups", len(nail.vertex_groups), "parent_type", nail.parent_type)

# ---- drop vertex colour layers: SA reads them as prelight (ours are black) ----
for a in list(nail_me.attributes):
    if a.data_type in {'FLOAT_COLOR', 'BYTE_COLOR'}:
        nail_me.attributes.remove(a)
nail_me.update()
log("COLOR_ATTRS_CLEARED", len(nail_me.color_attributes),
    [a.name for a in nail_me.color_attributes])

nail.name = "unnamed"
nail.data.name = "unnamed"
nail.location = (0, 0, 0)
nail.rotation_euler = (0, 0, 0)
nail.scale = (1, 1, 1)

# clean scene: only armature + mesh
for o in list(bpy.data.objects):
    if o not in (arm, nail):
        bpy.data.objects.remove(o, do_unlink=True)

log("SCENE_OBJS", [(o.name, o.type) for o in bpy.data.objects])
log("SCENE_VERSION", scene.get("dragonff_imported_version"))

# ============================================================
# 9. export DFF + TXD
# ============================================================
dff_path = os.path.join(OUT_DIR, "nailong.dff")
txd_path = os.path.join(OUT_DIR, "nailong.txd")
bpy.context.view_layer.objects.active = nail
bpy.ops.export_dff.scene(filepath=dff_path)
log("DFF_EXPORTED", dff_path, os.path.getsize(dff_path) if os.path.exists(dff_path) else "MISSING")

bpy.ops.scene.dragonff_txd_export(filepath=txd_path, only_used_textures=True)
log("TXD_EXPORTED", txd_path, os.path.getsize(txd_path) if os.path.exists(txd_path) else "MISSING")

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT_DIR, "nailong_ped.blend"))
log("BLEND_SAVED")

with open(os.path.join(OUT_DIR, "build_log.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(LOG))
print("BUILD_DONE")
