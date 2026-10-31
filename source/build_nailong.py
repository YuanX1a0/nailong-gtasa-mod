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

# ---- skin the body while it is still one clean shell (heat weighting works best) ----
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

# ---- eyes + mouth are rigid on the head bone ----
head_bone = [b for b in arm.data.bones if b.name.strip().lower() == 'head'][0]
hvg = det.vertex_groups.get(head_bone.name) or det.vertex_groups.new(name=head_bone.name)
hvg.add(list(range(len(det.data.vertices))), 1.0, 'REPLACE')
log("DETAIL_HEAD", head_bone.name, "verts", len(det.data.vertices))

# ---- rejoin ----
bpy.ops.object.select_all(action='DESELECT')
nail.select_set(True)
det.select_set(True)
bpy.context.view_layer.objects.active = nail
bpy.ops.object.join()
nail_me = nail.data
nail_me.update()
from collections import Counter
log("JOINED", "verts", len(nail_me.vertices), "polys", len(nail_me.polygons),
    "mats", [m.name for m in nail_me.materials],
    "mat_faces", dict(Counter(p.material_index for p in nail_me.polygons)))
log("COLOR_ATTRS_AFTER_REMESH", [(a.name, a.domain, a.data_type) for a in nail_me.color_attributes])
log("UV_AFTER_REMESH", [u.name for u in nail_me.uv_layers])

# ============================================================
# 4.5 push arm shell outward so it reads as a separate limb
#     (fat torso swallows the arms: inner arm sits 1-6 cm inside
#      the torso silhouette at every height band)
# ============================================================
ARM_KEY = ('upperarm', 'forearm', 'hand', 'finger')
arm_gidx = set(g.index for g in nail.vertex_groups
               if any(k in g.name.strip().lower() for k in ARM_KEY))

def arm_share(v):
    return sum(g.weight for g in v.groups if g.group in arm_gidx)

BASE_PUSH = 0.075      # unused fallback: rigid outward travel in world units
SH_TAPER = 0.16        # unused fallback
W0, W1 = 0.10, 0.65    # arm-weight ramp

# arms are one continuous shell with the fat torso, so translating vertices
# shears the shoulder apart. instead swing the whole arm out around the
# shoulder joint: the pivot does not move, the gap opens as a wedge.
ARM_OUT_DEG = 16.0

sh_pivot = {}
for b in arm.data.bones:
    nm = b.name.strip().lower()
    if 'upperarm' in nm:
        side = 'L' if nm.startswith('l') else 'R'
        sh_pivot[side] = arm.matrix_world @ b.head_local
log("ARM_PIVOT", {k: [round(c, 3) for c in v] for k, v in sh_pivot.items()})

def pivot_for(z):
    if len(sh_pivot) == 1:
        return next(iter(sh_pivot.values()))
    return sh_pivot['L'] if (sh_pivot['L'].z >= 0.0) == (z >= 0.0) else sh_pivot['R']

arm_vs = [v for v in nail_me.vertices if arm_share(v) > 0.02]
moved, maxd = 0, 0.0
for v in arm_vs:
    w = min(1.0, arm_share(v))
    p = pivot_for(v.co.z)
    sign = 1.0 if p.z >= 0.0 else -1.0
    q = Matrix.Rotation(math.radians(sign * ARM_OUT_DEG * w), 4, 'Y')
    nco = p + (q @ (v.co - p))
    d = (nco - v.co).length
    if d <= 1e-5:
        continue
    v.co = nco
    moved += 1
    maxd = max(maxd, d)
nail_me.update()
log("ARM_PUSH", "arm_verts", len(arm_vs), "moved", moved, "max", round(maxd, 4),
    "deg", ARM_OUT_DEG)

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
